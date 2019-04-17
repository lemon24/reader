import os
import json
from datetime import datetime

from reader.plugins.regex_mark_as_read import regex_mark_as_read

from fakeparser import Parser


def test_regex_mark_as_read(reader, monkeypatch, tmpdir):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match old')

    reader.add_feed(one.url)
    reader.update_feeds()

    config = tmpdir.join('config.json')
    with config.open('w') as f:
        json.dump({one.url: ['^match']}, f)
    monkeypatch.setitem(os.environ, 'READER_PLUGIN_REGEX_MARK_AS_READ_CONFIG', str(config))
    regex_mark_as_read(reader)

    one = parser.feed(1, datetime(2010, 1, 2))
    match_new = parser.entry(1, 2, datetime(2010, 1, 2), title='match new')
    parser.entry(1, 3, datetime(2010, 1, 2), title='no match')

    two = parser.feed(2, datetime(2010, 1, 2))
    parser.entry(2, 3, datetime(2010, 1, 2), title='match other')

    reader.add_feed(two.url)
    reader.update_feeds()

    assert len(list(reader.get_entries())) == 4
    assert set(reader.get_entries(which='read')) == {match_new._replace(feed=one, read=True)}


