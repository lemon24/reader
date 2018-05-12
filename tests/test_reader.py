from datetime import datetime
import threading

import pytest

from reader import Reader
from reader import Feed, Entry, Content, Enclosure
from reader import FeedExistsError, FeedNotFoundError, ParseError, EntryNotFoundError, StorageError

from fakeparser import Parser, BlockingParser, FailingParser, NotModifiedParser


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
        reader.mark_as_read((feed.url, entry.id))
    finally:
        blocking_parser.can_return_from_parser.set()
        t.join()


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

    assert set(reader.get_feeds()) == {one, Feed(two.url, None, None, None, None)}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == Feed(two.url, None, None, None, None)
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
    entry_tuple = feed.url, entry.id

    with pytest.raises(EntryNotFoundError):
        reader.mark_as_read(entry_tuple)
    with pytest.raises(EntryNotFoundError):
        reader.mark_as_unread(entry_tuple)

    reader.add_feed(feed.url)

    with pytest.raises(EntryNotFoundError):
        reader.mark_as_read(entry_tuple)
    with pytest.raises(EntryNotFoundError):
        reader.mark_as_unread(entry_tuple)

    reader.update_feeds()

    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_read(entry_tuple)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_read(entry_tuple)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_unread(entry_tuple)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_unread(entry_tuple)
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

    reader.mark_as_read((feed.url, entry_one.id))
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
    assert set(reader.get_entries(feed=one.url)) == {(one, entry_one)}
    assert set(reader.get_entries(feed=two.url)) == {(two, entry_two)}

    # TODO: Should this raise an exception?
    assert set(reader.get_entries(feed='bad feed')) == set()

    # TODO: How do we test the combination between which and feed_url?


@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test

    # check unchunked queries still blocks writes
    pytest.param(0, marks=pytest.mark.xfail(raises=StorageError, strict=True)),
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
    reader = Reader(db_path)
    reader.db.execute("PRAGMA busy_timeout = 0;")
    reader.mark_as_read((feed.url, entry.id))
    reader = Reader(db_path)
    reader.db.execute("PRAGMA busy_timeout = 0;")
    reader.mark_as_unread((feed.url, entry.id))

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
        Feed(f.url, None, None, None, None) for f in (one, two)
    }
    assert reader.get_feed(one.url) == Feed(one.url, None, None, None, None)
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


def test_get_feeds_order(reader):
    parser = Parser()
    reader._parse = parser

    feed2 = parser.feed(2, datetime(2010, 1, 2), title='two')
    feed1 = parser.feed(1, datetime(2010, 1, 1), title='one')
    feed3 = parser.feed(3, datetime(2010, 1, 3), title='three')

    reader.add_feed(feed2.url)
    reader.add_feed(feed1.url)
    reader.add_feed(feed3.url)

    assert list(reader.get_feeds()) == [
        Feed(f.url, None, None, None, None) for f in (feed1, feed2, feed3)]

    reader.update_feeds()

    assert list(reader.get_feeds()) == [feed1, feed3, feed2]


def test_set_feed_user_title(reader):
    parser = Parser()
    reader._parse = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    with pytest.raises(FeedNotFoundError):
        reader.set_feed_user_title(one.url, 'blah')

    reader.add_feed(one.url)

    assert reader.get_feed(one.url) == Feed(one.url, None, None, None, None)
    assert list(reader.get_feeds()) == [Feed(one.url, None, None, None, None)]

    reader.set_feed_user_title(one.url, 'blah')

    assert reader.get_feed(one.url) == Feed(one.url, None, None, None, 'blah')
    assert list(reader.get_feeds()) == [Feed(one.url, None, None, None, 'blah')]

    reader.update_feeds()

    assert reader.get_feed(one.url) == one._replace(user_title='blah')
    assert list(reader.get_feeds()) == [one._replace(user_title='blah')]
    assert list(reader.get_entries()) == [(one._replace(user_title='blah'), entry)]

    reader.set_feed_user_title(one.url, None)

    assert reader.get_feed(one.url) == one
    assert list(reader.get_feeds()) == [one]
    assert list(reader.get_entries()) == [(one, entry)]


def test_storage_errors_open(tmpdir):
    # try to open a directory
    with pytest.raises(StorageError):
        Reader(str(tmpdir))


def mark_as_read(reader, feed, entry):
    reader.mark_as_read((feed.url, entry.id))

def mark_as_unread(reader, feed, entry):
    reader.mark_as_unread((feed.url, entry.id))

def add_feed(reader, _, __):
    feed = reader._parse.feed(2)
    reader.add_feed(feed.url)

def remove_feed(reader, feed, __):
    reader.remove_feed(feed.url)

def update_feed(reader, feed, __):
    reader.update_feed(feed.url)

def update_feeds(reader, _, __):
    reader.update_feeds()

def get_feed(reader, feed, __):
    reader.get_feed(feed.url)

def get_feeds(reader, _, __):
    reader.get_feeds()

def get_entries(reader, _, __):
    list(reader.get_entries())

def get_entries_chunk_size_zero(reader, _, __):
    reader._get_entries_chunk_size = 0
    list(reader.get_entries())


@pytest.mark.slow
@pytest.mark.parametrize('do_stuff', [
    mark_as_read,
    mark_as_unread,
    add_feed,
    remove_feed,
    update_feed,
    update_feeds,
    get_feed,
    get_feeds,
    get_entries,
    get_entries_chunk_size_zero,
])
def test_storage_errors_locked(tmpdir, do_stuff):
    db_path = str(tmpdir.join('db.sqlite'))

    parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader = Reader(db_path)
    reader.db.execute("PRAGMA busy_timeout = 0;")
    reader._parse = parser
    reader.add_feed(feed.url)
    reader.update_feeds()

    in_transaction = threading.Event()
    can_return_from_transaction = threading.Event()

    def target():
        reader = Reader(db_path)
        reader.db.isolation_level = None
        reader.db.execute("BEGIN EXCLUSIVE;")
        in_transaction.set()
        can_return_from_transaction.wait()
        reader.db.execute("ROLLBACK;")

    t = threading.Thread(target=target)
    t.start()

    in_transaction.wait()

    try:
        with pytest.raises(StorageError):
            do_stuff(reader, feed, entry)
    finally:
        can_return_from_transaction.set()
        t.join()


def test_data_roundrip(reader):
    parser = Parser()
    reader._parse = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1),
        summary='summary',
        content=(
            Content('value3', 'type', 'en'),
            Content('value2'),
        ),
        enclosures=(
            Enclosure('http://e1', 'type', 1000),
            Enclosure('http://e2'),
        ),
    )

    reader.add_feed(feed.url)
    reader.update_feeds()

    assert list(reader.get_entries()) == [(feed, entry)]

