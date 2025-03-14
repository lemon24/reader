from __future__ import annotations

import builtins
import logging
import mimetypes
import shutil
import tempfile
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from typing import cast
from typing import ContextManager

from .._types import FeedForUpdate
from .._utils import MapFunction
from ..exceptions import InvalidFeedURLError
from ..exceptions import ParseError
from ..types import JSONType
from . import AcceptParserType
from . import EntryPair
from . import EntryPairsParserType
from . import F
from . import FeedForUpdateRetrieverType
from . import NotModified
from . import ParsedFeed
from . import ParseResult
from . import ParserType
from . import RetrievedFeed
from . import RetrieveError
from . import RetrieveResult
from . import RetrieverType
from . import wrap_exceptions
from ._http_utils import parse_accept_header
from ._http_utils import unparse_accept_header
from ._url_utils import normalize_url
from .requests import SessionFactory


log = logging.getLogger('reader')


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

        #: :class:`~reader._parser.requests.SessionFactory`
        #: used to create Requests sessions for retrieving feeds.
        #:
        #: Plugins may add request or response hooks to this.
        #:
        self.session_factory = SessionFactory()

    def parallel(
        self,
        feeds: Iterable[F],
        map: MapFunction[Any, Any] = map,
    ) -> Iterable[ParseResult[F, ParseError]]:
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
        with self.session_factory.persistent():
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

                yield cast(ParseResult[F, ParseError], result)

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
            # pass around *all* exception types,
            # unhandled exceptions get swallowed by the thread otherwise
            log.debug("retrieve() exception, traceback follows", exc_info=True)
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

        return self._retrieve(retriever, url, caching_info, accept)

    @contextmanager
    def _retrieve(
        self,
        retriever: RetrieverType[Any],
        url: str,
        caching_info: JSONType | None,
        accept: str | None,
    ) -> Iterator[RetrievedFeed[Any]]:
        with wrap_exceptions(url, 'during retriever'):
            context = retriever(url, caching_info, accept)
            with context as feed:
                if not isinstance(feed, RetrievedFeed):
                    feed = RetrievedFeed(feed)

                if not feed.slow_to_read:
                    yield feed
                    return

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

                with tempfile.TemporaryFile() as temp:
                    shutil.copyfileobj(feed.resource, temp)
                    temp.seek(0)
                    yield feed._replace(resource=temp)

    def parse_fn(
        self, result: RetrieveResult[F, Any, Exception]
    ) -> ParseResult[F, Exception]:
        """:meth:`parse` wrapper used by :meth:`parallel`.

        Takes one argument and does not raise exceptions.

        """
        feed, context = result

        http_info = None
        value: ParsedFeed | None | Exception
        try:
            if isinstance(context, Exception):
                raise context

            with context as retrieved:
                http_info = retrieved.http_info
                value = self.parse(feed.url, retrieved)

        except ParseError as e:
            if isinstance(e, NotModified):
                log.debug("parse_fn(): got not modified")
                value = None
            elif e is context:
                log.debug("parse_fn(): got retrieve error: %s: %s", type(e).__name__, e)
                value = e
            else:
                log.debug("parse_fn(): got parse error: %s: %s", type(e).__name__, e)
                value = e

            if isinstance(e, RetrieveError):
                if not http_info:
                    http_info = e.http_info

        except Exception as e:
            # pass around *all* exception types,
            # unhandled exceptions get swallowed by the thread otherwise
            # (not needed now, but for symmetry with retrieve_fn())
            log.debug("parse_fn(): got unexpected error: %s: %s", type(e).__name__, e)
            value = e

        return ParseResult(feed, value, http_info)

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
        with wrap_exceptions(url, 'during parser'):
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
