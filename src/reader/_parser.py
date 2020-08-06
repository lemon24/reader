import calendar
import contextlib
import inspect
import logging
import time
from collections import OrderedDict
from dataclasses import astuple
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import Callable
from typing import cast
from typing import Iterable
from typing import Iterator
from typing import Mapping
from typing import Optional
from typing import overload
from typing import Sequence
from typing import Tuple
from typing import TypeVar
from typing import Union

import feedparser  # type: ignore
import requests
from typing_extensions import Protocol

import reader
from ._types import EntryData
from ._types import FeedData
from ._types import ParsedFeed
from .exceptions import _NotModified
from .exceptions import ParseError
from .types import Content
from .types import Enclosure

try:
    import feedparser.http as feedparser_http  # type: ignore
except ImportError:
    feedparser_http = feedparser


log = logging.getLogger('reader')


@contextlib.contextmanager
def _make_feedparser_parse() -> Iterator[Callable[..., Any]]:
    """Force feedparser content sanitization and relative link resolution ON.

    https://github.com/lemon24/reader/issues/125
    https://github.com/lemon24/reader/issues/157

    TODO: This context manager is not needed once feedparser 6.0 is released.

    """

    signature = inspect.signature(feedparser.parse)
    have_kwargs = (
        'resolve_relative_uris' in signature.parameters
        and 'sanitize_html' in signature.parameters
    )

    if have_kwargs:

        def parse(*args: Any, **kwargs: Any) -> Any:
            return feedparser.parse(
                *args, resolve_relative_uris=True, sanitize_html=True, **kwargs
            )

        yield parse

    else:

        # This is in no way thread-safe, but what can you do?
        # TODO: Well, you could use locks to make it threadsafe...
        # https://docs.python.org/3/library/threading.html#lock-objects

        old_RESOLVE_RELATIVE_URIS = feedparser.RESOLVE_RELATIVE_URIS
        old_SANITIZE_HTML = feedparser.SANITIZE_HTML
        feedparser.RESOLVE_RELATIVE_URIS = True
        feedparser.SANITIZE_HTML = True

        try:
            yield feedparser.parse
        finally:
            feedparser.RESOLVE_RELATIVE_URIS = old_RESOLVE_RELATIVE_URIS
            feedparser.SANITIZE_HTML = old_SANITIZE_HTML


@overload
def _datetime_from_timetuple(tt: None) -> None:  # pragma: no cover
    ...


@overload
def _datetime_from_timetuple(tt: time.struct_time) -> datetime:  # pragma: no cover
    ...


def _datetime_from_timetuple(tt: Optional[time.struct_time]) -> Optional[datetime]:
    return datetime.utcfromtimestamp(calendar.timegm(tt)) if tt else None


def _get_updated_published(
    thing: Any, is_rss: bool
) -> Tuple[Optional[datetime], Optional[datetime]]:
    # feed.get and entry.get don't work for updated due historical reasons;
    # from the docs: "As of version 5.1.1, if this key [.updated] doesn't
    # exist but [thing].published does, the value of [thing].published
    # will be returned. [...] This mapping is temporary and will be
    # removed in a future version of feedparser."

    updated = None
    published = None
    if 'updated_parsed' in thing:
        updated = _datetime_from_timetuple(thing.updated_parsed)
    if 'published_parsed' in thing:
        published = _datetime_from_timetuple(thing.published_parsed)

    if published and not updated and is_rss:
        updated, published = published, None

    return updated, published


def _make_entry(
    feed_url: str, entry: Any, is_rss: bool
) -> EntryData[Optional[datetime]]:
    id = entry.get('id')

    # <guid> (entry.id) is not actually required for RSS;
    # <link> is, so we fall back to it.
    # https://github.com/lemon24/reader/issues/170
    # http://www.詹姆斯.com/blog/2006/08/rss-dup-detection
    if not id and is_rss:
        id = entry.get('link')
        log.debug(
            "parse %s: RSS entry does not have (gu)id, falling back to link", feed_url
        )

    if not id:
        # TODO: Pass a message to ParseError explaining why this is an error.
        # at the moment, the user just gets a "ParseError: <feed URL>" message.
        raise ParseError(feed_url)

    updated, published = _get_updated_published(entry, is_rss)

    content = []
    for data in entry.get('content', ()):
        data = {k: v for k, v in data.items() if k in ('value', 'type', 'language')}
        content.append(Content(**data))

    enclosures = []
    for data in entry.get('enclosures', ()):
        data = {k: v for k, v in data.items() if k in ('href', 'type', 'length')}
        if 'length' in data:
            try:
                data['length'] = int(data['length'])
            except (TypeError, ValueError):
                del data['length']
        enclosures.append(Enclosure(**data))

    return EntryData(
        feed_url,
        id,
        updated,
        entry.get('title'),
        entry.get('link'),
        entry.get('author'),
        published,
        entry.get('summary'),
        tuple(content),
        tuple(enclosures),
    )


# https://pythonhosted.org/feedparser/character-encoding.html#handling-incorrectly-declared-encodings
_THINGS_WE_CARE_ABOUT_BUT_ARE_SURVIVABLE = (
    feedparser.CharacterEncodingOverride,
    feedparser.NonXMLContentType,
)


def _process_feed(
    url: str, d: Any
) -> Tuple[FeedData, Iterable[EntryData[Optional[datetime]]]]:

    if d.get('bozo'):
        exception = d.get('bozo_exception')
        if isinstance(exception, _THINGS_WE_CARE_ABOUT_BUT_ARE_SURVIVABLE):
            log.warning("parse %s: got %r", url, exception)
        else:
            raise ParseError(url) from exception

    if not d.version:
        # TODO: pass a message to ParseError explaining what's happening
        raise ParseError(url)

    is_rss = d.version.startswith('rss')
    updated, _ = _get_updated_published(d.feed, is_rss)

    feed = FeedData(
        url, updated, d.feed.get('title'), d.feed.get('link'), d.feed.get('author'),
    )
    # This must be a list, not a generator expression,
    # otherwise the user may get a ParseError when calling
    # next(parse_result.entries), i.e. after parse() returned.
    entries = [_make_entry(url, e, is_rss) for e in d.entries]

    return feed, entries


_ParserType = Callable[[str, Optional[str], Optional[str]], ParsedFeed]


class Parser:

    user_agent = (
        f'python-reader/{reader.__version__} (+https://github.com/lemon24/reader)'
    )

    def __init__(self) -> None:
        self.parsers: 'OrderedDict[str, _ParserType]' = OrderedDict()
        self.session_hooks = SessionHooks()

        self.mount_parser('https://', self._parse_http)
        self.mount_parser('http://', self._parse_http)
        self.mount_parser('', self._parse_file)

    def mount_parser(self, prefix: str, parser: _ParserType) -> None:
        self.parsers[prefix] = parser
        keys_to_move = [k for k in self.parsers if len(k) < len(prefix)]
        for key in keys_to_move:
            self.parsers[key] = self.parsers.pop(key)

    def get_parser(self, url: str) -> _ParserType:
        for prefix, parser in self.parsers.items():
            if url.lower().startswith(prefix.lower()):
                return parser
        raise ParseError(f"no parsers were found for {url!r}")

    def __call__(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
    ) -> ParsedFeed:
        return self.get_parser(url)(url, http_etag, http_last_modified)

    def _parse_file(self, url: str, *args: Any, **kwargs: Any) -> ParsedFeed:
        # TODO: What about untrusted input? https://github.com/lemon24/reader/issues/155
        with _make_feedparser_parse() as parse:
            result = parse(url)
        feed, entries = _process_feed(url, result)
        return ParsedFeed(feed, entries)

    def make_session(self) -> 'SessionWrapper':
        session = SessionWrapper(hooks=self.session_hooks.copy())
        if self.user_agent:
            session.session.headers['User-Agent'] = self.user_agent
        return session

    def _parse_http(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
    ) -> ParsedFeed:
        """
        Following the implementation in:
        https://github.com/kurtmckee/feedparser/blob/develop/feedparser/http.py

        "Porting" notes:

        No need to add Accept-encoding (requests seems to do this already).

        No need to add Referer / User-Agent / Authorization / custom request
        headers, as they are not exposed in the Parser.__call__() interface
        (not yet, at least).

        We should add:

        * If-None-Match (http_etag)
        * If-Modified-Since (http_last_modified)
        * Accept (feedparser.(html.)ACCEPT_HEADER)
        * A-IM ("feed")

        """

        request_headers = {'Accept': feedparser_http.ACCEPT_HEADER, 'A-IM': 'feed'}
        if http_etag:
            request_headers['If-None-Match'] = http_etag
        if http_last_modified:
            request_headers['If-Modified-Since'] = http_last_modified

        try:
            # TODO: maybe share the session in the parser?
            # TODO: timeouts!
            with self.make_session() as session:
                response = session.get(url, headers=request_headers, stream=True)

                # Should we raise_for_status()? feedparser.parse() isn't.
                # Should we check the status on the feedparser.parse() result?

                response_headers = response.headers.copy()
                response_headers.setdefault('content-location', response.url)

                # Some feeds don't have a content type, which results in
                # feedparser.NonXMLContentType being raised. There are valid feeds
                # with no content type, so we set it anyway and hope feedparser
                # fails in some other way if the feed really is broken.
                # https://github.com/lemon24/reader/issues/108
                response_headers.setdefault('content-type', 'text/xml')

                with response, _make_feedparser_parse() as parse:
                    result = parse(response.raw, response_headers=response_headers)

        except Exception as e:
            raise ParseError(url) from e

        if response.status_code == 304:
            raise _NotModified(url)

        http_etag = response.headers.get('ETag', http_etag)
        http_last_modified = response.headers.get('Last-Modified', http_last_modified)

        feed, entries = _process_feed(url, result)
        return ParsedFeed(feed, entries, http_etag, http_last_modified)


_T = TypeVar('_T')


class _RequestPlugin(Protocol):
    def __call__(
        self, session: requests.Session, request: requests.Request, **kwargs: Any,
    ) -> Optional[requests.Request]:  # pragma: no cover
        ...


class _ResponsePlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        response: requests.Response,
        request: requests.Request,
        **kwargs: Any,
    ) -> Optional[requests.Request]:  # pragma: no cover
        ...


@dataclass
class SessionHooks:
    # TODO: add request hooks per the gist below
    # (removed because I didn't want to write tests for them)
    # https://gist.github.com/lemon24/f0adead297010a1afd8255c87a01db78#file-two-py

    request: Sequence[_RequestPlugin] = field(default_factory=list)
    response: Sequence[_ResponsePlugin] = field(default_factory=list)

    def copy(self: _T) -> _T:
        return type(self)(*(list(v) for v in astuple(self)))


@dataclass
class SessionWrapper:

    session: requests.Session = field(default_factory=requests.Session)
    hooks: SessionHooks = field(default_factory=SessionHooks)

    def get(
        self,
        url: Union[str, bytes],
        headers: Optional[Mapping[str, str]] = None,
        params: Union[None, bytes, Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        # kwargs get passed to requests.BaseAdapter.send();
        # can be one of: stream, timeout, verify, cert, proxies

        request = requests.Request('GET', url, headers=headers, params=params)

        for request_hook in self.hooks.request:
            request = request_hook(self.session, request, **kwargs) or request

        response = self.session.send(  # type: ignore
            self.session.prepare_request(request), **kwargs
        )

        for response_hook in self.hooks.response:
            new_request = response_hook(self.session, response, request, **kwargs)
            if new_request is None:
                continue

            # TODO: will this fail if stream=False?
            response.close()

            # TODO: is this assert needed? yes, we should raise a custom exception though
            assert isinstance(new_request, requests.Request)

            request = new_request
            response = self.session.send(  # type: ignore
                self.session.prepare_request(request), **kwargs
            )

        return cast(requests.Response, response)

    def __enter__(self: _T) -> _T:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()
