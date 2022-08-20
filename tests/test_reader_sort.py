from datetime import timedelta
from functools import partial

import pytest
from fakeparser import Parser
from test_reader import with_call_entries_recent_method
from utils import naive_datetime
from utils import utc_datetime as datetime


with_maybe_published_or_updated = pytest.mark.parametrize(
    'entry_kwargs',
    [
        {},
        {'published': datetime(2010, 1, 1)},
        {'updated': datetime(2010, 1, 1)},
    ],
)


@with_call_entries_recent_method
@with_maybe_published_or_updated
def test_entries_recent_first_updated(
    reader, chunk_size, pre_stuff, call_method, entry_kwargs
):
    """All other things being equal, entries should be sorted by first updated."""
    reader._storage.chunk_size = chunk_size
    reader._parser = parser = Parser()
    reader.add_feed(parser.feed(1))

    for id, day in [(3, 2), (2, 4), (4, 1), (1, 3)]:
        reader._now = lambda: naive_datetime(2010, 1, day)
        parser.entry(1, id, **entry_kwargs)
        reader.update_feeds()

    pre_stuff(reader)

    assert [eval(e.id)[1] for e in call_method(reader)] == [2, 1, 3, 4]


@with_call_entries_recent_method
@with_maybe_published_or_updated
def test_entries_recent_feed_order(
    reader, chunk_size, pre_stuff, call_method, entry_kwargs
):
    """All other things being equal, entries should be sorted by feed order.

    https://github.com/lemon24/reader/issues/87

    """
    reader._storage.chunk_size = chunk_size
    reader._parser = parser = Parser()
    reader.add_feed(parser.feed(1))

    for id in [3, 2, 4, 1]:
        parser.entry(1, id, **entry_kwargs)

    reader._now = lambda: naive_datetime(2010, 1, 1)
    reader.update_feeds()
    pre_stuff(reader)

    assert [eval(e.id)[1] for e in call_method(reader)] == [3, 2, 4, 1]


# FIXME:
# * entry published (or entry updated if published is none)
# * feed URL
# * entry last updated
# * entry id
# backdated


@with_call_entries_recent_method
@pytest.mark.parametrize('recent_threshold', [timedelta(0), timedelta(31)])
@pytest.mark.parametrize('reverse', [False, True])
def test_entries_recent_all(
    reader,
    chunk_size,
    pre_stuff,
    call_method,
    recent_threshold,
    reverse,
):
    """Entries should be sorted descending by (with decreasing priority):

    * entry first updated epoch (*)
    * entry published or updated (*)
    * feed URL
    * entry last updated
    * order of entry in feed
    * entry id

    """

    reader._storage.chunk_size = chunk_size
    reader._parser = parser = Parser()

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
        reader._now = lambda: naive_datetime(2010, 1, 1)
        update_with_published_or_updated(0, 'first update')

    def by_id():
        reader._now = lambda: naive_datetime(2010, 1, 6)

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
        reader._now = lambda: naive_datetime(2010, 1, 11)

        parser.entries[1].clear()
        parser.entry(1, 11, title='entry by feed order, newer')
        parser.entry(1, 12, title='entry by feed order, older')
        reader.update_feeds()

    def by_feed_url():
        reader._now = lambda: naive_datetime(2010, 1, 16)

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
        reader._now = lambda: naive_datetime(2010, 1, 21)
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

    pre_stuff(reader)

    reader._storage.recent_threshold = recent_threshold
    reader._now = lambda: naive_datetime(2010, 1, 31)

    if recent_threshold == timedelta(0):
        expected = [
            # after #279, should be here
            # (1, 21),
            # (1, 23),
            # (1, 22),
            (3, 1),
            (2, 1),
            (1, 21),
            (1, 1),
            (1, 11),
            (1, 12),
            (1, 23),
            (1, 3),
            (1, 7),
            (1, 6),
            (1, 22),
            (1, 2),
        ]
    elif recent_threshold == timedelta(31):
        # remove after #279 is done
        expected = [
            (1, 21),
            (1, 23),
            (1, 22),
            (3, 1),
            (2, 1),
            (1, 11),
            (1, 12),
            (1, 7),
            (1, 6),
            # at the end because first updated
            (1, 1),
            (1, 3),
            (1, 2),
        ]
    else:
        assert False, recent_threshold

    assert [eval(e.id) for e in call_method(reader)] == expected
