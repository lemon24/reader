import calendar
import json
import logging
import mimetypes
import os.path
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import BinaryIO
from typing import Callable
from typing import ContextManager
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import Tuple

import feedparser  # type: ignore
import iso8601
import requests
from typing_extensions import Protocol
from typing_extensions import runtime_checkable

import reader
from ._http_utils import parse_accept_header
from ._http_utils import parse_options_header
from ._http_utils import unparse_accept_header
from ._requests_utils import SessionHooks
from ._requests_utils import SessionWrapper
from ._types import EntryData
from ._types import FeedData
from ._types import ParsedFeed
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
        url,
        updated,
        d.feed.get('title'),
        d.feed.get('link'),
        d.feed.get('author'),
    )
    # This must be a list, not a generator expression,
    # otherwise the user may get a ParseError when calling
    # next(parse_result.entries), i.e. after parse() returned.
    entries = [_make_entry(url, e, is_rss) for e in d.entries]

    return feed, entries


class FeedparserParser:

    # Everything *except* the wildcard, which gets added back explicitly later on.
    # TODO: use parse_accept_header...
    http_accept = feedparser.http.ACCEPT_HEADER.partition(',*/*')[0]

    def __call__(
        self,
        url: str,
        file: BinaryIO,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Tuple[FeedData, Iterable[EntryData[Optional[datetime]]]]:
        """Like feedparser.parse(), but return a feed and entries,
        and re-raise bozo_exception as ParseError.

        url is NOT passed to feedparser; file and headers are.

        """
        # feedparser content sanitization and relative link resolution should be ON.
        # https://github.com/lemon24/reader/issues/125
        # https://github.com/lemon24/reader/issues/157
        result = feedparser.parse(
            file,
            resolve_relative_uris=True,
            sanitize_html=True,
            response_headers=headers,
        )
        return _process_feed(url, result)


# mainly for testing convenience
feedparser_parse = FeedparserParser()


def _dict_get(d, key, value_type):
    value = d.get(key)
    if value is not None:
        if not isinstance(value, value_type):
            # TODO: maybe warn?
            return None
    return value


def _jsonfeed_author(d):
    # from the spec:
    #
    # > JSON Feed version 1 specified a singular author field
    # > instead of the authors array used in version 1.1.
    # > New feeds should use authors, even if only 1 author is needed.
    # > Existing feeds can include both author and authors
    # > for compatibility with existing feed readers.
    # > Feed readers should always prefer authors if present.

    authors = _dict_get(d, 'authors', list)
    if not authors:
        author = _dict_get(d, 'author', dict)
    else:
        author = authors[0]
    if not author:
        return None

    # we only have one for now, it'll be the first one
    return (
        _dict_get(author, 'name', str)
        # fall back to the URL, at least until we have Feed.authors
        or _dict_get(author, 'url', str)
    )


def _parse_jsonfeed_date(s):
    return iso8601.parse_date(s).astimezone(timezone.utc).replace(tzinfo=None)


def _make_jsonfeed_entry(feed_url: str, d: Any, feed_lang: Optional[str]) -> EntryData:
    updated_str = _dict_get(d, 'date_modified', str)
    updated = _parse_jsonfeed_date(updated_str) if updated_str else None
    published_str = _dict_get(d, 'date_published', str)
    published = _parse_jsonfeed_date(published_str) if published_str else None

    # from the spec:
    #
    # > That said, there is one thing we insist on:
    # > any item without an id must be discarded.
    #
    # > If an id is presented as a number, a JSON Feed reader
    # > should coerce it to a string.
    # > If an id is blank or can’t be coerced to a valid string,
    # > the item must be discarded.

    id = _dict_get(d, 'id', (str, int, float))
    if id is not None:
        id = str(id).strip()
    if not id:
        # for now, we'll error out, like we do for feedparser;
        # if we decide to skip, we should do it for *all of them* later
        raise ParseError(feed_url, message="entry with no id")

    lang = _dict_get(d, 'language', str) or feed_lang
    content = []

    content_html = _dict_get(d, 'content_html', str)
    if content_html:
        content.append(Content(content_html, 'text/html', lang))
    content_text = _dict_get(d, 'content_text', str)
    if content_text:
        content.append(Content(content_text, 'text/plain', lang))

    enclosures = []
    for attd in _dict_get(d, 'attachments', list) or ():
        if not isinstance(attd, dict):
            continue
        url = _dict_get(attd, 'url', str)
        if not url:
            continue
        size_in_bytes = _dict_get(attd, 'size_in_bytes', (int, float))
        if size_in_bytes is not None:
            size_in_bytes = int(size_in_bytes)
        enclosures.append(
            Enclosure(url, _dict_get(attd, 'mime_type', str), size_in_bytes)
        )

    return EntryData(
        feed_url=feed_url,
        id=id,
        updated=updated,
        title=_dict_get(d, 'title', str),
        link=_dict_get(d, 'url', str),
        author=_jsonfeed_author(d),
        published=published,
        summary=_dict_get(d, 'summary', str),
        content=tuple(content),
        enclosures=tuple(enclosures),
    )


def _process_jsonfeed_feed(
    url: str, d: Any
) -> Tuple[FeedData, Iterable[EntryData[Optional[datetime]]]]:
    # FIXME: check version, maybe
    # "version": "https://jsonfeed.org/version/1.1",
    # "version": "https://jsonfeed.org/version/1",

    feed = FeedData(
        url=url,
        updated=None,
        title=_dict_get(d, 'title', str),
        link=_dict_get(d, 'home_page_url', str),
        author=_jsonfeed_author(d),
    )
    lang = _dict_get(d, 'language', str)

    entry_dicts = _dict_get(d, 'items', list) or ()
    entries = [_make_jsonfeed_entry(url, e, lang) for e in entry_dicts]

    return feed, entries


class JSONFeedParser:

    """https://jsonfeed.org/version/1.1"""

    http_accept = 'application/feed+json,application/json;q=0.9'

    def __call__(
        self,
        url: str,
        file: BinaryIO,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Tuple[FeedData, Iterable[EntryData[Optional[datetime]]]]:

        # FIXME: catch exception
        result = json.load(file)

        # FIXME: catch valueerrors
        return _process_jsonfeed_feed(url, result)


class RetrieveResult(NamedTuple):
    file: BinaryIO
    mime_type: Optional[str] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None
    headers: Optional[Mapping[str, str]] = None


RetrieverType = Callable[
    [str, Optional[str], Optional[str], Optional[str]], ContextManager[RetrieveResult]
]


class ParserType(Protocol):
    def __call__(
        self, url: str, file: BinaryIO, headers: Optional[Mapping[str, str]]
    ) -> Tuple[FeedData, Iterable[EntryData[Optional[datetime]]]]:  # pragma: no cover
        pass


@runtime_checkable
class AwareParserType(ParserType, Protocol):
    @property
    def http_accept(self) -> str:  # pragma: no cover
        pass


def normalize_url(url: str) -> str:
    # TODO: maybe normalize path as well?
    return urllib.parse.urlunparse(urllib.parse.urlparse(url))


class Parser:

    user_agent = (
        f'python-reader/{reader.__version__} (+https://github.com/lemon24/reader)'
    )

    def __init__(self) -> None:
        self.retrievers: 'OrderedDict[str, RetrieverType]' = OrderedDict()
        self.parsers_by_mime_type: Dict[str, List[Tuple[float, ParserType]]] = {}
        self.parsers_by_url: Dict[str, ParserType] = {}
        self.session_hooks = SessionHooks()

    def mount_retriever(self, prefix: str, retriever: RetrieverType) -> None:
        self.retrievers[prefix] = retriever
        keys_to_move = [k for k in self.retrievers if len(k) < len(prefix)]
        for key in keys_to_move:
            self.retrievers[key] = self.retrievers.pop(key)

    def get_retriever(self, url: str) -> RetrieverType:
        for prefix, retriever in self.retrievers.items():
            if url.lower().startswith(prefix.lower()):
                return retriever
        raise ParseError(url, message="no retriever for URL")

    def get_parser_by_mime_type(self, mime_type: str) -> Optional[ParserType]:
        parsers = self.parsers_by_mime_type.get(mime_type, ())
        if not parsers:
            parsers = self.parsers_by_mime_type.get('*/*', ())
        if parsers:
            return parsers[-1][1]
        return None

    def mount_parser_by_mime_type(
        self, parser: ParserType, http_accept: Optional[str] = None
    ) -> None:
        if not http_accept:
            if not isinstance(parser, AwareParserType):
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

    def get_parser_by_url(self, url: str) -> Optional[ParserType]:
        # we might change this to have some smarter matching, but YAGNI
        url = normalize_url(url)
        return self.parsers_by_url.get(url)

    def mount_parser_by_url(self, url: str, parser: ParserType) -> None:
        url = normalize_url(url)
        self.parsers_by_url[url] = parser

    def __call__(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
    ) -> ParsedFeed:
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

        with retriever(url, http_etag, http_last_modified, http_accept) as result:
            if not parser:
                mime_type = result.mime_type
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
                    raise ParseError(
                        url, message=f"no parser for MIME type {mime_type!r}"
                    )

            feed, entries = parser(
                url,
                result.file,
                result.headers,
            )

        return ParsedFeed(feed, entries, result.http_etag, result.http_last_modified)

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
class FileRetriever:

    """Bare path and file:// URI parser, with support for feed roots,
    per https://github.com/lemon24/reader/issues/155

    """

    feed_root: str

    def __post_init__(self) -> None:
        # give feed_root checks a chance to fail early
        self._normalize_url('known-good-feed-url')

    @contextmanager
    def __call__(self, url: str, *args: Any, **kwargs: Any) -> Iterator[RetrieveResult]:
        try:
            normalized_url = self._normalize_url(url)
        except ValueError as e:
            raise ParseError(url, message=str(e)) from None

        with wrap_exceptions(url, "while reading feed"):
            with open(normalized_url, 'rb') as file:
                yield RetrieveResult(file)

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
        # https://tools.ietf.org/html/rfc3229#section-10.5.3
        headers.setdefault('A-IM', 'feed')
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
class HTTPRetriever:

    """http(s):// retriever that uses Requests.

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

    NOTE: This is a very old docstring, header setting is spread in multiple places

    """

    make_session: _MakeSession

    @contextmanager
    def __call__(
        self,
        url: str,
        http_etag: Optional[str] = None,
        http_last_modified: Optional[str] = None,
        http_accept: Optional[str] = None,
    ) -> Iterator[RetrieveResult]:
        request_headers = {}
        if http_accept:
            request_headers['Accept'] = http_accept

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

            # The content is already decoded by requests/urllib3.
            response_headers.pop('content-encoding', None)
            response.raw.decode_content = True

            content_type = response_headers.get('content-type')
            mime_type: Optional[str]
            if content_type:
                mime_type, _ = parse_options_header(content_type)
            else:
                mime_type = None

            with wrap_exceptions(url, "while reading feed"), response:
                yield RetrieveResult(
                    response.raw,
                    mime_type,
                    http_etag,
                    http_last_modified,
                    response_headers,
                )


def default_parser(feed_root: Optional[str] = None) -> Parser:
    parser = Parser()

    http_retriever = HTTPRetriever(parser.make_session)
    parser.mount_retriever('https://', http_retriever)
    parser.mount_retriever('http://', http_retriever)
    if feed_root is not None:
        # empty string means catch-all
        parser.mount_retriever('', FileRetriever(feed_root))

    parser.mount_parser_by_mime_type(feedparser_parse)
    parser.mount_parser_by_mime_type(JSONFeedParser())
    # fall back to feedparser if there's no better match
    # (replicates feedparser's original behavior)
    parser.mount_parser_by_mime_type(feedparser_parse, '*/*;q=0.1')

    return parser
