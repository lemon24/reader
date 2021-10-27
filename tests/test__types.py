from types import SimpleNamespace

import pytest

from reader._types import entry_data_from_obj
from reader._types import EntryData
from reader._types import FeedData
from reader._types import fix_datetime_tzinfo
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


@pytest.mark.parametrize('data_file', ['full', 'empty'])
def test_entry_data_from_obj(data_dir, data_file):
    expected = {'url_base': '', 'rel_base': ''}
    exec(data_dir.join(f'{data_file}.rss.py').read(), expected)

    for i, entry in enumerate(expected['entries']):
        entry_utc = fix_datetime_tzinfo(entry, 'updated', 'published')

        assert entry == entry_data_from_obj(entry_utc), i

        entry_dict = entry_utc._asdict()
        if 'content' in entry_dict:
            entry_dict['content'] = [c._asdict() for c in entry_dict['content']]
        if 'enclosures' in entry_dict:
            entry_dict['enclosures'] = [e._asdict() for e in entry_dict['enclosures']]

        assert entry == entry_data_from_obj(entry_dict), i


@pytest.mark.parametrize(
    'exc, entry',
    [
        (AttributeError, SimpleNamespace()),
        (AttributeError, SimpleNamespace(feed_url='feed')),
        (AttributeError, SimpleNamespace(id='id')),
        (TypeError, SimpleNamespace(feed_url='feed', id=1)),
        (TypeError, SimpleNamespace(feed_url='feed', id=None)),
        (TypeError, SimpleNamespace(feed_url='feed', id='id', updated=1)),
        (TypeError, SimpleNamespace(feed_url='feed', id='id', title=1)),
        (TypeError, SimpleNamespace(feed_url='feed', id='id', content=1)),
        (
            AttributeError,
            SimpleNamespace(feed_url='feed', id='id', content=[SimpleNamespace()]),
        ),
        (
            TypeError,
            SimpleNamespace(
                feed_url='feed', id='id', content=[SimpleNamespace(value=1)]
            ),
        ),
        (
            TypeError,
            SimpleNamespace(
                feed_url='feed',
                id='id',
                content=[SimpleNamespace(value='value', type=1)],
            ),
        ),
        (
            AttributeError,
            SimpleNamespace(feed_url='feed', id='id', enclosures=[SimpleNamespace()]),
        ),
        (
            TypeError,
            SimpleNamespace(
                feed_url='feed', id='id', enclosures=[SimpleNamespace(href=1)]
            ),
        ),
        (
            TypeError,
            SimpleNamespace(
                feed_url='feed',
                id='id',
                enclosures=[SimpleNamespace(href='href', type=1)],
            ),
        ),
        (
            TypeError,
            SimpleNamespace(
                feed_url='feed',
                id='id',
                enclosures=[SimpleNamespace(href='href', length='1')],
            ),
        ),
    ],
)
def test_entry_data_from_obj_errors(exc, entry):

    with pytest.raises(exc):
        entry_data_from_obj(entry)

    with pytest.raises(exc):
        entry_dict = dict(vars(entry))
        if 'content' in entry_dict:
            entry_dict['content'] = [dict(vars(c)) for c in entry_dict['content']]
        if 'enclosures' in entry_dict:
            entry_dict['enclosures'] = [dict(vars(e)) for e in entry_dict['enclosures']]
        entry_data_from_obj(entry_dict)
