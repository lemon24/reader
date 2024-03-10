from __future__ import annotations

from collections.abc import Callable
from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
from .._types import ParsedFeed
from .._utils import lazy_import
from ..exceptions import ParseError
from ..types import _namedtuple_compat
from .requests import DEFAULT_TIMEOUT
from .requests import Headers
from .requests import SessionFactory
from .requests import TimeoutType


if TYPE_CHECKING:  # pragma: no cover
    from ._lazy import Parser as Parser

__getattr__ = lazy_import(__name__, ['Parser'])


T = TypeVar('T')
T_co = TypeVar('T_co', covariant=True)
T_cv = TypeVar('T_cv', contravariant=True)


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

    def __call__(
        self,
        url: str,
        http_etag: str | None = None,
        http_last_modified: str | None = None,
    ) -> ParsedFeed | None:
        self._lazy_init()
        assert self._parser is not None
        return self._parser(url, http_etag, http_last_modified)

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
        self, parser: ParserType[Any], http_accept: str | None = None
    ) -> None:
        # duplicate Parser check (fail early)
        if not http_accept:  # pragma: no cover
            if not isinstance(parser, HTTPAcceptParserType):
                raise TypeError("unaware parser type with no http_accept given")
        self._lazy_call('mount_parser_by_mime_type', parser, http_accept)

    def mount_parser_by_url(self, url: str, parser: ParserType[Any]) -> None:
        self._lazy_call('mount_parser_by_url', url, parser)


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


@contextmanager
def wrap_cm_exceptions(cm: ContextManager[T], url: str, when: str) -> Iterator[T]:
    with wrap_exceptions(url, when), cm as target:
        yield target
