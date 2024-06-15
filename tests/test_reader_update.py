"""
Tests related to update_feeds().

TODO: move all update tests from test_reader.py here

"""

import threading

import pytest

from fakeparser import Parser
from utils import utc_datetime as datetime


def test_duplicate_ids(reader):
    """If a feed has two entries with the same id, the first entry wins.

    This passes before (and after) 3.12, but not in 3.12.

    https://github.com/lemon24/reader/issues/335

    """
    reader._parser = parser = Parser()
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
def test_concurrent_update(monkeypatch, db_path, make_reader, new):
    """If a feed is updated in parallel, the last writer wins.

    This is the temporal equivalent of test_duplicate_ids().

    This passes before (and after) 3.12, but not in 3.12.

    https://github.com/lemon24/reader/issues/335

    """
    reader = make_reader(db_path)
    reader._parser = parser = Parser()

    reader.add_feed(parser.feed(1))
    if not new:
        entry = parser.entry(1, 1, title='zero')
        reader._now = lambda: datetime(2010, 1, 1)
        reader.update_feeds()
    entry = parser.entry(1, 1, title='one')

    in_make_intents = threading.Event()
    can_return_from_make_intents = threading.Event()

    def target():
        in_make_intents.wait()
        reader = make_reader(db_path)
        reader._parser = Parser.from_parser(parser)
        reader._parser.entry(1, 1, title='two')
        reader._now = lambda: datetime(2010, 1, 1, 1)
        reader.update_feeds()
        can_return_from_make_intents.set()

    from reader._update import Pipeline

    def update_feed(*args, **kwargs):
        monkeypatch.undo()
        in_make_intents.set()
        can_return_from_make_intents.wait()
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
def test_entry_deleted_during_update(monkeypatch, db_path, make_reader):
    """If an entry is deleted while being updated, the update should not fail.

    Additionally, first_updated/added, first_updated_epoch, and recent_sort
    should be preserved from the old (just deleted) entry.
    This is arbitrary, but should be consistent.

    """
    reader = make_reader(db_path)
    reader._parser = parser = Parser()

    reader.add_feed(parser.feed(1))
    entry = parser.entry(1, 1, title='zero')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    entry = parser.entry(1, 1, title='one')

    in_make_intents = threading.Event()
    can_return_from_make_intents = threading.Event()

    def target():
        in_make_intents.wait()
        reader = make_reader(db_path)
        reader._storage.delete_entries([entry.resource_id])
        can_return_from_make_intents.set()

    from reader._update import Pipeline

    def update_feed(*args, **kwargs):
        monkeypatch.undo()
        in_make_intents.set()
        can_return_from_make_intents.wait()
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
