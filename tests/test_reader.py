import logging
import sys
import threading
from collections import Counter
from datetime import datetime
from datetime import timedelta
from enum import Enum
from itertools import permutations

import pytest
from fakeparser import BlockingParser
from fakeparser import FailingParser
from fakeparser import NotModifiedParser
from fakeparser import Parser
from utils import make_url_base
from utils import rename_argument

import reader._parser
from reader import Content
from reader import Enclosure
from reader import Entry
from reader import EntryCounts
from reader import EntryNotFoundError
from reader import EntrySearchCounts
from reader import Feed
from reader import FeedCounts
from reader import FeedExistsError
from reader import FeedMetadataNotFoundError
from reader import FeedNotFoundError
from reader import InvalidPluginError
from reader import ParseError
from reader import Reader
from reader import StorageError
from reader import UpdatedFeed
from reader import UpdateResult
from reader._storage import Storage
from reader._types import DEFAULT_RESERVED_NAME_SCHEME
from reader._types import FeedUpdateIntent


# TODO: testing added/last_updated everywhere is kinda ugly


def test_update_feed_updated(reader, call_update_method, caplog):
    """If a feed is not newer than the stored one,
    it should be updated only if its content (hash) changed.

    Its entries should be processed anyway.

    Details in https://github.com/lemon24/reader/issues/76

    """
    parser = Parser()
    reader._parser = parser

    # Initial update.
    old_feed = parser.feed(1, datetime(2010, 1, 1), title='old')
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(old_feed.url)
    reader._now = lambda: datetime(2010, 1, 2)

    with caplog.at_level(logging.DEBUG, 'reader'):
        call_update_method(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2)
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2))
    }
    assert "feed has no last_updated, treating as updated" in caplog.text
    caplog.clear()

    # Entries should be processed anyway.
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 3)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 3)
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
    }
    assert "feed not updated, updating entries anyway" in caplog.text
    caplog.clear()

    # Feed gets updated because content (hash) changed.
    old_feed = parser.feed(1, datetime(2010, 1, 1), title='old-different-title')
    reader._now = lambda: datetime(2010, 1, 3, 12)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 3, 12)
    )
    assert reader.get_feed(feed) == feed
    assert "feed hash changed, treating as updated" in caplog.text
    caplog.clear()

    # The feed doesn't change, because .updated is older.
    # Entries get updated regardless.
    old_feed = parser.feed(1, datetime(2009, 1, 1), title='old-different-title')
    entry_three = parser.entry(1, 3, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 4)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        # doesn't change because it's not newer
        updated=datetime(2010, 1, 1),
        # changes because entries changed
        last_updated=datetime(2010, 1, 4),
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
        entry_three.as_entry(feed=feed, last_updated=datetime(2010, 1, 4)),
    }
    assert "feed not updated, updating entries anyway" in caplog.text
    caplog.clear()

    # The feed doesn't change; despite being newer, no entries have changed.
    old_feed = parser.feed(1, datetime(2010, 1, 2), title='old-different-title')
    reader._now = lambda: datetime(2010, 1, 4, 12)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        # doesn't change because no entries have changed
        updated=datetime(2010, 1, 1),
        # doesn't change because nothing changed
        last_updated=datetime(2010, 1, 4),
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
        entry_three.as_entry(feed=feed, last_updated=datetime(2010, 1, 4)),
    }
    assert "feed not updated, updating entries anyway" in caplog.text
    caplog.clear()

    # The feeds changes because it is newer *and* entries get updated.
    new_feed = parser.feed(1, datetime(2010, 1, 2), title='new')
    entry_four = parser.entry(1, 4, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 5)
    feed = new_feed.as_feed(
        added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 5)
    )

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, old_feed.url)

    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=feed, last_updated=datetime(2010, 1, 2)),
        entry_two.as_entry(feed=feed, last_updated=datetime(2010, 1, 3)),
        entry_three.as_entry(feed=feed, last_updated=datetime(2010, 1, 4)),
        entry_four.as_entry(feed=feed, last_updated=datetime(2010, 1, 5)),
    }
    assert "feed updated" in caplog.text
    caplog.clear()


def test_update_entry_updated(reader, call_update_method, caplog, monkeypatch):
    """An entry should be updated only if
    it is newer than the stored one OR its content (hash) changed.

    """
    parser = Parser()
    reader._parser = parser

    # Initial update.
    feed = parser.feed(1, datetime(2010, 1, 1))
    old_entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 2, 1)
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 2, 2)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, feed.url)

    feed = feed.as_feed(added=datetime(2010, 2, 1), last_updated=datetime(2010, 2, 2))
    assert set(reader.get_entries()) == {
        old_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 2))
    }
    assert "entry updated" in caplog.text
    caplog.clear()

    # Feed newer (doesn't change), entry remains unchanged.
    feed = parser.feed(1, datetime(2010, 1, 2))
    reader._now = lambda: datetime(2010, 2, 3)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, feed.url)

    feed = feed.as_feed(
        added=datetime(2010, 2, 1),
        updated=datetime(2010, 1, 1),
        last_updated=datetime(2010, 2, 2),
    )
    assert set(reader.get_entries()) == {
        old_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 2))
    }
    assert "entry not updated, skipping" in caplog.text
    assert "entry hash changed, updating" not in caplog.text
    caplog.clear()

    # Feed does not change, entry hash changes.
    feed = parser.feed(1, datetime(2010, 1, 2))
    new_entry = old_entry._replace(title='New Entry')
    parser.entries[1][1] = new_entry
    reader._now = lambda: datetime(2010, 2, 3, 12)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, feed.url)

    feed = feed.as_feed(
        added=datetime(2010, 2, 1), last_updated=datetime(2010, 2, 3, 12)
    )
    assert set(reader.get_entries()) == {
        new_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 3, 12))
    }
    assert "entry not updated, skipping" in caplog.text
    assert "entry hash changed, updating" in caplog.text
    caplog.clear()

    # Entry is newer.
    feed = parser.feed(1, datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    parser.entries[1][1] = new_entry
    reader._now = lambda: datetime(2010, 2, 4)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        call_update_method(reader, feed.url)

    feed = feed.as_feed(added=datetime(2010, 2, 1), last_updated=datetime(2010, 2, 4))
    assert set(reader.get_entries()) == {
        new_entry.as_entry(feed=feed, last_updated=datetime(2010, 2, 4))
    }
    assert "entry updated" in caplog.text
    caplog.clear()

    # Entry hash changes, but reaches the update limit.
    reader._now = lambda: datetime(2010, 2, 5)
    monkeypatch.setattr('reader._updater.HASH_CHANGED_LIMIT', 3)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        for i in range(1, 6):
            new_entry = new_entry._replace(title=f"Even Newer: change #{i}")
            parser.entries[1][1] = new_entry
            call_update_method(reader, feed.url)

    assert set(e.title for e in reader.get_entries()) == {"Even Newer: change #3"}
    assert caplog.text.count("entry hash changed, updating") == 3
    assert caplog.text.count("entry hash changed, but exceeds the update limit") == 2
    caplog.clear()


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
    feed = feed.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1))

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
    feed = feed.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2))

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
def test_update_blocking(db_path, make_reader, call_update_method):
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
        # can't use fixture because it would run close() in a different thread
        from reader import make_reader

        reader = make_reader(db_path)
        reader._parser = blocking_parser
        try:
            call_update_method(reader, feed.url)
        finally:
            reader.close()

    t = threading.Thread(target=target)
    t.start()

    blocking_parser.in_parser.wait()

    try:
        # shouldn't raise an exception
        reader.mark_entry_as_read((feed.url, entry.id))
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


def test_update_new(reader):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(one.url)
    reader.update_feeds(new=True)

    assert len(set(reader.get_feeds())) == 1
    assert set(reader.get_entries()) == set()

    one = parser.feed(1, datetime(2010, 2, 1), title='title')
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 1, 12)
    reader.add_feed(two.url)

    reader.update_feeds(new=False)
    assert {(f.url, f.last_updated, f.title) for f in reader.get_feeds()} == {
        ('1', datetime(2010, 1, 1, 12), 'title'),
        ('2', None, None),
    }

    reader._now = lambda: datetime(2010, 1, 2)
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new=True)

    two = two.as_feed(added=datetime(2010, 1, 1, 12), last_updated=datetime(2010, 1, 2))
    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 2))
    }

    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    one = one.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 3))
    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_one.as_entry(feed=one, last_updated=datetime(2010, 1, 3)),
        entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 2)),
    }


def test_update_new_no_last_updated(reader):
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

    reader.update_feeds(new=True)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


def test_update_new_not_modified(reader):
    """A feed should not be considered new anymore after getting _NotModified.

    https://github.com/lemon24/reader/issues/95

    """
    parser = NotModifiedParser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader._storage.update_feed(FeedUpdateIntent(feed.url, None, feed=feed))

    reader.update_feeds(new=True)

    parser = Parser.from_parser(parser)
    reader._parser = parser

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new=True)

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
    reader.update_feeds(new=True)
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
    return NotModifiedParser()


@pytest.mark.parametrize(
    'make_new_parser',
    [
        same_parser,
        updated_feeds_parser,
        raises_not_modified_parser,
    ],
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
        if (f, e)
        not in {
            (FeedAction.none, EntryAction.none),
        }
    ],
)
def test_update_feed_deleted(
    db_path, make_reader, call_update_method, feed_action, entry_action
):
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
        feed = parser.feed(1, datetime(2010, 1, 2), title='new title')

    if feed_action is not FeedAction.fail:
        parser_cls = BlockingParser
    else:

        class parser_cls(BlockingParser, FailingParser):
            pass

    blocking_parser = parser_cls.from_parser(parser)

    def target():
        # can't use fixture because it would run close() in a different thread
        from reader import make_reader

        blocking_parser.in_parser.wait()
        reader = make_reader(db_path)
        try:
            reader.delete_feed(feed.url)
        finally:
            blocking_parser.can_return_from_parser.set()
            try:
                reader.close()
            except StorageError as e:
                if 'database is locked' in str(e):
                    pass  # sometimes, it can be; we don't care
                else:
                    raise

    t = threading.Thread(target=target)
    t.start()

    try:
        reader._parser = blocking_parser
        if call_update_method.__name__ == 'call_update_feed':
            with pytest.raises(FeedNotFoundError) as excinfo:
                call_update_method(reader, feed.url)
            assert excinfo.value.url == feed.url
            assert 'no such feed' in excinfo.value.message
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
    one = one.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1))
    two = two.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 1))

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


def call_update_feeds_iter(reader):
    yield from reader.update_feeds_iter()


def call_update_feed_iter(reader):
    for feed in reader.get_feeds(updates_enabled=True):
        try:
            yield feed.url, reader.update_feed(feed)
        except ParseError as e:
            yield feed.url, e


@pytest.fixture(
    params=[
        call_update_feeds_iter,
        call_update_feed_iter,
    ]
)
def call_update_iter_method(request):
    return request.param


def test_update_feeds_iter(reader, call_update_iter_method):
    reader._parser = parser = FailingParser(condition=lambda url: url == '3')

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))
    one_two = parser.entry(1, 2, datetime(2010, 2, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    two_one = parser.entry(2, 1, datetime(2010, 2, 1))

    for feed in one, two:
        reader.add_feed(feed)

    assert dict(call_update_iter_method(reader)) == {
        '1': UpdatedFeed(url='1', new=2, modified=0),
        '2': UpdatedFeed(url='2', new=1, modified=0),
    }

    assert next(call_update_iter_method(reader)) == UpdateResult(
        '1', UpdatedFeed(url='1', new=0, modified=0)
    )

    one_two = parser.entry(1, 2, datetime(2010, 2, 2), title='new title')
    one_three = parser.entry(1, 3, datetime(2010, 2, 1))
    one_four = parser.entry(1, 4, datetime(2010, 2, 1))
    three = parser.feed(3, datetime(2010, 1, 1))

    reader.add_feed(three)

    rv = dict(call_update_iter_method(reader))
    assert set(rv) == set('123')

    assert rv['1'] == UpdatedFeed(url='1', new=2, modified=1)
    assert rv['2'] == UpdatedFeed(url='2', new=0, modified=0)

    assert isinstance(rv['3'], ParseError)
    assert rv['3'].url == '3'
    assert rv['3'].__cause__ is parser.exception

    reader._parser = parser = NotModifiedParser()

    assert dict(call_update_iter_method(reader)) == dict.fromkeys('123')


@pytest.mark.parametrize('exc_type', [StorageError, Exception])
def test_update_feeds_iter_raised_exception(reader, exc_type, call_update_iter_method):
    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    three = parser.feed(3, datetime(2010, 1, 1))

    for feed in one, two, three:
        reader.add_feed(feed)

    original_storage_update_feed = reader._storage.update_feed

    def storage_update_feed(intent):
        if intent.url == '2':
            raise exc_type('message')
        return original_storage_update_feed(intent)

    reader._storage.update_feed = storage_update_feed

    rv = {}
    with pytest.raises(exc_type) as excinfo:
        rv.update(call_update_iter_method(reader))
    assert 'message' in str(excinfo.value)

    if not sys.implementation.name == 'pypy':
        # for some reason, on PyPy the updates sometimes
        # happen out of order and rv is empty
        assert rv == {'1': UpdatedFeed(url='1', new=0, modified=0)}


def test_mark_as_read_unread(reader, entry_arg):
    # TODO: Test read/unread the same way important/unimportant are (or the other way around).

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    entry_with_feed = entry.as_entry(feed=feed)

    with pytest.raises(EntryNotFoundError) as excinfo:
        reader.mark_entry_as_read(entry_arg(entry_with_feed))
    assert (excinfo.value.feed_url, excinfo.value.id) == (entry.feed_url, entry.id)
    assert 'no such entry' in excinfo.value.message

    with pytest.raises(EntryNotFoundError) as excinfo:
        reader.mark_entry_as_unread(entry_arg(entry_with_feed))
    assert (excinfo.value.feed_url, excinfo.value.id) == (entry.feed_url, entry.id)
    assert 'no such entry' in excinfo.value.message

    reader.add_feed(feed.url)

    with pytest.raises(EntryNotFoundError):
        reader.mark_entry_as_read(entry_arg(entry_with_feed))

    with pytest.raises(EntryNotFoundError):
        reader.mark_entry_as_unread(entry_arg(entry_with_feed))

    reader.update_feeds()

    (entry,) = list(reader.get_entries())
    assert not entry.read

    reader.mark_entry_as_read(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert entry.read

    reader.mark_entry_as_read(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert entry.read

    reader.mark_entry_as_unread(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert not entry.read

    reader.mark_entry_as_unread(entry_arg(entry_with_feed))
    (entry,) = list(reader.get_entries())
    assert not entry.read


class FakeNow:
    def __init__(self, start, step):
        self.now = start
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


# TODO: we could just parametrize sort as well here (see test_pagination_basic for details)


def get_feeds(reader, **kwargs):
    return reader.get_feeds(**kwargs)


def get_entries(reader, **kwargs):
    return reader.get_entries(**kwargs)


def get_entries_recent(reader, **kwargs):
    return reader.get_entries(sort='recent', **kwargs)


def get_entries_random(reader, **kwargs):
    return reader.get_entries(sort='random', **kwargs)


def enable_and_update_search(reader):
    reader.enable_search()
    reader.update_search()


def search_entries(reader, **kwargs):
    return reader.search_entries('entry', **kwargs)


def search_entries_relevant(reader, **kwargs):
    return reader.search_entries('entry', sort='relevant', **kwargs)


def search_entries_recent(reader, **kwargs):
    return reader.search_entries('entry', sort='recent', **kwargs)


def search_entries_random(reader, **kwargs):
    return reader.search_entries('entry', sort='random', **kwargs)


with_call_entries_recent_method = pytest.mark.parametrize(
    'pre_stuff, call_method',
    [
        (lambda _: None, get_entries),
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


# sqlite3 on PyPy can be brittle
# (spurious "InterfaceError: Error binding parameter X")
# and we're doing lots of tiny queries here which may trigger it,
# so don't bother
@pytest.mark.skipif("sys.implementation.name == 'pypy'")
@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [1, 2, 3, 4])
@pytest.mark.parametrize(
    'pre_stuff, call_method',
    [
        (lambda _: None, get_entries),
        (enable_and_update_search, search_entries),
    ],
)
def test_get_entries_random(reader, chunk_size, pre_stuff, call_method):
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

    pre_stuff(reader)

    # all possible get_entries(sort='random') results
    all_tuples = set(permutations({e.id for e in reader.get_entries()}, chunk_size))

    # some get_entries(sort='random') results
    # (we call it enough times so it's likely we get all the results)
    random_tuples = Counter(
        tuple(e.id for e in call_method(reader, sort='random'))
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
    with pytest.raises(FeedNotFoundError) as excinfo:
        assert reader.get_feed(feed_arg(one))
    assert excinfo.value.url == one.url
    assert 'no such feed' in excinfo.value.message

    assert reader.get_feed(feed_arg(one), None) == None
    assert reader.get_feed(feed_arg(one), 1) == 1
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.delete_feed(feed_arg(one))
    assert excinfo.value.url == one.url
    assert 'no such feed' in excinfo.value.message

    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(feed_arg(one))
    reader.add_feed(feed_arg(two))

    assert set(reader.get_feeds()) == {
        Feed(f.url, added=datetime(2010, 1, 1)) for f in (one, two)
    }
    assert reader.get_feed(feed_arg(one)) == Feed(one.url, added=datetime(2010, 1, 1))
    assert set(reader.get_entries()) == set()

    with pytest.raises(FeedExistsError) as excinfo:
        reader.add_feed(feed_arg(one))
    assert excinfo.value.url == one.url
    assert 'feed exists' in excinfo.value.message

    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    one = one.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2))
    two = two.as_feed(added=datetime(2010, 1, 1), last_updated=datetime(2010, 1, 2))
    entry_one = entry_one.as_entry(feed=one, last_updated=datetime(2010, 1, 2))
    entry_two = entry_two.as_entry(feed=two, last_updated=datetime(2010, 1, 2))

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(feed_arg(one)) == one
    assert set(reader.get_entries()) == {entry_one, entry_two}

    reader.delete_feed(feed_arg(one))
    assert set(reader.get_feeds()) == {two}
    assert reader.get_feed(feed_arg(one), None) == None
    assert set(reader.get_entries()) == {entry_two}

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.delete_feed(feed_arg(one))


def test_get_feeds_sort_error(reader):
    with pytest.raises(ValueError):
        set(reader.get_feeds(sort='bad sort'))


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1, 2, 0])
def test_get_feeds_order_title(reader, chunk_size):
    """When sort='title', feeds should be sorted by (with decreasing
    priority):

    * feed user_title or feed title; feeds that have neither should appear first
    * feed URL

    https://github.com/lemon24/reader/issues/29
    https://github.com/lemon24/reader/issues/102

    """
    # for https://github.com/lemon24/reader/issues/203
    reader._storage.chunk_size = chunk_size

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

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.set_feed_user_title(feed_arg(one), 'blah')
    assert excinfo.value.url == one.url
    assert 'no such feed' in excinfo.value.message

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
            feed=feed.as_feed(
                added=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 3)
            ),
            last_updated=datetime(2010, 1, 3),
        )
    ]

    # TODO: this should be a different test
    (feed_for_update,) = reader._storage.get_feeds_for_update(url=feed.url)
    assert feed.hash == feed_for_update.hash
    (entry_for_update,) = reader._storage.get_entries_for_update(
        [(entry.feed_url, entry.id)]
    )
    assert entry.hash == entry_for_update.hash


def test_data_hashes_remain_stable():
    # TODO: note the duplication from test_data_roundtrip()

    parser = Parser()
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

    assert feed.hash == b'\x00\xda\xf5\xa1Je\x13],\xf0\xdb\xaa\x88d\x99\xc6'
    assert entry.hash == b'\x00f\xa9\xdb\t5\xdf\xedcK\xd9bm\x80,l'

    assert feed._replace(url='x', updated='x').hash == feed.hash
    assert (
        feed._replace(title='x').hash
        == b'\x00\xce\x81\xc7\x8d(\xab\xd8)\x06\x90?\xf9\x847\xc4'
    )

    assert entry._replace(feed_url='x', id='x', updated='x').hash == entry.hash
    assert (
        entry._replace(title='x').hash
        == b'\x00\x95\xc4\xe9\xd3\x95\xf6\xff\xf0*\xbd\x00L\x08\x1a\xa2'
    )


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

        # reader.core must "from datetime import datetime" !
        monkeypatch.setattr('reader.core.datetime', datetime_mock)

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
    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.set_feed_metadata_item('one', 'key', 'value')
    assert excinfo.value.url == 'one'
    assert 'no such feed' in excinfo.value.message

    with pytest.raises(FeedMetadataNotFoundError) as excinfo:
        reader.delete_feed_metadata_item('one', 'key')
    assert (excinfo.value.url, excinfo.value.key) == ('one', 'key')
    assert 'no such metadata' in excinfo.value.message

    reader.add_feed('feed')

    assert set(reader.get_feed_metadata('feed')) == set()
    with pytest.raises(FeedMetadataNotFoundError) as excinfo:
        reader.get_feed_metadata_item('feed', 'key')
    assert (excinfo.value.url, excinfo.value.key) == ('feed', 'key')
    assert 'no such metadata' in excinfo.value.message
    assert reader.get_feed_metadata_item('feed', 'key', None) is None
    assert reader.get_feed_metadata_item('feed', 'key', 0) == 0

    with pytest.raises(FeedMetadataNotFoundError):
        reader.delete_feed_metadata_item('one', 'key')

    reader.set_feed_metadata_item('feed', 'key', 'value')

    assert set(reader.get_feed_metadata('feed')) == {('key', 'value')}
    assert reader.get_feed_metadata_item('feed', 'key') == 'value'

    reader.delete_feed_metadata_item('feed', 'key')

    assert set(reader.get_feed_metadata('feed')) == set()
    with pytest.raises(FeedMetadataNotFoundError):
        reader.get_feed_metadata_item('feed', 'key')


def test_get_entry(reader, entry_arg):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 1, 2)
    reader.add_feed(feed.url)

    with pytest.raises(EntryNotFoundError) as excinfo:
        reader.get_entry(entry_arg(entry.as_entry(feed=feed)))
    assert (excinfo.value.feed_url, excinfo.value.id) == (entry.feed_url, entry.id)
    assert 'no such entry' in excinfo.value.message
    assert reader.get_entry(entry_arg(entry.as_entry(feed=feed)), None) == None
    assert reader.get_entry(entry_arg(entry.as_entry(feed=feed)), 1) == 1

    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    # TODO: find a way to not test added/last_updated here

    entry = entry.as_entry(
        feed=feed.as_feed(
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
    reader.mark_entry_as_important(entry_arg(entry))
    assert reader._storage.calls == [
        ('mark_as_important_unimportant', 'feed', 'entry', True)
    ]


def test_mark_as_unimportant(reader, entry_arg):
    reader._storage = FakeStorage()
    entry = Entry('entry', None, feed=Feed('feed'))
    reader.mark_entry_as_unimportant(entry_arg(entry))
    assert reader._storage.calls == [
        ('mark_as_important_unimportant', 'feed', 'entry', False)
    ]


@pytest.mark.parametrize(
    'exc', [EntryNotFoundError('feed', 'entry'), StorageError('whatever')]
)
@pytest.mark.parametrize(
    'meth', ['mark_entry_as_important', 'mark_entry_as_unimportant']
)
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
    with pytest.raises(StorageError) as excinfo:
        reader.add_feed('one')
    assert 'closed' in excinfo.value.message
    with pytest.raises(StorageError):
        list(reader.get_entries())
    assert 'closed' in excinfo.value.message
    # however, we must be able to call close() again:
    reader.close()


def test_direct_instantiation():
    with pytest.warns(UserWarning):
        Reader('storage', 'search', 'parser', DEFAULT_RESERVED_NAME_SCHEME)


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
        (enable_and_update_search, search_entries_random),
    ],
)


# TODO: there should probably be a way to get this from the fakeparser
ALL_IDS = {
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
        (
            dict(
                entry=Entry(
                    '1, 2',
                    datetime(2010, 2, 1),
                    feed=Feed('1'),
                )
            ),
            {(1, 2)},
        ),
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

    reader.mark_entry_as_read((one.url, one_two.id))
    reader.mark_entry_as_important((one.url, one_three.id))

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
def test_make_reader_feed_root(monkeypatch, make_reader, kwargs, feed_root):
    exc = Exception("whatever")

    def default_parser(feed_root, **kwargs):
        default_parser.feed_root = feed_root
        raise exc

    monkeypatch.setattr('reader.core.default_parser', default_parser)

    with pytest.raises(Exception) as excinfo:
        make_reader('', **kwargs)
    assert excinfo.value is exc

    assert default_parser.feed_root == feed_root


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_tags_basic(reader, chunk_size):
    reader._storage.chunk_size = chunk_size

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.add_feed_tag('one', 'tag')
    assert excinfo.value.url == 'one'
    assert 'no such feed' in excinfo.value.message

    # no-op
    reader.remove_feed_tag('one', 'tag')

    # also no-op
    assert list(reader.get_feed_tags('one')) == []
    assert list(reader.get_feed_tags()) == []

    reader.add_feed('one')
    reader.add_feed('two')

    # no tags
    assert list(reader.get_feed_tags('one')) == []
    assert list(reader.get_feed_tags()) == []

    reader.add_feed_tag('one', 'tag-1')
    assert list(reader.get_feed_tags('one')) == ['tag-1']
    assert list(reader.get_feed_tags()) == ['tag-1']

    # no-op
    reader.add_feed_tag('one', 'tag-1')

    reader.add_feed_tag('two', 'tag-2-2')
    reader.add_feed_tag('two', 'tag-2-1')
    assert list(reader.get_feed_tags('one')) == ['tag-1']
    assert list(reader.get_feed_tags('two')) == ['tag-2-1', 'tag-2-2']
    assert list(reader.get_feed_tags()) == ['tag-1', 'tag-2-1', 'tag-2-2']

    # no-op
    reader.remove_feed_tag('one', 'tag-2-1')
    assert list(reader.get_feed_tags('one')) == ['tag-1']
    assert list(reader.get_feed_tags('two')) == ['tag-2-1', 'tag-2-2']
    assert list(reader.get_feed_tags()) == ['tag-1', 'tag-2-1', 'tag-2-2']

    reader.remove_feed_tag('two', 'tag-2-1')
    assert list(reader.get_feed_tags('one')) == ['tag-1']
    assert list(reader.get_feed_tags('two')) == ['tag-2-2']
    assert list(reader.get_feed_tags()) == ['tag-1', 'tag-2-2']

    reader.add_feed_tag('two', 'tag-2-3')
    reader.add_feed_tag('two', 'tag-2-0')
    reader.add_feed_tag('two', 'tag-2-1')
    reader.add_feed_tag('one', 'tag-common')
    reader.add_feed_tag('two', 'tag-common')

    assert list(reader.get_feed_tags('one')) == ['tag-1', 'tag-common']
    assert list(reader.get_feed_tags('two')) == [
        'tag-2-0',
        'tag-2-1',
        'tag-2-2',
        'tag-2-3',
        'tag-common',
    ]
    assert list(reader.get_feed_tags()) == [
        'tag-1',
        'tag-2-0',
        'tag-2-1',
        'tag-2-2',
        'tag-2-3',
        'tag-common',
    ]

    reader.delete_feed('two')
    assert list(reader.get_feed_tags('one')) == ['tag-1', 'tag-common']
    assert list(reader.get_feed_tags('two')) == []
    assert list(reader.get_feed_tags()) == ['tag-1', 'tag-common']


def get_entry_id(entry):
    return eval(entry.id)


def noop(thing):
    return thing


def get_feeds(reader, **kwargs):
    return reader.get_feeds(**kwargs)


def get_feed_url(feed):
    return eval(feed.url)


# like with_call_entries_method, but include get_feeds()
with_call_feed_tags_method = pytest.mark.parametrize(
    'pre_stuff, call_method, tags_arg_name, id_from_object, id_from_expected',
    [
        (lambda _: None, get_entries_recent, 'feed_tags', get_entry_id, noop),
        (lambda _: None, get_entries_random, 'feed_tags', get_entry_id, noop),
        (
            enable_and_update_search,
            search_entries_relevant,
            'feed_tags',
            get_entry_id,
            noop,
        ),
        (
            enable_and_update_search,
            search_entries_recent,
            'feed_tags',
            get_entry_id,
            noop,
        ),
        (
            enable_and_update_search,
            search_entries_random,
            'feed_tags',
            get_entry_id,
            noop,
        ),
        # TODO: maybe test all the get_feeds sort orders
        (lambda _: None, get_feeds, 'tags', get_feed_url, lambda t: t[0]),
    ],
)


ALL_IDS = {
    (1, 1),
    (1, 2),
    (2, 1),
    (3, 1),
}


@with_call_feed_tags_method
@pytest.mark.parametrize(
    'args, expected',
    [
        ((), ALL_IDS),
        ((None,), ALL_IDS),
        (([],), ALL_IDS),
        (([[]],), ALL_IDS),
        ((True,), ALL_IDS - {(3, 1)}),
        (([True],), ALL_IDS - {(3, 1)}),
        ((False,), {(3, 1)}),
        (([False],), {(3, 1)}),
        (([True, False],), set()),
        (([[True, False]],), ALL_IDS),
        ((['tag'],), ALL_IDS - {(3, 1)}),
        (([['tag']],), ALL_IDS - {(3, 1)}),
        ((['tag', 'tag'],), ALL_IDS - {(3, 1)}),
        (([['tag'], ['tag']],), ALL_IDS - {(3, 1)}),
        (([['tag', 'tag']],), ALL_IDS - {(3, 1)}),
        ((['-tag'],), {(3, 1)}),
        ((['unknown'],), set()),
        ((['-unknown'],), ALL_IDS),
        ((['first'],), {(1, 1), (1, 2)}),
        ((['second'],), {(2, 1)}),
        ((['first', 'second'],), set()),
        (([['first'], ['second']],), set()),
        (([['first', 'second']],), {(1, 1), (1, 2), (2, 1)}),
        ((['first', 'tag'],), {(1, 1), (1, 2)}),
        ((['second', 'tag'],), {(2, 1)}),
        (([['first', 'second'], 'tag'],), {(1, 1), (1, 2), (2, 1)}),
        (([['first'], ['tag']],), {(1, 1), (1, 2)}),
        (([['first', 'tag']],), {(1, 1), (1, 2), (2, 1)}),
        ((['-first', 'tag'],), {(2, 1)}),
        (([['first', '-tag']],), ALL_IDS - {(2, 1)}),
        (([[False, 'first']],), {(1, 1), (1, 2), (3, 1)}),
        (([True, '-first'],), {(2, 1)}),
    ],
)
def test_filtering_tags(
    reader,
    pre_stuff,
    call_method,
    tags_arg_name,
    id_from_object,
    id_from_expected,
    args,
    expected,
):
    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))  # tag, first
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))
    one_two = parser.entry(1, 2, datetime(2010, 2, 1))

    two = parser.feed(2, datetime(2010, 1, 1))  # tag, second
    two_one = parser.entry(2, 1, datetime(2010, 1, 1))

    three = parser.feed(3, datetime(2010, 1, 1))  # <no tags>
    three_one = parser.entry(3, 1, datetime(2010, 1, 1))

    for feed in one, two, three:
        reader.add_feed(feed)

    reader.update_feeds()

    reader.add_feed_tag(one, 'tag')
    reader.add_feed_tag(one, 'first')
    reader.add_feed_tag(two, 'tag')
    reader.add_feed_tag(two, 'second')

    pre_stuff(reader)

    assert len(args) <= 1
    kwargs = {tags_arg_name: a for a in args}

    actual_set = set(map(id_from_object, call_method(reader, **kwargs)))
    expected_set = set(map(id_from_expected, expected))
    assert actual_set == expected_set, kwargs


ALL_IDS = {1, 2, 3, 4}


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), ALL_IDS),
        (dict(feed='1'), {1}),
        (dict(feed=Feed('1')), {1}),
        (dict(broken=None), ALL_IDS),
        (dict(broken=True), {2}),
        (dict(broken=False), ALL_IDS - {2}),
        (dict(updates_enabled=None), ALL_IDS),
        (dict(updates_enabled=True), ALL_IDS - {4}),
        (dict(updates_enabled=False), {4}),
    ],
)
def test_feeds_filtering(reader, kwargs, expected):
    reader._parser = parser = FailingParser(condition=lambda url: url == '2')

    one = parser.feed(1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    three = parser.feed(3, datetime(2010, 1, 1))
    four = parser.feed(4, datetime(2010, 1, 1))

    for feed in one, two, three, four:
        reader.add_feed(feed)

    reader.disable_feed_updates(four)

    reader.update_feeds()

    assert {eval(f.url) for f in reader.get_feeds(**kwargs)} == expected

    # TODO: how do we test the combinations between arguments?


@pytest.mark.parametrize(
    'kwargs',
    [
        dict(feed=object()),
        dict(broken=object()),
        dict(updates_enabled=object()),
    ],
)
def test_feeds_filtering_error(reader, kwargs):
    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(one)
    reader.update_feeds()

    with pytest.raises(ValueError):
        list(reader.get_feeds(**kwargs))


@pytest.fixture
def reader_with_two_feeds(reader):
    reader._parser = parser = FailingParser(condition=lambda url: False)

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))
    one_two = parser.entry(1, 2, datetime(2010, 1, 1))

    two = parser.feed(2, datetime(2010, 1, 1))
    two_one = parser.entry(2, 1, datetime(2010, 1, 1))

    for feed in one, two:
        reader.add_feed(feed)

    return reader


# BEGIN change_feed_url tests


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_errors(reader):
    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.change_feed_url('0', '3')
    assert excinfo.value.url == '0'

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.change_feed_url('0', '2')
    assert excinfo.value.url == '0'

    with pytest.raises(FeedExistsError) as excinfo:
        reader.change_feed_url('1', '2')
    assert excinfo.value.url == '2'


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_feed(reader):
    reader.update_feeds()

    reader._parser.condition = lambda url: url == '1'
    reader.update_feeds()

    reader.set_feed_user_title('1', 'user title')

    old_one = reader.get_feed('1')

    reader.change_feed_url('1', '3')

    assert not reader.get_feed('1', None)
    assert reader.get_feed('3') == old_one._replace(
        url='3',
        updated=None,
        last_updated=None,
        last_exception=None,
    )


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_feeds_for_update(reader):
    # TODO: this should probably be tested in test_storage.py

    reader._parser.http_etag = 'etag'
    reader._parser.http_last_modified = 'last-modified'
    reader.update_feeds()

    reader._parser.condition = lambda url: url == '1'
    reader.update_feeds()

    reader._storage.mark_as_stale('1')

    def get_feed(url):
        return next(reader._storage.get_feeds_for_update(url=url), None)

    old_one = get_feed('1')
    assert old_one.http_etag == 'etag'
    assert old_one.http_last_modified == 'last-modified'
    assert old_one.stale

    reader.change_feed_url('1', '3')

    assert not get_feed('1')
    assert get_feed('3') == old_one._replace(
        url='3',
        updated=None,
        last_updated=None,
        last_exception=False,
        stale=False,
        http_etag=None,
        http_last_modified=None,
    )


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_entries(reader):
    reader.update_feeds()

    old = set(reader.get_entries(feed='1'))
    assert {e.id for e in old} == {'1, 1', '1, 2'}

    reader.change_feed_url('1', '3')

    assert set(reader.get_entries(feed='1')) == set()

    new = set(reader.get_entries(feed='3'))
    assert {e.feed_url for e in new} == {'3'}

    def drop_feed(entry):
        return entry._replace(feed=None)

    assert set(map(drop_feed, new)) == set(map(drop_feed, old))


@rename_argument('reader', 'reader_with_two_feeds')
@pytest.mark.parametrize('new_feed_url', ['3', '2'])
def test_change_feed_url_second_update(reader, new_feed_url):
    reader._parser.feed(
        1, datetime(2010, 1, 1), title='old title', author='old author', link='old link'
    )
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    reader.delete_feed('2')

    old_one = reader.get_feed('1')

    reader.change_feed_url('1', new_feed_url)

    assert reader.get_feed(new_feed_url) == old_one._replace(
        url=new_feed_url,
        updated=None,
        last_updated=None,
    )

    reader._parser.feed(
        eval(new_feed_url),
        datetime(2010, 1, 2),
        title='new title',
        author='new author',
        link='new link',
    )
    reader._parser.entry(eval(new_feed_url), 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 1, 3)

    reader.update_feeds()

    assert reader.get_feed(new_feed_url) == old_one._replace(
        url=new_feed_url,
        updated=datetime(2010, 1, 2),
        last_updated=datetime(2010, 1, 3),
        title='new title',
        author='new author',
        link='new link',
    )

    new = set(reader.get_entries(feed=new_feed_url))
    assert {e.feed_url for e in new} == {new_feed_url}
    assert {(e.id, e.original_feed_url) for e in new} == {
        ('1, 1', '1'),
        ('1, 2', '1'),
        (f'{new_feed_url}, 1', new_feed_url),
    }


def test_change_feed_url_search_entry_id_repeats(reader):
    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))

    two = parser.feed(2, datetime(2010, 1, 1))
    parser.entries[2][1] = one_one._replace(feed_url='2')

    for feed in one, two:
        reader.add_feed(feed)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    # TODO: write another test to make sure things marked as to_update remain marked after change

    reader.delete_feed(two)
    reader.change_feed_url(one, two)

    new = set(reader.get_entries(feed=two))
    assert {(e.feed_url, e.id, e.original_feed_url) for e in new} == {
        ('2', '1, 1', '1'),
    }

    parser.entries[2] = {
        i: e._replace(updated=datetime(2010, 1, 2), title='new entry title')
        for i, e in parser.entries[2].items()
    }
    reader.update_feeds()

    new = set(reader.get_entries(feed=two))
    assert {(e.feed_url, e.id, e.original_feed_url) for e in new} == {
        ('2', '1, 1', '2'),
    }

    reader.update_search()

    (entry,) = reader.get_entries()
    (result,) = reader.search_entries('entry')
    assert (entry.id, entry.feed_url) == (result.id, result.feed_url)
    assert entry.title == result.metadata['.title'].value

    assert (
        reader._search.db.execute(
            "select count(*) from entries_search_sync_state;"
        ).fetchone()[0]
        == 1
    )
    assert (
        reader._search.db.execute("select count(*) from entries_search;").fetchone()[0]
        == 1
    )


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_original_feed_url(reader):
    reader.update_feeds()

    # Entry.original_feed_url should not change if the feed URL changes...

    assert {e.original_feed_url for e in reader.get_entries(feed='1')} == {'1'}
    reader.change_feed_url('1', '3')

    assert {e.original_feed_url for e in reader.get_entries(feed='3')} == {'1'}

    reader.change_feed_url('3', '4')
    assert {e.original_feed_url for e in reader.get_entries(feed='4')} == {'1'}

    # ... unless the entry appears with the same id in the new feed.

    reader._parser.feed(5, datetime(2010, 1, 2))
    reader._parser.entries[5].update(
        {
            e.id: e._replace(feed_url='5', updated=datetime(2010, 1, 2))
            for e in reader._parser.entries[1].values()
        }
    )

    reader.change_feed_url('4', '5')
    assert {e.original_feed_url for e in reader.get_entries(feed='5')} == {'1'}
    reader.update_feeds()
    assert {e.original_feed_url for e in reader.get_entries(feed='5')} == {'5'}


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_search(reader):
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    old = list(reader.search_entries('entry', feed='1'))
    assert {e.id for e in old} == {'1, 1', '1, 2'}
    assert {e.feed_url for e in old} == {'1'}

    reader.change_feed_url('1', '3')

    # TODO: maybe we should add an update_search() here,
    # to allow for the search results not being updated immediately

    assert list(reader.search_entries('entry', feed='1')) == []

    new = list(reader.search_entries('entry', feed='3'))
    assert new == [e._replace(feed_url='3') for e in old]


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_metadata(reader):
    reader.set_feed_metadata_item('1', 'key', 'value')

    reader.change_feed_url('1', '3')

    assert dict(reader.get_feed_metadata('1')) == {}
    assert dict(reader.get_feed_metadata('3')) == {'key': 'value'}


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_tags(reader):
    reader.add_feed_tag('1', 'tag')

    reader.change_feed_url('1', '3')

    assert set(reader.get_feed_tags('1')) == set()
    assert set(reader.get_feed_tags('3')) == {'tag'}


# END change_feed_url tests


def test_updates_enabled(reader):
    """Test Feed.updates_enabled functionality.

    https://github.com/lemon24/reader/issues/187#issuecomment-706539658

    """
    reader._parser = parser = FailingParser(condition=lambda url: False)

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    two_one = parser.entry(2, 1, datetime(2010, 1, 1))

    for feed in one, two:
        reader.add_feed(feed)

    # updates_enabled is true by default
    assert all(f.updates_enabled is True for f in reader.get_feeds())

    # sanity check that feeds were not updated yet
    assert all(f.updated is None for f in reader.get_feeds())
    assert {e.id for e in reader.get_entries()} == set()

    # sanity check that feeds update normally
    reader.update_feeds()
    assert all(f.updated == datetime(2010, 1, 1) for f in reader.get_feeds())
    assert {e.id: e.updated for e in reader.get_entries()} == {
        one_one.id: datetime(2010, 1, 1),
        two_one.id: datetime(2010, 1, 1),
    }

    # make one feed fail temporarily, so last_exception gets set
    parser.condition = lambda url: url == one.url
    reader.update_feeds()
    last_exception = reader.get_feed(one).last_exception
    assert last_exception is not None
    parser.condition = lambda url: False

    # disable_feed_updates sets updates_enabled to False
    reader.disable_feed_updates(one)
    assert reader.get_feed(one).updates_enabled is False
    # disable_feed_updates does not clear last_exception
    assert reader.get_feed(one).last_exception == last_exception
    # disable_feed_updates can be called twice
    reader.disable_feed_updates(one)

    one = parser.feed(1, datetime(2010, 1, 2))
    one_one = parser.entry(1, 1, datetime(2010, 1, 2))
    two = parser.feed(2, datetime(2010, 1, 2))
    two_one = parser.entry(2, 1, datetime(2010, 1, 2))

    # update_feeds skips feeds with updates_enabled == False
    reader.update_feeds()
    assert {f.url: f.updated for f in reader.get_feeds()} == {
        one.url: datetime(2010, 1, 1),
        two.url: datetime(2010, 1, 2),
    }
    assert {e.id: e.updated for e in reader.get_entries()} == {
        one_one.id: datetime(2010, 1, 1),
        two_one.id: datetime(2010, 1, 2),
    }

    # update_feed does not care about updates_enabled
    reader.update_feed(one)
    assert reader.get_feed(one).updated == datetime(2010, 1, 2)
    assert reader.get_entry(one_one).updated == datetime(2010, 1, 2)

    one = parser.feed(1, datetime(2010, 1, 3))
    one_one = parser.entry(1, 1, datetime(2010, 1, 3))
    two = parser.feed(2, datetime(2010, 1, 3))
    two_one = parser.entry(2, 1, datetime(2010, 1, 3))

    # update_feeds skips feeds with updates_enabled == False (again)
    reader.update_feeds()
    assert {f.url: f.updated for f in reader.get_feeds()} == {
        one.url: datetime(2010, 1, 2),
        two.url: datetime(2010, 1, 3),
    }
    assert {e.id: e.updated for e in reader.get_entries()} == {
        one_one.id: datetime(2010, 1, 2),
        two_one.id: datetime(2010, 1, 3),
    }

    # enable_feed_updates sets updates_enabled to True
    reader.enable_feed_updates(one)
    assert reader.get_feed(one).updates_enabled is True
    # enable_feed_updates can be called twice
    reader.enable_feed_updates(one)

    # update_feeds updates newly-enabled feeds
    reader.update_feeds()
    assert reader.get_feed(one).updated == datetime(2010, 1, 3)
    assert reader.get_entry(one_one).updated == datetime(2010, 1, 3)


def test_updates_enabled_errors(reader):
    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.enable_feed_updates('one')
    assert excinfo.value.url == 'one'
    assert 'no such feed' in excinfo.value.message

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.disable_feed_updates('one')
    assert excinfo.value.url == 'one'
    assert 'no such feed' in excinfo.value.message


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), FeedCounts(3, broken=1, updates_enabled=2)),
        (dict(feed='1'), FeedCounts(1, 0, 1)),
        (dict(tags=['tag']), FeedCounts(2, broken=1, updates_enabled=2)),
        (dict(broken=True), FeedCounts(1, broken=1, updates_enabled=1)),
        (dict(broken=False), FeedCounts(2, broken=0, updates_enabled=1)),
        (dict(updates_enabled=True), FeedCounts(2, broken=1, updates_enabled=2)),
        (dict(updates_enabled=False), FeedCounts(1, broken=0, updates_enabled=0)),
        (dict(broken=True, updates_enabled=False), FeedCounts(0, 0, 0)),
    ],
)
def test_feed_counts(reader, kwargs, expected):
    # TODO: fuzz get_feeds() == get_feed_counts()

    reader._parser = parser = FailingParser(condition=lambda url: False)

    one = parser.feed(1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    three = parser.feed(3, datetime(2010, 1, 1))

    for feed in one, two, three:
        reader.add_feed(feed)

    parser.condition = lambda url: url == two.url
    reader.disable_feed_updates(three)
    reader.add_feed_tag(one, 'tag')
    reader.add_feed_tag(two, 'tag')

    reader.update_feeds()

    assert reader.get_feed_counts(**kwargs) == expected


def get_entry_counts(reader, **kwargs):
    return reader.get_entry_counts(**kwargs)


def search_entry_counts(reader, **kwargs):
    return reader.search_entry_counts('entry', **kwargs)


with_call_entry_counts_method = pytest.mark.parametrize(
    'pre_stuff, call_method, rv_type',
    [
        (lambda _: None, get_entry_counts, EntryCounts),
        (enable_and_update_search, search_entry_counts, EntrySearchCounts),
    ],
)


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), EntryCounts(9, read=2, important=4, has_enclosures=8)),
        (dict(feed='1'), EntryCounts(1, read=0, important=0, has_enclosures=0)),
        (dict(feed='2'), EntryCounts(8, read=2, important=4, has_enclosures=8)),
        (
            dict(entry=('1', '1, 1')),
            EntryCounts(1, read=0, important=0, has_enclosures=0),
        ),
        (
            dict(entry=('2', '2, 1')),
            EntryCounts(1, read=1, important=1, has_enclosures=1),
        ),
        (
            dict(entry=('2', '2, 3')),
            EntryCounts(1, read=0, important=1, has_enclosures=1),
        ),
        (
            dict(entry=('2', '2, 5')),
            EntryCounts(1, read=0, important=0, has_enclosures=1),
        ),
        (dict(read=True), EntryCounts(2, read=2, important=2, has_enclosures=2)),
        (dict(read=False), EntryCounts(7, read=0, important=2, has_enclosures=6)),
        (dict(important=True), EntryCounts(4, read=2, important=4, has_enclosures=4)),
        (dict(important=False), EntryCounts(5, read=0, important=0, has_enclosures=4)),
        (
            dict(has_enclosures=True),
            EntryCounts(8, read=2, important=4, has_enclosures=8),
        ),
        (
            dict(has_enclosures=False),
            EntryCounts(1, read=0, important=0, has_enclosures=0),
        ),
        (
            dict(feed_tags=['tag']),
            EntryCounts(1, read=0, important=0, has_enclosures=0),
        ),
    ],
)
@with_call_entry_counts_method
def test_entry_counts(reader, kwargs, expected, pre_stuff, call_method, rv_type):
    # TODO: fuzz get_entries() == get_entry_counts()

    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 3))
    two = parser.feed(2, datetime(2010, 1, 3))
    three = parser.feed(3, datetime(2010, 1, 1))
    one_entry = parser.entry(
        1,
        1,
        datetime(2010, 1, 3),
        summary='summary',
        content=(Content('value3', 'type', 'en'), Content('value2')),
    )
    two_entries = [
        parser.entry(2, i, datetime(2010, 1, 3), enclosures=[]) for i in range(1, 1 + 8)
    ]

    # TODO: less overlap would be nice (e.g. some read that don't have enclosures)

    for entry in two_entries[:8]:
        int_feed_url, int_id = eval(entry.id)
        parser.entries[int_feed_url][int_id].enclosures.append(Enclosure('http://e'))

    for feed in one, two, three:
        reader.add_feed(feed)

    reader.add_feed_tag(one, 'tag')

    reader.update_feeds()
    pre_stuff(reader)

    for entry in two_entries[:2]:
        reader.mark_entry_as_read(entry)
    for entry in two_entries[:4]:
        reader.mark_entry_as_important(entry)

    rv = call_method(reader, **kwargs)
    assert type(rv) is rv_type
    # this isn't gonna work as well if the return types get different attributes
    assert rv._asdict() == expected._asdict()


with_call_paginated_method = pytest.mark.parametrize(
    'pre_stuff, call_method, sort_kwargs',
    [
        (lambda _: None, get_feeds, {}),
        (lambda _: None, get_feeds, dict(sort='title')),
        (lambda _: None, get_feeds, dict(sort='added')),
        (lambda _: None, get_entries, {}),
        (lambda _: None, get_entries, dict(sort='recent')),
        (enable_and_update_search, search_entries, {}),
        (enable_and_update_search, search_entries, dict(sort='relevant')),
        (enable_and_update_search, search_entries, dict(sort='recent')),
    ],
)


@pytest.fixture
def reader_with_three_feeds(reader):
    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1))
    parser.entry(1, 2, datetime(2010, 1, 1))
    parser.entry(1, 3, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    three = parser.feed(3, datetime(2010, 1, 1))

    for feed in one, two, three:
        reader.add_feed(feed)

    return reader


@with_call_paginated_method
@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 0, 1, 2])
@rename_argument('reader', 'reader_with_three_feeds')
def test_pagination_basic(reader, pre_stuff, call_method, sort_kwargs, chunk_size):
    reader._storage.chunk_size = chunk_size

    reader.update_feeds()
    pre_stuff(reader)

    def get_ids(**kwargs):
        return [o.object_id for o in call_method(reader, **sort_kwargs, **kwargs)]

    ids = get_ids()

    assert get_ids(starting_after=ids[0]) == ids[1:]
    assert get_ids(starting_after=ids[1]) == ids[2:]
    assert get_ids(starting_after=ids[2]) == ids[3:] == []

    assert get_ids(limit=1) == ids[:1]
    assert get_ids(limit=2) == ids[:2]
    assert get_ids(limit=3) == ids[:3] == ids

    assert get_ids(limit=1, starting_after=ids[0]) == ids[1:2]
    assert get_ids(limit=2, starting_after=ids[0]) == ids[1:3]
    assert get_ids(limit=2, starting_after=ids[1]) == ids[2:]
    assert get_ids(limit=2, starting_after=ids[2]) == ids[3:] == []


@pytest.mark.parametrize(
    'pre_stuff, call_method',
    [
        (lambda _: None, get_entries),
        (enable_and_update_search, search_entries),
    ],
)
@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 0, 1, 2])
@rename_argument('reader', 'reader_with_three_feeds')
def test_pagination_random(reader, pre_stuff, call_method, chunk_size):
    reader._storage.chunk_size = chunk_size

    reader.update_feeds()
    pre_stuff(reader)

    def get_ids(**kwargs):
        return [o.object_id for o in call_method(reader, sort='random', **kwargs)]

    ids = [o.object_id for o in call_method(reader)]

    assert len(get_ids(limit=1)) == min(1, chunk_size or 1, len(ids))
    assert len(get_ids(limit=2)) == min(2, chunk_size or 2, len(ids))
    assert len(get_ids(limit=3)) == min(3, chunk_size or 3, len(ids))

    with pytest.raises(ValueError):
        get_ids(starting_after=ids[0])

    with pytest.raises(ValueError):
        get_ids(limit=1, starting_after=ids[0])


NOT_FOUND_ERROR_CLS = {
    get_feeds: FeedNotFoundError,
    get_entries: EntryNotFoundError,
    search_entries: EntryNotFoundError,
}

NOT_FOUND_STARTING_AFTER = {
    get_feeds: '0',
    get_entries: ('1', '1, 0'),
    search_entries: ('1', '1, 0'),
}


@with_call_paginated_method
def test_starting_after_errors(reader, pre_stuff, call_method, sort_kwargs):
    pre_stuff(reader)

    error_cls = NOT_FOUND_ERROR_CLS[call_method]
    starting_after = NOT_FOUND_STARTING_AFTER[call_method]

    with pytest.raises(error_cls) as excinfo:
        list(call_method(reader, **sort_kwargs, starting_after=starting_after))
    assert excinfo.value.object_id == starting_after


@with_call_paginated_method
def test_limit_errors(reader, pre_stuff, call_method, sort_kwargs):
    pre_stuff(reader)

    def get_ids(**kwargs):
        return [o.object_id for o in call_method(reader, **sort_kwargs, **kwargs)]

    with pytest.raises(ValueError):
        get_ids(limit=object())
    with pytest.raises(ValueError):
        get_ids(limit=0)
    with pytest.raises(ValueError):
        get_ids(limit=-1)
    with pytest.raises(ValueError):
        get_ids(limit=1.0)


def test_logging_defaults():
    logger = logging.getLogger('reader')
    assert logger.level == logging.NOTSET
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)


@pytest.mark.parametrize(
    'kwargs, expected_timeout',
    [
        ({}, reader._parser.SESSION_TIMEOUT),
        ({'session_timeout': (1.234, 324.1)}, (1.234, 324.1)),
    ],
)
def test_session_timeout(monkeypatch, make_reader, kwargs, expected_timeout):
    def send(*args, timeout=None, **kwargs):
        raise Exception('timeout', timeout)

    monkeypatch.setattr('requests.adapters.HTTPAdapter.send', send)

    reader = make_reader(':memory:', **kwargs)
    reader.add_feed('http://www.example.com')

    with pytest.raises(ParseError) as exc_info:
        reader.update_feed('http://www.example.com')

    assert exc_info.value.__cause__.args == ('timeout', expected_timeout)


def test_plugins(monkeypatch, make_reader):
    def one(reader):
        one.reader = reader

    def two(reader):
        two.reader = reader

    from reader.plugins import _PLUGINS

    monkeypatch.setitem(_PLUGINS, 'one', one)

    reader = make_reader(':memory:', plugins=['one', two])

    assert one.reader is reader
    assert two.reader is reader

    with pytest.raises(InvalidPluginError) as exc_info:
        make_reader(':memory:', plugins=['two'])

    assert str(exc_info.value) == "no such built-in plugin: 'two'"


def test_reserved_names(make_reader):
    with pytest.raises(ValueError):
        make_reader(':memory:', reserved_name_scheme={})

    reader = make_reader(':memory:')

    assert reader.make_reader_reserved_name('key') == '.reader.key'
    assert reader.make_plugin_reserved_name('myplugin') == '.plugin.myplugin'
    assert reader.make_plugin_reserved_name('myplugin', 'key') == '.plugin.myplugin.key'

    with pytest.raises(AttributeError):
        reader.reserved_name_scheme = {}

    new_scheme = {'reader_prefix': '', 'plugin_prefix': '.', 'separator': ':'}

    reader.reserved_name_scheme = new_scheme

    assert reader.make_reader_reserved_name('key') == 'key'
    assert reader.make_plugin_reserved_name('myplugin') == '.myplugin'
    assert reader.make_plugin_reserved_name('myplugin', 'key') == '.myplugin:key'

    assert dict(reader.reserved_name_scheme) == new_scheme

    with pytest.raises(TypeError):
        reader.reserved_name_scheme['separator'] = '.'
