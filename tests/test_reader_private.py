from datetime import datetime

import pytest
from fakeparser import Parser
from fakeparser import ParserThatRemembers

from reader import Entry
from reader import Feed
from reader import FeedNotFoundError


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

    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {entry.as_entry(feed=feed)}

    new_feed = parser.feed(1, datetime(2010, 1, 1), title="new feed title")
    new_entry = parser.entry(1, 1, datetime(2010, 1, 1), title="new entry title")

    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {entry.as_entry(feed=feed)}

    parser.calls[:] = []
    reader._storage.mark_as_stale(feed.url)
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]
    assert set(reader.get_entries()) == {new_entry.as_entry(feed=new_feed)}


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
    assert set(reader.get_entries()) == {
        one.as_entry(feed=feed),
        two.as_entry(feed=feed),
    }
