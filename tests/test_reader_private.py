from datetime import datetime

import pytest
from fakeparser import Parser
from fakeparser import ParserThatRemembers

from reader import Entry
from reader import Feed
from reader import FeedNotFoundError
from reader import make_reader
from reader._storage import Storage


def test_update_stale(reader, call_update_method):
    """When a feed is marked as stale feeds/entries should be updated
    regardless of their .updated or caching headers.

    """
    parser = ParserThatRemembers()
    parser.http_etag = 'etag'
    parser.http_last_modified = 'last-modified'
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    with pytest.raises(FeedNotFoundError):
        reader._storage.mark_as_stale(feed.url)

    reader.add_feed(feed.url)

    reader._now = lambda: datetime(2010, 1, 1)
    call_update_method(reader, feed.url)

    assert set((f.url, f.title, f.last_updated) for f in reader.get_feeds()) == {
        (feed.url, feed.title, datetime(2010, 1, 1))
    }
    # FIXME: use entry.last_updated once we have it
    assert set((e.id, e.title) for e in reader.get_entries()) == {
        (entry.id, entry.title)
    }

    new_feed = parser.feed(1, datetime(2010, 1, 1), title="new feed title")
    new_entry = parser.entry(1, 1, datetime(2010, 1, 1), title="new entry title")

    # nothing changes after update
    reader._now = lambda: datetime(2010, 1, 2)
    call_update_method(reader, feed.url)
    assert set((f.url, f.title, f.last_updated) for f in reader.get_feeds()) == {
        (feed.url, feed.title, datetime(2010, 1, 1))
    }
    # FIXME: use entry.last_updated once we have it
    assert set((e.id, e.title) for e in reader.get_entries()) == {
        (entry.id, entry.title)
    }

    # but it does if we mark the feed as stale
    parser.calls[:] = []
    reader._storage.mark_as_stale(feed.url)
    reader._now = lambda: datetime(2010, 1, 3)
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]
    assert set((f.url, f.title, f.last_updated) for f in reader.get_feeds()) == {
        (feed.url, new_feed.title, datetime(2010, 1, 3))
    }
    # FIXME: use entry.last_updated once we have it
    assert set((e.id, e.title) for e in reader.get_entries()) == {
        (entry.id, new_entry.title)
    }


def test_update_parse(reader, call_update_method):
    """Updated feeds should pass caching headers back to ._parser()."""

    parser = ParserThatRemembers()
    parser.http_etag = 'etag'
    parser.http_last_modified = 'last-modified'
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]

    parser.calls[:] = []
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, 'etag', 'last-modified')]


def test_post_entry_add_plugins(reader):
    parser = Parser()
    reader._parser = parser

    plugin_calls = []

    def first_plugin(r, e):
        assert r is reader
        plugin_calls.append((first_plugin, e))

    def second_plugin(r, e):
        assert r is reader
        plugin_calls.append((second_plugin, e))

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader._post_entry_add_plugins.append(first_plugin)
    reader.update_feeds()
    assert plugin_calls == [(first_plugin, one)]
    assert set(e.id for e in reader.get_entries()) == {'1, 1'}

    plugin_calls[:] = []

    feed = parser.feed(1, datetime(2010, 1, 2))
    one = parser.entry(1, 1, datetime(2010, 1, 2))
    two = parser.entry(1, 2, datetime(2010, 1, 2))
    reader._post_entry_add_plugins.append(second_plugin)
    reader.update_feeds()
    assert plugin_calls == [
        (first_plugin, two),
        (second_plugin, two),
    ]
    assert set(e.id for e in reader.get_entries()) == {'1, 1', '1, 2'}

    # TODO: What is the expected behavior if a plugin raises an exception?


def test_make_reader_storage():
    storage = Storage(':memory:')
    reader = make_reader('', _storage=storage)
    assert reader._storage is storage
