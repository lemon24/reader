from __future__ import annotations

import builtins
import mimetypes
import shutil
import tempfile
from collections.abc import Callable
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Mapping
from contextlib import contextmanager
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast
from typing import ContextManager
from typing import Generic
from typing import NamedTuple
from typing import Protocol
from typing import runtime_checkable
from typing import TYPE_CHECKING
from typing import TypeVar

from structlog.contextvars import bound_contextvars

from .._types import EntryData
from .._types import EntryForUpdate
from .._types import FeedData
from .._types import FeedForUpdate
from .._utils import exiting
from .._utils import MapFunction
from ..exceptions import InvalidFeedURLError
from ..exceptions import ParseError
from ..types import _namedtuple_compat
from ..types import JSONType
from ._http_utils import parse_accept_header
from ._http_utils import unparse_accept_header
from ._url_utils import normalize_url

if TYPE_CHECKING:  # pragma: no cover
    from werkzeug.datastructures import RequestCacheControl

    from .http import TimeoutType


DEFAULT_TIMEOUT = (3.05, 60)


def default_parser(
    feed_root: str | None = None,
    user_agent: str | None = None,
    session_timeout: TimeoutType = DEFAULT_TIMEOUT,
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
    file_retriever = None
    if feed_root is not None:
        from .file import FileRetriever

        # validate feed_root early
        file_retriever = FileRetriever(feed_root)

    parser = Parser()

    @parser.lazy_init
    def post_init(parser: Parser) -> None:
        from .feedparser import FeedparserParser
        from .http import HTTPRetriever
        from .jsonfeed import JSONFeedParser

        http_retriever = HTTPRetriever(user_agent, session_timeout)
        parser.mount_retriever('https://', http_retriever)
        parser.mount_retriever('http://', http_retriever)
        if file_retriever is not None:
            # empty string means catch-all
            parser.mount_retriever('', file_retriever)

        feedparser_parser = FeedparserParser()
        parser.mount_parser_by_mime_type(feedparser_parser)
        parser.mount_parser_by_mime_type(JSONFeedParser())
        # fall back to feedparser if there's no better match
        # (replicates feedparser's original behavior)
        parser.mount_parser_by_mime_type(feedparser_parser, '*/*;q=0.1')

    return parser


ParserFunc = Callable[['Parser'], Any]
PF = TypeVar('PF', bound=ParserFunc)


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

        self.lazy_init_funcs: list[ParserFunc] = []

    def lazy_init(self, func: PF) -> PF:
        """FIXME: docstring"""
        self.lazy_init_funcs.append(func)
        return func

    def do_lazy_init(self) -> None:
        if not self.lazy_init_funcs:
            return
        while True:
            try:
                func = self.lazy_init_funcs.pop()
            except IndexError:
                break
            else:
                func(self)

    def parallel(
        self,
        feeds: Iterable[F],
        map: MapFunction[Any, Any] = map,
    ) -> Iterable[ParseResult]:
        """Retrieve and parse many feeds, possibly in parallel.

        Yields the parsed feeds, as soon as they are ready.

        Args:
            feeds (iterable(FeedArgument)): An iterable of feeds.
            map (function):
                A :func:`map`-like function;
                the results can be in any order.

        Yields:
            ParseResult:
                The result of retrieving and parsing a feed;
                the :attr:`~ParseResult.feed` is the object passed in ``feeds``.

        """

        with ExitStack() as stack:
            # we may want to make this reentrant at some point
            # (so retrievers don't need to deal with it)
            for retriever in self.retrievers.values():
                if isinstance(retriever, ContextManager):
                    stack.enter_context(retriever)

            # if stuff hangs weirdly during debugging, change this to builtins.map
            retrieve_results = map(self.retrieve_fn, feeds)

            # we could parallelize parse() as well;
            # however, most of the time is spent in pure-Python code,
            # which doesn't benefit from the threads on CPython:
            # https://github.com/lemon24/reader/issues/261#issuecomment-956412131
            parse_results = builtins.map(self.parse_fn, retrieve_results)

            # interestingly, if we "yield from ..." instead of
            # "for x in ...: yield x", mypy 1.11 does not complain
            # about yielding ParseResult[Exception]
            for result in parse_results:
                if isinstance(result.value, Exception):
                    if not isinstance(result.value, ParseError):
                        raise result.value

                    # don't expose parser-internal RetrieveError to callers
                    # TODO: not needed once RetrieveError is public API
                    if isinstance(result.value, RetrieveError):
                        e = result.value
                        value = ParseError(e.url, message=e.message)
                        value.__traceback__ = e.__traceback__
                        value.__cause__ = e.__cause__
                        result = result._replace(value=value)

                yield cast(ParseResult, result)

    def __call__(
        self, url: str, caching_info: JSONType | None = None
    ) -> ParsedFeed | None:
        """Retrieve and parse one feed.

        This is a convenience wrapper over :meth:`parallel`.

        Args:
            feed (str): The feed URL.
            caching_info (JSONType or None):
                :attr:`~RetrievedFeed.caching_info` from the last update.

        Returns:
            ParsedFeed or None:
            The parsed feed or :const:`None`, if the feed didn't change.

        Raises:
            ParseError

        """
        feed = FeedForUpdate(url, caching_info=caching_info)

        (result,) = self.parallel([feed])

        # make whole result available for testing
        if getattr(self, 'set_last_result', False):
            self.last_result = result

        value = result.value
        if isinstance(value, Exception):
            raise value
        return value

    def retrieve_fn(self, feed: F) -> RetrieveResult[F, Any, Exception]:
        """:meth:`retrieve` wrapper used by :meth:`parallel`.

        Takes one argument and does not raise exceptions.

        """
        try:
            context = self.retrieve(feed.url, feed.caching_info)
            return RetrieveResult(feed, context)
        except Exception as e:
            return RetrieveResult(feed, e)

    def retrieve(
        self, url: str, caching_info: JSONType | None = None
    ) -> ContextManager[RetrievedFeed[Any]]:
        """Retrieve a feed.

        Args:
            url (str): The feed URL.
            caching_info (JSONType or None):
                :attr:`~RetrievedFeed.caching_info` from the last update.

        Returns:
            contextmanager(RetrieveResult or None):
            A context manager with the retrieved feed as target.

        Raises:
            ParseError

        """
        parser = self.get_parser_by_url(url)

        accept: str | None
        if not parser:
            accept = unparse_accept_header(
                (mime_type, quality)
                for mime_type, parsers in self.parsers_by_mime_type.items()
                for quality, _ in parsers
            )
        else:
            # URL parsers get the default session / requests Accept (*/*);
            # later, we may use parser.accept, if it exists, but YAGNI
            accept = None

        retriever = self.get_retriever(url)

        with wrap_exceptions(url, 'during retriever'), bound_contextvars(feed=url):
            context = retriever(url, caching_info, accept)

            feed = context.__enter__()
            if not isinstance(feed, RetrievedFeed):
                feed = RetrievedFeed(feed)

            if not feed.slow_to_read:
                return exiting(context, feed)

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

            with exiting(context, None):
                temp = tempfile.TemporaryFile()
                try:
                    shutil.copyfileobj(feed.resource, temp)
                    temp.seek(0)
                except BaseException:
                    temp.close()
                    raise
                else:
                    return exiting(temp, feed._replace(resource=temp))

    def parse_fn(
        self, result: RetrieveResult[F, Any, Exception]
    ) -> ParseResultBase[F, FeedData, EntryData, Exception]:
        """:meth:`parse` wrapper used by :meth:`parallel`.

        Takes one argument and does not raise exceptions.

        """
        feed, context = result

        http_info = None
        value: ParsedFeed | None | Exception

        if isinstance(context, Exception):
            value = context
            if isinstance(context, RetrieveError):
                http_info = context.http_info
            if isinstance(context, NotModified):
                value = None
        else:
            try:
                with context as retrieved:
                    # we assign http_info after parse() to give it a chance
                    # to mutate the retrieved feed – alternatively, we need
                    # a way for parse() to surface information on error
                    try:
                        value = self.parse(feed.url, retrieved)
                    finally:
                        http_info = retrieved.http_info
            except Exception as e:
                value = e

        return ParseResultBase(feed, value, http_info)

    def parse(self, url: str, retrieved: RetrievedFeed[Any]) -> ParsedFeed:
        """Parse a retrieved feed.

        Args:
            url (str): The feed URL.
            retrieved (RetrievedFeed): The retrieved feed.

        Returns:
            ParsedFeed: The feed and entry data.

        Raises:
            ParseError

        """
        parser, mime_type = self.get_parser(url, retrieved.mime_type)
        headers = retrieved.http_info.headers if retrieved.http_info else None
        with wrap_exceptions(url, 'during parser'), bound_contextvars(feed=url):
            feed, entries = parser(url, retrieved.resource, headers)
            entries = list(entries)
        return ParsedFeed(feed, entries, mime_type, retrieved.caching_info)

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
        if parser := self.get_parser_by_url(url):
            return parser, mime_type

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

        if parser := self.get_parser_by_mime_type(mime_type):
            return parser, mime_type

        raise ParseError(url, message=f"no parser for MIME type {mime_type!r}")

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
        self.do_lazy_init()
        for prefix, retriever in self.retrievers.items():
            if url.lower().startswith(prefix.lower()):
                return retriever
        raise ParseError(url, message="no retriever for URL")

    def mount_parser_by_mime_type(
        self, parser: ParserType[Any], accept: str | None = None
    ) -> None:
        """Register a parser to one or more MIME types.

        Args:
            parser (ParserType): The parser.
            accept (str or None):
                The content types the parser supports,
                as an HTTP ``Accept`` header.
                If not given, use the parser's
                :attr:`~AcceptParserType.accept` attribute,
                if it has one.

        Raises:
            TypeError: The parser does not have an
                :attr:`~AcceptParserType.accept` attribute,
                and no ``accept`` was given.

        """
        if not accept:
            if not isinstance(parser, AcceptParserType):
                raise TypeError("unaware parser type with no accept given")
            accept = parser.accept

        for mime_type, quality in parse_accept_header(accept):
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
        self.do_lazy_init()
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
        self.do_lazy_init()
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
        with wrap_exceptions(feed.url, "during retriever.process_feed_for_update()"):
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
        with wrap_exceptions(url, "during parser.process_entry_pairs()"):
            return list(parser.process_entry_pairs(url, pairs))


class FeedArgument(Protocol):  # pragma: no cover
    """Any :class:`~reader._types.FeedForUpdate`-like object."""

    @property
    def url(self) -> str:
        """The feed URL."""

    @property
    def caching_info(self) -> JSONType | None:
        """:attr:`~RetrievedFeed.caching_info` from the last update."""


T = TypeVar('T')
T_co = TypeVar('T_co', covariant=True)
T_cv = TypeVar('T_cv', contravariant=True)
F = TypeVar('F', bound=FeedArgument)
E = TypeVar('E', bound=Exception)

Headers = Mapping[str, str]


@dataclass(frozen=True)
class HTTPInfo(_namedtuple_compat):
    """Details about an HTTP response."""

    #: The HTTP status code.
    status: int

    #: The HTTP response headers.
    headers: Headers

    def get_update_after(self, now: datetime) -> datetime | None:
        """Select the best "update after" date from available headers."""
        rv = []

        if self.status in (429, 503):
            try:
                seconds = int(self.headers.get('retry-after', ''))
                rv.append(now + timedelta(seconds=seconds))
            except ValueError:
                if retry_after := self.parse_date('retry-after', now):
                    rv.append(retry_after)

        # https://httpwg.org/specs/rfc9111.html#calculating.freshness.lifetime
        if cache_control := self.cache_control:

            # no-cache ("don't use cached version without revalidating") and
            # max-age ("can use cached for no more than") are mutually exclusive.
            #
            # If no-cache is present, max-age can / should(?) be ignored
            # (not specified by the RFC, but it's what browsers do[1][2]);
            # thankfully, this doesn't happen very often[1].
            #
            # Note that no-cache doesn't imply anything about ETag,
            # we always do conditional requests if ETag is present.
            #
            # [1]: https://www.fastly.com/blog/cache-control-wild#:~:text=conflicts
            # [2]: https://cache-tests.fyi/?id=cc-resp-no-store-fresh&id=cc-resp-no-cache
            #
            if not cache_control.no_cache:
                if max_age := cache_control.max_age:
                    rv.append(now + timedelta(seconds=max_age))

        elif expires := self.parse_date('expires', now):
            rv.append(expires)

        # TODO: RFC 9111 specifies a Last-Modified fallback heuristic,
        # but it might be better to implement it in the updater
        # as part of https://github.com/lemon24/reader/issues/382

        return max(rv, default=None)

    def parse_date(self, name: str, now: datetime | None = None) -> datetime | None:
        """Parse an HTTP date header and return a timezone-aware datetime.

        Return None if missing or if parsing fails.

        If `now` is given and the Date header is set,
        make the returned value relative to `now`.

        """
        # lazy import
        from ._http_utils import parse_date

        if value := parse_date(self.headers.get(name, '')):
            value = value.astimezone(timezone.utc)
            if now and (date := parse_date(self.headers.get('date', ''))):
                value = now + (value - date)
            return value

        return None

    @property
    def cache_control(self) -> RequestCacheControl | None:
        """Parsed Cache-Control header, or None if missing."""

        # lazy import
        from ._http_utils import parse_cache_control_header

        value = self.headers.get('cache-control')
        if not value:
            return None

        return parse_cache_control_header(value)


class RetrieveError(ParseError):
    """An error occurred while retrieving the feed.

    Can be used by retrievers to pass additional information to the parser.

    """

    def __init__(
        self,
        url: str,
        /,
        message: str = '',
        http_info: HTTPInfo | None = None,
    ) -> None:
        super().__init__(url, message=message)

        #: Details about the HTTP response.
        self.http_info = http_info


class NotModified(RetrieveError):
    """Raised by retrievers to tell the parser that the feed was not modified."""

    _default_message = "not modified"


class RetrieveResult(NamedTuple, Generic[F, T, E]):
    """The result of retrieving a feed, regardless of the outcome."""

    #: The feed (a :class:`FeedArgument`, usually a :class:`FeedForUpdate`).
    feed: F

    #: One of:
    #:
    #: * a context manager with the :class:`RetrievedFeed` as target
    #: * an exception
    #:
    value: ContextManager[RetrievedFeed[T]] | E


@dataclass(frozen=True)
class RetrievedFeed(_namedtuple_compat, Generic[T]):
    """A (successfully) retrieved feed, plus metadata."""

    #: The retrieved resource.
    #: Usually, a readable binary file.
    #: Passed to the parser.
    resource: T

    #: The MIME type of the resource.
    #: Used to select an appropriate parser.
    mime_type: str | None = None

    #: Caching info passed back to the retriever on the next update.
    #: Usually, the ``ETag`` and ``Last-Modified`` headers.
    caching_info: JSONType | None = None

    #: Details about the HTTP response.
    http_info: HTTPInfo | None = None

    #: Allow :class:`Parser` to :meth:`~io.BufferedIOBase.read`
    #: the resource into a temporary file,
    #: and pass that to the parser (as an optimization).
    #: Implies the resource is a readable binary file.
    slow_to_read: bool = False


class RetrieverType(Protocol[T_co]):  # pragma: no cover
    """A callable that knows how to retrieve a feed."""

    def __call__(
        self, url: str, caching_info: JSONType | None, accept: str | None
    ) -> ContextManager[RetrievedFeed[T_co] | T_co]:
        """Retrieve a feed.

        Args:
            feed (str): The feed URL.
            caching_info (JSONType or None):
                :attr:`~RetrievedFeed.caching_info` from the last update.
            accept (str or None):
                Content types to be retrieved, as an HTTP ``Accept`` header.

        Returns:
            contextmanager(RetrievedFeed or None):
            A context manager that has as target either
            a :class:`RetrievedFeed` wrapping the retrieved resource,
            or the bare resource.

        Raises:
            ParseError
            RetrieveError: To pass additional information to the parser.
            NotModified: To tell the parser that the feed was not modified.

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


FD = TypeVar('FD')
ED = TypeVar('ED')


class ParseResultBase(NamedTuple, Generic[F, FD, ED, E]):
    """The result of retrieving and parsing a feed, regardless of the outcome."""

    #: The feed (a :class:`FeedArgument`, usually a :class:`.FeedForUpdate`).
    feed: F

    #: One of:
    #:
    #: * the parsed feed
    #: * :const:`None`, if the feed didn't change
    #: * an exception
    #:
    value: ParsedFeedBase[FD, ED] | None | E

    #: Details about the HTTP response.
    http_info: HTTPInfo | None = None


class ParsedFeedBase(NamedTuple, Generic[FD, ED]):
    """A parsed feed."""

    #: The feed; usually :class:`FeedData`.
    feed: FD
    #: The entries; usually :class:`EntryData`.
    entries: Collection[ED]
    #: The MIME type of the feed resource.
    #: Used by :meth:`~reader._parser.Parser.process_entry_pairs`
    #: to select an appropriate parser.
    mime_type: str | None = None
    #: Caching info passed back to the retriever on the next update.
    #: Usually, the ``ETag`` and ``Last-Modified`` headers.
    caching_info: JSONType | None = None


EntryPairBase = tuple[ED, EntryForUpdate | None]

ParseResult = ParseResultBase[FeedForUpdate, FeedData, EntryData, ParseError]
ParsedFeed = ParsedFeedBase[FeedData, EntryData]
EntryPair = EntryPairBase[EntryData]

FeedAndEntries = tuple[FeedData, Collection[EntryData]]


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
class AcceptParserType(ParserType[T_cv], Protocol):  # pragma: no cover
    """A :class:`ParserType` that knows what content types it can handle."""

    @property
    def accept(self) -> str:
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


@contextmanager
def wrap_exceptions(url: str | ParseError, message: str = '') -> Iterator[None]:
    try:
        yield

    except ParseError:
        # reader exceptions are pass-through
        raise

    except Exception as e:
        exc = ParseError(url, message=message) if isinstance(url, str) else url

        if isinstance(e, OSError):
            # expected exception raised for various I/O errors;
            # requests.RequestException is a subclass of OSError
            raise exc from e

        exc._message = f"unexpected error {exc._message}".rstrip()
        raise exc from e
