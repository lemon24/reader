import logging
import os
import random
import sys
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from datetime import timezone
from enum import Enum
from itertools import permutations

import pytest

import reader._parser
from fakeparser import Parser
from reader import Content
from reader import Enclosure
from reader import Entry
from reader import EntryCounts
from reader import EntryError
from reader import EntryExistsError
from reader import EntryNotFoundError
from reader import EntrySearchCounts
from reader import Feed
from reader import FeedCounts
from reader import FeedExistsError
from reader import FeedNotFoundError
from reader import InvalidFeedURLError
from reader import ParseError
from reader import Reader
from reader import StorageError
from reader import TagNotFoundError
from reader import UpdatedFeed
from reader import UpdateResult
from reader._parser import HTTPInfo
from reader._parser import RetrieveError
from reader._storage import Storage
from reader._types import FeedFilter
from reader._types import FeedToUpdate
from reader._types import FeedUpdateIntent
from reader._update import next_update_after
from reader.core import DEFAULT_RESERVED_NAME_SCHEME
from reader_methods import enable_and_update_search
from reader_methods import get_entries
from reader_methods import get_entries_random
from reader_methods import get_entries_recent
from reader_methods import get_feeds
from reader_methods import search_entries
from reader_methods import search_entries_random
from reader_methods import search_entries_recent
from reader_methods import search_entries_relevant
from utils import Blocking
from utils import make_url_base
from utils import rename_argument
from utils import utc_datetime
from utils import utc_datetime as datetime


# TODO: testing added/last_updated/last_retrieved/update_after everywhere is kinda ugly


def test_update_feed_updated(reader, parser, update_feed, caplog):
    """If a feed is not newer than the stored one,
    it should be updated only if its content (hash) changed.

    Its entries should be processed anyway.

    Details in https://github.com/lemon24/reader/issues/76

    """
    # Initial update.
    old_feed = parser.feed(1, datetime(2010, 1, 1), title='old')
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(old_feed.url)
    reader._now = lambda: datetime(2010, 1, 2)

    with caplog.at_level(logging.DEBUG, 'reader'):
        update_feed(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 2),
        last_retrieved=datetime(2010, 1, 2),
        update_after=datetime(2010, 1, 2, 1),
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        )
    }
    assert "feed has no last_updated, treating as updated" in caplog.text
    caplog.clear()

    # Entries should be processed anyway.
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 3)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 3),
        last_retrieved=datetime(2010, 1, 3),
        update_after=datetime(2010, 1, 3, 1),
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        ),
        entry_two.as_entry(
            feed=feed,
            added=datetime(2010, 1, 3),
            last_updated=datetime(2010, 1, 3),
        ),
    }
    assert "feed has entries to update, treating as updated" in caplog.text
    caplog.clear()

    # Feed gets updated because content (hash) changed.
    old_feed = parser.feed(1, datetime(2010, 1, 1), title='old-different-title')
    reader._now = lambda: datetime(2010, 1, 3, 12)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 3, 12),
        last_retrieved=datetime(2010, 1, 3, 12),
        update_after=datetime(2010, 1, 3, 13),
    )
    assert reader.get_feed(feed) == feed
    assert "feed hash changed, treating as updated" in caplog.text
    caplog.clear()

    # The feed changes if entries changed, regardless of .updated being older.
    # Entries get updated regardless.
    old_feed = parser.feed(1, datetime(2009, 1, 1), title='old-different-title')
    entry_three = parser.entry(1, 3, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 4)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        updated=datetime(2009, 1, 1),
        last_updated=datetime(2010, 1, 4),
        last_retrieved=datetime(2010, 1, 4),
        update_after=datetime(2010, 1, 4, 1),
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        ),
        entry_two.as_entry(
            feed=feed,
            added=datetime(2010, 1, 3),
            last_updated=datetime(2010, 1, 3),
        ),
        entry_three.as_entry(
            feed=feed,
            added=datetime(2010, 1, 4),
            last_updated=datetime(2010, 1, 4),
        ),
    }
    assert "feed has entries to update, treating as updated" in caplog.text
    caplog.clear()

    # The feed doesn't change if only .updated changes (and there are no updated entries).
    old_feed = parser.feed(1, datetime(2010, 1, 2), title='old-different-title')
    reader._now = lambda: datetime(2010, 1, 4, 12)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, old_feed.url)

    feed = old_feed.as_feed(
        added=datetime(2010, 1, 1),
        # doesn't change because nothing except .updated changed
        updated=datetime(2009, 1, 1),
        # doesn't change because nothing changed
        last_updated=datetime(2010, 1, 4),
        # changes always
        last_retrieved=datetime(2010, 1, 4, 12),
        update_after=datetime(2010, 1, 4, 13),
    )
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        ),
        entry_two.as_entry(
            feed=feed,
            added=datetime(2010, 1, 3),
            last_updated=datetime(2010, 1, 3),
        ),
        entry_three.as_entry(
            feed=feed,
            added=datetime(2010, 1, 4),
            last_updated=datetime(2010, 1, 4),
        ),
    }
    assert "only feed updated changed, skipping" in caplog.text
    caplog.clear()

    # The feeds changes because ~~it is newer *and*~~ entries get updated.
    # TODO: same as "The feed changes if entries changed, regardless ...", remove?
    new_feed = parser.feed(1, datetime(2010, 1, 2), title='new')
    entry_four = parser.entry(1, 4, datetime(2010, 2, 1))
    reader._now = lambda: datetime(2010, 1, 5)
    feed = new_feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 5),
        last_retrieved=datetime(2010, 1, 5),
        update_after=datetime(2010, 1, 5, 1),
    )

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, old_feed.url)

    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        ),
        entry_two.as_entry(
            feed=feed,
            added=datetime(2010, 1, 3),
            last_updated=datetime(2010, 1, 3),
        ),
        entry_three.as_entry(
            feed=feed,
            added=datetime(2010, 1, 4),
            last_updated=datetime(2010, 1, 4),
        ),
        entry_four.as_entry(
            feed=feed,
            added=datetime(2010, 1, 5),
            last_updated=datetime(2010, 1, 5),
        ),
    }
    assert "feed has entries to update, treating as updated" in caplog.text
    caplog.clear()


def test_update_entry_updated(reader, parser, update_feed, caplog, monkeypatch):
    """An entry should be updated only if
    it is newer than the stored one OR its content (hash) changed.

    """
    # Initial update.
    feed = parser.feed(1, datetime(2010, 1, 1))
    old_entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader._now = lambda: datetime(2010, 2, 1)
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 2, 2)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, feed.url)

    feed = feed.as_feed(
        added=datetime(2010, 2, 1),
        last_updated=datetime(2010, 2, 2),
        last_retrieved=datetime(2010, 2, 2),
        update_after=datetime(2010, 2, 2, 1),
    )

    assert set(reader.get_entries()) == {
        old_entry.as_entry(
            feed=feed,
            added=datetime(2010, 2, 2),
            last_updated=datetime(2010, 2, 2),
        )
    }
    assert "entry new, updating" in caplog.text
    caplog.clear()

    # Feed newer (doesn't change), entry remains unchanged.
    feed = parser.feed(1, datetime(2010, 1, 2))
    reader._now = lambda: datetime(2010, 2, 3)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, feed.url)

    feed = feed.as_feed(
        added=datetime(2010, 2, 1),
        updated=datetime(2010, 1, 1),
        last_updated=datetime(2010, 2, 2),
        last_retrieved=datetime(2010, 2, 3),
        update_after=datetime(2010, 2, 3, 1),
    )
    assert set(reader.get_entries()) == {
        old_entry.as_entry(
            feed=feed,
            added=datetime(2010, 2, 2),
            last_updated=datetime(2010, 2, 2),
        )
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
        update_feed(reader, feed.url)

    feed = feed.as_feed(
        added=datetime(2010, 2, 1),
        last_updated=datetime(2010, 2, 3, 12),
        last_retrieved=datetime(2010, 2, 3, 12),
        update_after=datetime(2010, 2, 3, 13),
    )
    assert set(reader.get_entries()) == {
        new_entry.as_entry(
            feed=feed,
            added=datetime(2010, 2, 2),
            last_updated=datetime(2010, 2, 3, 12),
        )
    }
    assert "entry hash changed, updating" in caplog.text
    caplog.clear()

    # Entry is newer.
    feed = parser.feed(1, datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    parser.entries[1][1] = new_entry
    reader._now = lambda: datetime(2010, 2, 4)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        update_feed(reader, feed.url)

    feed = feed.as_feed(
        added=datetime(2010, 2, 1),
        last_updated=datetime(2010, 2, 4),
        last_retrieved=datetime(2010, 2, 4),
        update_after=datetime(2010, 2, 4, 1),
    )
    assert set(reader.get_entries()) == {
        new_entry.as_entry(
            feed=feed,
            added=datetime(2010, 2, 2),
            last_updated=datetime(2010, 2, 4),
        )
    }
    assert "entry updated, updating" in caplog.text
    caplog.clear()

    # Entry hash changes, but reaches the update limit.
    reader._now = lambda: datetime(2010, 2, 5)
    monkeypatch.setattr('reader._update.HASH_CHANGED_LIMIT', 3)

    with caplog.at_level(logging.DEBUG, logger='reader'):
        for i in range(1, 6):
            new_entry = new_entry._replace(title=f"Even Newer: change #{i}")
            parser.entries[1][1] = new_entry
            update_feed(reader, feed.url)

    assert {e.title for e in reader.get_entries()} == {"Even Newer: change #3"}
    assert caplog.text.count("entry hash changed, updating") == 3
    assert caplog.text.count("entry hash changed, but exceeds the update limit") == 2
    caplog.clear()


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_update_no_updated(reader, parser, chunk_size, update_feed):
    """If a feed has updated == None, it should be treated as updated.

    If an entry has updated == None, it should be updated every time.

    """
    reader._storage.chunk_size = chunk_size

    feed = parser.feed(1, None, title='old')
    entry_one = parser.entry(1, 1, None, title='old')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(feed.url)
    update_feed(reader, feed)
    feed = feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 1),
        last_retrieved=datetime(2010, 1, 1),
        update_after=datetime(2010, 1, 1, 1),
    )

    assert set(reader.get_feeds()) == {feed}
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            updated=None,
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 1),
        )
    }

    feed = parser.feed(1, None, title='new')
    entry_one = parser.entry(1, 1, None, title='new')
    entry_two = parser.entry(1, 2, None)
    reader._now = lambda: datetime(2010, 1, 2)
    update_feed(reader, feed)
    feed = feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 2),
        last_retrieved=datetime(2010, 1, 2),
        update_after=datetime(2010, 1, 2, 1),
    )

    assert set(reader.get_feeds()) == {feed}
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=feed,
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 2),
        ),
        entry_two.as_entry(
            feed=feed,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        ),
    }


@pytest.mark.slow
def test_update_blocking(db_path, make_reader, parser, update_feed):
    """Calls to reader._parser() shouldn't block the underlying storage."""

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    feed2 = parser.feed(2, datetime(2010, 1, 1))

    reader = make_reader(db_path)

    reader.add_feed(feed.url)
    reader.add_feed(feed2.url)
    reader.update_feeds()

    parser.retrieve = blocking_retrieve = Blocking(parser.retrieve)

    def target():
        with reader:
            update_feed(reader, feed.url)

    t = threading.Thread(target=target)
    t.start()

    with blocking_retrieve:
        # shouldn't raise an exception
        reader.mark_entry_as_read((feed.url, entry.id))

    t.join()


def test_update_not_modified(reader, parser, update_feed):
    """A feed should not be updated if it was not modified."""

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    update_feed(reader, feed.url)

    parser.feed(1, datetime(2010, 1, 2))
    parser.entry(1, 1, datetime(2010, 1, 2))

    reader._parser.not_modified()

    # shouldn't raise an exception
    update_feed(reader, feed.url)

    assert set(reader.get_entries()) == set()


def test_update_new(reader, parser):
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

    two = two.as_feed(
        added=datetime(2010, 1, 1, 12),
        last_updated=datetime(2010, 1, 2),
        last_retrieved=datetime(2010, 1, 2),
        update_after=datetime(2010, 1, 2, 1),
    )
    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_two.as_entry(
            feed=two,
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        )
    }

    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    one = one.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 3),
        last_retrieved=datetime(2010, 1, 3),
        update_after=datetime(2010, 1, 3, 1),
    )
    assert len(set(reader.get_feeds())) == 2
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=one,
            added=datetime(2010, 1, 3),
            last_updated=datetime(2010, 1, 3),
        ),
        entry_two.as_entry(
            feed=two._replace(
                last_retrieved=datetime(2010, 1, 3),
                update_after=datetime(2010, 1, 3, 1),
            ),
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 2),
        ),
    }


def test_update_new_no_last_updated(reader, parser):
    """A feed should be updated if it has no last_updated.

    https://github.com/lemon24/reader/issues/95

    """
    feed = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds(new=True)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


def test_update_new_not_modified(reader, parser):
    """A feed should not be considered new anymore after getting _NotModified.

    https://github.com/lemon24/reader/issues/95

    """
    parser.not_modified()

    feed = parser.feed(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds(new=True)

    parser.reset_mode()

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds(new=True)

    # the entry isn't added because feed is not new on the second update_feeds
    assert len(list(reader.get_entries(feed=feed.url))) == 0


@pytest.mark.parametrize('workers', [-1, 0])
def test_update_workers(reader, parser, workers):
    one = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(one.url)
    with pytest.raises(ValueError):
        reader.update_feeds(workers=workers)


def test_update_last_updated_entries_updated_feed_not_updated(
    reader, parser, update_feed
):
    """A feed's last_updated should be updated if any of its entries are,
    even if the feed itself isn't updated.

    """
    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 1, 1)
    update_feed(reader, feed.url)

    def get_feed_for_update(feed):
        options = FeedFilter.from_args(feed)
        (rv,) = reader._storage.get_feeds_for_update(options)
        return rv

    feed_for_update = get_feed_for_update(feed)
    assert feed_for_update.last_updated == datetime(2010, 1, 1)

    parser.entry(1, 1, datetime(2010, 1, 1))
    reader._now = lambda: datetime(2010, 1, 2)
    update_feed(reader, feed.url)

    feed_for_update = get_feed_for_update(feed)
    assert feed_for_update.last_updated == datetime(2010, 1, 2)


@pytest.mark.parametrize('workers', [1, 2])
def test_update_feeds_parse_error(reader, parser, workers, caplog):
    caplog.set_level(logging.ERROR, 'reader')

    one = parser.feed(1, datetime(2010, 1, 1), title='one')
    two = parser.feed(2, datetime(2010, 1, 1), title='two')
    three = parser.feed(3, datetime(2010, 1, 1), title='three')

    for feed in one, two, three:
        reader.add_feed(feed.url)
    reader.update_feeds(workers=workers)

    assert {f.title for f in reader.get_feeds()} == {'one', 'two', 'three'}

    parser.raise_exc(lambda url: url == '2')
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


@pytest.mark.parametrize('workers', [1, 2])
def test_update_feeds_parse_error_on_retriever_enter(reader, parser, workers):
    one = parser.feed(1, datetime(2010, 1, 1), title='one')
    two = parser.feed(2, datetime(2010, 1, 1), title='two')
    three = parser.feed(3, datetime(2010, 1, 1), title='three')

    for feed in one, two, three:
        reader.add_feed(feed.url)

    def retrieve(url, *args):
        @contextmanager
        def make_context():
            raise ParseError(url)
            yield 'unreachable'

        return make_context()

    parser.retrieve = retrieve

    reader.update_feeds(workers=workers)

    assert {f.url for f in reader.get_feeds(new=True)} == set()
    assert {f.url for f in reader.get_feeds(broken=True)} == {'1', '2', '3'}


@pytest.fixture
def reader_with_one_feed(reader, parser):
    feed = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    return reader


@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_not_updated(reader, update_feed):
    assert reader.get_feed('1').last_exception is None


@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_ok(reader, update_feed):
    update_feed(reader, '1')
    assert reader.get_feed('1').last_exception is None
    assert next(reader.get_entries()).feed.last_exception is None


@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_failed(reader, parser, update_feed):
    update_feed(reader, '1')

    def get_feed_last_updated(feed):
        options = FeedFilter.from_args(None, feed)
        (rv,) = reader._storage.get_feeds_for_update(options)
        return rv.last_updated

    old_last_updated = get_feed_last_updated('1')
    assert old_last_updated is not None

    parser.raise_exc()
    try:
        update_feed(reader, '1')
    except ParseError:
        pass

    # The cause gets stored.
    last_exception = reader.get_feed('1').last_exception
    assert next(reader.get_entries()).feed.last_exception == last_exception
    assert last_exception.type_name == 'reader.exceptions.ParseError'
    assert last_exception.value_str == "'1': builtins.Exception: failing"
    assert last_exception.traceback_str.startswith('Traceback')

    parser.raise_exc(ValueError('another'))
    try:
        update_feed(reader, '1')
    except ParseError:
        pass

    # The cause changes.
    last_exception = reader.get_feed('1').last_exception
    assert last_exception.type_name == 'reader.exceptions.ParseError'
    assert last_exception.value_str == "'1': builtins.ValueError: another"

    # The cause does not get reset if other feeds get updated.
    parser.reset_mode()
    parser.feed(2, datetime(2010, 1, 1))
    reader.add_feed('2')
    reader.update_feeds(new=True)
    assert reader.get_feed('1').last_exception == last_exception
    assert reader.get_feed('2').last_exception is None

    # None of the failures bumped last_updated.
    new_last_updated = get_feed_last_updated('1')
    assert new_last_updated == old_last_updated


def updated_feeds_parser(parser):
    parser.feeds = {
        number: feed._replace(
            updated=feed.updated + timedelta(1), title=f'New title for #{number}'
        )
        for number, feed in parser.feeds.items()
    }
    parser.reset_mode()


@pytest.mark.parametrize(
    'update_parser',
    [
        Parser.reset_mode,
        updated_feeds_parser,
        Parser.not_modified,
    ],
)
@rename_argument('reader', 'reader_with_one_feed')
def test_last_exception_reset(reader, update_feed, update_parser):
    update_feed(reader, '1')

    reader._parser.raise_exc()
    try:
        update_feed(reader, '1')
    except ParseError:
        pass

    update_parser(reader._parser)

    update_feed(reader, '1')
    assert reader.get_feed('1').last_exception is None


def test_update_feeds_unexpected_error(reader, parser, monkeypatch):
    feed = parser.feed(1, datetime(2010, 1, 1), title='one')
    reader.add_feed(feed.url)

    exc = Exception('unexpected')

    def _update_feed(*_, **__):
        raise exc

    monkeypatch.setattr('reader._update.Pipeline.update_feed', _update_feed)

    with pytest.raises(Exception) as excinfo:
        reader.update_feeds()

    assert excinfo.value is exc


@pytest.mark.parametrize('action', ['', 'not_modified', 'raise_exc'])
def test_last_retrieved_update_after_basic(reader, parser, action):
    feed = parser.feed(1)
    reader.add_feed(feed)

    feed = reader.get_feed(feed)
    assert feed.last_retrieved is None
    assert feed.update_after is None
    assert feed.last_updated is None

    if action:
        getattr(parser, action)()

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    assert feed.last_retrieved == datetime(2010, 1, 1)
    assert feed.update_after == datetime(2010, 1, 1, 1)
    assert feed.last_updated == (datetime(2010, 1, 1) if not action else None)

    reader._now = lambda: datetime(2010, 1, 1, 0, 59, 59)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    assert feed.last_retrieved == datetime(2010, 1, 1, 0, 59, 59)
    assert feed.update_after == datetime(2010, 1, 1, 1)

    reader._now = lambda: datetime(2010, 1, 1, 1)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    assert feed.last_retrieved == datetime(2010, 1, 1, 1)
    assert feed.update_after == datetime(2010, 1, 1, 2)


@pytest.mark.parametrize(
    'global_config, feed_config, expected',
    [
        ({'interval': 120}, Ellipsis, datetime(2010, 1, 1, 2)),
        (Ellipsis, {'interval': 120}, datetime(2010, 1, 1, 2)),
        ({'interval': 60 * 24 * 1000}, {'interval': 120}, datetime(2010, 1, 1, 2)),
        # minimum value
        ({'interval': 1}, Ellipsis, datetime(2010, 1, 1, 0, 1)),
    ],
)
def test_update_after_interval(reader, parser, global_config, feed_config, expected):
    feed = parser.feed(1)
    reader.add_feed(feed)

    if global_config is not Ellipsis:
        reader.set_tag((), '.reader.update', global_config)
    if feed_config is not Ellipsis:
        reader.set_tag(feed, '.reader.update', feed_config)

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    assert feed.update_after == expected


@pytest.mark.parametrize(
    'global_config, feed_config',
    [
        ({'interval': 60 * 24, 'jitter': 1 / 12}, Ellipsis),
        (Ellipsis, {'interval': 60 * 24, 'jitter': 1 / 12}),
        ({'interval': 60 * 24}, {'jitter': 1 / 12}),
        ({'jitter': 1 / 12}, {'interval': 60 * 24}),
        ({'interval': 60 * 24, 'jitter': 1}, {'jitter': 1 / 12}),
    ],
)
def test_update_after_jitter(reader, parser, global_config, feed_config, monkeypatch):
    feed = parser.feed(1)
    reader.add_feed(feed)

    if global_config is not Ellipsis:
        reader.set_tag((), '.reader.update', global_config)
    if feed_config is not Ellipsis:
        reader.set_tag(feed, '.reader.update', feed_config)

    monkeypatch.setattr('random.random', lambda: 0.1)

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    # 0.1 * 120 minutes = 12 minutes
    assert feed.update_after == datetime(2010, 1, 2, 0, 12)


@pytest.mark.parametrize(
    'config',
    [
        {},
        None,
        'not-a-dict',
        {'interval': None, 'jitter': None},
        {'interval': '1.0', 'jitter': 'not-a-float'},
        {'interval': 'inf', 'jitter': 'inf'},
        {'interval': 0, 'jitter': 'nan'},
        {'jitter': -1},
        {'jitter': 100},
    ],
)
@pytest.mark.parametrize('config_is_global', [True, False])
def test_update_after_invalid_config(reader, parser, config, config_is_global):
    feed = parser.feed(1)
    reader.add_feed(feed)

    reader.set_tag(() if config_is_global else feed, '.reader.update', config)

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    assert feed.update_after == datetime(2010, 1, 1, 1)


@pytest.mark.parametrize(
    'interval, retry_after, update_after',
    [
        (60, 3600, datetime(2010, 1, 1, 1)),
        (60, 6000, datetime(2010, 1, 1, 2)),
        (60, 'Fri, 01 Jan 2010 01:40:00 GMT', datetime(2010, 1, 1, 2)),
        (60, 'Fri, 01 Jan 2010 01:40:00', datetime(2010, 1, 1, 2)),
        (60, 'Fri, 01 Jan 2010 02:40:00 +0100', datetime(2010, 1, 1, 2)),
        (60, 2000, datetime(2010, 1, 1, 1)),
        (15, 6000, datetime(2010, 1, 1, 1, 45)),
        (15, 2000, datetime(2010, 1, 1, 0, 45)),
        (60, None, datetime(2010, 1, 1, 1)),
        (60, -2000, datetime(2010, 1, 1, 1)),
        (60, 'Fri, 01 Jan 2010 00:40:00 GMT', datetime(2010, 1, 1, 1)),
        (60, 'Thu, 31 Dec 2009 23:40:00 GMT', datetime(2010, 1, 1, 1)),
        (60, "not a date, not an int", datetime(2010, 1, 1, 1)),
    ],
)
def test_update_retry_after(reader, parser, interval, retry_after, update_after):
    feed = parser.feed(1)
    reader.add_feed(feed)

    reader.set_tag(feed, '.reader.update', {'interval': interval})

    status = random.choice([429, 503])
    headers = {'retry-after': retry_after} if retry_after is not None else {}
    parser.raise_exc(RetrieveError('', http_info=HTTPInfo(status, headers)))

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()
    feed = reader.get_feed(feed)

    assert feed.update_after == update_after


@pytest.mark.parametrize(
    'now, interval, jitter, random, expected',
    [
        # hours
        (datetime(2010, 1, 1), 60 * 8, 0, 0, datetime(2010, 1, 1, 8)),
        (datetime(2010, 1, 1, 7, 59, 59), 60 * 8, 0, 0, datetime(2010, 1, 1, 8)),
        (datetime(2010, 1, 1, 8), 60 * 8, 0, 0, datetime(2010, 1, 1, 16)),
        (datetime(2010, 1, 1, 20), 60 * 8, 0, 0, datetime(2010, 1, 2)),
        # days
        # if the interval is 7 days, the next value is a Monday
        (datetime(2010, 1, 1), 60 * 24 * 7, 0, 0, datetime(2010, 1, 4)),
        (datetime(2010, 1, 3, 23, 59, 59), 60 * 24 * 7, 0, 0, datetime(2010, 1, 4)),
        (datetime(2010, 1, 4), 60 * 24 * 7, 0, 0, datetime(2010, 1, 11)),
        (datetime(2024, 5, 30), 60 * 24 * 7, 0, 0, datetime(2024, 6, 3)),
        # otherwise, it's somewhat arbitrary (but next values are interval apart)
        (datetime(2010, 1, 1), 60 * 24 * 3, 0, 0, datetime(2010, 1, 2)),
        (datetime(2010, 1, 1, 23), 60 * 24 * 3, 0, 0, datetime(2010, 1, 2)),
        (datetime(2010, 1, 2), 60 * 24 * 3, 0, 0, datetime(2010, 1, 5)),
        (datetime(2010, 1, 4, 23), 60 * 24 * 3, 0, 0, datetime(2010, 1, 5)),
        (datetime(2010, 1, 5), 60 * 24 * 3, 0, 0, datetime(2010, 1, 8)),
        # jitter
        (datetime(2010, 1, 1), 60 * 8, 1, 0, datetime(2010, 1, 1, 8)),
        (datetime(2010, 1, 1), 60 * 8, 1, 0.5, datetime(2010, 1, 1, 12)),
        (datetime(2010, 1, 1), 60 * 8, 1, 1, datetime(2010, 1, 1, 16)),
        (datetime(2010, 1, 1), 60 * 8, 0.5, 0.5, datetime(2010, 1, 1, 10)),
        (datetime(2010, 1, 1), 60 * 8, 0.5, 0.1, datetime(2010, 1, 1, 8, 24)),
        (datetime(2010, 1, 1), 60 * 8, 0.5, 0.12, datetime(2010, 1, 1, 8, 28)),
        (datetime(2010, 1, 1), 60 * 8, 0.5, 0.123, datetime(2010, 1, 1, 8, 29)),
    ],
)
def test_next_update_after(monkeypatch, now, interval, jitter, random, expected):
    monkeypatch.setattr('random.random', lambda: random)
    assert next_update_after(now, interval, jitter) == expected


def test_update_scheduled(reader, parser, call_update_iter_method):
    one = parser.feed(1)
    two = parser.feed(2)
    three = parser.feed(3)
    for feed in one, two, three:
        reader.add_feed(feed)

    reader.set_tag(two, '.reader.update', {'interval': 1})
    reader.set_tag(three, '.reader.update', {'interval': 120, 'jitter': 0.5})

    def update():
        return set(dict(call_update_iter_method(reader, scheduled=True)))

    reader._now = lambda: datetime(2010, 1, 1)
    assert update() == {'1', '2', '3'}
    assert update() == set()

    reader._now = lambda: datetime(2010, 1, 1, 0, 0, 1)
    assert update() == set()
    reader._now = lambda: datetime(2010, 1, 1, 0, 0, 59)
    assert update() == set()

    reader._now = lambda: datetime(2010, 1, 1, 0, 1)
    assert update() == {'2'}
    reader._now = lambda: datetime(2010, 1, 1, 0, 59)
    assert update() == {'2'}

    reader._now = lambda: datetime(2010, 1, 1, 1)
    assert update() == {'1', '2'}
    assert update() == set()

    reader._now = lambda: datetime(2010, 1, 1, 1, 1)
    assert update() == {'2'}
    reader._now = lambda: datetime(2010, 1, 1, 1, 59)
    assert update() == {'2'}

    reader._now = lambda: datetime(2010, 1, 1, 3)
    assert update() == {'1', '2', '3'}
    assert update() == set()

    reader._now = lambda: datetime(2010, 1, 31)
    assert update() == {'1', '2', '3'}
    assert update() == set()


@pytest.mark.slow
@pytest.mark.parametrize(
    'scheduled, end, expected_counts',
    [
        (False, datetime(2010, 1, 1, 2), dict.fromkeys('1234', 60 * 2)),
        (True, datetime(2010, 1, 1, 8), {'1': 4, '2': 60 * 8, '3': 2, '4': 1}),
    ],
)
def test_update_scheduled_sweep(reader, parser, scheduled, end, expected_counts):
    one = parser.feed(1)
    two = parser.feed(2)
    three = parser.feed(3)
    four = parser.feed(4)
    for feed in one, two, three, four:
        reader.add_feed(feed)

    reader.set_tag((), '.reader.update', {'interval': 60 * 2})
    reader.set_tag(two, '.reader.update', {'interval': 1})
    reader.set_tag(three, '.reader.update', {'interval': 60 * 4, 'jitter': 0.5})
    reader.set_tag(four, '.reader.update', {'interval': 60 * 8, 'jitter': 1})

    now = datetime(2010, 1, 1)
    reader._now = lambda: now
    counts = Counter()
    while now < end:
        counts.update(r.url for r in reader.update_feeds_iter(scheduled=scheduled))
        now += timedelta(seconds=60)

    assert dict(counts) == expected_counts


def test_set_update_interval_up(reader, parser):
    feed = parser.feed(1)
    reader.add_feed(feed)

    reader.set_tag(feed, '.reader.update', {'interval': 60})

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    reader.set_tag(feed, '.reader.update', {'interval': 240})

    reader._now = lambda: datetime(2010, 1, 1, 0, 59)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 0

    reader._now = lambda: datetime(2010, 1, 1, 1)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 1

    reader._now = lambda: datetime(2010, 1, 1, 3, 59)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 0

    reader._now = lambda: datetime(2010, 1, 1, 4)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 1


def test_set_update_interval_down(reader, parser):
    feed = parser.feed(1)
    reader.add_feed(feed)

    reader.set_tag(feed, '.reader.update', {'interval': 240})

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    reader.set_tag(feed, '.reader.update', {'interval': 60})

    reader._now = lambda: datetime(2010, 1, 1, 3, 59)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 0

    reader._now = lambda: datetime(2010, 1, 1, 4)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 1

    reader._now = lambda: datetime(2010, 1, 1, 4, 59)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 0

    reader._now = lambda: datetime(2010, 1, 1, 5)
    assert len(list(reader.update_feeds_iter(scheduled=True))) == 1


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
    db_path, make_reader, parser, update_feed, feed_action, entry_action
):
    """reader.update_feed should raise FeedNotFoundError if the feed is
    deleted during parsing.

    reader.update_feeds shouldn't (but should log).

    """
    reader = make_reader(db_path)

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

    if feed_action is FeedAction.fail:
        parser.raise_exc()

    parser.retrieve = blocking_retrieve = Blocking(parser.retrieve)

    def target():
        with reader, blocking_retrieve:
            reader.delete_feed(feed.url)

    t = threading.Thread(target=target)
    t.start()

    if update_feed.__name__ == 'update_feed':
        with pytest.raises(FeedNotFoundError) as excinfo:
            update_feed(reader, feed.url)
        assert excinfo.value.url == feed.url
        assert 'no such feed' in excinfo.value.message
    elif update_feed.__name__.startswith('update_feeds'):
        # shouldn't raise an exception
        update_feed(reader, feed.url)
    else:
        assert False, "shouldn't happen"

    t.join()


def test_update_feed(reader, parser, feed_arg):
    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1))

    with pytest.raises(FeedNotFoundError):
        reader.update_feed(feed_arg(one))

    reader._now = lambda: datetime(2010, 1, 1)
    one = one.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 1),
        last_retrieved=datetime(2010, 1, 1),
        update_after=datetime(2010, 1, 1, 1),
    )
    two = two.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 1),
        last_retrieved=datetime(2010, 1, 1),
        update_after=datetime(2010, 1, 1, 1),
    )

    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feed(feed_arg(one))

    assert set(reader.get_feeds()) == {one, Feed(two.url, added=datetime(2010, 1, 1))}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == Feed(two.url, added=datetime(2010, 1, 1))
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=one,
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 1),
        )
    }

    reader.update_feed(feed_arg(two))

    assert set(reader.get_feeds()) == {one, two}
    assert reader.get_feed(one.url) == one
    assert reader.get_feed(two.url) == two
    assert set(reader.get_entries()) == {
        entry_one.as_entry(
            feed=one,
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 1),
        ),
        entry_two.as_entry(
            feed=two,
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 1),
        ),
    }

    reader._parser.raise_exc()

    with pytest.raises(ParseError):
        reader.update_feed(feed_arg(one))


def call_update_feeds_iter(reader, **kwargs):
    yield from reader.update_feeds_iter(**kwargs)


def call_update_feed_iter(reader, **kwargs):
    for feed in reader.get_feeds(updates_enabled=True, **kwargs):
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


def test_update_feeds_iter(reader, parser, call_update_iter_method):
    parser.raise_exc(lambda url: url == '3')

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
        '1', UpdatedFeed(url='1', new=0, modified=0, unmodified=2)
    )

    one_two = parser.entry(1, 2, datetime(2010, 2, 2), title='new title')
    one_three = parser.entry(1, 3, datetime(2010, 2, 1))
    one_four = parser.entry(1, 4, datetime(2010, 2, 1))
    three = parser.feed(3, datetime(2010, 1, 1))

    reader.add_feed(three)

    rv = dict(call_update_iter_method(reader))
    assert set(rv) == set('123')

    assert rv['1'] == UpdatedFeed(url='1', new=2, modified=1, unmodified=1)
    assert rv['2'] == UpdatedFeed(url='2', new=0, modified=0, unmodified=1)

    assert isinstance(rv['3'], ParseError)
    assert rv['3'].url == '3'
    assert rv['3'].__cause__ is parser.exc

    reader._parser.not_modified()

    assert dict(call_update_iter_method(reader)) == dict.fromkeys('123')


@pytest.mark.parametrize('exc_type', [StorageError, Exception])
def test_update_feeds_iter_raised_exception(
    reader, parser, exc_type, call_update_iter_method
):
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


def test_mark_as_read_unread(reader, parser, entry_arg):
    # TODO: Test read/unread the same way important/unimportant are (or the other way around).

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


# sqlite3 on PyPy can be brittle
# (spurious "InterfaceError: Error binding parameter X")
# and we're doing lots of tiny queries here which may trigger it,
# so don't bother
@pytest.mark.skipif("sys.implementation.name == 'pypy'")
@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [1, 2, 3, 4])
@pytest.mark.parametrize('get_entries', [get_entries, search_entries])
def test_get_entries_random(reader, parser, get_entries, chunk_size):
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

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.entry(1, 2, datetime(2010, 1, 1))
    three = parser.entry(1, 3, datetime(2010, 1, 1))
    four = parser.entry(1, 4, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()
    get_entries.after_update(reader)

    # all possible get_entries(sort='random') results
    all_tuples = set(permutations({e.id for e in reader.get_entries()}, chunk_size))

    # some get_entries(sort='random') results
    # (we call it enough times so it's likely we get all the results)
    random_tuples = Counter(
        tuple(e.id for e in get_entries(reader, sort='random'))
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


def test_add_remove_get_feeds(reader, parser, feed_arg):
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

    # no exception
    reader.delete_feed(feed_arg(one), True)

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

    # no exception
    reader.add_feed(feed_arg(one), True)

    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    one = one.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 2),
        last_retrieved=datetime(2010, 1, 2),
        update_after=datetime(2010, 1, 2, 1),
    )
    two = two.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 2),
        last_retrieved=datetime(2010, 1, 2),
        update_after=datetime(2010, 1, 2, 1),
    )
    entry_one = entry_one.as_entry(
        feed=one, added=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 2)
    )
    entry_two = entry_two.as_entry(
        feed=two, added=datetime(2010, 1, 2), last_updated=datetime(2010, 1, 2)
    )

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


def test_get_feeds_order_title(reader, parser, chunk_size):
    """When sort='title', feeds should be sorted by (with decreasing
    priority):

    * feed user_title or feed title; feeds that have neither should appear first
    * feed URL

    https://github.com/lemon24/reader/issues/29
    https://github.com/lemon24/reader/issues/102

    """
    # for https://github.com/lemon24/reader/issues/203
    reader._storage.chunk_size = chunk_size

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


def test_get_feeds_order_title_case_insensitive(reader, parser):
    """When sort='title', feeds should be sorted by title in a case
    insensitive way.

    https://github.com/lemon24/reader/issues/103

    """
    feed1 = parser.feed(1, datetime(2010, 1, 1), title='aaa')
    feed2 = parser.feed(2, datetime(2010, 1, 2), title='bbb')
    feed3 = parser.feed(3, datetime(2010, 1, 3), title='Aba')

    reader.add_feed(feed1.url)
    reader.add_feed(feed2.url)
    reader.add_feed(feed3.url)

    reader.update_feeds()

    assert list(f.url for f in reader.get_feeds()) == '1 3 2'.split()


def test_get_feeds_order_added(reader, parser):
    """When sort='added', feeds should be sorted by (with decreasing
    priority):

    * feed added, descending
    * feed URL

    https://github.com/lemon24/reader/issues/98

    """
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


def test_set_feed_user_title(reader, parser, feed_arg):
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


def test_data_roundtrip(reader, parser):
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
                added=datetime(2010, 1, 2),
                last_updated=datetime(2010, 1, 3),
                last_retrieved=datetime(2010, 1, 3),
                update_after=datetime(2010, 1, 3, 1),
            ),
            added=datetime(2010, 1, 3),
            last_updated=datetime(2010, 1, 3),
        )
    ]

    # TODO: this should be a different test
    (feed_for_update,) = reader._storage.get_feeds_for_update(
        FeedFilter.from_args(feed)
    )
    assert feed.hash == feed_for_update.hash
    (entry_for_update,) = reader._storage.get_entries_for_update(
        [(entry.feed_url, entry.id)]
    )
    assert entry.hash == entry_for_update.hash


def test_data_hashes_remain_stable(parser):
    # TODO: note the duplication from test_data_roundtrip()

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


def test_get_entry(reader, parser, entry_arg):
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
            added=datetime(2010, 1, 2),
            last_updated=datetime(2010, 1, 3),
            last_retrieved=datetime(2010, 1, 3),
            update_after=datetime(2010, 1, 3, 1),
        ),
        added=datetime(2010, 1, 3),
        last_updated=datetime(2010, 1, 3),
    )
    assert reader.get_entry(entry_arg(entry)) == entry


class FakeStorage:
    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def close(self):
        self.calls.append(('close',))

    def set_entry_important(self, entry, important, modified):
        self.calls.append(('set_entry_important', entry, important, modified))
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
    reader._now = lambda: datetime(2010, 1, 1)
    entry = Entry('entry', None, feed=Feed('feed'))
    reader.mark_entry_as_important(entry_arg(entry))
    assert reader._storage.calls == [
        ('set_entry_important', ('feed', 'entry'), True, datetime(2010, 1, 1))
    ]


def test_mark_as_unimportant(reader, entry_arg):
    reader._storage = FakeStorage()
    reader._now = lambda: datetime(2010, 1, 1)
    entry = Entry('entry', None, feed=Feed('feed'))
    reader.mark_entry_as_unimportant(entry_arg(entry))
    assert reader._storage.calls == [
        ('set_entry_important', ('feed', 'entry'), False, datetime(2010, 1, 1))
    ]


def test_set_entry_important_none(reader, parser, entry_arg):
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(feed)
    reader.update_feeds()

    entry = reader.get_entry(entry)
    assert entry.important is None
    assert entry.important_modified is None

    reader._now = lambda: datetime(2010, 1, 1)
    reader.mark_entry_as_important(entry_arg(entry))
    entry = reader.get_entry(entry)
    assert entry.important is True

    reader._now = lambda: datetime(2010, 1, 2)
    reader.set_entry_important(entry, None)

    entry = reader.get_entry(entry)
    assert entry.important is None
    assert entry.important_modified == datetime(2010, 1, 2)


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


def test_direct_instantiation():
    with pytest.warns(UserWarning):
        Reader('storage', 'search', 'parser', DEFAULT_RESERVED_NAME_SCHEME)


@pytest.mark.parametrize(
    'kwargs, feed_root',
    [
        (dict(), None),
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


@pytest.fixture
def reader_with_two_feeds(reader, parser):
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
        last_retrieved=None,
        update_after=None,
    )


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_feeds_for_update(reader):
    # TODO: this should probably be tested in test_storage.py

    reader._parser.caching_info = 'caching'
    reader.update_feeds()

    reader._parser.condition = lambda url: url == '1'
    reader.update_feeds()

    reader._storage.set_feed_stale('1', True)

    def get_feed(feed):
        return next(
            reader._storage.get_feeds_for_update(FeedFilter.from_args(None, feed)),
            None,
        )

    old_one = get_feed('1')
    assert old_one.caching_info == 'caching'
    assert old_one.stale

    reader.change_feed_url('1', '3')

    assert not get_feed('1')
    assert get_feed('3') == old_one._replace(
        url='3',
        updated=None,
        caching_info=None,
        last_updated=None,
        last_exception=False,
        stale=False,
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
    reader.update_search()

    reader.delete_feed('2')

    old_one = reader.get_feed('1')

    reader.change_feed_url('1', new_feed_url)

    assert reader.get_feed(new_feed_url) == old_one._replace(
        url=new_feed_url,
        updated=None,
        last_updated=None,
        last_retrieved=None,
        update_after=None,
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
        last_retrieved=datetime(2010, 1, 3),
        update_after=datetime(2010, 1, 3, 1),
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


def test_change_feed_url_search_entry_id_repeats(reader, parser):
    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))

    two = parser.feed(2, datetime(2010, 1, 1))
    parser.entries[2][1] = one_one._replace(feed_url='2')

    for feed in one, two:
        reader.add_feed(feed)
    reader.update_feeds()
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
        reader._search.get_db()
        .execute("select count(*) from entries_search_sync_state;")
        .fetchone()[0]
        == 1
    )
    assert (
        reader._search.get_db()
        .execute("select count(*) from entries_search;")
        .fetchone()[0]
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
    reader.update_search()

    old = list(reader.search_entries('entry', feed='1'))
    assert {e.id for e in old} == {'1, 1', '1, 2'}
    assert {e.feed_url for e in old} == {'1'}

    reader.change_feed_url('1', '3')
    reader.update_search()

    assert list(reader.search_entries('entry', feed='1')) == []

    new = list(reader.search_entries('entry', feed='3'))
    assert new == [e._replace(feed_url='3') for e in old]


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_metadata(reader):
    reader.set_tag('1', 'key', 'value')

    reader.change_feed_url('1', '3')

    assert dict(reader.get_tags('1')) == {}
    assert dict(reader.get_tags('3')) == {'key': 'value'}


@rename_argument('reader', 'reader_with_two_feeds')
def test_change_feed_url_tags(reader):
    reader.set_tag('1', 'tag')

    reader.change_feed_url('1', '3')

    assert set(reader.get_tag_keys('1')) == set()
    assert set(reader.get_tag_keys('3')) == {'tag'}


# END change_feed_url tests


def test_updates_enabled(reader, parser):
    """Test Feed.updates_enabled functionality.

    https://github.com/lemon24/reader/issues/187#issuecomment-706539658

    """
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
    parser.raise_exc(lambda url: url == one.url)
    reader.update_feeds()
    last_exception = reader.get_feed(one).last_exception
    assert last_exception is not None
    parser.reset_mode()

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
def reader_with_three_feeds(reader, parser):
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
@rename_argument('reader', 'reader_with_three_feeds')
def test_pagination_basic(reader, pre_stuff, call_method, sort_kwargs, chunk_size):
    reader._storage.chunk_size = chunk_size

    reader.update_feeds()
    pre_stuff(reader)

    def get_ids(**kwargs):
        return [o.resource_id for o in call_method(reader, **sort_kwargs, **kwargs)]

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
@rename_argument('reader', 'reader_with_three_feeds')
def test_pagination_random(reader, pre_stuff, call_method, chunk_size):
    reader._storage.chunk_size = chunk_size

    reader.update_feeds()
    pre_stuff(reader)

    def get_ids(**kwargs):
        return [o.resource_id for o in call_method(reader, sort='random', **kwargs)]

    ids = [o.resource_id for o in call_method(reader)]

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
    get_feeds: ('0',),
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
    assert excinfo.value.resource_id == starting_after


@with_call_paginated_method
def test_limit_errors(reader, pre_stuff, call_method, sort_kwargs):
    pre_stuff(reader)

    def get_ids(**kwargs):
        return [o.resource_id for o in call_method(reader, **sort_kwargs, **kwargs)]

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
        ({}, reader._parser.requests.DEFAULT_TIMEOUT),
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


@pytest.mark.parametrize('flag', ['read', 'important'])
@rename_argument('reader', 'reader_with_one_feed')
def test_entry_read_important_modified_gets_set_to_now(reader, flag):
    reader.update_feeds()

    entry = next(reader.get_entries())
    assert not getattr(entry, flag)
    assert getattr(entry, f'{flag}_modified') is None

    reader._now = lambda: datetime(2010, 1, 1)
    getattr(reader, f'mark_entry_as_{flag}')(entry)
    entry = next(reader.get_entries())
    assert getattr(entry, flag)
    assert getattr(entry, f'{flag}_modified') == datetime(2010, 1, 1)

    reader._now = lambda: datetime(2010, 1, 2)
    getattr(reader, f'mark_entry_as_{flag}')(entry)
    entry = next(reader.get_entries())
    assert getattr(entry, f'{flag}_modified') == datetime(2010, 1, 2)

    reader._now = lambda: datetime(2010, 1, 3)
    getattr(reader, f'mark_entry_as_un{flag}')(entry)
    entry = next(reader.get_entries())
    assert not getattr(entry, flag)
    assert getattr(entry, f'{flag}_modified') == datetime(2010, 1, 3)


@pytest.mark.parametrize('flag', ['read', 'important'])
@rename_argument('reader', 'reader_with_one_feed')
def test_entry_read_important_modified_argument(reader, flag, monkeypatch_tz):
    from datetime import datetime

    reader.update_feeds()

    entry = next(reader.get_entries())
    reader._now = lambda: datetime(2010, 1, 1)

    getattr(reader, f'set_entry_{flag}')(
        entry, True, modified=datetime(2010, 1, 1, tzinfo=timezone(timedelta(hours=-2)))
    )
    entry = next(reader.get_entries())
    assert getattr(entry, f'{flag}_modified') == utc_datetime(2010, 1, 1, 2)

    getattr(reader, f'set_entry_{flag}')(entry, True, modified=None)
    entry = next(reader.get_entries())
    assert getattr(entry, f'{flag}_modified') is None

    # time.tzset() does not exist on Windows
    if os.name == 'nt':
        return

    monkeypatch_tz('UTC')
    getattr(reader, f'set_entry_{flag}')(entry, True, modified=datetime(2010, 1, 1, 4))
    entry = next(reader.get_entries())
    assert getattr(entry, f'{flag}_modified') == utc_datetime(2010, 1, 1, 4)

    monkeypatch_tz('Etc/GMT+6')
    getattr(reader, f'set_entry_{flag}')(entry, True, modified=datetime(2010, 1, 1))
    entry = next(reader.get_entries())
    assert getattr(entry, f'{flag}_modified') == utc_datetime(2010, 1, 1, 6)


@pytest.mark.parametrize('flag', ['read', 'important'])
def test_entry_read_important_modified_remains_set_after_update(reader, parser, flag):
    feed = parser.feed(1)
    entry = parser.entry(1, 1)
    reader.add_feed(feed)
    reader.update_feeds()

    entry = reader.get_entry(entry)
    assert not getattr(entry, flag)
    assert getattr(entry, f'{flag}_modified') is None

    reader._now = lambda: datetime(2010, 1, 1)
    getattr(reader, f'mark_entry_as_{flag}')(entry)

    entry = parser.entry(1, 1, title='new')
    reader.update_feeds()

    entry = next(reader.get_entries())
    assert entry.title == 'new'
    assert getattr(entry, flag)
    assert getattr(entry, f'{flag}_modified') == datetime(2010, 1, 1)


@pytest.mark.parametrize('value', [None, 2, 'true'])
@rename_argument('reader', 'reader_with_one_feed')
def test_set_entry_read_value_error(reader, value):
    reader.update_feeds()
    entry = next(reader.get_entries())
    with pytest.raises(ValueError):
        reader.set_entry_read(entry, value)


@pytest.mark.parametrize('value', [2, 'true'])
@rename_argument('reader', 'reader_with_one_feed')
def test_set_entry_important_value_error(reader, value):
    reader.update_feeds()
    entry = next(reader.get_entries())
    with pytest.raises(ValueError):
        reader.set_entry_important(entry, value)


allow_invalid_url_feed_root = 'C:\\tmp' if os.name == 'nt' else '/tmp'


@pytest.mark.parametrize(
    'feed_root, url',
    [
        # checking a bunch of common known-bad URLs,
        # there are more detailed tests in test_parser.py
        (None, 'feed.xml'),
        (None, 'http://'),
        (None, 'nope://feed.xml'),
        (allow_invalid_url_feed_root, '/feed.xml'),
        (allow_invalid_url_feed_root, 'http://'),
        (allow_invalid_url_feed_root, 'nope://feed.xml'),
    ],
)
def test_allow_invalid_url(make_reader, feed_root, url):
    reader = make_reader(':memory:', feed_root=feed_root)

    with pytest.raises(InvalidFeedURLError) as excinfo:
        reader.add_feed(url)
    assert excinfo.value.url == url

    reader.add_feed(url, allow_invalid_url=True)

    reader.delete_feed(url)

    old = 'https://www.example.com/feed.xml'
    reader.add_feed(old)

    with pytest.raises(InvalidFeedURLError) as excinfo:
        reader.change_feed_url(old, url)
    assert excinfo.value.url == url

    reader.change_feed_url(old, url, allow_invalid_url=True)


@rename_argument('reader', 'reader_with_one_feed')
def test_entry_source(reader):
    reader.update_feeds()
    assert next(reader.get_entries()).added_by == 'feed'


def test_add_entry(reader, parser):
    reader._now = lambda: datetime(2010, 1, 1)

    # adding it fails if feed doesn't exist

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.add_entry(dict(feed_url='1', id='1, 1'))
    assert excinfo.value.resource_id == ('1',)

    # add it by user (from dict)

    feed = parser.feed(1)
    reader.add_feed(feed)

    expected_entry = Entry(
        '1, 1',
        last_updated=datetime(2010, 1, 1),
        added=datetime(2010, 1, 1),
        added_by='user',
        original_feed_url='1',
        feed=Feed('1', added=datetime(2010, 1, 1)),
    )

    reader.add_entry(dict(feed_url='1', id='1, 1'))
    assert reader.get_entry(('1', '1, 1')) == expected_entry

    # adding it again fails

    with pytest.raises(EntryExistsError) as excinfo:
        reader.add_entry(expected_entry)
    assert excinfo.value.resource_id == ('1', '1, 1')

    # adding it again with overwrite=True works

    reader.add_entry(dict(feed_url='1', id='1, 1', title='new'), overwrite=True)
    assert reader.get_entry(('1', '1, 1')) == expected_entry._replace(title='new')

    # add it by user (from object)

    reader._storage.delete_entries([('1', '1, 1')])
    reader._now = lambda: datetime(2010, 1, 2)

    reader.add_entry(expected_entry)
    assert reader.get_entry(('1', '1, 1')) == expected_entry._replace(
        last_updated=datetime(2010, 1, 2),
        added=datetime(2010, 1, 2),
    )
    assert reader._storage.get_entry_recent_sort(('1', '1, 1')) == datetime(2010, 1, 2)

    # add it by feed (update)

    reader._now = lambda: datetime(2010, 1, 3)

    entry = parser.entry(1, 1)
    reader.update_feeds()

    assert reader.get_entry(('1', '1, 1')) == entry.as_entry(
        last_updated=datetime(2010, 1, 3),
        added=datetime(2010, 1, 2),
        added_by='feed',
        feed=feed.as_feed(
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 3),
            last_retrieved=datetime(2010, 1, 3),
            update_after=datetime(2010, 1, 3, 1),
        ),
    )


def test_delete_entry(reader, parser):
    with pytest.raises(EntryNotFoundError) as excinfo:
        reader.delete_entry(('1', '1, 1'))
    assert excinfo.value.resource_id == ('1', '1, 1')

    # no exception
    reader.delete_entry(('1', '1, 1'), True)

    feed = parser.feed(1)
    reader.add_feed(feed)

    reader.add_entry(dict(feed_url='1', id='1, 1'))
    parser.entry(1, 2)
    reader.update_feeds()

    assert {(e.id, e.added_by) for e in reader.get_entries()} == {
        ('1, 1', 'user'),
        ('1, 2', 'feed'),
    }

    reader.delete_entry(('1', '1, 1'))

    with pytest.raises(EntryError) as excinfo:
        reader.delete_entry(('1', '1, 2'))
    assert excinfo.value.resource_id == ('1', '1, 2')
    assert excinfo.value.message == "entry must be added by 'user', got 'feed'"

    assert {(e.id, e.added_by) for e in reader.get_entries()} == {
        ('1, 2', 'feed'),
    }


@pytest.mark.parametrize('data_file', ['full', 'empty'])
def test_copy_entry(reader, data_dir, data_file):
    reader._now = lambda: datetime(2010, 1, 1)
    src_url = str(data_dir.joinpath(f'{data_file}.atom'))
    src_id = (src_url, 'urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a')
    reader.add_feed(src_url)
    reader.update_feeds()

    if data_file == 'full':
        reader._now = lambda: datetime(2010, 1, 2)
        reader.mark_entry_as_read(src_id)
        reader.mark_entry_as_unimportant(src_id)
        reader.set_tag(src_id, 'empty')
        reader.set_tag(src_id, 'key', 'value')

    reader._now = lambda: datetime(2010, 2, 1)
    dst_url = 'dst'
    dst_id = (dst_url, 'id')
    reader.add_feed(dst_url)
    reader.copy_entry(src_id, dst_id)

    def clean(entry):
        return entry._replace(
            id=None,
            source=None,
            added_by=None,
            original_feed_url=None,
            _sequence=None,
            feed=None,
        )

    def get_tags(entry):
        return dict(reader.get_tags(entry))

    src = reader.get_entry(src_id)
    dst = reader.get_entry(dst_id)

    assert clean(src) == clean(dst)
    assert get_tags(src) == get_tags(dst)

    assert dst.id == 'id'
    assert dst.added_by == 'user'
    assert dst.original_feed_url == src_url

    if src.source:
        src_source = src.source.__dict__
    else:
        src_source = {k: getattr(src.feed, k) for k in dst.source.__dict__}
    assert src_source == dst.source.__dict__

    get_recent_sort = reader._storage.get_entry_recent_sort
    assert get_recent_sort(src_id) == get_recent_sort(dst_id)

    # src does not exist
    with pytest.raises(EntryNotFoundError) as excinfo:
        reader.copy_entry((src_url, 'inexistent'), dst_id)
    assert excinfo.value.resource_id == (src_url, 'inexistent')

    # dst exists
    with pytest.raises(EntryExistsError) as excinfo:
        reader.copy_entry(src_id, dst_id)
    assert excinfo.value.resource_id == dst_id

    # dst feed does not exist
    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.copy_entry(src_id, ('inexistent', 'id'))
    assert excinfo.value.resource_id == ('inexistent',)

    # delete
    reader.delete_entry(dst_id)

    # user title has priority in source if original entry does not have source
    reader.set_feed_user_title(src_url, 'user')
    reader.copy_entry(src_id, dst_id)
    dst = reader.get_entry(dst_id)
    assert dst.source.title == 'user' if not src.source else src.source.title


@pytest.mark.parametrize('same_thread', [True, False])
def test_delete_feed(make_reader, db_path, parser, same_thread):
    reader = make_reader(db_path)
    feed = parser.feed(1)
    entry = parser.entry(1, 'feed')

    reader.add_feed(feed)
    reader.update_feeds()
    reader.add_entry(dict(feed_url='1', id='user'))
    reader.copy_entry(entry, ('1', 'copy'))
    reader.set_tag(feed, 'tag', 'feed')
    reader.set_tag(entry, 'tag', 'entry')

    assert {e.resource_id for e in reader.get_entries()} == {
        ('1', 'feed'),
        ('1', 'user'),
        ('1', 'copy'),
    }
    assert dict(reader.get_tags(feed)) == {'tag': 'feed'}
    assert dict(reader.get_tags(entry)) == {'tag': 'entry'}

    if same_thread:
        reader.delete_feed(feed)
    else:
        # would cause the test to fail if foreign key enforcement
        # was not enabled in other threads (like prior to 3.16)
        thread = threading.Thread(target=reader.delete_feed, args=(feed,))
        thread.start()
        thread.join()

    reader.add_feed(feed)
    assert {e.resource_id for e in reader.get_entries()} == set()
    assert dict(reader.get_tags(feed)) == {}

    reader.update_feeds()
    assert dict(reader.get_tags(entry)) == {}
