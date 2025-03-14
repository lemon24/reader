from __future__ import annotations

from collections.abc import Callable
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import cast
from typing import ContextManager
from typing import Generic
from typing import NamedTuple
from typing import Optional
from typing import Protocol
from typing import runtime_checkable
from typing import TYPE_CHECKING
from typing import TypeVar

from .._types import EntryData
from .._types import EntryForUpdate
from .._types import FeedData
from .._types import FeedForUpdate
from .._utils import lazy_import
from ..exceptions import ParseError
from ..types import _namedtuple_compat
from ..types import JSONType
from .requests import DEFAULT_TIMEOUT
from .requests import Headers
from .requests import SessionFactory
from .requests import TimeoutType


if TYPE_CHECKING:  # pragma: no cover
    from ._lazy import Parser as Parser


__getattr__ = lazy_import(__name__, ['Parser'])


def default_parser(
    feed_root: str | None = None,
    session_timeout: TimeoutType = DEFAULT_TIMEOUT,
    _lazy: bool = True,
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

    def post_init(parser: Parser) -> None:
        from .feedparser import FeedparserParser
        from .http import HTTPRetriever
        from .jsonfeed import JSONFeedParser

        parser.session_factory.timeout = session_timeout

        http_retriever = HTTPRetriever(parser.session_factory.transient)
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

    if not _lazy:
        from . import Parser

        parser = Parser()
        post_init(parser)
    else:
        parser = cast('Parser', LazyParser(post_init))

    return parser


class LazyParser:
    def __init__(self, post_init: Callable[[Parser], None]) -> None:
        self._post_init = post_init
        self._parser: Parser | None = None
        self._calls: dict[str, list[tuple[Any, ...]]] = {}
        self._session_factory = SessionFactory()

    def __getattr__(self, name: str) -> Any:
        self._lazy_init()
        return getattr(self._parser, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith('_'):
            object.__setattr__(self, name, value)
        else:
            self._lazy_init()
            object.__setattr__(self._parser, name, value)

    def __call__(
        self, url: str, caching_info: JSONType | None = None
    ) -> ParsedFeed | None:
        self._lazy_init()
        assert self._parser is not None
        return self._parser(url, caching_info)

    def _lazy_init(self) -> None:
        if self._parser:
            return
        from ._lazy import Parser

        self._parser = parser = Parser()
        parser.session_factory = self._session_factory
        self._post_init(parser)
        for name, calls in self._calls.items():
            method = getattr(parser, name)
            for args in calls:
                method(*args)

    def _lazy_call(self, name: str, *args: Any) -> None:
        if self._parser:  # pragma: no cover
            getattr(self._parser, name)(*args)
        else:
            self._calls.setdefault(name, []).append(args)

    @property
    def session_factory(self) -> SessionFactory:
        return self._session_factory

    def mount_retriever(self, prefix: str, retriever: RetrieverType[Any]) -> None:
        self._lazy_call('mount_retriever', prefix, retriever)

    def mount_parser_by_mime_type(
        self, parser: ParserType[Any], accept: str | None = None
    ) -> None:
        # duplicate Parser check (fail early)
        if not accept:  # pragma: no cover
            if not isinstance(parser, AcceptParserType):
                raise TypeError("unaware parser type with no accept given")
        self._lazy_call('mount_parser_by_mime_type', parser, accept)

    def mount_parser_by_url(self, url: str, parser: ParserType[Any]) -> None:
        self._lazy_call('mount_parser_by_url', url, parser)


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


@dataclass(frozen=True)
class HTTPInfo(_namedtuple_compat):
    """Details about an HTTP response."""

    #: The HTTP status code.
    status: int

    #: The HTTP response headers.
    headers: Headers

    @property
    def retry_after(self) -> datetime | timedelta | None:
        """Parsed Retry-After header.

        None if parsing fails (instead of raising an exception).
        Always a timezone-aware datetime object;
        if timezone information is missing, UTC is assumed.

        """
        # lazy import
        from ._http_utils import parse_date

        value = self.headers.get('retry-after')
        if not value:
            return None

        try:
            seconds = int(value)
        except ValueError:
            return parse_date(value)

        return timedelta(seconds=seconds)


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


class ParseResult(NamedTuple, Generic[F, E]):
    """The result of retrieving and parsing a feed, regardless of the outcome."""

    #: The feed (a :class:`FeedArgument`, usually a :class:`.FeedForUpdate`).
    feed: F

    #: One of:
    #:
    #: * the parsed feed
    #: * :const:`None`, if the feed didn't change
    #: * an exception
    #:
    value: ParsedFeed | None | E

    #: Details about the HTTP response.
    http_info: HTTPInfo | None = None


class ParsedFeed(NamedTuple):
    """A parsed feed."""

    #: The feed.
    feed: FeedData
    #: The entries.
    entries: Collection[EntryData]
    #: The MIME type of the feed resource.
    #: Used by :meth:`~reader._parser.Parser.process_entry_pairs`
    #: to select an appropriate parser.
    mime_type: str | None = None
    #: Caching info passed back to the retriever on the next update.
    #: Usually, the ``ETag`` and ``Last-Modified`` headers.
    caching_info: JSONType | None = None


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
