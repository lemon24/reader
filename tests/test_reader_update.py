"""
Tests related to update_feeds().

TODO: move all update tests from test_reader.py here

"""

import threading
from unittest.mock import ANY

import pytest

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
