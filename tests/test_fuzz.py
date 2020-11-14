import sys

import hypothesis.strategies as st
import pytest
from fakeparser import Parser
from hypothesis import given
from hypothesis import settings
from test_reader import get_entries_random
from test_reader import search_entries_random
from test_reader import with_call_entries_method

from reader import make_reader


# Skip on PyPy, as these tests are even slower there.
# Reconsider when we start using hypothesis profiles.
pytestmark = pytest.mark.skipif("sys.implementation.name == 'pypy'")


@st.composite
def data_and_kwargs(draw):
    data = draw(
        st.lists(
            st.tuples(st.integers(), st.integers(), st.datetimes(), st.datetimes())
        )
    )

    kwargs = draw(
        st.fixed_dictionaries(
            {},
            optional={
                'read': st.none() | st.booleans(),
                'important': st.none() | st.booleans(),
                'has_enclosures': st.none() | st.booleans(),
                'feed': st.none()
                | st.sampled_from([f'{t[0]}' for t in data] + [''])
                | st.text(),
                'entry': st.none()
                | st.sampled_from(
                    [(f'{t[0]}', f'{t[0]}, {t[1]}') for t in data] + [('', '')]
                )
                | st.tuples(st.text(), st.text()),
            },
        )
    )

    chunk_size = draw(st.integers(0, len(data) * 2))

    return data, kwargs, chunk_size


@pytest.mark.slow
@with_call_entries_method
@given(data_and_kwargs=data_and_kwargs())
@settings(deadline=1000 if sys.implementation.name == 'pypy' else 400)
def test_sort_and_filter_subset_basic(data_and_kwargs, pre_stuff, call_method):
    entry_data, kwargs, chunk_size = data_and_kwargs

    # can't use reader fixture because of
    # https://github.com/pytest-dev/pytest/issues/916
    reader = make_reader(':memory:')

    reader._storage.chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser

    for feed_id, entry_id, feed_updated, entry_updated in entry_data:
        seen_feed = feed_id in parser.feeds
        feed = parser.feed(feed_id, feed_updated)
        parser.entry(feed_id, entry_id, entry_updated)
        if not seen_feed:
            reader.add_feed(feed.url)

    reader.update_feeds()
    pre_stuff(reader)

    expected = [
        (fid, eid) for fid, entries in parser.entries.items() for eid in entries
    ]

    actual = [eval(e.id) for e in call_method(reader)]

    if call_method not in (get_entries_random, search_entries_random):
        assert len(expected) == len(actual)
        assert set(expected) == set(actual)
    else:
        assert set(expected) >= set(actual)

    actual = [eval(e.id) for e in call_method(reader, **kwargs)]
    assert set(expected) >= set(actual)
