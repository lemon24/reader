from datetime import datetime, timedelta
import threading
from enum import Enum

import pytest

from reader import Reader
from reader import Feed, Entry, Content, Enclosure
from reader import FeedExistsError, FeedNotFoundError, ParseError, EntryNotFoundError, StorageError

from reader.core.storage import Storage

from fakeparser import Parser, BlockingParser, FailingParser, NotModifiedParser

from utils import make_url_base


def test_update_feed_updated(reader, call_update_method):
    """If a feed is not newer than the stored one, it should not be updated,
    but its entries should be processed anyway.

    Details in https://github.com/lemon24/reader/issues/76

    """

    parser = Parser()
    reader._parser = parser

    old_feed = parser.feed(1, datetime(2010, 1, 1), title='old')
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(old_feed.url)
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {entry_one._replace(feed=old_feed)}

    parser.feed(1, datetime(2010, 1, 1), title='old-different-title')
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=old_feed),
        entry_two._replace(feed=old_feed),
    }

    parser.feed(1, datetime(2009, 1, 1), title='even-older')
    entry_three = parser.entry(1, 3, datetime(2010, 2, 1))
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=old_feed),
        entry_two._replace(feed=old_feed),
        entry_three._replace(feed=old_feed),
    }

    new_feed = parser.feed(1, datetime(2010, 1, 2), title='new')
    entry_four = parser.entry(1, 4, datetime(2010, 2, 1))
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=new_feed),
        entry_two._replace(feed=new_feed),
        entry_three._replace(feed=new_feed),
        entry_four._replace(feed=new_feed),
    }


def test_update_entry_updated(reader, call_update_method):
    """An entry should be updated only if it is newer than the stored one."""

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    old_entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {old_entry._replace(feed=feed)}

    feed = parser.feed(1, datetime(2010, 1, 2))
    new_entry = old_entry._replace(title='New Entry')
    parser.entries[1][1] = new_entry
    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {old_entry._replace(feed=feed)}

    feed = parser.feed(1, datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    parser.entries[1][1] = new_entry
    call_update_method(reader, feed.url)
    assert set(reader.get_entries()) == {new_entry._replace(feed=feed)}


@pytest.mark.parametrize('chunk_size', [Reader._get_entries_chunk_size, 1])
def test_update_no_updated(reader, chunk_size, call_update_method):
    """If a feed has updated == None, it should be treated as updated.

    If an entry has updated == None, it should:

    * be updated every time, but
    * have updated set to the first time it was updated until it has a new
      updated != None

    This means a stored entry always has updated set.

    https://github.com/lemon24/reader/issues/88

    """
    reader._get_entries_chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, None, title='old')
    entry_one = parser.entry(1, 1, None, title='old')
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 1, 1)
    call_update_method(reader, feed)

    assert set(reader.get_feeds()) == {feed}
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=feed, updated=datetime(2010, 1, 1)),
    }

    feed = parser.feed(1, None, title='new')
    entry_one = parser.entry(1, 1, None, title='new')
    entry_two = parser.entry(1, 2, None)
    reader._now = lambda: datetime(2010, 1, 2)
    call_update_method(reader, feed)

    assert set(reader.get_feeds()) == {feed}
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=feed, updated=datetime(2010, 1, 1)),
        entry_two._replace(feed=feed, updated=datetime(2010, 1, 2)),
    }


@pytest.mark.slow
def test_update_blocking(db_path, call_update_method):
    """Calls to reader._parser() shouldn't block the underlying storage."""

    parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    feed2 = parser.feed(2, datetime(2010, 1, 1))

    reader = Reader(db_path)
    reader._parser = parser

    reader.add_feed(feed.url)
    reader.add_feed(feed2.url)
    reader.update_feeds()

    blocking_parser = BlockingParser.from_parser(parser)

    def target():
        reader = Reader(db_path)
        reader._parser = blocking_parser
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
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    call_update_method(reader, feed.url)

    parser.feed(1, datetime(2010, 1, 2))
    parser.entry(1, 1, datetime(2010, 1, 2))

    not_modified_parser = NotModifiedParser.from_parser(parser)
    reader._parser = not_modified_parser

    # shouldn't raise an exception
    call_update_method(reader, feed.url)

    assert set(reader.get_entries()) == set()


def test_update_new_only(reader):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(one.url)
    reader.update_feeds(new_only=True)

    assert len(set(reader.get_feeds())) == 1
    assert set(reader.get_entries()) == set()

    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))
    reader.add_feed(two.url)
    reader.update_feeds(new_only=True)

    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_two._replace(feed=two),
    }

    reader.update_feeds()

    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=one),
        entry_two._replace(feed=two),
    }


def test_update_new_only_no_last_updated(reader):
    """A feed should be updated if it has no last_updated.

    https://github.com/lemon24/reader/issues/95

    """
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    # updated must be None if last_updated is None
    reader._storage.update_feed(feed.url, feed._replace(updated=None),
                                None, None, last_updated=None)

    reader.update_feeds(new_only=True)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new_only=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


def test_update_new_only_not_modified(reader):
    """A feed should not be considered new anymore after getting NotModified.

    https://github.com/lemon24/reader/issues/95

    """
    parser = NotModifiedParser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader._storage.update_feed(feed.url, feed, None, None, last_updated=None)

    reader.update_feeds(new_only=True)

    parser = Parser.from_parser(parser)
    reader._parser = parser

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new_only=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


def test_update_last_updated_entries_updated_feed_not_updated(reader, call_update_method):
    """A feed's last_updated should be updated if any of its entries are,
    even if the feed itself isn't updated.

    """
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 1, 1)
    call_update_method(reader, feed.url)

    feed_for_update, = reader._storage.get_feeds_for_update(url=feed.url)
    assert feed_for_update.last_updated ==  datetime(2010, 1, 1)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader._now = lambda: datetime(2010, 1, 2)
    call_update_method(reader, feed.url)

    feed_for_update, = reader._storage.get_feeds_for_update(url=feed.url)
    assert feed_for_update.last_updated ==  datetime(2010, 1, 2)


def test_update_feeds_parse_error(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader._parser = FailingParser()

    # shouldn't raise an exception
    reader.update_feeds()


class FeedAction(Enum):
    none = object()
    update = object()

class EntryAction(Enum):
    none = object()
    insert = object()
    update = object()


@pytest.mark.slow
@pytest.mark.parametrize('feed_action, entry_action', [
    (f, e)
    for f in FeedAction
    for e in EntryAction
    if (f, e) != (FeedAction.none, EntryAction.none)
])
def test_update_feed_deleted(db_path, call_update_method,
                             feed_action, entry_action):
    """reader.update_feed should raise FeedNotFoundError if the feed is
    deleted during parsing.

    reader.update_feeds shouldn't (but should log).

    """

    parser = Parser()
    reader = Reader(db_path)
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader.update_feeds()

    if entry_action is not EntryAction.none:
        parser.entry(1, 1, datetime(2010, 1, 1))
        if entry_action is EntryAction.update:
            reader.update_feeds()
            parser.entry(1, 1, datetime(2010, 1, 2))

    if feed_action is FeedAction.update:
        feed = parser.feed(1, datetime(2010, 1, 2))

    blocking_parser = BlockingParser.from_parser(parser)

    def target():
        try:
            blocking_parser.in_parser.wait()
            reader = Reader(db_path)
            reader.remove_feed(feed.url)
        finally:
            blocking_parser.can_return_from_parser.set()

    t = threading.Thread(target=target)
    t.start()

    try:
        reader._parser = blocking_parser
        if call_update_method.__name__ == 'call_update_feed':
            with pytest.raises(FeedNotFoundError) as excinfo:
                call_update_method(reader, feed.url)
            assert excinfo.value.url == feed.url
        elif call_update_method.__name__ == 'call_update_feeds':
            # shouldn't raise an exception
            call_update_method(reader, feed.url)
        else:
            assert False, "shouldn't happen"
    finally:
        t.join()


def test_update_feed(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))

    with pytest.raises(FeedNotFoundError):
        reader.update_feed(feed_arg(one))

    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feed(feed_arg(one))

    assert set(reader.get_feeds()) == {one, Feed(two.url, None, None, None, None)}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == Feed(two.url, None, None, None, None)
    assert set(reader.get_entries()) == {entry_one._replace(feed=one)}

    reader.update_feed(feed_arg(two))

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == two
    assert set(reader.get_entries()) == {
        entry_one._replace(feed=one),
        entry_two._replace(feed=two),
    }

    reader._parser = FailingParser()

    with pytest.raises(ParseError):
        reader.update_feed(feed_arg(one))


def test_mark_as_read_unread(reader, entry_arg):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    entry_with_feed = entry._replace(feed=feed)

    with pytest.raises(EntryNotFoundError):
        reader.mark_as_read(entry_arg(entry_with_feed))
    with pytest.raises(EntryNotFoundError):
        reader.mark_as_unread(entry_arg(entry_with_feed))

    reader.add_feed(feed.url)

    with pytest.raises(EntryNotFoundError):
        reader.mark_as_read(entry_arg(entry_with_feed))
    with pytest.raises(EntryNotFoundError):
        reader.mark_as_unread(entry_arg(entry_with_feed))

    reader.update_feeds()

    entry, = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_read(entry_arg(entry_with_feed))
    entry, = list(reader.get_entries())
    assert entry.read

    reader.mark_as_read(entry_arg(entry_with_feed))
    entry, = list(reader.get_entries())
    assert entry.read

    reader.mark_as_unread(entry_arg(entry_with_feed))
    entry, = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_unread(entry_arg(entry_with_feed))
    entry, = list(reader.get_entries())
    assert not entry.read


class FakeNow:

    def __init__(self, start, step):
        self.now = start
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


GET_ENTRIES_ORDER_DATA = {
    'all_newer_than_threshold': (timedelta(100), [
        '1 3 2010-01-04',
        '1 4 2010-01-03',
        '2 3 2010-01-02',
        '1 2 2010-01-02',
        '2 5 2009-12-20',
        '2 2 2010-01-02',
        '1 1 2010-01-02',
        '2 1 2010-01-05',
        '2 4 2010-01-04',
    ]),
    'all_older_than_threshold': (timedelta(0), [
        '2 1 2010-01-05',
        '2 4 2010-01-04',
        '1 3 2010-01-04',
        '1 4 2010-01-03',
        '2 3 2010-01-02',
        '2 2 2010-01-02',
        '1 2 2010-01-02',
        '1 1 2010-01-02',
        '2 5 2009-12-20',
    ]),
    'some_older_than_threshold': (Storage.recent_threshold, [
        '1 3 2010-01-04',
        '1 4 2010-01-03',
        '2 1 2010-01-05',
        '2 4 2010-01-04',
        # published or updated >= timedelta(3)
        '2 3 2010-01-02',
        '2 2 2010-01-02',
        '1 2 2010-01-02',
        '1 1 2010-01-02',
        '2 5 2009-12-20',
    ]),
}

@pytest.mark.parametrize('order_data_key', GET_ENTRIES_ORDER_DATA)
@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test
    0,                                  # unchunked query
])
def test_get_entries_order(reader, chunk_size, order_data_key):
    """Entries should be sorted descending by (with decreasing priority):

    * entry first updated (only if newer than _storage.recent_threshold)
    * entry published
    * entry updated
    * feed URL
    * order of entry in feed
    * entry id

    https://github.com/lemon24/reader/issues/97
    https://github.com/lemon24/reader/issues/106
    https://github.com/lemon24/reader/issues/113

    """

    # TODO: Break this into smaller tests; working with it for #113 was a pain.

    reader._get_entries_chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser
    reader._now = FakeNow(datetime(2010, 1, 1), timedelta(microseconds=1))

    one = parser.feed(1)
    two = parser.feed(2)
    reader.add_feed(two.url)

    parser.entry(2, 1, datetime(2010, 1, 1), published=datetime(2010, 1, 1))
    parser.entry(2, 4, datetime(2010, 1, 4))
    two = parser.feed(2, datetime(2010, 1, 4))
    reader._now.now = datetime(2010, 1, 2)
    reader.update_feeds()

    reader.add_feed(one.url)

    parser.entry(1, 1, datetime(2010, 1, 2))
    one = parser.feed(1, datetime(2010, 1, 2))
    reader._now.now = datetime(2010, 1, 3)
    reader.update_feeds()

    parser.entry(2, 1, datetime(2010, 1, 5))
    parser.entry(2, 2, datetime(2010, 1, 2))
    two = parser.feed(2, datetime(2010, 1, 5))
    reader._now.now = datetime(2010, 1, 4)
    reader.update_feeds()

    parser.entry(1, 2, datetime(2010, 1, 2))
    parser.entry(1, 4, datetime(2010, 1, 3))
    parser.entry(1, 3, datetime(2010, 1, 4))
    one = parser.feed(1, datetime(2010, 1, 6))
    parser.entry(2, 3, datetime(2010, 1, 2))
    parser.entry(2, 5, datetime(2010, 1, 3), published=datetime(2009, 12, 20))
    two = parser.feed(2, datetime(2010, 1, 6))
    reader._now.now = datetime(2010, 1, 5)
    reader.update_feeds()

    recent_threshold, expected = GET_ENTRIES_ORDER_DATA[order_data_key]

    reader._storage.recent_threshold = recent_threshold
    reader._now.now = datetime(2010, 1, 6)

    def to_str(e):
        _, _, _, feed, _, entry = e.id.split('/')
        return "{} {} {:%Y-%m-%d}".format(feed, entry, e.published or e.updated)

    assert [to_str(e) for e in reader.get_entries()] == expected


@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test
    0,                                  # unchunked query
])
def test_get_entries_feed_order(reader, chunk_size):
    """All other things being equal, get_entries() should yield entries
    in the order they appear in the feed.

    https://github.com/lemon24/reader/issues/87

    """
    reader._get_entries_chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser
    reader._now = lambda: datetime(2010, 1, 1)

    feed = parser.feed(1, datetime(2010, 1, 1))
    three = parser.entry(1, 3, datetime(2010, 1, 1))
    two = parser.entry(1, 2, datetime(2010, 1, 1))
    four = parser.entry(1, 4, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    have = list(reader.get_entries())
    expected = [e._replace(feed=feed) for e in [three, two, four, one]]
    assert have == expected

    feed = parser.feed(1, datetime(2010, 1, 2))
    del parser.entries[1][1]
    one = parser.entry(1, 1, datetime(2010, 1, 2))
    del parser.entries[1][4]
    four = parser.entry(1, 4, datetime(2010, 1, 2))
    del parser.entries[1][2]
    two = parser.entry(1, 2, datetime(2010, 1, 2))

    reader.update_feeds()

    have = list(reader.get_entries())
    expected = [e._replace(feed=feed) for e in [one, four, two, three]]
    assert have == expected


def test_get_entries_which(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.mark_as_read((feed.url, entry_one.id))
    entry_one = entry_one._replace(read=True)

    entry_one = entry_one._replace(feed=feed)
    entry_two = entry_two._replace(feed=feed)

    assert set(reader.get_entries()) == {entry_one, entry_two}
    assert set(reader.get_entries(which='all')) == {entry_one, entry_two}
    assert set(reader.get_entries(which='read')) == {entry_one}
    assert set(reader.get_entries(which='unread')) == {entry_two}

    with pytest.raises(ValueError):
        set(reader.get_entries(which='bad which'))


def test_get_entries_feed_url(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))
    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feeds()

    entry_one = entry_one._replace(feed=one)
    entry_two = entry_two._replace(feed=two)

    assert set(reader.get_entries()) == {entry_one, entry_two}
    assert set(reader.get_entries(feed=feed_arg(one))) == {entry_one}
    assert set(reader.get_entries(feed=feed_arg(two))) == {entry_two}

    # TODO: Should this raise an exception?
    assert set(reader.get_entries(feed='bad feed')) == set()

    # TODO: How do we test the combination between which and feed_url?


def test_add_remove_get_feeds(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))

    assert set(reader.get_feeds()) == set()
    assert reader.get_feed(feed_arg(one)) == None
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedNotFoundError):
        reader.remove_feed(feed_arg(one))

    reader.add_feed(feed_arg(one))
    reader.add_feed(feed_arg(two))

    assert set(reader.get_feeds()) == {
        Feed(f.url, None, None, None, None) for f in (one, two)
    }
    assert reader.get_feed(feed_arg(one)) == Feed(one.url, None, None, None, None)
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedExistsError):
        reader.add_feed(feed_arg(one))

    reader.update_feeds()

    entry_one = entry_one._replace(feed=one)
    entry_two = entry_two._replace(feed=two)

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(feed_arg(one)) == one
    assert set(reader.get_entries()) == {entry_one, entry_two}

    reader.remove_feed(feed_arg(one))
    assert set(reader.get_feeds()) == {two}
    assert reader.get_feed(feed_arg(one)) == None
    assert set(reader.get_entries()) == {entry_two}

    with pytest.raises(FeedNotFoundError):
        reader.remove_feed(feed_arg(one))

    with pytest.raises(ValueError):
        set(reader.get_feeds(sort='bad sort'))


def test_get_feeds_order_title(reader):
    """When sort='title', feeds should be sorted by (with decreasing
    priority):

    * feed user_title or feed title; feeds that have neither should appear first
    * feed URL

    https://github.com/lemon24/reader/issues/29
    https://github.com/lemon24/reader/issues/102

    """
    parser = Parser()
    reader._parser = parser

    feed2 = parser.feed(2, datetime(2010, 1, 2), title='two')
    feed1 = parser.feed(1, datetime(2010, 1, 1), title='one')
    feed3 = parser.feed(3, datetime(2010, 1, 3), title='three')
    feed4 = parser.feed(4, datetime(2010, 1, 1))
    feed5 = parser.feed(5, datetime(2010, 1, 1))

    reader.add_feed(feed2.url)
    reader.add_feed(feed1.url)
    reader.add_feed(feed3.url)
    reader.add_feed(feed4.url)
    reader.add_feed(feed5.url)

    assert list(reader.get_feeds()) == [
        Feed(f.url, None, None, None, None) for f in (feed1, feed2, feed3, feed4, feed5)]

    reader.update_feeds()
    reader.set_feed_user_title(feed5, 'five')

    assert list(reader.get_feeds()) == [
        feed4, feed5._replace(user_title='five'), feed1, feed3, feed2]


def test_get_feeds_order_title_case_insensitive(reader):
    """When sort='title', feeds should be sorted by title in a case
    insensitive way.

    https://github.com/lemon24/reader/issues/103

    """
    parser = Parser()
    reader._parser = parser

    feed1 = parser.feed(1, datetime(2010, 1, 1), title='aaa')
    feed2 = parser.feed(2, datetime(2010, 1, 2), title='bbb')
    feed3 = parser.feed(3, datetime(2010, 1, 3), title='Aba')

    reader.add_feed(feed1.url)
    reader.add_feed(feed2.url)
    reader.add_feed(feed3.url)

    reader.update_feeds()

    assert list(reader.get_feeds()) == [feed1, feed3, feed2]


def test_get_feeds_order_added(reader):
    """When sort='added', feeds should be sorted by (with decreasing
    priority):

    * feed added, descending (feeds that don't have it should appear last)
    * feed URL

    https://github.com/lemon24/reader/issues/98

    """

    parser = Parser()
    reader._parser = parser

    reader._now = lambda: datetime(2010, 1, 1)
    feed1 = parser.feed(1, datetime(2010, 1, 2))
    reader.add_feed(feed1.url)

    reader._now = lambda: datetime(2010, 1, 2)
    feed2 = parser.feed(2, datetime(2010, 1, 1))
    reader.add_feed(feed2.url)

    reader._now = lambda: None
    feed3 = parser.feed(3, datetime(2010, 1, 3))
    reader.add_feed(feed3.url)

    assert list(reader.get_feeds(sort='added')) == [
        Feed(f.url, None, None, None, None) for f in [feed2, feed1, feed3]]

    reader.update_feeds()

    assert list(reader.get_feeds(sort='added')) == [feed2, feed1, feed3]


def test_set_feed_user_title(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    with pytest.raises(FeedNotFoundError):
        reader.set_feed_user_title(feed_arg(one), 'blah')

    reader.add_feed(one.url)

    assert reader.get_feed(one.url) == Feed(one.url, None, None, None, None, None)
    assert list(reader.get_feeds()) == [Feed(one.url, None, None, None, None, None)]

    reader.set_feed_user_title(feed_arg(one), 'blah')

    assert reader.get_feed(one.url) == Feed(one.url, None, None, None, None, 'blah')
    assert list(reader.get_feeds()) == [Feed(one.url, None, None, None, None, 'blah')]

    reader.update_feeds()

    one_with_title = one._replace(user_title='blah')

    assert reader.get_feed(one.url) == one_with_title
    assert list(reader.get_feeds()) == [one_with_title]
    assert list(reader.get_entries()) == [entry._replace(feed=one_with_title)]

    reader.set_feed_user_title(feed_arg(one), None)

    assert reader.get_feed(one.url) == one
    assert list(reader.get_feeds()) == [one]
    assert list(reader.get_entries()) == [entry._replace(feed=one)]


def test_data_roundrip(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1), author='feed author')
    entry = parser.entry(1, 1, datetime(2010, 1, 1), author='entry author',
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

    assert list(reader.get_entries()) == [entry._replace(feed=feed)]


def test_get_entries_has_enclosure(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.entry(1, 2, datetime(2010, 1, 1), enclosures=())
    three = parser.entry(1, 3, datetime(2010, 1, 1),
        enclosures=(Enclosure('http://e2'), ),
    )

    reader.add_feed(feed.url)
    reader.update_feeds()

    one = one._replace(feed=feed)
    two = two._replace(feed=feed, enclosures=())
    three = three._replace(feed=feed)

    assert set(reader.get_entries()) == {one, two, three}
    assert set(reader.get_entries(has_enclosures=None)) == {one, two, three}
    assert set(reader.get_entries(has_enclosures=False)) == {one, two}
    assert set(reader.get_entries(has_enclosures=True)) == {three}

    with pytest.raises(ValueError):
        set(reader.get_entries(has_enclosures='bad has_enclosures'))


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_integration(reader, feed_type, data_dir):
    feed_filename = 'full.{}'.format(feed_type)
    feed_url = str(data_dir.join(feed_filename))

    reader.add_feed(feed_url)
    reader.update_feeds()

    feed, = reader.get_feeds()
    entries = set(reader.get_entries())

    url_base, rel_base = make_url_base(feed_url)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    assert feed == expected['feed']
    assert entries == {e._replace(feed=feed) for e in expected['entries']}

