from __future__ import annotations

import calendar
import logging
import time
import warnings
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import IO
from typing import TYPE_CHECKING

from .._types import EntryData
from .._types import FeedData
from .._vendor import feedparser
from ..exceptions import ParseError
from ..types import Content
from ..types import Enclosure
from ._http_utils import parse_accept_header
from ._http_utils import unparse_accept_header


if TYPE_CHECKING:  # pragma: no cover
    from . import FeedAndEntries
    from .requests import Headers


log = logging.getLogger('reader')


class FeedparserParser:
    # The wildcard gets added back explicitly later on.
    http_accept = unparse_accept_header(
        (v, q)
        for v, q in parse_accept_header(feedparser.http.ACCEPT_HEADER)
        if v != '*/*'
    )

    def __call__(
        self,
        url: str,
        resource: IO[bytes],
        headers: Headers | None = None,
    ) -> FeedAndEntries:
        """Like feedparser.parse(), but return a feed and entries,
        and re-raise bozo_exception as ParseError.

        url is NOT passed to feedparser; resource and headers are.

        """
        # feedparser content sanitization and relative link resolution should be ON.
        # https://github.com/lemon24/reader/issues/125
        # https://github.com/lemon24/reader/issues/157
        result = feedparser.parse(
            resource,
            resolve_relative_uris=True,
            sanitize_html=True,
            response_headers=headers or {},  # type: ignore[arg-type]
        )
        return _process_feed(url, result)


# https://feedparser.readthedocs.io/en/latest/character-encoding.html#handling-incorrectly-declared-encodings
_SURVIVABLE_EXCEPTION_TYPES = (
    feedparser.CharacterEncodingOverride,
    feedparser.NonXMLContentType,
)


def _process_feed(url: str, d: Any) -> tuple[FeedData, list[EntryData]]:
    if d.get('bozo'):
        exception = d.get('bozo_exception')
        if isinstance(exception, _SURVIVABLE_EXCEPTION_TYPES):
            log.warning("parse %s: got %r", url, exception)
        else:
            raise ParseError(url, message="error while parsing feed") from exception

    if not d.version:
        raise ParseError(url, message="unknown feed type")

    is_rss = d.version.startswith('rss')

    feed = FeedData(
        url,
        _get_datetime_attr(d.feed, 'updated_parsed'),
        d.feed.get('title'),
        d.feed.get('link'),
        d.feed.get('author'),
        d.feed.get('subtitle'),
        d.version,
    )

    # entries must be a list, not a generator expression,
    # otherwise the user may get a ParseError when calling
    # next(parse_result.entries), i.e. after parse() returned.
    entries = []
    first_parse_error = None

    for e in d.entries:
        try:
            entry = _process_entry(url, e, is_rss)
        except ParseError as e:
            # Skip entries that raise ParseError with a warning.
            # https://github.com/lemon24/reader/issues/281
            warnings.warn(e, stacklevel=1)
            if not first_parse_error:
                first_parse_error = e
        else:
            entries.append(entry)

    # If all entries failed, raise the first exception.
    if first_parse_error and not entries:
        raise first_parse_error

    return feed, entries


def _get_datetime_attr(thing: Any, key: str) -> datetime | None:
    # feedparser.FeedParserDict.get('updated') defaults to published
    # for historical reasons; "key in thing" bypasses that
    value = thing[key] if key in thing else None
    return _datetime_from_timetuple(value) if value else None


def _datetime_from_timetuple(tt: time.struct_time) -> datetime:
    return datetime.fromtimestamp(calendar.timegm(tt), timezone.utc)


def _process_entry(feed_url: str, entry: Any, is_rss: bool) -> EntryData:
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
        raise ParseError(feed_url, message="entry with no id or fallback")

    content = []
    for data in entry.get('content', ()):
        data = {k: v for k, v in data.items() if k in ('value', 'type', 'language')}
        content.append(Content(**data))

    enclosures = []
    for data in entry.get('enclosures', ()):
        data = {k: v for k, v in data.items() if k in ('href', 'type', 'length')}
        href = data.get('href')
        if not href:
            continue
        if 'length' in data:
            try:
                data['length'] = int(data['length'])
            except (TypeError, ValueError):
                del data['length']
        enclosures.append(Enclosure(**data))

    return EntryData(
        feed_url,
        id,
        _get_datetime_attr(entry, 'updated_parsed'),
        entry.get('title'),
        entry.get('link'),
        entry.get('author'),
        _get_datetime_attr(entry, 'published_parsed'),
        entry.get('summary'),
        tuple(content),
        tuple(enclosures),
    )
