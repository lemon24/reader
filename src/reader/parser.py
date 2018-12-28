import time
import datetime
import calendar
import logging
import functools
import urllib.parse
import contextlib

import feedparser
import requests

try:
    import feedparser.http as feedparser_http
except ImportError:
    feedparser_http = feedparser

from .types import Feed, Entry, Content, Enclosure
from .exceptions import ParseError, NotModified

log = logging.getLogger('reader')


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
        content,
        enclosures,
        False,
        None,
    )


def _process_feed(url, d):

    if d.get('bozo'):
        exception = d.get('bozo_exception')
        if isinstance(exception, feedparser.CharacterEncodingOverride):
            log.warning("parse %s: got %r", url, exception)
        else:
            raise ParseError(url) from exception

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

    return feed, entries


class RequestsParser:

    def __init__(self):
        self.response_plugins = []
        self._verify = True

    def __call__(self, url, http_etag=None, http_last_modified=None):
        url_split = urllib.parse.urlparse(url)

        if url_split.scheme in ('http', 'https'):
            return self._parse_http(url, http_etag, http_last_modified)

        return self._parse_file(url)

    def _parse_file(self, path):
        # TODO: What about untrusted input?
        result = feedparser.parse(path)
        return _process_feed(path, result) + (None, None)

    def _parse_http(self, url, http_etag, http_last_modified):
        """
        Following the implementation in:
        https://github.com/kurtmckee/feedparser/blob/develop/feedparser/http.py

        "Porting" notes:

        No need to add Accept-encoding (requests seems to do this already).

        No need to add Referer / User-Agent / Authorization / custom request
        headers, as they are not exposed in the reader.parser.parse interface
        (not yet, at least).

        We should add:

        * If-None-Match (http_etag)
        * If-Modified-Since (http_last_modified)
        * Accept (feedparser.(html.)ACCEPT_HEADER)
        * A-IM ("feed")

        """

        headers = {
            'Accept': feedparser_http.ACCEPT_HEADER,
            'A-IM': 'feed',
        }
        if http_etag:
            headers['If-None-Match'] = http_etag
        if http_last_modified:
            headers['If-Modified-Since'] = http_last_modified

        request = requests.Request('GET', url, headers=headers)

        try:
            session = requests.Session()
            response = session.send(session.prepare_request(request),
                                    stream=True, verify=self._verify)

            for plugin in self.response_plugins:
                rv = plugin(session, response, request)
                if rv is None:
                    continue
                assert isinstance(rv, requests.Request)
                response.close()
                request = rv
                response = session.send(session.prepare_request(request),
                                        stream=True, verify=self._verify)

            # Should we raise_for_status()? feedparser.parse() isn't.
            # Should we check the status on the feedparser.parse() result?

            headers = response.headers.copy()
            headers.setdefault('content-location', response.url)

            # with response doesn't work with requests 2.9.1
            with contextlib.closing(response):
                result = feedparser.parse(response.raw, response_headers=headers)

        except Exception as e:
            raise ParseError(url) from e

        if response.status_code == 304:
            raise NotModified(url)

        http_etag = response.headers.get('ETag', http_etag)
        http_last_modified = response.headers.get('Last-Modified', http_last_modified)

        return _process_feed(url, result) + (http_etag, http_last_modified)


