import calendar
import logging
import os.path
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import Tuple

import feedparser  # type: ignore
import requests
from typing_extensions import Protocol

import reader
from ._requests_utils import SessionHooks
from ._requests_utils import SessionWrapper
from ._types import EntryData
from ._types import FeedData
from ._types import ParsedFeed
from ._types import ParserType
from .exceptions import _NotModified
from .exceptions import ParseError
from .types import Content
from .types import Enclosure


log = logging.getLogger('reader')


def _datetime_from_timetuple(tt: time.struct_time) -> datetime:
    return datetime.utcfromtimestamp(calendar.timegm(tt))


def _get_updated_published(
    thing: Any, is_rss: bool
) -> Tuple[Optional[datetime], Optional[datetime]]:
    def convert(key: str) -> Any:
        # feedparser.FeedParserDict.get('updated') defaults to published
        # for historical reasons; "key in thing" bypasses that
        value = thing[key] if key in thing else None
        return _datetime_from_timetuple(value) if value else None

    updated = convert('updated_parsed')
    published = convert('published_parsed')

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
        raise ParseError(feed_url, message="entry with no id or link fallback")

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
            raise ParseError(url, message="error while parsing feed") from exception

    if not d.version:
        raise ParseError(url, message="unknown feed type")

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


def parse_feed(
    url: str, *args: Any, **kwargs: Any
) -> Tuple[FeedData, Iterable[EntryData[Optional[datetime]]]]:
    """Like feedparser.parse(), but return a feed and entries,
    and re-raise bozo_exception as ParseError.

    url is NOT passed to feedparser; args and kwargs are.

    """
    # feedparser content sanitization and relative link resolution should be ON.
    # https://github.com/lemon24/reader/issues/125
    # https://github.com/lemon24/reader/issues/157
    result = feedparser.parse(
        *args, resolve_relative_uris=True, sanitize_html=True, **kwargs,
    )
    return _process_feed(url, result)


class Parser:

    user_agent = (
        f'python-reader/{reader.__version__} (+https://github.com/lemon24/reader)'
    )

    def __init__(self) -> None:
        self.parsers: 'OrderedDict[str, ParserType]' = OrderedDict()
        self.session_hooks = SessionHooks()

    def mount_parser(self, prefix: str, parser: ParserType) -> None:
        self.parsers[prefix] = parser
        keys_to_move = [k for k in self.parsers if len(k) < len(prefix)]
        for key in keys_to_move:
            self.parsers[key] = self.parsers.pop(key)

    def get_parser(self, url: str) -> ParserType:
        for prefix, parser in self.parsers.items():
            if url.lower().startswith(prefix.lower()):
                return parser
        raise ParseError(url, message="no parser for URL")

    def __call__(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
    ) -> ParsedFeed:
        return self.get_parser(url)(url, http_etag, http_last_modified)

    def make_session(self) -> SessionWrapper:
        session = SessionWrapper(hooks=self.session_hooks.copy())
        if self.user_agent:
            session.session.headers['User-Agent'] = self.user_agent
        return session


@contextmanager
def wrap_exceptions(url: str, when: str) -> Iterator[None]:
    try:
        yield
    except (ParseError, _NotModified):
        # reader exceptions are pass-through
        raise
    except OSError as e:
        # requests.RequestException is also a subclass of OSError
        raise ParseError(url, message=f"error {when}") from e
    except Exception as e:
        raise ParseError(url, message=f"unexpected error {when}") from e


@dataclass
class FileParser:

    """Bare path and file:// URI parser, with support for feed roots,
    per https://github.com/lemon24/reader/issues/155

    """

    feed_root: str

    def __post_init__(self) -> None:
        # give feed_root checks a chance to fail early
        self._normalize_url('known-good-feed-url')

    def __call__(self, url: str, *args: Any, **kwargs: Any) -> ParsedFeed:
        try:
            normalized_url = self._normalize_url(url)
        except ValueError as e:
            raise ParseError(url, message=str(e)) from None

        with wrap_exceptions(url, "while reading feed"):
            with open(normalized_url, 'rb') as file:
                feed, entries = parse_feed(url, file)

        return ParsedFeed(feed, entries)

    def _normalize_url(self, url: str) -> str:
        path = _extract_path(url)
        if self.feed_root:
            path = _resolve_root(self.feed_root, path)
            if _is_windows_device_file(path):
                raise ValueError("path must not be a device file")
        return path


def _extract_path(url: str) -> str:
    """Transform a file URI or a path to a path."""

    url_parsed = urllib.parse.urlparse(url)

    if url_parsed.scheme == 'file':
        if url_parsed.netloc not in ('', 'localhost'):
            raise ValueError("unknown authority for file URI")
        # TODO: maybe disallow query, params, fragment too, to reserve for future uses

        return urllib.request.url2pathname(url_parsed.path)

    if url_parsed.scheme:
        # on Windows, drive is the drive letter or UNC \\host\share;
        # on POSIX, drive is always empty
        drive, _ = os.path.splitdrive(url)

        if not drive:
            # should end up as the same type as "no parsers were found", maybe
            raise ValueError("unknown scheme for file URI")

        # we have a scheme, but we're on Windows and url looks like a path
        return url

    # no scheme, treat as a path
    return url


def _is_abs_path(path: str) -> bool:
    """Return True if path is an absolute pathname.

    Unlike os.path.isabs(), return False on Windows if there's no drive
    (e.g. "\\path").

    """
    is_abs = os.path.isabs(path)
    has_drive = os.name != 'nt' or os.path.splitdrive(path)[0]
    return all([is_abs, has_drive])


def _is_rel_path(path: str) -> bool:
    """Return True if path is a relative pathname.

    Unlike "not os.path.isabs()", return False on windows if there's a drive
    (e.g. "C:path").

    """
    is_abs = os.path.isabs(path)
    has_drive = os.name == 'nt' and os.path.splitdrive(path)[0]
    return not any([is_abs, has_drive])


def _resolve_root(root: str, path: str) -> str:
    """Resolve a path relative to a root, and normalize the result.

    This is a path computation, there's no checks perfomed on the arguments.

    It works like os.normcase(os.path.normpath(os.path.join(root, path))),
    but with additional restrictions:

    * root must be absolute.
    * path must be relative.
    * Directory traversal above the root is not allowed;
      https://en.wikipedia.org/wiki/Directory_traversal_attack

    Symlinks are allowed, as long as they're under the root.

    Note that the '..' components are collapsed with no regard for symlinks.

    """

    # this implementation is based on the requirements / notes in
    # https://github.com/lemon24/reader/issues/155#issuecomment-672324186

    if not _is_abs_path(root):
        raise ValueError(f"root must be absolute: {root!r}")
    if not _is_rel_path(path):
        raise ValueError(f"path must be relative: {path!r}")

    root = os.path.normcase(os.path.normpath(root))

    # we normalize the path **before** symlinks are resolved;
    # i.e. it behaves as realpath -L (logical), not realpath -P (physical).
    # https://docs.python.org/3/library/os.path.html#os.path.normpath
    # https://stackoverflow.com/questions/34865153/os-path-normpath-and-symbolic-links
    path = os.path.normcase(os.path.normpath(os.path.join(root, path)))

    # this means we support symlinks, as long as they're under the root
    # (the target itself may be outside).

    # if we want to prevent symlink targets outside root,
    # we should do it here.

    if not path.startswith(root):
        raise ValueError(f"path cannot be outside root: {path!r}")

    return path


# from https://github.com/pallets/werkzeug/blob/b45ac05b7feb30d4611d6b754bd94334ece4b1cd/src/werkzeug/utils.py#L40
_windows_device_files = (
    "CON",
    "AUX",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "LPT1",
    "LPT2",
    "LPT3",
    "PRN",
    "NUL",
)


def _is_windows_device_file(path: str) -> bool:
    if os.name != 'nt':
        return False
    filename = os.path.basename(os.path.normpath(path)).upper()
    return filename in _windows_device_files


class _MakeSession(Protocol):
    # https://github.com/python/mypy/issues/708#issuecomment-647124281 workaround
    def __call__(self) -> SessionWrapper:  # pragma: no cover
        ...


def caching_get(
    session: SessionWrapper,
    url: str,
    http_etag: Optional[str] = None,
    http_last_modified: Optional[str] = None,
    **kwargs: Any,
) -> Tuple[requests.Response, Optional[str], Optional[str]]:
    headers = dict(kwargs.pop('headers', {}))
    if http_etag:
        headers.setdefault('If-None-Match', http_etag)
    if http_last_modified:
        headers.setdefault('If-Modified-Since', http_last_modified)

    response = session.get(url, headers=headers, **kwargs)

    try:
        response.raise_for_status()
    except Exception as e:
        raise ParseError(url, message="bad HTTP status code") from e

    if response.status_code == 304:
        raise _NotModified(url)

    http_etag = response.headers.get('ETag', http_etag)
    http_last_modified = response.headers.get('Last-Modified', http_last_modified)

    return response, http_etag, http_last_modified


@dataclass
class HTTPParser:

    """
    http(s):// parser that uses Requests.

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

    make_session: _MakeSession

    def __call__(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
    ) -> ParsedFeed:
        request_headers = {'Accept': feedparser.http.ACCEPT_HEADER, 'A-IM': 'feed'}

        # TODO: maybe share the session in the parser?
        # TODO: timeouts!

        with self.make_session() as session:
            with wrap_exceptions(url, "while getting feed"):
                response, http_etag, http_last_modified = caching_get(
                    session,
                    url,
                    http_etag,
                    http_last_modified,
                    headers=request_headers,
                    stream=True,
                )

            response_headers = response.headers.copy()
            response_headers.setdefault('content-location', response.url)

            # Some feeds don't have a content type, which results in
            # feedparser.NonXMLContentType being raised. There are valid feeds
            # with no content type, so we set it anyway and hope feedparser
            # fails in some other way if the feed really is broken.
            # https://github.com/lemon24/reader/issues/108
            response_headers.setdefault('content-type', 'text/xml')

            # The content is already decoded by requests/urllib3.
            response_headers.pop('content-encoding', None)
            response.raw.decode_content = True

            with wrap_exceptions(url, "while reading feed"), response:
                feed, entries = parse_feed(
                    url, response.raw, response_headers=response_headers,
                )

        return ParsedFeed(feed, entries, http_etag, http_last_modified)


def default_parser(feed_root: Optional[str] = None) -> Parser:
    parser = Parser()
    http_parser = HTTPParser(parser.make_session)
    parser.mount_parser('https://', http_parser)
    parser.mount_parser('http://', http_parser)
    if feed_root is not None:
        # empty string means catch-all
        parser.mount_parser('', FileParser(feed_root))
    return parser
