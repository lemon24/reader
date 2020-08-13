import logging
import threading
from collections import Counter
from datetime import datetime
from datetime import timedelta
from enum import Enum
from itertools import permutations

import pytest
from fakeparser import _NotModifiedParser
from fakeparser import BlockingParser
from fakeparser import FailingParser
from fakeparser import Parser
from utils import make_url_base
from utils import rename_argument

from reader import Content
from reader import Enclosure
from reader import Entry
from reader import EntryNotFoundError
from reader import Feed
from reader import FeedExistsError
from reader import FeedNotFoundError
from reader import make_reader
from reader import MetadataNotFoundError
from reader import ParseError
from reader import Reader
from reader import StorageError
from reader._storage import Storage
from reader._types import FeedUpdateIntent


# TODO: testing added/last_updated everywhere is kinda ugly


def test_update_feed_updated(reader, call_update_method):
    """If a feed is not newer than the stored one, it should not be updated,
    but its entries should be processed anyway.

    Details in https://github.com/lemon24/reader/issues/76

    """

    parser = Parser()
    reader._parser = parser

    old_feed = parser.feed(1, datetime(2010, 1, 1), title='old')
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(old_feed.url)
    reader._now = lambda: datetime(2010, 1, 2)
    call_update_method(reader, old_feed.url)
    feed = old_feed._replace(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2)
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2))
    }

    parser.feed(1, datetime(2010, 1, 1), title='old-different-title')
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 3)
    call_update_method(reader, old_feed.url)
    feed = old_feed._replace(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 3)
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
    }

    even_older_feed = parser.feed(1, datetime(2009, 1, 1), title='even-older')
    entry_three = parser.entry(1, 3, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 4)
    call_update_method(reader, old_feed.url)
    feed = old_feed._replace(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 4)
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
        entry_three.as_entry(feed=feed, last_updated=datetime(2010, 1, 4)),
    }

    new_feed = parser.feed(1, datetime(2010, 1, 2), title='new')
    entry_four = parser.entry(1, 4, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 5)
    feed = new_feed._replace(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 5)
    )
    call_update_method(reader, old_feed.url)
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
        entry_three.as_entry(feed=feed, last_updated=datetime(2010, 1, 4)),
        entry_four.as_entry(feed=feed, last_updated=datetime(2010, 1, 5)),
    }


def test_update_entry_updated(reader, call_update_method):
    """An entry should be updated only if it is newer than the stored one."""

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    old_entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 2, 1)
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 2, 2)
    call_update_method(reader, feed.url)
    feed = feed._replace(added=datetime(2010, 2, 1), last_updated=datetime(2010, 2, 2))
    assert set(reader.get_entries()) == {
        old_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 2))
    }

    feed = parser.feed(1, datetime(2010, 1, 2))
    new_entry = old_entry._replace(title='New Entry')
    parser.entries[1][1] = new_entry
    reader._now = lambda: datetime(2010, 2, 3)
    call_update_method(reader, feed.url)
    feed = feed._replace(added=datetime(2010, 2, 1), last_updated=datetime(2010, 2, 3))
    assert set(reader.get_entries()) == {
        old_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 2))
    }

    feed = parser.feed(1, datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    parser.entries[1][1] = new_entry
    reader._now = lambda: datetime(2010, 2, 4)
    call_update_method(reader, feed.url)
    feed = feed._replace(added=datetime(2010, 2, 1), last_updated=datetime(2010, 2, 4))
    assert set(reader.get_entries()) == {
        new_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 4))
    }


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_update_no_updated(reader, chunk_size, call_update_method):
    """If a feed has updated == None, it should be treated as updated.

    If an entry has updated == None, it should:

    * be updated every time, but
    * have updated set to the first time it was updated until it has a new
      updated != None

    This means a stored entry always has updated set.

    https://github.com/lemon24/reader/issues/88

    """
    reader._storage.chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, None, title='old')
    entry_one = parser.entry(1, 1, None, title='old')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(feed.url)
    call_update_method(reader, feed)
    feed = feed._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1))

    assert set(reader.get_feeds()) == {feed}
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed, updated=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1)
        )
    }

    feed = parser.feed(1, None, title='new')
    entry_one = parser.entry(1, 1, None, title='new')
    entry_two = parser.entry(1, 2, None)
    reader._now = lambda: datetime(2010, 1, 2)
    call_update_method(reader, feed)
    feed = feed._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2))

    assert set(reader.get_feeds()) == {feed}
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed, updated=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2)
        ),
        entry_two.as_entry(
            feed=feed, updated=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 2)
        ),
    }


@pytest.mark.slow
def test_update_blocking(db_path, call_update_method):
    """Calls to reader._parser() shouldn't block the underlying storage."""

    parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    feed2 = parser.feed(2, datetime(2010, 1, 1))

    reader = make_reader(db_path)
    reader._parser = parser

    reader.add_feed(feed.url)
    reader.add_feed(feed2.url)
    reader.update_feeds()

    blocking_parser = BlockingParser.from_parser(parser)

    def target():
        reader = make_reader(db_path)
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

    not_modified_parser = _NotModifiedParser.from_parser(parser)
    reader._parser = not_modified_parser

    # shouldn't raise an exception
    call_update_method(reader, feed.url)

    assert set(reader.get_entries()) == set()


def test_update_new_only(reader):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(one.url)
    reader.update_feeds(new_only=True)

    assert len(set(reader.get_feeds())) == 1
    assert set(reader.get_entries()) == set()

    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 2)
    reader.add_feed(two.url)
    reader.update_feeds(new_only=True)

    two = two._replace(added=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 2))
    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 2))
    }

    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    one = one._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 3))
    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=one, last_updated=datetime(2010, 1, 3)),
        entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 2)),
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
    reader._storage.update_feed(
        FeedUpdateIntent(feed.url, None, feed=feed._replace(updated=None))
    )

    reader.update_feeds(new_only=True)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new_only=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


def test_update_new_only_not_modified(reader):
    """A feed should not be considered new anymore after getting _NotModified.

    https://github.com/lemon24/reader/issues/95

    """
    parser = _NotModifiedParser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader._storage.update_feed(FeedUpdateIntent(feed.url, None, feed=feed))

    reader.update_feeds(new_only=True)

    parser = Parser.from_parser(parser)
    reader._parser = parser

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new_only=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


@pytest.mark.parametrize('workers', [-1, 0])
def test_update_workers(reader, workers):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(one.url)
    with pytest.raises(ValueError):
        reader.update_feeds(workers=workers)


def test_update_last_updated_entries_updated_feed_not_updated(
    reader, call_update_method
):
    """A feed's last_updated should be updated if any of its entries are,
    even if the feed itself isn't updated.

    """
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 1, 1)
    call_update_method(reader, feed.url)

    (feed_for_update,) = reader._storage.get_feeds_for_update(url=feed.url)
    assert feed_for_update.last_updated == datetime(2010, 1, 1)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader._now = lambda: datetime(2010, 1, 2)
    call_update_method(reader, feed.url)

    (feed_for_update,) = reader._storage.get_feeds_for_update(url=feed.url)
    assert feed_for_update.last_updated == datetime(2010, 1, 2)


@pytest.mark.parametrize('workers', [1, 2])
def test_update_feeds_parse_error(reader, workers, caplog):
    caplog.set_level(logging.ERROR, 'reader')

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1), title='one')
    two = parser.feed(2, datetime(2010, 1, 1), title='two')
    three = parser.feed(3, datetime(2010, 1, 1), title='three')

    for feed in one, two, three:
        reader.add_feed(feed.url)
    reader.update_feeds(workers=workers)

    assert {f.title for f in reader.get_feeds()} == {'one', 'two', 'three'}

    parser = FailingParser(condition=lambda url: url == '2')
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 2), title='ONE')
    two = parser.feed(2, datetime(2010, 1, 2), title='TWO')
    three = parser.feed(3, datetime(2010, 1, 2), title='THREE')

    # shouldn't raise an exception
    reader.update_feeds(workers=workers)

    # it should skip 2 and update 3
    assert {f.title for f in reader.get_feeds()} == {'ONE', 'two', 'THREE'}

    # it should log the error, with traceback
    (record,) = caplog.records
    assert record.levelname == 'ERROR'
    exc = record.exc_info[1]
    assert isinstance(exc, ParseError)
    assert exc.url == '2'
    assert str(exc.__cause__) == 'failing'
    assert repr(exc.url) in record.message
    assert repr(exc.__cause__) in record.message


@pytest.fixture
def reader_with_one_feed(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    return reader


@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_not_updated(reader, call_update_method):
    assert reader.get_feed('1').last_exception is None


@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_ok(reader, call_update_method):
    call_update_method(reader, '1')
    assert reader.get_feed('1').last_exception is None
    assert next(reader.get_entries()).feed.last_exception is None


@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_failed(reader, call_update_method):
    call_update_method(reader, '1')
    old_parser = reader._parser

    old_last_updated = next(reader._storage.get_feeds_for_update('1')).last_updated
    assert old_last_updated is not None

    reader._parser = FailingParser()
    try:
        call_update_method(reader, '1')
    except ParseError:
        pass

    # The cause gets stored.
    last_exception = reader.get_feed('1').last_exception
    assert next(reader.get_entries()).feed.last_exception == last_exception
    assert last_exception.type_name == 'builtins.Exception'
    assert last_exception.value_str == 'failing'
    assert last_exception.traceback_str.startswith('Traceback')

    reader._parser.exception = ValueError('another')
    try:
        call_update_method(reader, '1')
    except ParseError:
        pass

    # The cause changes.
    last_exception = reader.get_feed('1').last_exception
    assert last_exception.type_name == 'builtins.ValueError'
    assert last_exception.value_str == 'another'

    # The cause does not get reset if other feeds get updated.
    reader._parser = old_parser
    old_parser.feed(2, datetime(2010, 1, 1))
    reader.add_feed('2')
    reader.update_feeds(new_only=True)
    assert reader.get_feed('1').last_exception == last_exception
    assert reader.get_feed('2').last_exception is None

    # None of the failures bumped last_updated.
    new_last_updated = next(reader._storage.get_feeds_for_update('1')).last_updated
    assert new_last_updated == old_last_updated


def same_parser(parser):
    return parser


def updated_feeds_parser(parser):
    parser.feeds = {
        number: feed._replace(
            updated=feed.updated + timedelta(1), title=f'New title for #{number}'
        )
        for number, feed in parser.feeds.items()
    }
    return parser


def raises_not_modified_parser(_):
    return _NotModifiedParser()


@pytest.mark.parametrize(
    'make_new_parser', [same_parser, updated_feeds_parser, raises_not_modified_parser,]
)
@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_reset(reader, call_update_method, make_new_parser):
    call_update_method(reader, '1')
    old_parser = reader._parser

    reader._parser = FailingParser()
    try:
        call_update_method(reader, '1')
    except ParseError:
        pass

    reader._parser = make_new_parser(old_parser)
    call_update_method(reader, '1')
    assert reader.get_feed('1').last_exception is None


def test_update_feeds_unexpected_error(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1), title='one')
    reader.add_feed(feed.url)

    exc = Exception('unexpected')

    def _update_feed(*_, **__):
        raise exc

    reader._update_feed = _update_feed

    with pytest.raises(Exception) as excinfo:
        reader.update_feeds()

    assert excinfo.value is exc


class FeedAction(Enum):
    none = object()
    update = object()
    fail = object()


class EntryAction(Enum):
    none = object()
    insert = object()
    update = object()


@pytest.mark.slow
@pytest.mark.parametrize(
    'feed_action, entry_action',
    [
        (f, e)
        for f in FeedAction
        for e in EntryAction
        if (f, e) not in {(FeedAction.none, EntryAction.none),}
    ],
)
def test_update_feed_deleted(db_path, call_update_method, feed_action, entry_action):
    """reader.update_feed should raise FeedNotFoundError if the feed is
    deleted during parsing.

    reader.update_feeds shouldn't (but should log).

    """

    parser = Parser()
    reader = make_reader(db_path)
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

    if feed_action is not FeedAction.fail:
        parser_cls = BlockingParser
    else:

        class parser_cls(BlockingParser, FailingParser):
            pass

    blocking_parser = parser_cls.from_parser(parser)

    def target():
        try:
            blocking_parser.in_parser.wait()
            reader = make_reader(db_path)
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
        elif call_update_method.__name__.startswith('call_update_feeds'):
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

    reader._now = lambda: datetime(2010, 1, 1)
    one = one._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1))
    two = two._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1))

    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feed(feed_arg(one))

    assert set(reader.get_feeds()) == {one, Feed(two.url, added=datetime(2010, 1, 1))}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == Feed(two.url, added=datetime(2010, 1, 1))
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=one, last_updated=datetime(2010, 1, 1))
    }

    reader.update_feed(feed_arg(two))

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == two
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=one, last_updated=datetime(2010, 1, 1)),
        entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 1)),
    }

    reader._parser = FailingParser()

    with pytest.raises(ParseError):
        reader.update_feed(feed_arg(one))


def test_mark_as_read_unread(reader, entry_arg):
    # TODO: Test read/unread the same way important/unimportant are (or the other way around).

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    entry_with_feed = entry.as_entry(feed=feed)

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

    (entry,) = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_read(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert entry.read

    reader.mark_as_read(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert entry.read

    reader.mark_as_unread(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_unread(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert not entry.read


class FakeNow:
    def __init__(self, start, step):
        self.now = start
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


def get_entries_default(reader, **kwargs):
    return reader.get_entries(**kwargs)


def get_entries_recent(reader, **kwargs):
    return reader.get_entries(sort='recent', **kwargs)


def get_entries_random(reader, **kwargs):
    return reader.get_entries(sort='random', **kwargs)


def enable_and_update_search(reader):
    reader.enable_search()
    reader.update_search()


def search_entries_default(reader, **kwargs):
    return reader.search_entries('entry', **kwargs)


def search_entries_relevant(reader, **kwargs):
    return reader.search_entries('entry', sort='relevant', **kwargs)


def search_entries_recent(reader, **kwargs):
    return reader.search_entries('entry', sort='recent', **kwargs)


with_call_entries_recent_method = pytest.mark.parametrize(
    'pre_stuff, call_method',
    [
        (lambda _: None, get_entries_default),
        (lambda _: None, get_entries_recent),
        (enable_and_update_search, search_entries_recent),
    ],
)


# use the pre-#141 threshold to avoid updating GET_ENTRIES_ORDER_DATA
GET_ENTRIES_ORDER_RECENT_THRESHOLD = timedelta(3)

GET_ENTRIES_ORDER_DATA = {
    'all_newer_than_threshold': (
        timedelta(100),
        [
            (1, 3, '2010-01-04'),
            (1, 4, '2010-01-03'),
            (2, 3, '2010-01-02'),
            (1, 2, '2010-01-02'),
            (2, 5, '2009-12-20'),
            (2, 2, '2010-01-02'),
            (1, 1, '2010-01-02'),
            (2, 1, '2010-01-05'),
            (2, 4, '2010-01-04'),
        ],
    ),
    'all_older_than_threshold': (
        timedelta(0),
        [
            (2, 1, '2010-01-05'),
            (2, 4, '2010-01-04'),
            (1, 3, '2010-01-04'),
            (1, 4, '2010-01-03'),
            (2, 3, '2010-01-02'),
            (2, 2, '2010-01-02'),
            (1, 2, '2010-01-02'),
            (1, 1, '2010-01-02'),
            (2, 5, '2009-12-20'),
        ],
    ),
    'some_older_than_threshold': (
        GET_ENTRIES_ORDER_RECENT_THRESHOLD,
        [
            (1, 3, '2010-01-04'),
            (1, 4, '2010-01-03'),
            (2, 1, '2010-01-05'),
            (2, 4, '2010-01-04'),
            # published or updated >= timedelta(3)
            (2, 3, '2010-01-02'),
            (2, 2, '2010-01-02'),
            (1, 2, '2010-01-02'),
            (1, 1, '2010-01-02'),
            (2, 5, '2009-12-20'),
        ],
    ),
}


@pytest.mark.parametrize('order_data_key', GET_ENTRIES_ORDER_DATA)
@pytest.mark.parametrize(
    'chunk_size',
    [
        # the default
        Storage.chunk_size,
        # rough result size for this test
        1,
        2,
        3,
        8,
        # unchunked query
        0,
    ],
)
@with_call_entries_recent_method
def test_get_entries_recent_order(
    reader, chunk_size, order_data_key, pre_stuff, call_method
):
    """Entries should be sorted descending by (with decreasing priority):

    * entry first updated (only if newer than _storage.recent_threshold)
    * entry published (or entry updated if published is none)
    * feed URL
    * entry last updated
    * order of entry in feed
    * entry id

    https://github.com/lemon24/reader/issues/97
    https://github.com/lemon24/reader/issues/106
    https://github.com/lemon24/reader/issues/113

    """

    # TODO: Break this into smaller tests; working with it for #113 was a pain.

    reader._storage.chunk_size = chunk_size
    reader._storage.recent_threshold = GET_ENTRIES_ORDER_RECENT_THRESHOLD

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

    pre_stuff(reader)

    assert [eval(e.id) for e in call_method(reader)] == [t[:2] for t in expected]


@pytest.mark.parametrize(
    'chunk_size',
    [
        # the default
        Storage.chunk_size,
        # rough result size for this test
        1,
        2,
        3,
        8,
        # unchunked query
        0,
    ],
)
@with_call_entries_recent_method
def test_get_entries_recent_feed_order(reader, chunk_size, pre_stuff, call_method):
    """All other things being equal, get_entries() should yield entries
    in the order they appear in the feed.

    https://github.com/lemon24/reader/issues/87

    """
    reader._storage.chunk_size = chunk_size

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
    pre_stuff(reader)

    assert [eval(e.id)[1] for e in call_method(reader)] == [3, 2, 4, 1]

    parser.feed(1, datetime(2010, 1, 2))
    del parser.entries[1][1]
    one = parser.entry(1, 1, datetime(2010, 1, 2))
    del parser.entries[1][4]
    four = parser.entry(1, 4, datetime(2010, 1, 2))
    del parser.entries[1][2]
    two = parser.entry(1, 2, datetime(2010, 1, 2))

    reader.update_feeds()
    pre_stuff(reader)

    assert [eval(e.id)[1] for e in call_method(reader)] == [1, 4, 2, 3]


@pytest.mark.parametrize('chunk_size', [1, 2, 3, 4])
def test_get_entries_random(reader, chunk_size):
    """Black box get_entries(sort='random') good enough™ test.

    To have a more open-box test we'd need to:

    * mock SQLite random() to return something predictable (e.g. 0, 1, 2, ...);
      achievable with an application-devined function
    * know the initial order of the entries before ORDER BY random() is applied;
      this is undefined; we could first sort the entries by id in a subquery,
      but this would slow things down unnecessarily when not testing

    Alternatively, we could rewrite the query to ORDER BY random_rank(entry_id);
    random_rank could then return whatever we want during testing,
    and random() otherwise; this would likely add a performance hit.

    """
    reader._storage.chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.entry(1, 2, datetime(2010, 1, 1))
    three = parser.entry(1, 3, datetime(2010, 1, 1))
    four = parser.entry(1, 4, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    # all possible get_entries(sort='random') results
    all_tuples = set(permutations({e.id for e in reader.get_entries()}, chunk_size))

    # some get_entries(sort='random') results
    # (we call it enough times so it's likely we get all the results)
    random_tuples = Counter(
        tuple(e.id for e in reader.get_entries(sort='random'))
        for _ in range(20 * len(all_tuples))
    )

    # check all results are chunk_size length
    # (only true if we have at least chunk_size entries)
    # (already checked by the check below in some way)
    for ids in random_tuples:
        assert len(ids) == chunk_size

    # check all results are "possible" (no wrong results)
    assert set(random_tuples).difference(all_tuples) == set()

    # check all possible results were generated
    # (this may fail, but it's extremely unlikely)
    assert set(random_tuples) == all_tuples

    # TODO: we could also look at the distribution or something here,
    # but we're not really trying to test the SQLite random(),
    # just that the output is "reasonably random"


def test_get_entries_sort_error(reader):
    with pytest.raises(ValueError):
        set(reader.get_entries(sort='bad sort'))


def test_add_remove_get_feeds(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))

    assert set(reader.get_feeds()) == set()
    with pytest.raises(FeedNotFoundError):
        assert reader.get_feed(feed_arg(one))
    assert reader.get_feed(feed_arg(one), None) == None
    assert reader.get_feed(feed_arg(one), default=1) == 1
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedNotFoundError):
        reader.remove_feed(feed_arg(one))

    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(feed_arg(one))
    reader.add_feed(feed_arg(two))

    assert set(reader.get_feeds()) == {
        Feed(f.url, added=datetime(2010, 1, 1)) for f in (one, two)
    }
    assert reader.get_feed(feed_arg(one)) == Feed(one.url, added=datetime(2010, 1, 1))
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedExistsError):
        reader.add_feed(feed_arg(one))

    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    one = one._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2))
    two = two._replace(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2))
    entry_one = entry_one.as_entry(feed=one, last_updated=datetime(2010, 1, 2))
    entry_two = entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 2))

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(feed_arg(one)) == one
    assert set(reader.get_entries()) == {entry_one, entry_two}

    reader.remove_feed(feed_arg(one))
    assert set(reader.get_feeds()) == {two}
    assert reader.get_feed(feed_arg(one), None) == None
    assert set(reader.get_entries()) == {entry_two}

    with pytest.raises(FeedNotFoundError):
        reader.remove_feed(feed_arg(one))


def test_get_feeds_sort_error(reader):
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

    assert list(f.url for f in reader.get_feeds()) == '1 2 3 4 5'.split()

    reader.update_feeds()
    reader.set_feed_user_title(feed5, 'five')

    assert list(f.url for f in reader.get_feeds()) == '4 5 1 3 2'.split()


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

    assert list(f.url for f in reader.get_feeds()) == '1 3 2'.split()


def test_get_feeds_order_added(reader):
    """When sort='added', feeds should be sorted by (with decreasing
    priority):

    * feed added, descending
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

    reader._now = lambda: datetime(2009, 12, 31)
    feed3 = parser.feed(3, datetime(2010, 1, 3))
    reader.add_feed(feed3.url)

    assert list(f.url for f in reader.get_feeds(sort='added')) == '2 1 3'.split()

    reader.update_feeds()

    assert list(f.url for f in reader.get_feeds(sort='added')) == '2 1 3'.split()


def test_set_feed_user_title(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1), title='title')
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    with pytest.raises(FeedNotFoundError):
        reader.set_feed_user_title(feed_arg(one), 'blah')

    reader.add_feed(one.url)

    def title_tuple(feed):
        return feed.url, feed.title, feed.user_title

    assert title_tuple(reader.get_feed(one.url)) == (one.url, None, None)
    assert [title_tuple(f) for f in reader.get_feeds()] == [(one.url, None, None)]

    reader.set_feed_user_title(feed_arg(one), 'blah')

    assert title_tuple(reader.get_feed(one.url)) == (one.url, None, 'blah')
    assert [title_tuple(f) for f in reader.get_feeds()] == [(one.url, None, 'blah')]

    reader.update_feeds()

    assert title_tuple(reader.get_feed(one.url)) == (one.url, 'title', 'blah')
    assert [title_tuple(f) for f in reader.get_feeds()] == [(one.url, 'title', 'blah')]

    reader.set_feed_user_title(feed_arg(one), None)

    assert title_tuple(reader.get_feed(one.url)) == (one.url, 'title', None)
    assert [title_tuple(f) for f in reader.get_feeds()] == [(one.url, 'title', None)]


def test_data_roundtrip(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1), author='feed author')
    entry = parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        author='entry author',
        summary='summary',
        content=(Content('value3', 'type', 'en'), Content('value2')),
        enclosures=(Enclosure('http://e1', 'type', 1000), Enclosure('http://e2')),
    )

    reader._now = lambda: datetime(2010, 1, 2)
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    assert list(reader.get_entries()) == [
        entry.as_entry(
            feed=feed._replace(
                added=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 3)
            ),
            last_updated=datetime(2010, 1, 3),
        )
    ]


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_integration(reader, feed_type, data_dir, monkeypatch):
    feed_filename = 'full.{}'.format(feed_type)
    feed_url = str(data_dir.join(feed_filename))

    # On CPython, we can't mock datetime.datetime.utcnow because
    # datetime.datetime is a built-in/extension type; we can mock the class.
    # On PyPy, we can mock the class, but it results in weird type errors
    # when the mock/subclass and original datetime class interact.

    try:
        # if we can set attributes on the class, we just patch utcnow() directly
        # (we don't use monkeypatch because it breaks cleanup if it doesn't work)
        datetime.utcnow = datetime.utcnow
        datetime_mock = datetime
    except TypeError:
        # otherwise, we monkeypatch the datetime class on the module
        class datetime_mock(datetime):
            pass

        monkeypatch.setattr('datetime.datetime', datetime_mock)

    monkeypatch.setattr(datetime_mock, 'utcnow', lambda: datetime(2010, 1, 1))
    reader.add_feed(feed_url)
    monkeypatch.setattr(datetime_mock, 'utcnow', lambda: datetime(2010, 1, 2))
    reader.update_feeds()
    monkeypatch.undo()

    (feed,) = reader.get_feeds()
    entries = set(reader.get_entries())

    url_base, rel_base = make_url_base(feed_url)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    assert feed == expected['feed'].as_feed(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2)
    )
    assert entries == {
        e.as_entry(feed=feed, last_updated=datetime(2010, 1, 2))
        for e in expected['entries']
    }


def test_feed_metadata(reader):
    with pytest.raises(FeedNotFoundError):
        reader.set_feed_metadata('one', 'key', 'value')

    with pytest.raises(MetadataNotFoundError):
        reader.delete_feed_metadata('one', 'key')

    reader.add_feed('feed')

    assert set(reader.iter_feed_metadata('feed')) == set()
    with pytest.raises(MetadataNotFoundError):
        reader.get_feed_metadata('feed', 'key')
    assert reader.get_feed_metadata('feed', 'key', None) is None
    assert reader.get_feed_metadata('feed', 'key', default=0) == 0

    with pytest.raises(MetadataNotFoundError):
        reader.delete_feed_metadata('one', 'key')

    reader.set_feed_metadata('feed', 'key', 'value')

    assert set(reader.iter_feed_metadata('feed')) == {('key', 'value')}
    assert reader.get_feed_metadata('feed', 'key') == 'value'

    reader.delete_feed_metadata('feed', 'key')

    assert set(reader.iter_feed_metadata('feed')) == set()
    with pytest.raises(MetadataNotFoundError):
        reader.get_feed_metadata('feed', 'key')


def test_get_entry(reader, entry_arg):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 1, 2)
    reader.add_feed(feed.url)

    with pytest.raises(EntryNotFoundError):
        reader.get_entry(entry_arg(entry.as_entry(feed=feed)))
    assert reader.get_entry(entry_arg(entry.as_entry(feed=feed)), None) == None
    assert reader.get_entry(entry_arg(entry.as_entry(feed=feed)), default=1) == 1

    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    # TODO: find a way to not test added/last_updated here

    entry = entry.as_entry(
        feed=feed._replace(
            added=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 3)
        ),
        last_updated=datetime(2010, 1, 3),
    )
    assert reader.get_entry(entry_arg(entry)) == entry


class FakeStorage:
    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def close(self):
        self.calls.append(('close',))

    def mark_as_important_unimportant(self, feed_url, entry_id, important):
        self.calls.append(
            ('mark_as_important_unimportant', feed_url, entry_id, important)
        )
        if self.exc:
            raise self.exc

    def get_entries(self, *args):
        # FIXME: This is still a bad way of mocking get_entries.
        self.calls.append(('get_entries', args))
        if self.exc:
            raise self.exc
        return ()


# TODO: Test important/unimportant the same way read/unread are (or the other way around).


def test_mark_as_important(reader, entry_arg):

    reader._storage = FakeStorage()
    entry = Entry('entry', None, feed=Feed('feed'))
    reader.mark_as_important(entry_arg(entry))
    assert reader._storage.calls == [
        ('mark_as_important_unimportant', 'feed', 'entry', True)
    ]


def test_mark_as_unimportant(reader, entry_arg):
    reader._storage = FakeStorage()
    entry = Entry('entry', None, feed=Feed('feed'))
    reader.mark_as_unimportant(entry_arg(entry))
    assert reader._storage.calls == [
        ('mark_as_important_unimportant', 'feed', 'entry', False)
    ]


@pytest.mark.parametrize(
    'exc', [EntryNotFoundError('feed', 'entry'), StorageError('whatever')]
)
@pytest.mark.parametrize('meth', ['mark_as_important', 'mark_as_unimportant'])
def test_mark_as_important_unimportant_error(reader, exc, meth):
    reader._storage = FakeStorage(exc=exc)
    with pytest.raises(Exception) as excinfo:
        getattr(reader, meth)(('feed', 'entry'))
    assert excinfo.value is exc


def test_close(reader):
    reader._storage = FakeStorage()
    reader.close()
    assert reader._storage.calls == [('close',)]


def test_closed(reader):
    reader.close()
    # TODO: Maybe parametrize with all the methods.
    with pytest.raises(StorageError):
        reader.add_feed('one')
    with pytest.raises(StorageError):
        list(reader.get_entries())
    # however, we must be able to call close() again:
    reader.close()


def test_direct_instantiation():
    with pytest.warns(UserWarning):
        Reader('storage', 'search', 'parser')


# BEGIN entry filtering tests

# We're testing both get_entries() and search_entries() here,
# since filtering works the same for them.


with_call_entries_method = pytest.mark.parametrize(
    'pre_stuff, call_method',
    [
        (lambda _: None, get_entries_recent),
        (lambda _: None, get_entries_random),
        (enable_and_update_search, search_entries_relevant),
        (enable_and_update_search, search_entries_recent),
    ],
)


# TODO: there should probably be a way to get this from the fakeparser
ALL_IDS = all_ids = {
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (2, 1),
}


@with_call_entries_method
@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), ALL_IDS),
        (dict(read=None), ALL_IDS),
        (dict(read=True), {(1, 2)}),
        (dict(read=False), ALL_IDS - {(1, 2)}),
        (dict(important=None), ALL_IDS),
        (dict(important=True), {(1, 3)}),
        (dict(important=False), ALL_IDS - {(1, 3)}),
        (dict(has_enclosures=None), ALL_IDS),
        (dict(has_enclosures=True), {(1, 4)}),
        (dict(has_enclosures=False), ALL_IDS - {(1, 4)}),
        (dict(feed=None), ALL_IDS),
        (dict(feed='1'), {(1, 1), (1, 2), (1, 3), (1, 4)}),
        (dict(feed='2'), {(2, 1)}),
        (dict(feed=Feed('2')), {(2, 1)}),
        (dict(feed='inexistent'), set()),
        (dict(entry=None), ALL_IDS),
        (dict(entry=('1', '1, 1')), {(1, 1)}),
        (dict(entry=('1', '1, 2')), {(1, 2)}),
        (dict(entry=Entry('1, 2', datetime(2010, 2, 1), feed=Feed('1'),)), {(1, 2)},),
        (dict(entry=('inexistent', 'also-inexistent')), set()),
    ],
)
def test_entries_filtering(reader, pre_stuff, call_method, kwargs, expected):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))
    one_two = parser.entry(1, 2, datetime(2010, 2, 1))  # read
    one_three = parser.entry(1, 3, datetime(2010, 2, 1))  # important
    one_four = parser.entry(
        1, 4, datetime(2010, 2, 1), enclosures=[Enclosure('http://e2')]
    )
    two = parser.feed(2, datetime(2010, 1, 1))
    two_one = parser.entry(2, 1, datetime(2010, 2, 1))

    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feeds()

    reader.mark_as_read((one.url, one_two.id))
    reader.mark_as_important((one.url, one_three.id))

    pre_stuff(reader)

    assert {eval(e.id) for e in call_method(reader, **kwargs)} == expected

    # TODO: how do we test the combinations between arguments?


@with_call_entries_method
@pytest.mark.parametrize(
    'kwargs',
    [
        dict(read=object()),
        dict(important=object()),
        dict(has_enclosures=object()),
        dict(feed=object()),
        dict(entry=object()),
    ],
)
def test_entries_filtering_error(reader, pre_stuff, call_method, kwargs):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(one.url)
    reader.update_feeds()

    pre_stuff(reader)

    with pytest.raises(ValueError):
        list(call_method(reader, **kwargs))


# END entry filtering tests


@pytest.mark.parametrize(
    'kwargs, feed_root',
    [
        (dict(), ''),
        (dict(feed_root=None), None),
        (dict(feed_root=''), ''),
        (dict(feed_root='/path'), '/path'),
    ],
)
def test_make_reader_feed_root(monkeypatch, kwargs, feed_root):
    exc = Exception("whatever")

    def default_parser(feed_root):
        default_parser.feed_root = feed_root
        raise exc

    monkeypatch.setattr('reader.core.default_parser', default_parser)

    with pytest.raises(Exception) as excinfo:
        make_reader('', **kwargs)
    assert excinfo.value is exc

    assert default_parser.feed_root == feed_root
