from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import IO
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

import iso8601

from .._types import EntryData
from .._types import FeedData
from ..exceptions import ParseError
from ..types import Content
from ..types import Enclosure


if TYPE_CHECKING:  # pragma: no cover
    from . import FeedAndEntries
    from .requests import Headers


class JSONFeedParser:
    """https://jsonfeed.org/version/1.1"""

    accept = 'application/feed+json,application/json;q=0.9'

    def __call__(
        self,
        url: str,
        resource: IO[bytes],
        headers: Headers | None = None,
    ) -> FeedAndEntries:
        try:
            result = json.load(resource)
        except json.JSONDecodeError as e:
            raise ParseError(url, "invalid JSON") from e
        return _process_feed(url, result)


_VERSION_URL_PREFIX = "https://jsonfeed.org/version/"
_VERSIONS = {
    f"{_VERSION_URL_PREFIX}1.1": 'json11',
    f"{_VERSION_URL_PREFIX}1": 'json10',
}
_VERSION_UNKNOWN = 'json'


def _process_feed(url: str, d: Any) -> FeedAndEntries:
    version = _get(d, 'version', str) or ''
    version_lower = version.lower()
    if not version_lower.startswith(_VERSION_URL_PREFIX):
        raise ParseError(url, f"missing or bad JSON Feed version: {version!r}")
    version_code = _VERSIONS.get(version_lower, _VERSION_UNKNOWN)

    feed = FeedData(
        url=url,
        updated=None,
        title=_get(d, 'title', str),
        link=_get(d, 'home_page_url', str),
        author=_get_author(d),
        subtitle=_get(d, 'description', str),
        version=version_code,
    )
    lang = _get(d, 'language', str)

    # TODO: skip entries that raise ParseError with a warning
    entry_dicts = _get(d, 'items', list) or ()
    entries = [_process_entry(url, e, lang) for e in entry_dicts]

    return feed, entries


_T = TypeVar('_T')
_U = TypeVar('_U')
_V = TypeVar('_V')


def _get(
    d: Any,
    key: str,
    value_type: (
        type[_T] | tuple[type[_T], type[_U]] | tuple[type[_T], type[_U], type[_V]]
    ),
) -> _T | _U | _V | None:
    value = d.get(key)
    if value is not None:
        if not isinstance(value, value_type):
            return None
    return cast(Union[_T, _U, _V], value)


def _get_author(d: Any) -> str | None:
    # from the spec:
    #
    # > JSON Feed version 1 specified a singular author field
    # > instead of the authors array used in version 1.1.
    # > New feeds should use authors, even if only 1 author is needed.
    # > Existing feeds can include both author and authors
    # > for compatibility with existing feed readers.
    # > Feed readers should always prefer authors if present.

    author: dict[Any, Any] | None
    for maybe_author in _get(d, 'authors', list) or ():
        if isinstance(maybe_author, dict):
            author = maybe_author
            break
    else:
        author = _get(d, 'author', dict)

    if not author:
        return None

    # we only have one for now, it'll be the first one
    return (
        _get(author, 'name', str)
        # fall back to the URL, at least until we have Feed.authors
        or _get(author, 'url', str)
    )


def _process_entry(feed_url: str, d: Any, feed_lang: str | None) -> EntryData:
    updated_str = _get(d, 'date_modified', str)
    updated = _parse_date(updated_str) if updated_str else None
    published_str = _get(d, 'date_published', str)
    published = _parse_date(published_str) if published_str else None

    # from the spec:
    #
    # > That said, there is one thing we insist on:
    # > any item without an id must be discarded.
    #
    # > If an id is presented as a number, a JSON Feed reader
    # > should coerce it to a string.
    # > If an id is blank or can’t be coerced to a valid string,
    # > the item must be discarded.

    id = _get(d, 'id', (str, int, float))
    if id is not None:
        id = str(id).strip()
    if not id:
        # for now, we'll error out, like we do for feedparser;
        # if we decide to skip, we should do it for *all of them* later
        raise ParseError(feed_url, message="entry with no id")

    lang = _get(d, 'language', str) or feed_lang
    content = []

    content_html = _get(d, 'content_html', str)
    if content_html:
        content.append(Content(content_html, 'text/html', lang))
    content_text = _get(d, 'content_text', str)
    if content_text:
        content.append(Content(content_text, 'text/plain', lang))

    enclosures = []
    for attd in _get(d, 'attachments', list) or ():
        if not isinstance(attd, dict):
            continue
        url = _get(attd, 'url', str)
        if not url:
            continue
        size_in_bytes = _get(attd, 'size_in_bytes', (int, float))
        if size_in_bytes is not None:
            size_in_bytes = int(size_in_bytes)
        enclosures.append(Enclosure(url, _get(attd, 'mime_type', str), size_in_bytes))

    return EntryData(
        feed_url=feed_url,
        id=id,
        updated=updated,
        title=_get(d, 'title', str),
        link=_get(d, 'url', str),
        author=_get_author(d),
        published=published,
        summary=_get(d, 'summary', str),
        content=tuple(content),
        enclosures=tuple(enclosures),
    )


def _parse_date(s: str) -> datetime | None:
    try:
        dt = iso8601.parse_date(s)
    except iso8601.ParseError:
        return None
    assert isinstance(dt, datetime)
    return dt.astimezone(timezone.utc)
