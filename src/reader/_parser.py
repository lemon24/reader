import logging
import mimetypes
import shutil
import tempfile
from collections import OrderedDict
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from typing import Collection
from typing import ContextManager
from typing import Dict
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import Protocol
from typing import runtime_checkable
from typing import Tuple
from typing import TypeVar
from typing import Union

import reader
from ._http_utils import parse_accept_header
from ._http_utils import unparse_accept_header
from ._requests_utils import DEFAULT_TIMEOUT
from ._requests_utils import SessionFactory
from ._requests_utils import TimeoutType
from ._types import EntryData
from ._types import EntryForUpdate
from ._types import FeedData
from ._types import FeedForUpdate
from ._types import ParsedFeed
from ._url_utils import normalize_url
from ._utils import MapType
from .exceptions import InvalidFeedURLError
from .exceptions import ParseError
from .types import _namedtuple_compat


log = logging.getLogger('reader')


Headers = Mapping[str, str]

T_co = TypeVar('T_co', covariant=True)
T_cv = TypeVar('T_cv', contravariant=True)


# RetrieveResult was a NamedTuple, but generic ones aren't supported yet:
# https://github.com/python/mypy/issues/685


@dataclass(frozen=True)
class RetrieveResult(_namedtuple_compat, Generic[T_co]):
    file: T_co
    mime_type: Optional[str] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None
    headers: Optional[Headers] = None


class RetrieverType(Protocol[T_co]):  # pragma: no cover

    slow_to_read: bool

    def __call__(
        self,
        url: str,
        http_etag: Optional[str],
        http_last_modified: Optional[str],
        http_accept: Optional[str],
    ) -> ContextManager[Optional[RetrieveResult[T_co]]]:
        ...

    def validate_url(self, url: str) -> None:
        """Check if ``url`` is valid for this retriever.

        Raises:
            InvalidFeedURLError: If ``url`` is not valid.

        """


@runtime_checkable
class FeedForUpdateRetrieverType(RetrieverType[T_co], Protocol):  # pragma: no cover
    def process_feed_for_update(self, feed: FeedForUpdate) -> FeedForUpdate:
        ...


FeedAndEntries = Tuple[FeedData, Collection[EntryData]]
EntryPair = Tuple[EntryData, Optional[EntryForUpdate]]


class ParserType(Protocol[T_cv]):  # pragma: no cover
    def __call__(
        self, url: str, file: T_cv, headers: Optional[Headers]
    ) -> FeedAndEntries:
        ...


@runtime_checkable
class HTTPAcceptParserType(ParserType[T_cv], Protocol):  # pragma: no cover
    @property
    def http_accept(self) -> str:
        ...


@runtime_checkable
class EntryPairsParserType(ParserType[T_cv], Protocol):  # pragma: no cover
    def process_entry_pairs(
        self, url: str, pairs: Iterable[EntryPair]
    ) -> Iterable[EntryPair]:
        ...


class FeedArgument(Protocol):  # pragma: no cover
    @property
    def url(self) -> str:
        ...

    @property
    def http_etag(self) -> Optional[str]:
        ...

    @property
    def http_last_modified(self) -> Optional[str]:
        ...


class FeedArgumentTuple(NamedTuple):
    url: str
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None


FA = TypeVar('FA', bound=FeedArgument)


def default_parser(
    feed_root: Optional[str] = None, session_timeout: TimeoutType = DEFAULT_TIMEOUT
) -> 'Parser':
    parser = Parser()
    parser.session_factory.timeout = session_timeout

    from ._retrievers import HTTPRetriever
    from ._feedparser import FeedparserParser
    from ._jsonfeed import JSONFeedParser

    http_retriever = HTTPRetriever(parser.session_factory.transient)
    parser.mount_retriever('https://', http_retriever)
    parser.mount_retriever('http://', http_retriever)
    if feed_root is not None:
        from ._retrievers import FileRetriever

        # empty string means catch-all
        parser.mount_retriever('', FileRetriever(feed_root))

    feedparser_parser = FeedparserParser()
    parser.mount_parser_by_mime_type(feedparser_parser)
    parser.mount_parser_by_mime_type(JSONFeedParser())
    # fall back to feedparser if there's no better match
    # (replicates feedparser's original behavior)
    parser.mount_parser_by_mime_type(feedparser_parser, '*/*;q=0.1')

    return parser


USER_AGENT = f'python-reader/{reader.__version__} (+https://github.com/lemon24/reader)'


class Parser:

    """Meta-parser: retrieve and parse a feed by delegation."""

    def __init__(self) -> None:
        # Typing the link between parser and retriever would be nice,
        # but seems hard to do; for a simplified version of the problem:
        # https://gist.github.com/lemon24/b9338bea9aef176cbadcbfc25687dcf5
        #
        # Higher Kinded Types might be a way of doing it,
        # https://returns.readthedocs.io/en/latest/pages/hkt.html

        self.retrievers: 'OrderedDict[str, RetrieverType[Any]]' = OrderedDict()
        self.parsers_by_mime_type: Dict[str, List[Tuple[float, ParserType[Any]]]] = {}
        self.parsers_by_url: Dict[str, ParserType[Any]] = {}
        self.session_factory = SessionFactory(USER_AGENT)

    def parallel(
        self, feeds: Iterable[FA], map: MapType = map, is_parallel: bool = True
    ) -> Iterable[Tuple[FA, Union[Optional[ParsedFeed], ParseError]]]:
        def retrieve(
            feed: FA,
        ) -> Tuple[FA, Union[ContextManager[Optional[RetrieveResult[Any]]], Exception]]:
            try:
                context = self.retrieve(
                    feed.url, feed.http_etag, feed.http_last_modified, is_parallel
                )
                return feed, context
            except Exception as e:
                # pass around *all* exception types,
                # unhandled exceptions get swallowed by the thread otherwise
                log.debug("retrieve() exception, traceback follows", exc_info=True)
                return feed, e

        with self.session_factory.persistent():

            # if stuff hangs weirdly during debugging, change this to builtins.map
            retrieve_results = map(retrieve, feeds)

            # we could parallelize parse() as well;
            # however, most of the time is spent in pure-Python code,
            # which doesn't benefit from the threads on CPython:
            # https://github.com/lemon24/reader/issues/261#issuecomment-956412131

            for feed, context in retrieve_results:
                if isinstance(context, ParseError):
                    yield feed, context
                    continue

                if isinstance(context, Exception):  # pragma: no cover
                    raise context

                try:
                    with context as result:

                        if not result or isinstance(result, ParseError):
                            yield feed, result
                            continue

                        yield feed, self.parse(feed.url, result)

                except ParseError as e:
                    log.debug("parse() exception, traceback follows", exc_info=True)
                    yield feed, e

    def __call__(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
    ) -> Optional[ParsedFeed]:
        """Thin wrapper for parallel(), to be used by parser tests."""

        feed = FeedArgumentTuple(url, http_etag, http_last_modified)

        # is_parallel=True ensures the parser tests cover more code
        ((_, result),) = self.parallel([feed], is_parallel=True)

        if isinstance(result, Exception):
            raise result
        return result

    def retrieve(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
        is_parallel: bool = False,
    ) -> ContextManager[Optional[RetrieveResult[Any]]]:

        parser = self.get_parser_by_url(url)

        http_accept: Optional[str]
        if not parser:
            http_accept = unparse_accept_header(
                (mime_type, quality)
                for mime_type, parsers in self.parsers_by_mime_type.items()
                for quality, _ in parsers
            )
        else:
            # URL parsers get the default session / requests Accept (*/*);
            # later, we may use parser.http_accept, if it exists, but YAGNI
            http_accept = None

        retriever = self.get_retriever(url)
        context = retriever(url, http_etag, http_last_modified, http_accept)

        if not (is_parallel and retriever.slow_to_read):
            return context

        # Ensure we read everything *before* yielding the response,
        # i.e. __enter__() does most of the work.
        #
        # Gives a ~20% speed improvement over yielding response.raw
        # when updating many feeds in parallel,
        # with a 2-8% increase in memory usage:
        # https://github.com/lemon24/reader/issues/261#issuecomment-956303210
        #
        # SpooledTemporaryFile() is just as fast as TemporaryFile():
        # https://github.com/lemon24/reader/issues/261#issuecomment-957469041

        with context as result:
            if not result:
                return nullcontext()

            temp = tempfile.TemporaryFile()
            shutil.copyfileobj(result.file, temp)
            temp.seek(0)

            result = result._replace(file=temp)

        @contextmanager
        def make_context() -> Iterator[RetrieveResult[Any]]:
            assert result is not None, result  # for mypy
            with wrap_exceptions(url, "while reading feed"), temp:
                yield result

        return make_context()

    def parse(self, url: str, result: RetrieveResult[Any]) -> ParsedFeed:
        parser, mime_type = self.get_parser(url, result.mime_type)
        feed, entries = parser(url, result.file, result.headers)
        return ParsedFeed(
            feed, entries, result.http_etag, result.http_last_modified, mime_type
        )

    def get_parser(
        self, url: str, mime_type: Optional[str]
    ) -> Tuple[ParserType[Any], Optional[str]]:
        parser = self.get_parser_by_url(url)
        if not parser:
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(url)

            # https://tools.ietf.org/html/rfc7231#section-3.1.1.5
            #
            # > If a Content-Type header field is not present, the recipient
            # > MAY either assume a media type of "application/octet-stream"
            # > ([RFC2046], Section 4.5.1) or examine the data to determine its type.
            #
            if not mime_type:
                mime_type = 'application/octet-stream'

            parser = self.get_parser_by_mime_type(mime_type)
            if not parser:
                raise ParseError(url, message=f"no parser for MIME type {mime_type!r}")

        return parser, mime_type

    def validate_url(self, url: str) -> None:
        """Check if ``url`` is valid without actually retrieving it.

        Raises:
            InvalidFeedURLError: If ``url`` is not valid.

        """
        try:
            retriever = self.get_retriever(url)
        except ParseError as e:
            raise InvalidFeedURLError(e.url, message=e.message) from None
        try:
            retriever.validate_url(url)
        except ValueError as e:
            raise InvalidFeedURLError(url) from e

    def mount_retriever(self, prefix: str, retriever: RetrieverType[Any]) -> None:
        self.retrievers[prefix] = retriever
        keys_to_move = [k for k in self.retrievers if len(k) < len(prefix)]
        for key in keys_to_move:
            self.retrievers[key] = self.retrievers.pop(key)

    def get_retriever(self, url: str) -> RetrieverType[Any]:
        for prefix, retriever in self.retrievers.items():
            if url.lower().startswith(prefix.lower()):
                return retriever
        raise ParseError(url, message="no retriever for URL")

    def mount_parser_by_mime_type(
        self, parser: ParserType[Any], http_accept: Optional[str] = None
    ) -> None:
        if not http_accept:
            if not isinstance(parser, HTTPAcceptParserType):
                raise TypeError("unaware parser type with no http_accept given")
            http_accept = parser.http_accept

        for mime_type, quality in parse_accept_header(http_accept):
            if not quality:
                continue

            parsers = self.parsers_by_mime_type.setdefault(mime_type, [])

            existing_qualities = sorted(
                (q, i) for i, (q, _) in enumerate(parsers) if q > quality
            )
            index = existing_qualities[0][1] if existing_qualities else 0
            parsers.insert(index, (quality, parser))

    def get_parser_by_mime_type(self, mime_type: str) -> Optional[ParserType[Any]]:
        parsers = self.parsers_by_mime_type.get(mime_type, ())
        if not parsers:
            parsers = self.parsers_by_mime_type.get('*/*', ())
        if parsers:
            return parsers[-1][1]
        return None

    def mount_parser_by_url(self, url: str, parser: ParserType[Any]) -> None:
        url = normalize_url(url)
        self.parsers_by_url[url] = parser

    def get_parser_by_url(self, url: str) -> Optional[ParserType[Any]]:
        # we might change this to have some smarter matching, but YAGNI
        url = normalize_url(url)
        return self.parsers_by_url.get(url)

    def process_feed_for_update(self, feed: FeedForUpdate) -> FeedForUpdate:
        retriever = self.get_retriever(feed.url)
        if not isinstance(retriever, FeedForUpdateRetrieverType):
            return feed
        return retriever.process_feed_for_update(feed)

    def process_entry_pairs(
        self, url: str, mime_type: Optional[str], pairs: Iterable[EntryPair]
    ) -> Iterable[EntryPair]:
        parser, _ = self.get_parser(url, mime_type)
        if not isinstance(parser, EntryPairsParserType):
            return pairs
        return parser.process_entry_pairs(url, pairs)


@contextmanager
def wrap_exceptions(url: str, when: str) -> Iterator[None]:
    try:
        yield
    except ParseError:
        # reader exceptions are pass-through
        raise
    except OSError as e:
        # requests.RequestException is also a subclass of OSError
        raise ParseError(url, message=f"error {when}") from e
    except Exception as e:
        raise ParseError(url, message=f"unexpected error {when}") from e
