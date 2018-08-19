from datetime import datetime

import pytest

from reader import FeedNotFoundError, Feed, Entry
from reader.reader import feed_argument, entry_argument

from fakeparser import ParserThatRemembers


def test_update_stale(reader, call_update_method):
    """When a feed is marked as stale feeds/entries should be updated
    regardless of their .updated or caching headers.

    """
    parser = ParserThatRemembers()
    parser.http_etag = 'etag'
    parser.http_last_modified = 'last-modified'
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    with pytest.raises(FeedNotFoundError):
        reader._mark_as_stale(feed.url)

    reader.add_feed(feed.url)

    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {entry._replace(feed=feed)}

    new_feed = parser.feed(1, datetime(2010, 1, 1), title="new feed title")
    new_entry = parser.entry(1, 1, datetime(2010, 1, 1), title="new entry title")

    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {entry._replace(feed=feed)}

    parser.calls[:] = []
    reader._mark_as_stale(feed.url)
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]
    assert set(reader.get_entries()) == {new_entry._replace(feed=new_feed)}


def test_update_parse(reader, call_update_method):
    """Updated feeds should pass caching headers back to ._parse()."""

    parser = ParserThatRemembers()
    parser.http_etag = 'etag'
    parser.http_last_modified = 'last-modified'
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]

    parser.calls[:] = []
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, 'etag', 'last-modified')]


def test_feed_argument():
    feed = Feed('url')
    assert feed_argument(feed) == feed.url
    assert feed_argument(feed.url) == feed.url
    with pytest.raises(ValueError):
        feed_argument(1)

def test_entry_argument():
    feed = Feed('url')
    entry = Entry('entry', 'updated', feed=feed)
    entry_tuple = feed.url, entry.id
    assert entry_argument(entry) == entry_tuple
    assert entry_argument(entry_tuple) == entry_tuple
    with pytest.raises(ValueError):
        entry_argument(1)
    with pytest.raises(ValueError):
        entry_argument('ab')
    with pytest.raises(ValueError):
        entry_argument((1, 'b'))
    with pytest.raises(ValueError):
        entry_argument(('a', 2))
    with pytest.raises(ValueError):
        entry_argument(('a', 'b', 'c'))


