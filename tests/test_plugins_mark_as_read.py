import json
import os
from dataclasses import _MISSING_TYPE

import pytest

from fakeparser import Parser
from utils import utc_datetime as datetime


def test_regex_mark_as_read_backfill(make_reader):
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

    one = parser.feed(1)
    reader.add_feed(one)

    match_1 = parser.entry(1, 1, title='match 1')
    match_2 = parser.entry(1, 2, title='match 2')
    match_3 = parser.entry(1, 3, title='match 3')
    no_match_4 = parser.entry(1, 4, title='no match 4')
    no_match_5 = parser.entry(1, 5, title='no match 5')

    # an entry that has been touched by the user and marked as read and importand -- this entry will not be modified after reader.update_feeds()
    match_existing = parser.entry(
        1, 6, title='match: existing entry already touched by the user'
    )

    # call reader.update_feeds() once to get the feed/entries into reader
    reader.update_feeds()

    assert len(list(reader.get_entries())) == 6

    reader.set_entry_read(match_existing, True, None)
    reader.set_entry_important(match_existing, True, None)

    assert len(list(reader.get_entries(read=False))) == 5
    # existing entry already touched by the user
    assert len(list(reader.get_entries(read=True))) == 1

    reader.set_tag(one, '.reader.mark-as-read.once')
    reader.set_tag(one, key, value)
    # call reader.update_feeds() again to test the .reader.mark-as-read.once flag
    reader.update_feeds()

    assert len(list(reader.get_entries(read=True))) == 4
    # assert that only matching entries that were not touched by the user are modified
    assert len(list(reader.get_entries(read=True, important=False))) == 3
    assert len(list(reader.get_entries(read=False))) == 2

    assert get_entry_data(read=True) == {
        (match_1.id, True, None, False, None),
        (match_2.id, True, None, False, None),
        (match_3.id, True, None, False, None),
        (match_existing.id, True, None, True, None),
    }

    # assert that .reader.mark-as-read.once tag is not set anymore
    assert reader.get_tag(one, '.reader.mark-as-read.once', "no value") == "no value"


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

    reader._now = lambda: datetime(2010, 1, 1)
    reader.add_feed(one)

    reader.update_feeds()

    reader.set_tag(one, key, value)

    one = parser.feed(1, datetime(2010, 1, 2))
    match_new = parser.entry(1, 2, datetime(2010, 1, 2), title='match new')
    parser.entry(1, 3, datetime(2010, 1, 2), title='no match')

    two = parser.feed(2, datetime(2010, 1, 2))
    parser.entry(2, 3, datetime(2010, 1, 2), title='match other')

    reader._now = lambda: datetime(2010, 2, 1)
    reader.add_feed(two)
    reader.update_feeds()

    assert len(list(reader.get_entries())) == 4
    assert get_entry_data(read=True) == {
        (match_new.id, True, None, False, None),
    }

    parser.entry(1, 3, datetime(2010, 1, 2), title='no match once again')

    reader._now = lambda: datetime(2010, 3, 1)
    reader.update_feeds()

    assert get_entry_data(read=True) == {
        (match_new.id, True, None, False, None),
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


def test_entry_deleted(make_reader):
    def delete_entry_plugin(reader):
        def hook(reader, entry, _):
            if entry.resource_id == ('1', '1, 1'):
                reader._storage.delete_entries([entry.resource_id])

        reader.after_entry_update_hooks.append(hook)

    reader = make_reader(
        ':memory:', plugins=[delete_entry_plugin, 'reader.mark_as_read']
    )
    reader._parser = parser = Parser()
    one = parser.feed(1)
    reader.add_feed(one)
    reader.set_tag(one, '.reader.mark-as-read', {'title': ['one']})
    parser.entry(1, 1, title='one')
    parser.entry(1, 2, title='two')

    # shouldn't fail
    reader.update_feeds()

    assert {eval(e.id)[1] for e in reader.get_entries()} == {2}


def test_missing_title(make_reader):
    reader = make_reader(':memory:', plugins=['reader.mark_as_read'])
    reader._parser = parser = Parser()
    one = parser.feed(1)
    reader.add_feed(one)
    parser.entry(1, 1, title=None)
    parser.entry(1, 2, title='')
    parser.entry(1, 3, title='three')

    reader.set_tag(one, '.reader.mark-as-read', {'title': ['^$']})

    # shouldn't fail
    reader.update_feeds()

    assert {eval(e.id)[1] for e in reader.get_entries(read=True)} == {1, 2}
