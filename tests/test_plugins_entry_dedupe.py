from datetime import datetime

import pytest
from fakeparser import Parser

from reader import Content
from reader import Entry
from reader.plugins.entry_dedupe import _is_duplicate
from reader.plugins.entry_dedupe import _normalize


def test_normalize():
    assert _normalize('\n\n<B>whatever</B>&nbsp; Blah </p>') == 'whatever blah'


def make_entry(title=None, summary=None, content=None):
    entry = Entry('id', None, title=title, summary=summary)
    if content:
        entry = entry._replace(content=[Content(*content)])
    return entry


IS_DUPLICATE_DATA = [
    (make_entry(), make_entry(), False),
    (make_entry(title='title'), make_entry(title='title'), False),
    (make_entry(summary='summary'), make_entry(summary='summary'), False),
    (
        make_entry(content=('value', 'text/html')),
        make_entry(content=('value', 'text/html')),
        False,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='title', summary='summary'),
        True,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='other', summary='summary'),
        False,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='title', summary='other'),
        False,
    ),
    (
        make_entry(title='title', content=('value', 'text/html')),
        make_entry(title='title', content=('value', 'text/html')),
        True,
    ),
    (
        make_entry(title='title', content=('value', 'text/html')),
        make_entry(title='other', content=('value', 'text/html')),
        False,
    ),
    (
        make_entry(title='title', content=('value', 'text/html')),
        make_entry(title='title', content=('other', 'text/html')),
        False,
    ),
    (
        make_entry(title='title', content=('value', 'text/plain')),
        make_entry(title='title', content=('value', 'text/plain')),
        False,
    ),
    (
        make_entry(title='title', summary='value'),
        make_entry(title='title', content=('value', 'text/html')),
        False,
    ),
]


@pytest.mark.parametrize('one, two, result', IS_DUPLICATE_DATA)
def test_is_duplicate(one, two, result):
    assert bool(_is_duplicate(one, two)) is bool(result)


def test_plugin(make_reader):
    reader = make_reader(':memory:', plugins=['reader.entry_dedupe'])
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    old = parser.entry(1, 1, datetime(2010, 1, 1), title='title', summary='old')
    title_only_one = parser.entry(1, 2, datetime(2010, 1, 1), title='title only')
    read_one = parser.entry(1, 3, datetime(2010, 1, 1), title='title', summary='read')
    unread_one = parser.entry(
        1, 4, datetime(2010, 1, 1), title='title', summary='unread'
    )
    important_one = parser.entry(
        1, 5, datetime(2010, 1, 1), title='important', summary='also important'
    )
    modified_one = parser.entry(
        1, 6, datetime(2010, 1, 1), title='title', summary='will be modified'
    )

    # TODO just use the feeds/entries as arguments

    reader.add_feed(one.url)
    reader.update_feeds()
    reader.mark_entry_as_read((one.url, read_one.id))
    reader.mark_entry_as_important((one.url, important_one.id))

    one = parser.feed(1, datetime(2010, 1, 2))
    new = parser.entry(1, 11, datetime(2010, 1, 2), title='title', summary='new')
    title_only_two = parser.entry(1, 12, datetime(2010, 1, 2), title='title only')
    read_two = parser.entry(1, 13, datetime(2010, 1, 2), title='title', summary='read')
    unread_two = parser.entry(
        1, 14, datetime(2010, 1, 2), title='title', summary='unread'
    )
    important_two = parser.entry(
        1, 15, datetime(2010, 1, 2), title='important', summary='also important'
    )
    modified_two = parser.entry(
        1, 6, datetime(2010, 1, 1), title='title', summary='was modified'
    )

    reader.update_feeds()

    assert set((e.id, e.read, e.important) for e in reader.get_entries()) == {
        t + (False,)
        for t in {
            # remain untouched
            (old.id, False),
            (new.id, False),
            # also remain untouched
            (title_only_one.id, False),
            (title_only_two.id, False),
            # the new one is marked as read because the old one was
            (read_one.id, True),
            (read_two.id, True),
            # the old one is marked as read in favor of the new one
            (unread_one.id, True),
            (unread_two.id, False),
            # modified entry is ignored by plugin
            (modified_one.id, False),
        }
    } | {
        # the new one is important because the old one was;
        # the old one is not important anymore
        (important_one.id, True, False),
        (important_two.id, False, True),
    }
