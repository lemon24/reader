import json
import os
from datetime import datetime

from fakeparser import Parser

from reader._plugins.regex_mark_as_read import regex_mark_as_read


def test_regex_mark_as_read(reader, monkeypatch, tmpdir):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match old')

    reader.add_feed(one.url)
    reader.update_feeds()

    reader.set_feed_metadata(one, 'regex-mark-as-read', {'patterns': ['^match']})

    regex_mark_as_read(reader)

    one = parser.feed(1, datetime(2010, 1, 2))
    match_new = parser.entry(1, 2, datetime(2010, 1, 2), title='match new')
    parser.entry(1, 3, datetime(2010, 1, 2), title='no match')

    two = parser.feed(2, datetime(2010, 1, 2))
    parser.entry(2, 3, datetime(2010, 1, 2), title='match other')

    reader.add_feed(two.url)
    reader.update_feeds()

    assert len(list(reader.get_entries())) == 4
    assert set((e.id, e.read) for e in reader.get_entries(read=True)) == {
        (match_new.id, True),
    }
