import string
from dataclasses import dataclass
from types import SimpleNamespace

import hypothesis.strategies as st
import pytest
from hypothesis import example
from hypothesis import given

from reader import Entry
from reader import EntrySearchResult
from reader import Feed
from reader.types import _entry_argument
from reader.types import _feed_argument
from reader.types import _namedtuple_compat
from reader.types import ExceptionInfo
from reader.types import HighlightedString
from reader.types import MISSING


def test_namedtuple_compat():
    @dataclass(frozen=True)
    class Object(_namedtuple_compat):
        one: int
        two: int = None

    assert Object._make((1, 2)) == Object(1, 2)
    with pytest.raises(TypeError):
        Object._make((1,))
    with pytest.raises(TypeError):
        Object._make((1, 2, 3))

    assert Object(1, 1)._replace(two=2) == Object(1, 2)

    assert Object(1, 2)._asdict() == {'one': 1, 'two': 2}


def test__feed_argument():
    feed = Feed('url')
    assert _feed_argument(feed) == feed.url
    assert _feed_argument(feed.url) == feed.url
    with pytest.raises(ValueError):
        _feed_argument(1)


def test__entry_argument():
    feed = Feed('url')
    entry = Entry('entry', 'updated', feed=feed)
    entry_tuple = feed.url, entry.id
    assert _entry_argument(entry) == entry_tuple
    assert _entry_argument(entry_tuple) == entry_tuple
    with pytest.raises(ValueError):
        _entry_argument(entry._replace(feed=None))
    with pytest.raises(ValueError):
        _entry_argument(1)
    with pytest.raises(ValueError):
        _entry_argument('ab')
    with pytest.raises(ValueError):
        _entry_argument((1, 'b'))
    with pytest.raises(ValueError):
        _entry_argument(('a', 2))
    with pytest.raises(ValueError):
        _entry_argument(('a', 'b', 'c'))


@pytest.mark.parametrize(
    'highlights',
    [
        [slice(0, None)],
        [slice(None, 0)],
        [slice(0, 1, 1)],
        [slice(0, 1, 0)],
        [slice(0, 1, -1)],
        [slice(1, 0)],
        [slice(-1, 0)],
        [slice(0, -1)],
        [slice(4, 5)],
        [slice(5, 5)],
        [slice(0, 1), slice(0, 2)],
        [slice(0, 2), slice(1, 3)],
    ],
)
def test_highlighted_string_slice_validation(highlights):
    with pytest.raises(ValueError):
        HighlightedString('abcd', highlights)


HS_EXTRACT_DATA = [
    # input, value, highlights
    ('', '', []),
    (' one ', ' one ', []),
    ('><one', 'one', ['']),
    ('><><one', 'one', ['', '']),
    ('\t >one\n< ', '\t one\n ', ['one\n']),
    ('>one< two >three< four', 'one two three four', ['one', 'three']),
    ('one >two< three >four<', 'one two three four', ['two', 'four']),
]


@pytest.mark.parametrize('input, value, highlights', HS_EXTRACT_DATA)
def test_highlighted_string_extract(input, value, highlights, before='>', after='<'):
    string = HighlightedString.extract(input, before, after)
    assert string.value == value
    for hl in string.highlights:
        assert hl.start is not None
        assert hl.stop is not None
        assert hl.step is None
    assert [string.value[hl] for hl in string.highlights] == highlights


@st.composite
def maybe_highlighted_words_and_markers(draw):
    random = draw(st.randoms(use_true_random=True))
    marker = ''.join(random.choices(string.ascii_letters, k=20))
    before = f'>{marker}>'
    after = f'<{marker}<'
    maybe_highlighted_words = st.lists(st.tuples(st.text(), st.booleans()))
    return draw(maybe_highlighted_words), before, after


# TODO: maybe use hypothesis profiles
@pytest.mark.slow
@given(maybe_highlighted_words_and_markers())
def test_highlighted_string_extract_fuzz(maybe_highlighted_words_and_markers):
    words, before, after = maybe_highlighted_words_and_markers
    input = ''.join(f'{before}{w}{after}' if h else w for w, h in words)
    value = ''.join(w for w, _ in words)
    highlights = [w for w, h in words if h]
    test_highlighted_string_extract(input, value, highlights, before, after)


@pytest.mark.parametrize('input', ['>one', '>one >two<<', '<two', 'one>', 'two<'])
def test_highlighted_string_extract_errors(input):
    with pytest.raises(ValueError):
        HighlightedString.extract(input, '>', '<')


HS_SPLIT_APPLY_DATA = [
    # string, split, apply, apply_upper
    (HighlightedString(), [''], '', ''),
    (HighlightedString('abcd'), ['abcd'], 'abcd', 'ABCD'),
    (HighlightedString('abcd', [slice(0, 4)]), ['', 'abcd', ''], 'xabcdy', 'xABCDy'),
    (HighlightedString('abcd', [slice(0, 0)]), ['', '', 'abcd'], 'xyabcd', 'xyABCD'),
    (HighlightedString('abcd', [slice(4, 4)]), ['abcd', '', ''], 'abcdxy', 'ABCDxy'),
    (HighlightedString('abcd', [slice(2, 2)]), ['ab', '', 'cd'], 'abxycd', 'ABxyCD'),
    (HighlightedString('abcd', [slice(1, 3)]), ['a', 'bc', 'd'], 'axbcyd', 'AxBCyD'),
    (
        HighlightedString('abcd', [slice(0, 0), slice(0, 0)]),
        ['', '', '', '', 'abcd'],
        'xyxyabcd',
        'xyxyABCD',
    ),
    (
        HighlightedString('abcd', [slice(1, 2), slice(2, 3)]),
        ['a', 'b', '', 'c', 'd'],
        'axbyxcyd',
        'AxByxCyD',
    ),
    (
        HighlightedString('abcd', [slice(2, 3), slice(1, 2)]),
        ['a', 'b', '', 'c', 'd'],
        'axbyxcyd',
        'AxByxCyD',
    ),
    (
        HighlightedString('abcd', [slice(1, 2), slice(3, 4)]),
        ['a', 'b', 'c', 'd', ''],
        'axbycxdy',
        'AxByCxDy',
    ),
    (
        HighlightedString('abcd', [slice(0, 1), slice(2, 3)]),
        ['', 'a', 'b', 'c', 'd'],
        'xaybxcyd',
        'xAyBxCyD',
    ),
    (
        HighlightedString('one two three four', [slice(0, 3), slice(8, 13)]),
        ['', 'one', ' two ', 'three', ' four'],
        'xoney two xthreey four',
        'xONEy TWO xTHREEy FOUR',
    ),
]


@pytest.mark.parametrize('string, expected', [t[:2] for t in HS_SPLIT_APPLY_DATA])
def test_highlighted_string_split(string, expected):
    assert list(string.split()) == expected


@pytest.mark.parametrize(
    'string, expected, expected_upper', [t[:1] + t[2:] for t in HS_SPLIT_APPLY_DATA]
)
def test_highlighted_string_apply(string, expected, expected_upper):
    assert string.apply('', '') == string.value
    assert string.apply('x', 'y') == expected
    assert string.apply('x', 'y', str.upper) == expected_upper


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


@pytest.mark.parametrize('string', [t[0] for t in HS_SPLIT_APPLY_DATA])
def test_highlighted_string_str(string):
    assert str(string) == string.value


@pytest.mark.parametrize(
    'input, before, after',
    [(t[0], '>', '<') for t in HS_EXTRACT_DATA]
    + [(t[2], 'x', 'y') for t in HS_SPLIT_APPLY_DATA]
    + [(t[3], 'x', 'y') for t in HS_SPLIT_APPLY_DATA],
)
def test_highlighted_string_roundtrip(input, before, after):
    assert HighlightedString.extract(input, before, after).apply(before, after) == input


@pytest.mark.slow
@given(maybe_highlighted_words_and_markers())
def test_highlighted_string_roundtrip_fuzz(maybe_highlighted_words_and_markers):
    words, before, after = maybe_highlighted_words_and_markers
    input = ''.join(f'{before}{w}{after}' if h else w for w, h in words)
    test_highlighted_string_roundtrip(input, before, after)


def test_missing():
    assert repr(MISSING) == 'no value'


def test_exception_info():
    try:
        raise ValueError('message')
    except Exception as e:
        ei = ExceptionInfo.from_exception(e)

    assert ei.type_name == 'builtins.ValueError'
    assert ei.value_str == 'message'
    assert ei.traceback_str.startswith('Traceback')
    assert ei.traceback_str.rstrip().endswith('ValueError: message')
