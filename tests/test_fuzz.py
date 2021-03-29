import string
import sys

import hypothesis.strategies as st
import pytest
from fakeparser import Parser
from hypothesis import example
from hypothesis import given
from hypothesis import settings
from test_reader import get_entries_random
from test_reader import search_entries_random
from test_reader import with_call_entries_method
from test_types import test_highlighted_string_extract
from test_types import test_highlighted_string_roundtrip

from reader import make_reader
from reader.types import HighlightedString


# Skip, since these add about 10s to the test suite
# and fail intermittently because the deadline gets exceeded.
# Especially skip on PyPy, since they're even slower there,
# and also increase the likelyhood of tests failing due to sqlite3 brittleness.
#
# Things to do when we reconsider:
#
# * use hypothesis profiles
# * write better tests, so we can actually get value from this
#
# Existing issue: https://github.com/lemon24/reader/issues/188
#
pytestmark = pytest.mark.skip()


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
    # TODO: use the make_reader() fixture if possible
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


@st.composite
def maybe_highlighted_words_and_markers(draw):
    random = draw(st.randoms(use_true_random=True))
    marker = ''.join(random.choices(string.ascii_letters, k=20))
    before = f'>{marker}>'
    after = f'<{marker}<'
    maybe_highlighted_words = st.lists(st.tuples(st.text(), st.booleans()))
    return draw(maybe_highlighted_words), before, after


@pytest.mark.slow
@given(maybe_highlighted_words_and_markers())
def test_highlighted_string_extract_fuzz(maybe_highlighted_words_and_markers):
    words, before, after = maybe_highlighted_words_and_markers
    input = ''.join(f'{before}{w}{after}' if h else w for w, h in words)
    value = ''.join(w for w, _ in words)
    highlights = [w for w, h in words if h]
    test_highlighted_string_extract(input, value, highlights, before, after)


@pytest.mark.slow
@given(st.lists(st.tuples(st.text(), st.booleans())), st.text(), st.text())
def test_highlighted_string_apply_fuzz(words, before, after):
    slices = []
    current_index = 0
    for word, is_highlight in words:
        next_index = current_index + len(word)
        if is_highlight:
            slices.append(slice(current_index, next_index))
        current_index = next_index

    string = HighlightedString(''.join(w for w, _ in words), slices)

    expected = ''.join(f'{before}{w}{after}' if h else w for w, h in words)

    assert string.apply(before, after) == expected


@pytest.mark.slow
@given(maybe_highlighted_words_and_markers())
def test_highlighted_string_roundtrip_fuzz(maybe_highlighted_words_and_markers):
    words, before, after = maybe_highlighted_words_and_markers
    input = ''.join(f'{before}{w}{after}' if h else w for w, h in words)
    test_highlighted_string_roundtrip(input, before, after)
