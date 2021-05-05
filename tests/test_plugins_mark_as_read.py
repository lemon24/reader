import json
import os
from datetime import datetime

import pytest
from fakeparser import Parser


@pytest.mark.parametrize(
    'key, value',
    [
        ('.reader.mark_as_read', {'title': ['^match']}),
        # TODO: remove before 2.0
        ('regex-mark-as-read', {'patterns': ['^match']}),
    ],
)
def test_regex_mark_as_read(make_reader, key, value):
    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match old')

    reader.add_feed(one)
    reader.update_feeds()

    reader.set_feed_metadata(one, key, value)

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

    # Check migration from the old-style config happened.
    # TODO: remove before 2.0
    assert reader.get_feed_metadata(one, 'regex-mark-as-read', None) is None
    assert reader.get_feed_metadata(one, '.reader.mark_as_read', None) == {
        'title': ['^match']
    }


@pytest.mark.parametrize('value', ['x', {'title': 'x'}, {'title': [1]}])
def test_regex_mark_as_read_bad_metadata(make_reader, value):
    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match')

    reader.add_feed(one)
    reader.set_feed_metadata(one, '.reader.mark_as_read', value)

    reader.update_feeds()

    assert [e.read for e in reader.get_entries()] == [False]
