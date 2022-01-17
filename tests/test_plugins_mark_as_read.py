import json
import os

import pytest
from fakeparser import Parser
from utils import naive_datetime
from utils import utc_datetime as datetime


def test_regex_mark_as_read(make_reader):
    key = '.reader.mark-as-read'
    value = {'title': ['^match']}

    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    def get_entry_data(**kwargs):
        return {
            (e.id, e.read, e.read_modified, e.important, e.important_modified)
            for e in reader.get_entries(**kwargs)
        }

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match old')

    reader._now = lambda: naive_datetime(2010, 1, 1)
    reader.add_feed(one)

    reader.update_feeds()

    reader.set_tag(one, key, value)

    one = parser.feed(1, datetime(2010, 1, 2))
    match_new = parser.entry(1, 2, datetime(2010, 1, 2), title='match new')
    parser.entry(1, 3, datetime(2010, 1, 2), title='no match')

    two = parser.feed(2, datetime(2010, 1, 2))
    parser.entry(2, 3, datetime(2010, 1, 2), title='match other')

    reader._now = lambda: naive_datetime(2010, 2, 1)
    reader.add_feed(two)
    reader.update_feeds()

    assert len(list(reader.get_entries())) == 4
    assert get_entry_data(read=True) == {
        (match_new.id, True, datetime(2010, 2, 1), False, datetime(2010, 2, 1)),
    }

    parser.entry(1, 3, datetime(2010, 1, 2), title='no match once again')

    reader._now = lambda: naive_datetime(2010, 3, 1)
    reader.update_feeds()

    assert get_entry_data(read=True) == {
        (match_new.id, True, datetime(2010, 2, 1), False, datetime(2010, 2, 1)),
    }


@pytest.mark.parametrize('value', ['x', {'title': 'x'}, {'title': [1]}])
def test_regex_mark_as_read_bad_metadata(make_reader, value):
    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), title='match')

    reader.add_feed(one)
    reader.set_tag(one, '.reader.mark-as-read', value)

    reader.update_feeds()

    assert [e.read for e in reader.get_entries()] == [False]


@pytest.mark.parametrize('with_entry', [False, True])
def test_regex_mark_as_read_pre_2_7_metadata(make_reader, with_entry):
    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])

    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    if with_entry:
        parser.entry(1, 1, datetime(2010, 1, 1), title='match old')

    reader.add_feed(one)
    reader.set_tag(one, '.reader.mark_as_read', {'title': ['^match']})

    reader.update_feeds()

    assert all(e.read for e in reader.get_entries())

    tags = dict(reader.get_tags(one))
    assert '.reader.mark_as_read' not in tags
    assert tags['.reader.mark-as-read'] == {'title': ['^match']}
