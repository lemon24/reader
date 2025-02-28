from datetime import timedelta
from functools import partial

import pytest

from utils import rename_argument
from utils import utc_datetime as datetime


with_maybe_published_or_updated = pytest.mark.parametrize(
    'entry_kwargs',
    [
        {},
        {'published': datetime(2010, 1, 1)},
        {'updated': datetime(2010, 1, 1)},
    ],
)


# TODO: more recent tests
#
# * entry published or updated
# * feed URL
# * entry last updated
# * entry id


@rename_argument('get_entries', 'get_entries_recent')
@with_maybe_published_or_updated
def test_entries_recent_first_updated(
    reader, parser, chunk_size, get_entries, entry_kwargs
):
    """All other things being equal, entries should be sorted by first updated."""
    reader._storage.chunk_size = chunk_size
    reader.add_feed(parser.feed(1))

    for id, day in [(3, 2), (2, 4), (4, 1), (1, 3)]:
        reader._now = lambda: datetime(2010, 1, day)
        parser.entry(1, id, **entry_kwargs)
        reader.update_feeds()

    get_entries.after_update(reader)

    assert [eval(e.id)[1] for e in get_entries(reader)] == [2, 1, 3, 4]


@rename_argument('get_entries', 'get_entries_recent')
@with_maybe_published_or_updated
def test_entries_recent_feed_order(
    reader, parser, chunk_size, get_entries, entry_kwargs
):
    """All other things being equal, entries should be sorted by feed order.

    https://github.com/lemon24/reader/issues/87

    """
    reader._storage.chunk_size = chunk_size
    reader.add_feed(parser.feed(1))

    for id in [3, 2, 4, 1]:
        parser.entry(1, id, **entry_kwargs)

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()
    get_entries.after_update(reader)

    assert [eval(e.id)[1] for e in get_entries(reader)] == [3, 2, 4, 1]


@rename_argument('get_entries', 'get_entries_recent')
@pytest.mark.parametrize('reverse', [False, True], ids=['forward', 'reverse'])
def test_entries_recent_all(reader, parser, chunk_size, get_entries, reverse):
    """Entries should be sorted descending by (with decreasing priority):

    * entry first updated epoch
      if the feed is not new
      else entry published or updated or first updated epoch
    * entry published or updated or first updated epoch
    * feed URL
    * entry last updated
    * order of entry in feed
    * entry id

    https://github.com/lemon24/reader/issues/97
    https://github.com/lemon24/reader/issues/106
    https://github.com/lemon24/reader/issues/113
    https://github.com/lemon24/reader/issues/279

    """

    reader._storage.chunk_size = chunk_size

    for feed in [1, 2, 3]:
        reader.add_feed(parser.feed(feed))

    def update_with_published_or_updated(offset, kind):
        parser.entries[1].clear()

        functions = [
            partial(
                parser.entry,
                1,
                offset + 3,
                title='entry by published or updated, {kind}, mid',
                published=datetime(2010, 1, 6, 12),
            ),
            partial(
                parser.entry,
                1,
                offset + 1,
                title='entry by published or updated, {kind}, newer',
                updated=datetime(2010, 1, 11, 12),
            ),
            partial(
                parser.entry,
                1,
                offset + 2,
                title='entry by published or updated, {kind}, older',
                published=datetime(2010, 1, 1),
                # ignored
                updated=datetime(2010, 1, 7),
            ),
        ]
        if reverse:
            functions = reversed(functions)

        for fn in functions:
            fn()

        reader.update_feeds()

    def by_published_or_updated_first_update():
        # first update, ignored
        reader._now = lambda: datetime(2010, 1, 1)
        update_with_published_or_updated(0, 'first update')

    def by_id():
        reader._now = lambda: datetime(2010, 1, 6)

        functions = [
            partial(parser.entry, 1, 6, title='entry by id, older'),
            partial(parser.entry, 1, 7, title='entry by id, newer'),
        ]
        if reverse:
            functions = reversed(functions)

        for fn in functions:
            parser.entries[1].clear()
            fn()
            reader.update_feeds()

    def by_feed_order():
        reader._now = lambda: datetime(2010, 1, 11)

        parser.entries[1].clear()
        parser.entry(1, 11, title='entry by feed order, newer')
        parser.entry(1, 12, title='entry by feed order, older')
        reader.update_feeds()

    def by_feed_url():
        reader._now = lambda: datetime(2010, 1, 16)

        functions = [
            partial(parser.entry, 2, 1, title='entry by feed url, older'),
            partial(parser.entry, 3, 1, title='entry by feed url, newer'),
        ]
        if reverse:
            functions = reversed(functions)

        for fn in functions:
            fn()

        reader.update_feeds()

    def by_published_or_updated_not_first_update():
        reader._now = lambda: datetime(2010, 1, 21)
        update_with_published_or_updated(20, 'not first update')

    updates = [by_published_or_updated_first_update]
    other_updates = [
        by_id,
        by_feed_order,
        by_feed_url,
        by_published_or_updated_not_first_update,
    ]
    if reverse:
        other_updates = list(reversed(other_updates))
    updates += other_updates

    for update in updates:
        update()

    get_entries.after_update(reader)

    reader._now = lambda: datetime(2010, 1, 31)

    assert [eval(e.id) for e in get_entries(reader)] == [
        (1, 21),
        (1, 23),
        (1, 22),
        (3, 1),
        (2, 1),
        (1, 1),
        (1, 11),
        (1, 12),
        (1, 3),
        (1, 7),
        (1, 6),
        (1, 2),
    ]


@rename_argument('get_entries', 'get_entries_recent')
def test_entries_recent_new_feed(reader, parser, get_entries):
    """Entries from the first update should be sorted by published/updated."""

    one = parser.feed(1)
    reader.add_feed(one)
    parser.entry(1, 1, published=datetime(2010, 1, 30))
    parser.entry(1, 2, published=datetime(2010, 1, 10))
    parser.entry(1, 3, published=datetime(2010, 1, 20))
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    # update after change_feed_url() also counts as first update
    two = parser.feed(2)
    parser.entry(2, 4, published=datetime(2010, 1, 15))
    parser.entry(2, 5, published=datetime(2010, 1, 5))
    parser.entry(2, 6, published=datetime(2010, 1, 25))
    reader.change_feed_url(one, two)
    reader._now = lambda: datetime(2010, 3, 1)
    reader.update_feeds()

    get_entries.after_update(reader)

    assert [eval(e.id) for e in get_entries(reader)] == [
        (1, 1),
        (2, 6),
        (1, 3),
        (2, 4),
        (1, 2),
        (2, 5),
    ]
