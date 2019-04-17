from datetime import datetime

import pytest

from reader.plugins.feed_entry_dedupe import feed_entry_dedupe, normalize, is_duplicate
from reader import Entry, Content

from fakeparser import Parser


def test_normalize():
    assert normalize('\n\n<B>whatever</B>&nbsp; Blah </p>') == 'whatever blah'


def make_entry(title=None, summary=None, content=None):
    entry = Entry('id', None, title=title, summary=summary)
    if content:
        entry = entry._replace(content=[Content(*content)])
    return entry

IS_DUPLICATE_DATA = [
    (make_entry(), make_entry(), False),

    (make_entry(title='title'),
     make_entry(title='title'), False),
    (make_entry(summary='summary'),
     make_entry(summary='summary'), False),
    (make_entry(content=('value', 'text/html')),
     make_entry(content=('value', 'text/html')), False),

    (make_entry(title='title', summary='summary'),
     make_entry(title='title', summary='summary'), True),
    (make_entry(title='title', summary='summary'),
     make_entry(title='other', summary='summary'), False),
    (make_entry(title='title', summary='summary'),
     make_entry(title='title', summary='other'), False),

    (make_entry(title='title', content=('value', 'text/html')),
     make_entry(title='title', content=('value', 'text/html')), True),
    (make_entry(title='title', content=('value', 'text/html')),
     make_entry(title='other', content=('value', 'text/html')), False),
    (make_entry(title='title', content=('value', 'text/html')),
     make_entry(title='title', content=('other', 'text/html')), False),

    (make_entry(title='title', content=('value', 'text/plain')),
     make_entry(title='title', content=('value', 'text/plain')), False),
    (make_entry(title='title', summary='value'),
     make_entry(title='title', content=('value', 'text/html')), False),
]

@pytest.mark.parametrize('one, two, result', IS_DUPLICATE_DATA)
def test_is_duplicate(one, two, result):
    assert bool(is_duplicate(one, two)) is bool(result)


def test_feed_entry_dedupe(reader, monkeypatch, tmpdir):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    old = parser.entry(1, 1, datetime(2010, 1, 1), title='title', summary='old')
    title_only_one = parser.entry(1, 2, datetime(2010, 1, 1), title='title only')
    read_one = parser.entry(1, 3, datetime(2010, 1, 1), title='title', summary='read')
    unread_one = parser.entry(1, 4, datetime(2010, 1, 1), title='title', summary='unread')

    reader.add_feed(one.url)
    reader.update_feeds()
    reader.mark_as_read((one.url, read_one.id))

    feed_entry_dedupe(reader)

    one = parser.feed(1, datetime(2010, 1, 2))
    new = parser.entry(1, 5, datetime(2010, 1, 2), title='title', summary='new')
    title_only_two = parser.entry(1, 6, datetime(2010, 1, 2), title='title only')
    read_two = parser.entry(1, 7, datetime(2010, 1, 2), title='title', summary='read')
    unread_two = parser.entry(1, 8, datetime(2010, 1, 2), title='title', summary='unread')

    reader.update_feeds()

    assert set(reader.get_entries()) == {
        e._replace(feed=one) for e in {
            # remain untouched
            old, new,
            # also remain untouched
            title_only_one, title_only_two,
            # the new one is marked as read because the old one was
            read_one._replace(read=True), read_two._replace(read=True),
            # the old one is marked as read in favor of the new one
            unread_one._replace(read=True), unread_two,
        }
    }


