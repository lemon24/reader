import pytest
from fakeparser import Parser
from test_reader import with_call_entries_recent_method
from test_reader import with_chunk_size_for_recent_test
from utils import naive_datetime
from utils import utc_datetime as datetime


# FIXME: mark most of the parameters as slow

with_maybe_published_or_updated = pytest.mark.parametrize(
    'entry_kwargs',
    [
        {},
        {'published': datetime(2010, 1, 1)},
        {'updated': datetime(2010, 1, 1)},
    ],
)


@with_chunk_size_for_recent_test
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
        three = parser.entry(1, id, **entry_kwargs)
        reader.update_feeds()

    pre_stuff(reader)

    assert [eval(e.id)[1] for e in call_method(reader)] == [2, 1, 3, 4]


@with_chunk_size_for_recent_test
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
