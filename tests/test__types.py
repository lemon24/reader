import pytest

from reader._types import EntryData
from reader._types import FeedData
from reader._types import tag_filter_argument


TAG_DATA = [
    ([], [None, [], (), [[]], ((),), [[], []]]),
    ([[True]], [True, [True], [[True]]]),
    ([[False]], [False, [False], [[False]]]),
    ([[True], [False]], [[True, False], [[True], [False]]]),
    ([[True, False]], [[[True, False]]]),
    ([[(False, 'one')]], [['one'], [['one']], ['one', []], [[], ['one'], []]]),
    ([[(False, 'one')], [(True, 'two')]], [['one', '-two'], [['one'], ['-two']]]),
    ([[(False, 'one'), (True, 'two')]], [[['one', '-two']]]),
    ([[True], [(False, 'one')]], [[True, 'one'], [True, ['one']], [[True], 'one']]),
    ([[(False, 'one'), False]], [[['one', False]]]),
]
TAG_DATA_FLAT = [(input, expected) for expected, inputs in TAG_DATA for input in inputs]


@pytest.mark.parametrize('input, expected', TAG_DATA_FLAT)
def test_tag_filter_argument(input, expected):
    assert tag_filter_argument(input) == expected


DEFINITELY_NOT_TAGS = [0, 1, 2, {}, set(), object()]

TAG_DATA_BAD = [
    ("argument must be", DEFINITELY_NOT_TAGS + ['', 'one', '-one']),
    ("must be non-empty", [[''], ['-'], [['']], [['-']]]),
    (
        "elements of argument must be",
        [[t] for t in DEFINITELY_NOT_TAGS] + [[[t]] for t in DEFINITELY_NOT_TAGS],
    ),
]
TAG_DATA_BAD_FLAT = [
    (input, error) for error, inputs in TAG_DATA_BAD for input in inputs
]


@pytest.mark.parametrize('input, error', TAG_DATA_BAD_FLAT)
def test_tag_filter_argument_error(input, error):
    with pytest.raises(ValueError) as excinfo:
        tag_filter_argument(input, 'argument')
    assert error in str(excinfo.value)
