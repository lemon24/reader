"""
Tests related to update_feeds().

TODO: move all update tests from test_reader.py here

"""

import logging
import sys
import threading
from contextlib import contextmanager
from unittest.mock import ANY

import pytest

from reader import FeedNotFoundError
from reader import ParseError
from reader import StorageError
from reader import UpdatedFeed
from reader import UpdateResult
from utils import Blocking
from utils import utc_datetime as datetime


# BEGIN: should (not) update

# fmt: off

def prepare_feed(reader):
    feed = reader._parser.feed(1, datetime(2010, 1, 1), title='old')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(feed.url)
    reader._now = lambda: datetime(2010, 1, 2)
    return feed

def entry_is_added(reader):
    return reader._parser.entry(1, 1, datetime(2010, 1, 1), title='one')

def prepare_feed_and_entry(reader):
    return prepare_feed(reader), entry_is_added(reader)

def nothing_changes(reader):
    pass

def feed_changes(reader):
    reader._parser.feed(1, datetime(2010, 1, 1), title='new')

def feed_updated_is_older(reader):
    reader._parser.feed(1, datetime(2009, 12, 31), title='old')

def feed_updated_is_newer(reader):
    reader._parser.feed(1, datetime(2010, 1, 2), title='old')

def entry_changes(reader):
    reader._parser.entry(1, 1, datetime(2010, 1, 1), title='ONE')

def entry_updated_is_older(reader):
    reader._parser.entry(1, 1, datetime(2009, 12, 31), title='one')

def entry_updated_is_newer(reader):
    reader._parser.entry(1, 1, datetime(2010, 1, 2), title='one')

def second_entry_is_added(reader):
    return reader._parser.entry(1, 2, datetime(2010, 1, 1), title='two')

def feed_updated_is_older_and_entry_changes(reader):
    reader._parser.feed(1, datetime(2009, 12, 31), title='old')
    reader._parser.entry(1, 1, datetime(2010, 1, 1), title='ONE')

def feed_updated_is_newer_and_entry_changes(reader):
    reader._parser.feed(1, datetime(2010, 1, 2), title='old')
    reader._parser.entry(1, 1, datetime(2010, 1, 1), title='ONE')

# fmt: on


@pytest.mark.noscheduled
def test_basic(reader, parser, update_feed, subtests):

    with subtests.test("empty feed"):
        feed = prepare_feed(reader)
        expected_feed = feed.as_feed(
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 2),
            last_retrieved=datetime(2010, 1, 2),
            update_after=datetime(2010, 1, 2, 1),
        )

        update_feed(reader, feed)

        assert reader.get_feed(feed) == expected_feed
        assert set(reader.get_entries()) == set()

    with subtests.test("add first entry"):
        one = entry_is_added(reader)

        update_feed(reader, feed)

        assert reader.get_feed(feed) == expected_feed
        assert set(reader.get_entries()) == {
            one.as_entry(
                feed=expected_feed,
                added=datetime(2010, 1, 2),
                last_updated=datetime(2010, 1, 2),
            ),
        }

    with subtests.test("add second entry"):
        two = second_entry_is_added(reader)
        reader._now = lambda: datetime(2010, 1, 3)
        expected_feed = feed.as_feed(
            added=datetime(2010, 1, 1),
            last_updated=datetime(2010, 1, 3),
            last_retrieved=datetime(2010, 1, 3),
            update_after=datetime(2010, 1, 3, 1),
        )

        update_feed(reader, feed)

        assert reader.get_feed(feed) == expected_feed
        assert set(reader.get_entries()) == {
            one.as_entry(
                feed=expected_feed,
                added=datetime(2010, 1, 2),
                last_updated=datetime(2010, 1, 2),
            ),
            two.as_entry(
                feed=expected_feed,
                added=datetime(2010, 1, 3),
                last_updated=datetime(2010, 1, 3),
            ),
        }


@pytest.mark.parametrize(
    'when',
    [
        feed_changes,
        entry_changes,
        second_entry_is_added,
        feed_updated_is_older_and_entry_changes,
        feed_updated_is_newer_and_entry_changes,
    ],
)
def test_feed_is_updated(reader, parser, when):
    old_feed, _ = prepare_feed_and_entry(reader)
    reader.update_feeds()

    reader._now = lambda: datetime(2010, 1, 3)
    when(reader)
    reader.update_feeds()

    new_feed = parser.feeds[1]
    assert reader.get_feed(old_feed) == new_feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 3),
        last_retrieved=datetime(2010, 1, 3),
        update_after=datetime(2010, 1, 3, 1),
    )


@pytest.mark.parametrize(
    'when', [nothing_changes, feed_updated_is_older, feed_updated_is_newer]
)
def test_feed_is_not_updated(reader, parser, when):
    old_feed, _ = prepare_feed_and_entry(reader)
    reader.update_feeds()

    reader._now = lambda: datetime(2010, 1, 3)
    when(reader)
    reader.update_feeds()

    assert reader.get_feed(old_feed) == old_feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 2),
        last_retrieved=datetime(2010, 1, 3),
        update_after=datetime(2010, 1, 3, 1),
    )


@pytest.mark.parametrize(
    'when', [entry_changes, entry_updated_is_older, entry_updated_is_newer]
)
def test_entry_is_updated(reader, parser, when):
    feed, _ = prepare_feed_and_entry(reader)
    reader.update_feeds()

    reader._now = lambda: datetime(2010, 1, 3)
    when(reader)
    reader.update_feeds()

    new_one = parser.entries[1][1]
    expected_feed = feed.as_feed(
        added=datetime(2010, 1, 1),
        last_updated=datetime(2010, 1, 3),
        last_retrieved=datetime(2010, 1, 3),
        update_after=datetime(2010, 1, 3, 1),
    )
    assert reader.get_entry(new_one) == new_one.as_entry(
        feed=expected_feed,
        added=datetime(2010, 1, 2),
        last_updated=datetime(2010, 1, 3),
    )


@pytest.mark.parametrize(
    'when',
    [nothing_changes, feed_changes, feed_updated_is_newer, second_entry_is_added],
)
def test_entry_is_not_updated(reader, parser, when):
    feed, old_one = prepare_feed_and_entry(reader)
    reader.update_feeds()

    reader._now = lambda: datetime(2010, 1, 3)
    when(reader)
    reader.update_feeds()

    assert reader.get_entry(old_one) == old_one.as_entry(
        feed=ANY,
        added=datetime(2010, 1, 2),
        last_updated=datetime(2010, 1, 2),
    )


def test_entry_is_not_updated_past_update_limit(reader, parser):
    feed = prepare_feed(reader)

    for i in range(1, 31):
        reader._now = lambda: datetime(2010, 1, i)
        one = parser.entry(1, 1, datetime(2010, 1, 1), title=f"one #{i}")
        reader.update_feeds()

    assert reader.get_entry(one).title == "one #25"


# END: should (not) update


@pytest.mark.noscheduled
def test_not_modified(reader, parser, update_feed):
    """A feed should not be updated if it was not modified."""

    feed = parser.feed(1, datetime(2010, 1, 1), title='old')
    reader.add_feed(feed)
    reader._now = lambda: datetime(2010, 1, 1)
    update_feed(reader, feed)

    parser.feed(1, datetime(2010, 1, 2), title='new')
    parser.entry(1, 1, datetime(2010, 1, 2))

    reader._parser.not_modified()
    reader._now = lambda: datetime(2010, 1, 2)

    # shouldn't raise an exception
    update_feed(reader, feed)

    actual_feed = reader.get_feed(feed)
    assert actual_feed.last_updated == datetime(2010, 1, 1)
    assert actual_feed.last_retrieved == datetime(2010, 1, 2)
    assert set(reader.get_entries()) == set()


# BEGIN: update errors


def test_update_feeds_logs_parse_error(reader, parser, caplog):
    caplog.set_level(logging.ERROR, 'reader')

    reader.add_feed(parser.feed(1))
    parser.raise_exc()

    # shouldn't raise an exception
    reader.update_feeds()

    # it should log the error, with traceback
    (record,) = caplog.records
    assert record.levelname == 'ERROR'
    exc = record.exc_info[1]
    assert isinstance(exc, ParseError)
    assert exc.url == '1'
    assert str(exc.__cause__) == 'failing'
    assert repr(exc.url) in record.message
    assert repr(exc.__cause__) in record.message


def parse_error(parser):
    parser.raise_exc(lambda url: url == '1')


def retriever_enter_error(parser):
    original_retrieve = parser.retrieve

    def retrieve(url, *args):
        @contextmanager
        def raise_exc():
            raise ParseError(url)
            yield 'unreachable'

        return raise_exc() if url == '1' else original_retrieve(url, *args)

    parser.retrieve = retrieve


@pytest.mark.parametrize('workers', [1, 2])
@pytest.mark.parametrize('when', [parse_error, retriever_enter_error])
def test_update_feeds_does_not_stop_on(reader, parser, when, workers):
    parser.with_titles()
    for i in 1, 2, 3:
        reader.add_feed(parser.feed(i))

    when(parser)
    reader.update_feeds(workers=workers)

    assert {f.title for f in reader.get_feeds()} == {None, "feed 2", "feed 3"}


def test_update_feeds_unexpected_error(reader, parser, monkeypatch):
    parser.with_titles()
    for i in 1, 2, 3:
        reader.add_feed(parser.feed(i))

    exc = Exception('unexpected')

    def update_feed(*_, **__):
        raise exc

    monkeypatch.setattr('reader._update.Pipeline.update_feed', update_feed)

    with pytest.raises(Exception) as excinfo:
        reader.update_feeds()
    assert excinfo.value is exc

    assert [f.title for f in reader.get_feeds()] == [None, None, None]
    assert [f.last_retrieved for f in reader.get_feeds()] == [None, None, None]


@pytest.mark.noscheduled
def test_last_exception(reader, parser, subtests):
    reader.add_feed(parser.feed(1))
    parser.entry(1, 1)

    with subtests.test("is none if not updated"):
        assert reader.get_feed('1').last_exception is None

    with subtests.test("is none if updated successfully"):
        reader._now = lambda: datetime(2010, 1, 1)
        reader.update_feeds()
        assert reader.get_feed('1').last_exception is None

    with subtests.test("is set on error"):
        reader._now = lambda: datetime(2010, 1, 2)
        parser.raise_exc()
        reader.update_feeds()

        feed = reader.get_feed('1')
        assert feed.last_updated == datetime(2010, 1, 1)
        assert feed.last_retrieved == datetime(2010, 1, 2)

        last_exception = feed.last_exception
        assert last_exception.type_name == 'reader.exceptions.ParseError'
        assert last_exception.value_str == "'1': builtins.Exception: failing"
        assert last_exception.traceback_str.startswith('Traceback')

        assert next(reader.get_entries()).feed.last_exception == last_exception

    with subtests.test("is updated on another error"):
        reader._now = lambda: datetime(2010, 1, 3)
        parser.raise_exc(ValueError('another'))
        reader.update_feeds()

        feed = reader.get_feed('1')
        assert feed.last_updated == datetime(2010, 1, 1)
        assert feed.last_retrieved == datetime(2010, 1, 3)

        last_exception = feed.last_exception
        assert last_exception.value_str == "'1': builtins.ValueError: another"


@pytest.mark.noscheduled
@pytest.mark.parametrize('by', ['reset_mode', 'not_modified'])
def test_last_exception_is_reset_by(reader, parser, by):
    reader.add_feed(parser.feed(1))

    reader._now = lambda: datetime(2010, 1, 1)
    parser.raise_exc()
    reader.update_feeds()

    assert reader.get_feed('1').last_exception is not None

    reader._now = lambda: datetime(2010, 1, 2)
    getattr(parser, by)()
    reader.update_feeds()

    feed = reader.get_feed('1')
    assert feed.last_updated == (datetime(2010, 1, 2) if by == 'reset_mode' else None)
    assert feed.last_retrieved == datetime(2010, 1, 2)
    assert feed.last_exception is None


@pytest.mark.noscheduled
def test_last_exception_is_not_reset_by_another_feed(reader, parser):
    parser.with_titles()
    for i in 1, 2:
        reader.add_feed(parser.feed(i))
    parser.raise_exc()
    reader.update_feeds()

    parser.reset_mode()
    reader.update_feed('2')

    assert reader.get_feed('1').last_exception is not None
    assert reader.get_feed('2').last_exception is None


# END: update errors


# BEGIN: update_feeds_iter()

# TODO: these don't necessarily need the workers= version


@pytest.mark.noscheduled
def test_update_feeds_iter_basic(reader, parser, update_feeds_iter):
    assert dict(update_feeds_iter(reader)) == {}

    for i in 1, 2:
        reader.add_feed(parser.feed(i))

    assert dict(update_feeds_iter(reader)) == {
        '1': UpdatedFeed(url='1'),
        '2': UpdatedFeed(url='2'),
    }

    parser.entry(1, 1)
    parser.entry(1, 2)
    parser.entry(2, 1)

    assert dict(update_feeds_iter(reader)) == {
        '1': UpdatedFeed(url='1', new=2),
        '2': UpdatedFeed(url='2', new=1),
    }

    parser.entry(1, 2, title='new')
    parser.entry(1, 3)
    parser.entry(1, 4)

    assert dict(update_feeds_iter(reader)) == {
        '1': UpdatedFeed(url='1', new=2, modified=1, unmodified=1),
        '2': UpdatedFeed(url='2', new=0, modified=0, unmodified=1),
    }


def test_update_feeds_iter_parse_error(reader, parser, update_feeds_iter):
    for i in 1, 2:
        reader.add_feed(parser.feed(i))
    parser.raise_exc(lambda url: url == '1')

    rv = dict(update_feeds_iter(reader))

    assert isinstance(rv['1'], ParseError)
    assert rv['1'].url == '1'
    assert rv['1'].__cause__ is parser.exc
    assert rv['2'] == UpdatedFeed(url='2')


def test_update_feeds_iter_not_modified(reader, parser, update_feeds_iter):
    for i in 1, 2:
        reader.add_feed(parser.feed(i))
    parser.not_modified(lambda url: url == '1')

    assert dict(update_feeds_iter(reader)) == {
        '1': None,
        '2': UpdatedFeed(url='2'),
    }


@pytest.mark.parametrize('exc_type', [StorageError, Exception])
def test_update_feeds_iter_unexpected_error(
    reader, parser, exc_type, update_feeds_iter
):
    for i in 1, 2, 3:
        reader.add_feed(parser.feed(i))

    original_storage_update_feed = reader._storage.update_feed
    exc = exc_type('message')

    def storage_update_feed(intent):
        if intent.url == '2':
            raise exc
        return original_storage_update_feed(intent)

    reader._storage.update_feed = storage_update_feed

    rv = {}
    with pytest.raises(exc_type) as excinfo:
        rv.update(update_feeds_iter(reader))
    assert excinfo.value is exc

    if 'workers' not in update_feeds_iter.__name__:
        assert rv == {'1': UpdatedFeed(url='1')}


# END: update_feeds_iter()


# BEGIN: update_feed()

# return value and ParseError handling covered in update_feeds_iter() tests


def test_update_feed_basic(reader, parser, feed_arg):
    one = parser.feed(1, title='one')
    parser.entry(1, 1)
    two = parser.feed(2, title='two')
    parser.entry(2, 1)

    for feed in one, two:
        reader.add_feed(feed)

    reader._now = lambda: datetime(2010, 1, 1)

    reader.update_feed(feed_arg(one))

    assert {(f.title, f.last_updated) for f in reader.get_feeds()} == {
        ('one', datetime(2010, 1, 1)),
        (None, None),
    }
    assert {e.id for e in reader.get_entries()} == {'1, 1'}


def test_update_feed_updates_not_scheduled_feeds(reader, parser):
    feed = parser.feed(1, title='old')
    reader.add_feed(feed)

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    feed = parser.feed(1, title='new')
    reader._now = lambda: datetime(2010, 1, 1, 0, 1)
    reader.update_feed(feed)

    assert reader.get_feed(feed).title == 'new'


def test_update_feed_not_found(reader):
    with pytest.raises(FeedNotFoundError):
        reader.update_feed('1')


def test_update_feed_value_error(reader):
    with pytest.raises(ValueError):
        reader.update_feed(object())


# END: update_feed()


# BEGIN: edge cases


@pytest.mark.slow
@pytest.mark.noscheduled
def test_parser_doesnt_block_storage(db_path, make_reader, parser):
    reader = make_reader(db_path)

    feed = parser.feed(1)
    entry = parser.entry(1, 1)
    reader.add_feed(feed)

    reader.update_feeds()

    for i in range(2, 4):
        reader.add_feed(parser.feed(i))

    parser.retrieve = Blocking(parser.retrieve)

    def target():
        with reader:
            reader.update_feeds()

    t = threading.Thread(target=target)
    t.start()

    with parser.retrieve:
        # shouldn't raise an exception
        reader.mark_entry_as_read((feed.url, entry.id))

    t.join()


def test_duplicate_ids(reader, parser):
    """If a feed has two entries with the same id, the first entry wins.

    This passes before (and after) 3.12, but not in 3.12.

    https://github.com/lemon24/reader/issues/335

    """
    old_parse = parser.parse

    reader.add_feed(parser.feed(1))
    entry = parser.entry(1, 1, title='one')

    # parser only supports unique ids, so we monkeypatch it

    def parse(url, result):
        rv = old_parse(url, result)
        (entry,) = rv.entries
        rv = rv._replace(entries=[entry._replace(title='two'), entry])
        return rv

    parser.parse = parse

    reader.update_feeds()

    assert reader.get_entry(entry).title == 'two'


@pytest.mark.slow
@pytest.mark.noscheduled
@pytest.mark.parametrize('when', [feed_changes, entry_is_added])
def test_feed_deleted_during_update(db_path, make_reader, parser, update_feed, when):
    reader = make_reader(db_path)
    feed = prepare_feed(reader)
    reader.update_feeds()

    when(reader)

    parser.retrieve = Blocking(parser.retrieve)

    def target():
        with reader, parser.retrieve:
            reader.delete_feed(feed)

    t = threading.Thread(target=target)
    t.start()

    if update_feed.__name__ == 'update_feed':
        with pytest.raises(FeedNotFoundError) as excinfo:
            update_feed(reader, feed)
    else:
        # shouldn't raise an exception
        update_feed(reader, feed)

    t.join()


@pytest.mark.slow
@pytest.mark.parametrize('new', [True, False])
def test_concurrent_update(monkeypatch, db_path, make_reader, parser, new):
    """If a feed is updated in parallel, the last writer wins.

    This is the temporal equivalent of test_duplicate_ids().

    This passes before (and after) 3.12, but not in 3.12.

    https://github.com/lemon24/reader/issues/335

    """
    reader = make_reader(db_path)

    reader.add_feed(parser.feed(1))
    if not new:
        entry = parser.entry(1, 1, title='zero')
        reader._now = lambda: datetime(2010, 1, 1)
        reader.update_feeds()
    entry = parser.entry(1, 1, title='one')

    block = Blocking()

    def target():
        with block:
            reader = make_reader(db_path)
            reader._parser = parser.copy()
            reader._parser.entry(1, 1, title='two')
            reader._now = lambda: datetime(2010, 1, 1, 1)
            reader.update_feeds()

    from reader._update import Pipeline

    def update_feed(*args, **kwargs):
        monkeypatch.undo()
        block()
        assert reader.get_entry(entry).title == 'two'
        return Pipeline.update_feed(*args, **kwargs)

    # TODO: this would have been easier if Pipeline were a reader attribute
    monkeypatch.setattr(Pipeline, 'update_feed', update_feed)

    t = threading.Thread(target=target)
    t.start()
    try:
        reader._now = lambda: datetime(2010, 1, 1, 2)
        reader.update_feeds()
    finally:
        t.join()

    entry = reader.get_entry(entry)
    assert entry.title == 'one'
    assert entry.added == (datetime(2010, 1, 1, 1) if new else datetime(2010, 1, 1))
    assert entry.last_updated == datetime(2010, 1, 1, 2)


@pytest.mark.slow
def test_entry_deleted_during_update(monkeypatch, db_path, make_reader, parser):
    """If an entry is deleted while being updated, the update should not fail.

    Additionally, first_updated/added, first_updated_epoch, and recent_sort
    should be preserved from the old (just deleted) entry.
    This is arbitrary, but should be consistent.

    """
    reader = make_reader(db_path)

    reader.add_feed(parser.feed(1))
    entry = parser.entry(1, 1, title='zero')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    entry = parser.entry(1, 1, title='one')

    block = Blocking()

    def target():
        with block:
            reader = make_reader(db_path)
            reader._storage.delete_entries([entry.resource_id])

    from reader._update import Pipeline

    def update_feed(*args, **kwargs):
        monkeypatch.undo()
        block()
        return Pipeline.update_feed(*args, **kwargs)

    # TODO: this would have been easier if Pipeline were a reader attribute
    monkeypatch.setattr(Pipeline, 'update_feed', update_feed)

    before_entry = reader.get_entry(entry)
    (before_efu,) = reader._storage.get_entries_for_update([entry.resource_id])

    t = threading.Thread(target=target)
    t.start()
    try:
        reader._now = lambda: datetime(2010, 1, 1, 2)
        reader.update_feeds()
    finally:
        t.join()

    after_entry = reader.get_entry(entry)
    assert after_entry.title == 'one'
    assert after_entry.added == before_entry.added
    assert after_entry.last_updated == datetime(2010, 1, 1, 2)

    (after_efu,) = reader._storage.get_entries_for_update([entry.resource_id])
    assert before_efu.first_updated == after_efu.first_updated
    assert before_efu.first_updated_epoch == after_efu.first_updated_epoch
    assert before_efu.recent_sort == after_efu.recent_sort


# END: edge cases


def test_new(reader, parser, subtests):
    feed = parser.feed(1, title='old')
    parser.entry(1, 1, title='one')
    reader.add_feed(feed)

    with subtests.test("only old"):
        reader._now = lambda: datetime(2010, 1, 1)
        reader.update_feeds(new=False)

        feed = reader.get_feed(feed)
        assert feed.title is None
        assert feed.last_updated is None
        assert feed.last_retrieved is None
        assert len(list(reader.get_entries())) == 0

    with subtests.test("only new"):
        reader._now = lambda: datetime(2010, 1, 2)
        reader.update_feeds(new=True)

        feed = reader.get_feed(feed)
        assert feed.title == 'old'
        assert feed.last_updated == datetime(2010, 1, 2)
        assert feed.last_retrieved == datetime(2010, 1, 2)
        assert len(list(reader.get_entries())) == 1

    with subtests.test("not new anymore"):
        feed = parser.feed(1, title='new')
        parser.entry(1, 2, title='two')

        reader._now = lambda: datetime(2010, 1, 3)
        reader.update_feeds(new=True)

        feed = reader.get_feed(feed)
        assert feed.title == 'old'
        assert feed.last_updated == datetime(2010, 1, 2)
        assert feed.last_retrieved == datetime(2010, 1, 2)
        assert len(list(reader.get_entries())) == 1


@pytest.mark.parametrize('how', ['not_modified', 'raise_exc'])
def test_new_failed_update(reader, parser, how, subtests):
    feed = parser.feed(1, title='feed')
    reader.add_feed(feed)

    with subtests.test("only new"):
        reader._now = lambda: datetime(2010, 1, 1)
        getattr(parser, how)()
        reader.update_feeds(new=True)

        feed = reader.get_feed(feed)
        assert feed.title is None
        assert feed.last_updated is None
        assert feed.last_retrieved == datetime(2010, 1, 1)

    with subtests.test("not new anymore"):
        reader._now = lambda: datetime(2010, 1, 2)
        parser.reset_mode()
        reader.update_feeds(new=True)

        feed = reader.get_feed(feed)
        assert feed.title is None
        assert feed.last_updated is None
        assert feed.last_retrieved == datetime(2010, 1, 1)


def test_updates_enabled_scheduled(reader, parser):
    """Bug: updates_enabled=True was not working when scheduled=True.

    https://github.com/lemon24/reader/issues/365

    """
    reader._now = lambda: datetime(2010, 1, 1)
    one = parser.feed(1)
    reader.add_feed(one)
    reader.update_feeds()

    reader.disable_feed_updates(one)

    reader._now = lambda: datetime(2010, 1, 2)
    assert list(reader.update_feeds_iter(scheduled=True, updates_enabled=True)) == []
