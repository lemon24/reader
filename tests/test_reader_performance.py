"""
Test behaviors that are not specified by the API but are expected of the
SQLite implementation.

"""

from datetime import datetime
import threading

import pytest

from reader.reader import Reader
from reader.parser import ParseError
from fakeparser import Parser

from test_reader import call_update_feeds, call_update_feed


class BlockingParser(Parser):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_parser = threading.Event()
        self.can_return_from_parser = threading.Event()

    def __call__(self, *args, **kwargs):
        self.in_parser.set()
        self.can_return_from_parser.wait()
        raise ParseError()


@pytest.mark.slow
@pytest.mark.parametrize('call_update_method', [call_update_feeds, call_update_feed])
def test_mark_as_read_during_update_feeds(monkeypatch, tmpdir, call_update_method):
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


@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test

    # check unchunked queries still blocks writes
    pytest.param(0, marks=pytest.mark.xfail(raises=Exception, strict=True)),
])
def test_mark_as_read_during_get_entries(monkeypatch, tmpdir, chunk_size):
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

