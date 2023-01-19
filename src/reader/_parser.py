from __future__ import annotations

import logging
import mimetypes
import shutil
import tempfile
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from typing import ContextManager
from typing import Generic
from typing import NamedTuple
from typing import Optional
from typing import Protocol
from typing import runtime_checkable
from typing import TypeVar

from ._http_utils import parse_accept_header
from ._http_utils import unparse_accept_header
from ._requests_utils import DEFAULT_TIMEOUT
from ._requests_utils import Headers
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


def default_parser(
    feed_root: str | None = None, session_timeout: TimeoutType = DEFAULT_TIMEOUT
) -> Parser:
    """Create a pre-configured :class:`Parser`.

    Args:
        feed_root (str or None):
            See :func:`~reader.make_reader` for details.
        session_timeout (float or tuple(float, float) or None):
            See :func:`~reader.make_reader` for details.

    Returns:
        Parser: The parser.

    """
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


class Parser:

    """Retrieve and parse feeds by delegating to
    :class:`retrievers <RetrieverType>` and :class:`parsers <ParserType>`.

    To retrieve and parse a single feed,
    you can :meth:`call<__call__>` the parser object directly.

    :class:`~reader.Reader` only uses the following methods:

    * :meth:`parallel`
    * :meth:`validate_url`
    * :meth:`process_feed_for_update`
    * :meth:`process_entry_pairs`

    To add retrievers and parsers:

    * :meth:`mount_retriever`
    * :meth:`mount_parser_by_mime_type`
    * :meth:`mount_parser_by_url`

    The rest of the methods are low-level methods.

    """

    def __init__(self) -> None:
        # Typing the link between parser and retriever would be nice,
        # but seems hard to do; for a simplified version of the problem:
        # https://gist.github.com/lemon24/b9338bea9aef176cbadcbfc25687dcf5
        #
        # Higher Kinded Types might be a way of doing it,
        # https://returns.readthedocs.io/en/latest/pages/hkt.html

        self.retrievers: dict[str, RetrieverType[Any]] = {}
        self.parsers_by_mime_type: dict[str, list[tuple[float, ParserType[Any]]]] = {}
        self.parsers_by_url: dict[str, ParserType[Any]] = {}

        #: :class:`~reader._requests_utils.SessionFactory`
        #: used to create Requests sessions for retrieving feeds.
        #:
        #: Plugins may add request or response hooks to this.
        #:
        self.session_factory = SessionFactory()

    def parallel(
        self,
        feeds: Iterable[FeedArgument],
        map: MapType = map,
        is_parallel: bool = True,
    ) -> Iterable[tuple[FeedArgument, ParsedFeed | None | ParseError]]:
        """Retrieve and parse many feeds, possibly in parallel.

        Yields the parsed feeds, as soon as they are ready.

        Args:
            feeds (iterable(FeedArgument)): An iterable of feeds.
            map (function):
                A :func:`map`-like function;
                the results can be in any order.
            is_parallel (bool): Whether ``map`` runs the tasks in parallel.

        Yields:
            tuple(:class:`FeedArgument`, :class:`~reader._types.ParsedFeed` or :const:`None` or :class:`~reader.ParseError`):

                A (feed, result) pair, where result is either:

                * the parsed feed
                * :const:`None`, if the feed didn't change
                * an exception instance

        """

        def retrieve(
            feed: FeedArgument,
        ) -> tuple[
            FeedArgument, ContextManager[RetrieveResult[Any] | None] | Exception
        ]:
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
        http_etag: str | None = None,
        http_last_modified: str | None = None,
    ) -> ParsedFeed | None:
        """Retrieve and parse one feed.

        This is a convenience wrapper over :meth:`parallel`.

        Args:
            feed (str): The feed URL.
            http_etag (str or None):
                The HTTP ``ETag`` header from the last update.
            http_last_modified (str or None):
                The the HTTP ``Last-Modified`` header from the last update.

        Returns:
            ParsedFeed or None:
            The parsed feed or :const:`None`, if the feed didn't change.

        Raises:
            ParseError

        """
        feed = FeedArgumentTuple(url, http_etag, http_last_modified)

        # is_parallel=True ensures the parser tests cover more code
        ((_, result),) = self.parallel([feed], is_parallel=True)

        if isinstance(result, Exception):
            raise result
        return result

    def retrieve(
        self,
        url: str,
        http_etag: str | None = None,
        http_last_modified: str | None = None,
        is_parallel: bool = False,
    ) -> ContextManager[RetrieveResult[Any] | None]:
        """Retrieve a feed.

        Args:
            url (str): The feed URL.
            http_etag (str or None):
                The HTTP ``ETag`` header from the last update.
            http_last_modified (str or None):
                The the HTTP ``Last-Modified`` header from the last update.
            is_parallel (bool):
                Whether this was called from :meth:`parallel`
                (writes the contents to a temporary file, if possible).

        Returns:
            contextmanager(RetrieveResult or None):
            A context manager that has as target either the result
            or :const:`None`, if the feed didn't change.

        Raises:
            ParseError

        """
        parser = self.get_parser_by_url(url)

        http_accept: str | None
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
            shutil.copyfileobj(result.resource, temp)
            temp.seek(0)

            result = result._replace(resource=temp)

        @contextmanager
        def make_context() -> Iterator[RetrieveResult[Any]]:
            assert result is not None, result  # for mypy
            with wrap_exceptions(url, "while reading feed"), temp:
                yield result

        return make_context()

    def parse(self, url: str, result: RetrieveResult[Any]) -> ParsedFeed:
        """Parse a retrieved feed.

        Args:
            url (str): The feed URL.
            result (RetrieveResult): A retrieve result.

        Returns:
            ParsedFeed: The feed and entry data.

        Raises:
            ParseError

        """
        parser, mime_type = self.get_parser(url, result.mime_type)
        feed, entries = parser(url, result.resource, result.headers)
        return ParsedFeed(
            feed, entries, result.http_etag, result.http_last_modified, mime_type
        )

    def get_parser(
        self, url: str, mime_type: str | None
    ) -> tuple[ParserType[Any], str | None]:
        """Select an appropriate parser for a feed.

        Parsers :meth:`registered by URL <mount_parser_by_url>`
        take precedence over those
        :meth:`registered by MIME type <mount_parser_by_mime_type>`.

        If no MIME type is given, guess it from the URL
        using :func:`mimetypes.guess_type`.
        If the MIME type can't be guessed,
        default to ``application/octet-stream``.

        Args:
            url (str): The feed URL.
            mime_type (str or None): The MIME type of the retrieved resource.

        Returns:
            tuple(ParserType, str):
            The parser, and the (possibly guessed) MIME type.

        Raises:
            ParseError: No parser matches.

        """
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
        """Register a retriever to a URL prefix.

        Retrievers are sorted in descending order by prefix length.

        Args:
            prefix (str): A URL prefix.
            retriever (RetrieverType): The retriever.

        """
        self.retrievers[prefix] = retriever
        keys_to_move = [k for k in self.retrievers if len(k) < len(prefix)]
        for key in keys_to_move:
            self.retrievers[key] = self.retrievers.pop(key)

    def get_retriever(self, url: str) -> RetrieverType[Any]:
        """Get the retriever for a URL.

        Args:
            url (str): The URL.

        Returns:
            RetrieverType: The matching retriever.

        Raises:
            ParseError: No retriever matches the URL.

        """
        for prefix, retriever in self.retrievers.items():
            if url.lower().startswith(prefix.lower()):
                return retriever
        raise ParseError(url, message="no retriever for URL")

    def mount_parser_by_mime_type(
        self, parser: ParserType[Any], http_accept: str | None = None
    ) -> None:
        """Register a parser to one or more MIME types.

        Args:
            parser (ParserType): The parser.
            http_accept (str or None):
                The content types the parser supports,
                as an ``Accept`` HTTP header value.
                If not given, use the parser's
                :attr:`~HTTPAcceptParserType.http_accept` attribute,
                if it has one.

        Raises:
            TypeError: The parser does not have an
                :attr:`~HTTPAcceptParserType.http_accept` attribute,
                and no ``http_accept`` was given.

        """
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

    def get_parser_by_mime_type(self, mime_type: str) -> ParserType[Any] | None:
        """Get a parser for a MIME type.

        Args:
            mime_type (str): The MIME type of the feed resource.

        Returns:
            ParserType: The parser.

        Raises:
            ParseError: No parser matches the MIME type.

        """
        parsers = self.parsers_by_mime_type.get(mime_type, ())
        if not parsers:
            parsers = self.parsers_by_mime_type.get('*/*', ())
        if parsers:
            return parsers[-1][1]
        return None

    def mount_parser_by_url(self, url: str, parser: ParserType[Any]) -> None:
        """Register a parser to an exact URL.

        Args:
            prefix (str): A URL.
            parser (ParserType): The parser.

        """
        url = normalize_url(url)
        self.parsers_by_url[url] = parser

    def get_parser_by_url(self, url: str) -> ParserType[Any] | None:
        """Get a parser that was registered by URL.

        Args:
            url (str): The URL.

        Returns:
            ParserType: The parser.

        Raises:
            ParseError: No parser was registered for the URL.

        """
        # we might change this to have some smarter matching, but YAGNI
        url = normalize_url(url)
        return self.parsers_by_url.get(url)

    def process_feed_for_update(self, feed: FeedForUpdate) -> FeedForUpdate:
        """Change update-relevant information about a feed
        before it is passed to the retriever.

        Delegates to :meth:`~FeedForUpdateRetrieverType.process_feed_for_update`
        of the appropriate retriever.

        Args:
            feed (FeedForUpdate): Feed information.

        Returns:
            FeedForUpdate:
            The passed-in feed information, possibly modified.

        """
        retriever = self.get_retriever(feed.url)
        if not isinstance(retriever, FeedForUpdateRetrieverType):
            return feed
        return retriever.process_feed_for_update(feed)

    def process_entry_pairs(
        self, url: str, mime_type: str | None, pairs: Iterable[EntryPair]
    ) -> Iterable[EntryPair]:
        """Process entry data before being stored.

        Delegates to :meth:`~EntryPairsParserType.process_entry_pairs`
        of the appropriate parser.

        Args:
            url (str): The feed URL.
            mime_type (str or None): The MIME type of the feed.
            pairs (iterable(tuple(EntryData, EntryForUpdate or None))):
                (entry data, entry for update) pairs.

        Returns:
            iterable(tuple(EntryData, EntryForUpdate or None)):
            (entry data, entry for update) pairs, possibly modified.

        """
        parser, _ = self.get_parser(url, mime_type)
        if not isinstance(parser, EntryPairsParserType):
            return pairs
        return parser.process_entry_pairs(url, pairs)


T_co = TypeVar('T_co', covariant=True)
T_cv = TypeVar('T_cv', contravariant=True)


@dataclass(frozen=True)
class RetrieveResult(_namedtuple_compat, Generic[T_co]):
    """The result of retrieving a feed, plus metadata."""

    # should be a NamedTuple, but the typing one became generic only in 3.11,
    # and we don't want to depend on typing_extensions at runtime

    # TODO: coalesce http_etag and http_last_modified into a single thing?

    #: The result of retrieving a feed.
    #: Usually, a readable binary file.
    #: Passed to the parser.
    resource: T_co
    #: The MIME type of the resource.
    #: Used to select an appropriate parser.
    mime_type: str | None = None
    #: The HTTP ``ETag`` header associated with the resource.
    #: Passed back to the retriever on the next update.
    http_etag: str | None = None
    #: The HTTP ``Last-Modified`` header associated with the resource.
    #: Passed back to the retriever on the next update.
    http_last_modified: str | None = None
    #: The HTTP response headers associated with the resource.
    #: Passed to the parser.
    headers: Headers | None = None


class RetrieverType(Protocol[T_co]):  # pragma: no cover

    """A callable that knows how to retrieve a feed."""

    #: Allow :class:`Parser` to :meth:`~io.BufferedIOBase.read`
    #: the result :attr:`~RetrieveResult.resource` into a temporary file,
    #: and pass that to the parser (as an optimization).
    #: Implies the :attr:`~RetrieveResult.resource` is a readable binary file.
    slow_to_read: bool

    def __call__(
        self,
        url: str,
        http_etag: str | None,
        http_last_modified: str | None,
        http_accept: str | None,
    ) -> ContextManager[RetrieveResult[T_co] | None]:
        """Retrieve a feed.

        Args:
            feed (str): The feed URL.
            http_etag (str or None):
                The HTTP ``ETag`` header from the last update.
            http_last_modified (str or None):
                The the HTTP ``Last-Modified`` header from the last update.
            http_accept (str or None):
                Content types to be retrieved, as an HTTP ``Accept`` header.

        Returns:
            contextmanager(RetrieveResult or None):
            A context manager that has as target either the result
            or :const:`None`, if the feed didn't change.

        Raises:
            ParseError

        """

    def validate_url(self, url: str) -> None:
        """Check if ``url`` is valid for this retriever.

        Raises:
            InvalidFeedURLError: If ``url`` is not valid.

        """


@runtime_checkable
class FeedForUpdateRetrieverType(RetrieverType[T_co], Protocol):  # pragma: no cover

    """A :class:`RetrieverType` that can change update-relevant information."""

    def process_feed_for_update(self, feed: FeedForUpdate) -> FeedForUpdate:
        """Change update-relevant information about a feed
        before it is passed to the retriever (:meth:`RetrieverType.__call__`).

        Args:
            feed (FeedForUpdate): Feed information.

        Returns:
            FeedForUpdate:
            The passed-in feed information, possibly modified.

        """


FeedAndEntries = tuple[FeedData, Collection[EntryData]]
EntryPair = tuple[EntryData, Optional[EntryForUpdate]]


class ParserType(Protocol[T_cv]):  # pragma: no cover

    """A callable that knows how to parse a retrieved feed."""

    def __call__(
        self, url: str, resource: T_cv, headers: Headers | None
    ) -> FeedAndEntries:
        """Parse a feed.

        Args:
            resource: The feed resource. Usually, a readable binary file.
            headers (dict(str, str) or None):
                The HTTP response headers associated with the resource.

        Returns:
            tuple(FeedData, collection(EntryData)): The feed and entry data.

        Raises:
            ParseError

        """


@runtime_checkable
class HTTPAcceptParserType(ParserType[T_cv], Protocol):  # pragma: no cover

    """A :class:`ParserType` that knows what content it can handle."""

    @property
    def http_accept(self) -> str:
        """The content types this parser supports,
        as an ``Accept`` HTTP header value.

        """


@runtime_checkable
class EntryPairsParserType(ParserType[T_cv], Protocol):  # pragma: no cover

    """A :class:`ParserType` that can modify entry data before being stored."""

    def process_entry_pairs(
        self, url: str, pairs: Iterable[EntryPair]
    ) -> Iterable[EntryPair]:
        """Process entry data before being stored.

        Args:
            url (str): The feed URL.
            pairs (iterable(tuple(EntryData, EntryForUpdate or None))):
                (entry data, entry for update) pairs.

        Returns:
            iterable(tuple(EntryData, EntryForUpdate or None)):
            (entry data, entry for update) pairs, possibly modified.

        """


class FeedArgument(Protocol):  # pragma: no cover

    """Any :class:`~reader._types.FeedForUpdate`-like object."""

    @property
    def url(self) -> str:
        """The feed URL."""

    @property
    def http_etag(self) -> str | None:
        """The HTTP ``ETag`` header from the last update."""

    @property
    def http_last_modified(self) -> str | None:
        """The the HTTP ``Last-Modified`` header from the last update."""


class FeedArgumentTuple(NamedTuple):
    url: str
    http_etag: str | None = None
    http_last_modified: str | None = None


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
