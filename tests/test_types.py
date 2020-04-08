from dataclasses import dataclass

import pytest

from reader import Entry
from reader import Feed
from reader.core.types import _namedtuple_compat
from reader.core.types import entry_argument
from reader.core.types import feed_argument
from reader.core.types import HighlightedString


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


def test_feed_argument():
    feed = Feed('url')
    assert feed_argument(feed) == feed.url
    assert feed_argument(feed.url) == feed.url
    with pytest.raises(ValueError):
        feed_argument(1)


def test_entry_argument():
    feed = Feed('url')
    entry = Entry('entry', 'updated', feed=feed)
    entry_tuple = feed.url, entry.id
    assert entry_argument(entry) == entry_tuple
    assert entry_argument(entry_tuple) == entry_tuple
    with pytest.raises(ValueError):
        entry_argument(entry._replace(feed=None))
    with pytest.raises(ValueError):
        entry_argument(1)
    with pytest.raises(ValueError):
        entry_argument('ab')
    with pytest.raises(ValueError):
        entry_argument((1, 'b'))
    with pytest.raises(ValueError):
        entry_argument(('a', 2))
    with pytest.raises(ValueError):
        entry_argument(('a', 'b', 'c'))


# TODO: re-use the params below
@pytest.mark.parametrize(
    'string', [HighlightedString('abcd'), HighlightedString('abcd', [slice(0, 4)]),]
)
def test_highlighted_string_str(string):
    assert str(string) == string.value


@pytest.mark.parametrize(
    'slices',
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
def test_highlighted_string_slice_validation(slices):
    with pytest.raises(ValueError):
        HighlightedString('abcd', slices)


@pytest.mark.parametrize(
    'input, value, highlights',
    [
        ('', '', []),
        (' one ', ' one ', []),
        ('><one', 'one', ['']),
        ('><><one', 'one', ['', '']),
        ('\t >one\n< ', '\t one\n ', ['one\n']),
        ('>one< two >three< four', 'one two three four', ['one', 'three']),
        ('one >two< three >four<', 'one two three four', ['two', 'four']),
    ],
)
def test_highlighted_string_extract(input, value, highlights):
    string = HighlightedString.extract(input, '>', '<')
    assert string.value == value
    for hl in string.highlights:
        assert hl.start is not None
        assert hl.stop is not None
        assert hl.step is None
    assert [string.value[hl] for hl in string.highlights] == highlights


@pytest.mark.parametrize('input', ['>one', '>one >two<<', '<two', 'one>', 'two<'])
def test_highlighted_string_extract_errors(input):
    with pytest.raises(ValueError):
        HighlightedString.extract(input, '>', '<')


@pytest.mark.parametrize(
    'string, expected',
    [
        (HighlightedString(), ['']),
        (HighlightedString('abcd'), ['abcd']),
        (HighlightedString('abcd', [slice(0, 4)]), ['', 'abcd', '']),
        (HighlightedString('abcd', [slice(0, 0)]), ['', '', 'abcd']),
        (HighlightedString('abcd', [slice(4, 4)]), ['abcd', '', '']),
        (HighlightedString('abcd', [slice(2, 2)]), ['ab', '', 'cd']),
        (HighlightedString('abcd', [slice(1, 3)]), ['a', 'bc', 'd']),
        (
            HighlightedString('abcd', [slice(0, 0), slice(0, 0)]),
            ['', '', '', '', 'abcd'],
        ),
        (
            HighlightedString('abcd', [slice(1, 2), slice(2, 3)]),
            ['a', 'b', '', 'c', 'd'],
        ),
        (
            HighlightedString('abcd', [slice(2, 3), slice(1, 2)]),
            ['a', 'b', '', 'c', 'd'],
        ),
        (
            HighlightedString('abcd', [slice(1, 2), slice(3, 4)]),
            ['a', 'b', 'c', 'd', ''],
        ),
        (
            HighlightedString('abcd', [slice(0, 1), slice(2, 3)]),
            ['', 'a', 'b', 'c', 'd'],
        ),
        (
            HighlightedString(
                'one two three four', [slice(0, 3, None), slice(8, 13, None)]
            ),
            ['', 'one', ' two ', 'three', ' four'],
        ),
    ],
)
def test_highlighted_string_split(string, expected):
    assert list(string.split()) == expected


@pytest.mark.parametrize(
    'string, expected, expected_upper',
    [
        (HighlightedString(), '', ''),
        (HighlightedString('abcd'), 'abcd', 'ABCD'),
        (HighlightedString('abcd', [slice(0, 4)]), 'xabcdy', 'xABCDy'),
        (HighlightedString('abcd', [slice(0, 0)]), 'xyabcd', 'xyABCD'),
        (HighlightedString('abcd', [slice(4, 4)]), 'abcdxy', 'ABCDxy'),
        (HighlightedString('abcd', [slice(2, 2)]), 'abxycd', 'ABxyCD'),
        (HighlightedString('abcd', [slice(1, 3)]), 'axbcyd', 'AxBCyD'),
        (HighlightedString('abcd', [slice(0, 0), slice(0, 0)]), 'xyxyabcd', 'xyxyABCD'),
        (HighlightedString('abcd', [slice(1, 2), slice(2, 3)]), 'axbyxcyd', 'AxByxCyD'),
        (HighlightedString('abcd', [slice(2, 3), slice(1, 2)]), 'axbyxcyd', 'AxByxCyD'),
        (HighlightedString('abcd', [slice(1, 2), slice(3, 4)]), 'axbycxdy', 'AxByCxDy'),
        (HighlightedString('abcd', [slice(0, 1), slice(2, 3)]), 'xaybxcyd', 'xAyBxCyD'),
    ],
)
def test_highlighted_string_apply(string, expected, expected_upper):
    assert string.apply('', '') == string.value
    assert string.apply('x', 'y') == expected
    assert string.apply('x', 'y', str.upper) == expected_upper
