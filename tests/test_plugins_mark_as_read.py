import json
import os
from datetime import datetime

import pytest
from fakeparser import Parser


def test_regex_mark_as_read(make_reader):
    key = '.reader.mark_as_read'
    value = {'title': ['^match']}

    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match old')

    reader.add_feed(one)
    reader.update_feeds()

    reader.set_feed_metadata_item(one, key, value)

    one = parser.feed(1, datetime(2010, 1, 2))
    match_new = parser.entry(1, 2, datetime(2010, 1, 2), title='match new')
    parser.entry(1, 3, datetime(2010, 1, 2), title='no match')

    two = parser.feed(2, datetime(2010, 1, 2))
    parser.entry(2, 3, datetime(2010, 1, 2), title='match other')

    reader.add_feed(two)
    reader.update_feeds()

    assert len(list(reader.get_entries())) == 4
    assert set((e.id, e.read) for e in reader.get_entries(read=True)) == {
        (match_new.id, True),
    }

    parser.entry(1, 3, datetime(2010, 1, 2), title='no match once again')
    reader.update_feeds()

    assert set((e.id, e.read) for e in reader.get_entries(read=True)) == {
        (match_new.id, True),
    }


@pytest.mark.parametrize('value', ['x', {'title': 'x'}, {'title': [1]}])
def test_regex_mark_as_read_bad_metadata(make_reader, value):
    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match')

    reader.add_feed(one)
    reader.set_feed_metadata_item(one, '.reader.mark_as_read', value)

    reader.update_feeds()

    assert [e.read for e in reader.get_entries()] == [False]
