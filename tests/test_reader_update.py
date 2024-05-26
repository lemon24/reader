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
        reader.update_feeds()
    entry = parser.entry(1, 1, title='one')

    in_make_intents = threading.Event()
    can_return_from_make_intents = threading.Event()

    def target():
        in_make_intents.wait()
        reader = make_reader(db_path)
        reader._parser = Parser.from_parser(parser)
        reader._parser.entry(1, 1, title='two')
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
        reader.update_feeds()
    finally:
        t.join()

    assert reader.get_entry(entry).title == 'one'
