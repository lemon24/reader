import time
import datetime
import calendar
import logging

import feedparser

from .types import Feed, Entry, Content, Enclosure
from .exceptions import ParseError, NotModified

log = logging.getLogger('reader')


HANDLERS = []

try:
    import certifi
    import ssl
    import urllib.request
    HANDLERS.append(
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where()))
    )
except ImportError:
    pass


def _datetime_from_timetuple(tt):
    return datetime.datetime.utcfromtimestamp(calendar.timegm(tt)) if tt else None

def _get_updated_published(thing, is_rss):
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


def _make_entry(entry, is_rss):
    assert entry.id
    updated, published = _get_updated_published(entry, is_rss)
    assert updated

    content = []
    for data in entry.get('content', ()):
        data = {k: v for k, v in data.items() if k in ('value', 'type', 'language')}
        content.append(Content(**data))
    content = tuple(content)

    enclosures = []
    for data in entry.get('enclosures', ()):
        data = {k: v for k, v in data.items() if k in ('href', 'type', 'length')}
        if 'length' in data:
            try:
                data['length'] = int(data['length'])
            except (TypeError, ValueError):
                del data['length']
        enclosures.append(Enclosure(**data))
    enclosures = tuple(enclosures)

    return Entry(
        entry.id,
        updated,
        entry.get('title'),
        entry.get('link'),
        entry.get('author'),
        published,
        entry.get('summary'),
        content or None,
        enclosures or None,
        False,
        None,
    )


def parse(url, http_etag=None, http_last_modified=None):

    d = feedparser.parse(url, etag=http_etag, modified=http_last_modified,
                         handlers=HANDLERS)

    if d.get('bozo'):
        exception = d.get('bozo_exception')
        if isinstance(exception, feedparser.CharacterEncodingOverride):
            log.warning("parse %s: got %r", url, exception)
        else:
            raise ParseError(url) from exception

    if d.get('status') == 304:
        raise NotModified(url)

    http_etag = d.get('etag', http_etag)
    http_last_modified = d.get('modified', http_last_modified)

    is_rss = d.version.startswith('rss')
    updated, _ = _get_updated_published(d.feed, is_rss)

    feed = Feed(
        url,
        updated,
        d.feed.get('title'),
        d.feed.get('link'),
        d.feed.get('author'),
        None,
    )
    entries = (_make_entry(e, is_rss) for e in d.entries)

    return feed, entries, http_etag, http_last_modified

