from datetime import datetime
import threading

import pytest

from reader.reader import Reader
from reader.types import Feed
from reader.exceptions import FeedExistsError, FeedNotFoundError, ParseError, NotModified, EntryNotFoundError
from fakeparser import Parser, BlockingParser, FailingParser, NotModifiedParser


@pytest.fixture
def reader():
    return Reader(':memory:')


def call_update_feeds(reader, _):
    reader.update_feeds()

def call_update_feed(reader, url):
    reader.update_feed(url)


@pytest.mark.parametrize('call_update_method', [call_update_feeds, call_update_feed])
def test_update_feed_updated(reader, call_update_method):
    """A feed should be processed only if it is newer than the stored one."""

    parser = Parser()
    reader._parse = parser

    old_feed = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(old_feed.url)
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {(old_feed, entry_one)}

    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {(old_feed, entry_one)}

    new_feed = parser.feed(1, datetime(2010, 1, 2))
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {(new_feed, entry_one), (new_feed, entry_two)}


@pytest.mark.parametrize('call_update_method', [call_update_feeds, call_update_feed])
def test_update_entry_updated(reader, call_update_method):
    """An entry should be updated only if it is newer than the stored one."""

    parser = Parser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    old_entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {(feed, old_entry)}

    feed = parser.feed(1, datetime(2010, 1, 2))
    new_entry = old_entry._replace(title='New Entry')
    parser.entries[1][1] = new_entry
    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {(feed, old_entry)}

    feed = parser.feed(1, datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    parser.entries[1][1] = new_entry
    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {(feed, new_entry)}


@pytest.mark.slow
@pytest.mark.parametrize('call_update_method', [call_update_feeds, call_update_feed])
def test_update_blocking(monkeypatch, tmpdir, call_update_method):
    """Calls to reader._parse() shouldn't block the underlying storage."""

    monkeypatch.chdir(tmpdir)
    db_path = str(tmpdir.join('db.sqlite'))

    parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    feed2 = parser.feed(2, datetime(2010, 1, 1))

    reader = Reader(db_path)
    reader._parse = parser

    reader.add_feed(feed.url)
    reader.add_feed(feed2.url)
    reader.update_feeds()

    blocking_parser = BlockingParser.from_parser(parser)

    def target():
        reader = Reader(db_path)
        reader._parse = blocking_parser
        call_update_method(reader, feed.url)

    t = threading.Thread(target=target)
    t.start()

    blocking_parser.in_parser.wait()

    try:
        # shouldn't raise an exception
        reader.mark_as_read(feed.url, entry.id)
    finally:
        blocking_parser.can_return_from_parser.set()
        t.join()

@pytest.mark.parametrize('call_update_method', [call_update_feeds, call_update_feed])
def test_update_not_modified(reader, call_update_method):
    """A feed should not be updated if it was not modified."""

    parser = Parser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    call_update_method(reader, feed.url)

    parser.feed(1, datetime(2010, 1, 2))
    parser.entry(1, 1, datetime(2010, 1, 2))

    not_modified_parser = NotModifiedParser.from_parser(parser)
    reader._parse = not_modified_parser

    # shouldn't raise an exception
    call_update_method(reader, feed.url)

    assert set(reader.get_entries()) == set()


def test_update_feeds_parse_error(reader):
    parser = Parser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader._parse = FailingParser()

    # shouldn't raise an exception
    reader.update_feeds()


def test_update_feed(reader):
    parser = Parser()
    reader._parse = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))

    with pytest.raises(FeedNotFoundError):
        reader.update_feed(one.url)

    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feed(one.url)

    assert set(reader.get_feeds()) == {one, Feed(two.url, None, None, None)}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == Feed(two.url, None, None, None)
    assert set(reader.get_entries()) == {(one, entry_one)}

    reader.update_feed(two.url)

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == two
    assert set(reader.get_entries()) == {(one, entry_one), (two, entry_two)}

    reader._parse = FailingParser()

    with pytest.raises(ParseError):
        reader.update_feed(one.url)


def test_mark_as_read_unread(reader):
    parser = Parser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    with pytest.raises(EntryNotFoundError):
        reader.mark_as_read(feed.url, entry.id)
    with pytest.raises(EntryNotFoundError):
        reader.mark_as_unread(feed.url, entry.id)

    reader.add_feed(feed.url)

    with pytest.raises(EntryNotFoundError):
        reader.mark_as_read(feed.url, entry.id)
    with pytest.raises(EntryNotFoundError):
        reader.mark_as_unread(feed.url, entry.id)

    reader.update_feeds()

    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_read(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_read(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_unread(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_unread(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read


@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test
    0,                                  # unchunked query
])
def test_get_entries_order(reader, chunk_size):
    reader._get_entries_chunk_size = chunk_size

    parser = Parser()
    reader._parse = parser

    one = parser.feed(1)
    two = parser.feed(2)
    reader.add_feed(two.url)

    parser.entry(2, 1, datetime(2010, 1, 1))
    parser.entry(2, 4, datetime(2010, 1, 4))
    two = parser.feed(2, datetime(2010, 1, 4))
    reader.update_feeds()

    reader.add_feed(one.url)

    parser.entry(1, 1, datetime(2010, 1, 2))
    one = parser.feed(1, datetime(2010, 1, 2))
    reader.update_feeds()

    parser.entry(2, 1, datetime(2010, 1, 5))
    parser.entry(2, 2, datetime(2010, 1, 2))
    two = parser.feed(2, datetime(2010, 1, 5))
    reader.update_feeds()

    parser.entry(1, 2, datetime(2010, 1, 2))
    parser.entry(1, 4, datetime(2010, 1, 3))
    parser.entry(1, 3, datetime(2010, 1, 4))
    one = parser.feed(1, datetime(2010, 1, 6))
    parser.entry(2, 3, datetime(2010, 1, 2))
    parser.entry(2, 5, datetime(2010, 1, 3))
    two = parser.feed(2, datetime(2010, 1, 6))
    reader.update_feeds()

    expected = sorted(
        parser.get_tuples(),
        key=lambda t: (t[1].updated, t[0].url, t[1].id),
        reverse=True)

    assert list(reader.get_entries()) == expected


def test_get_entries_which(reader):
    parser = Parser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.mark_as_read(feed.url, entry_one.id)
    entry_one = entry_one._replace(read=True)

    assert set(reader.get_entries()) == {(feed, entry_one), (feed, entry_two)}
    assert set(reader.get_entries(which='all')) == {(feed, entry_one), (feed, entry_two)}
    assert set(reader.get_entries(which='read')) == {(feed, entry_one)}
    assert set(reader.get_entries(which='unread')) == {(feed, entry_two)}

    with pytest.raises(ValueError):
        set(reader.get_entries(which='bad which'))


def test_get_entries_feed_url(reader):
    parser = Parser()
    reader._parse = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))
    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feeds()

    assert set(reader.get_entries()) == {(one, entry_one), (two, entry_two)}
    assert set(reader.get_entries(feed_url=one.url)) == {(one, entry_one)}
    assert set(reader.get_entries(feed_url=two.url)) == {(two, entry_two)}

    # TODO: Should this raise an exception?
    assert set(reader.get_entries(feed_url='bad feed')) == set()

    # TODO: How do we test the combination between which and feed_url?


@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test

    # check unchunked queries still blocks writes
    pytest.param(0, marks=pytest.mark.xfail(raises=Exception, strict=True)),
])
def test_get_entries_blocking(monkeypatch, tmpdir, chunk_size):
    """Unconsumed reader.get_entries() shouldn't block the underlying storage."""

    monkeypatch.chdir(tmpdir)
    db_path = str(tmpdir.join('db.sqlite'))

    parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    parser.entry(1, 2, datetime(2010, 1, 2))
    parser.entry(1, 3, datetime(2010, 1, 3))

    reader = Reader(db_path)
    reader._parse = parser
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader._get_entries_chunk_size = chunk_size

    entries = reader.get_entries(which='unread')
    next(entries)

    # shouldn't raise an exception
    Reader(db_path).mark_as_read(feed.url, entry.id)
    Reader(db_path).mark_as_unread(feed.url, entry.id)

    # just a sanity check
    assert len(list(entries)) == 3 - 1


def test_add_remove_get_feeds(reader):
    parser = Parser()
    reader._parse = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))

    assert set(reader.get_feeds()) == set()
    assert reader.get_feed(one.url) == None
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedNotFoundError):
        reader.remove_feed(one.url)

    reader.add_feed(one.url)
    reader.add_feed(two.url)

    assert set(reader.get_feeds()) == {
        Feed(f.url, None, None, None) for f in (one, two)
    }
    assert reader.get_feed(one.url) == Feed(one.url, None, None, None)
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedExistsError):
        reader.add_feed(one.url)

    reader.update_feeds()

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(one.url) == one
    assert set(reader.get_entries()) == {(one, entry_one), (two, entry_two)}

    reader.remove_feed(one.url)
    assert set(reader.get_feeds()) == {two}
    assert reader.get_feed(one.url) == None
    assert set(reader.get_entries()) == {(two, entry_two)}

    with pytest.raises(FeedNotFoundError):
        reader.remove_feed(one.url)
