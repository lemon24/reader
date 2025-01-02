import string
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

import pytest

from reader import Content
from reader import Entry
from reader import EntryError
from reader import EntrySearchResult
from reader import EntrySource
from reader import ExceptionInfo
from reader import Feed
from reader import FeedError
from reader import HighlightedString
from reader import UpdatedFeed
from reader import UpdateResult
from reader._types import EntryData
from reader._types import FeedData
from reader.types import _entry_argument
from reader.types import _feed_argument
from reader.types import _namedtuple_compat
from reader.types import _resource_argument
from reader.types import MISSING


def test_namedtuple_compat():
    @dataclass(frozen=True)
    class Object(_namedtuple_compat):
        one: int
        two: int = None

    assert Object(1, 1)._replace(two=2) == Object(1, 2)
    assert Object(1, 2)._asdict() == {'one': 1, 'two': 2}


BAD_RESOURCE_ARGUMENTS = [
    1,
    Feed(None),
    Feed(1),
    (1, 'b'),
    ('a', 2),
    (None, 'b'),
    ('a', None),
    ('a', 'b', 'c'),
    Entry('entry', feed=None),
    Entry(None, feed=Feed('url')),
    Entry(1, feed=Feed('url')),
    Entry('entry', feed=Feed(None)),
]
BAD_FEED_ARGUMENTS = [(), ('a', 'b')] + BAD_RESOURCE_ARGUMENTS
BAD_ENTRY_ARGUMENTS = [(), 1, 'ab', Feed('url')] + BAD_RESOURCE_ARGUMENTS
WILDCARD_ARGUMENTS = [None, (None,), (None, None)]


def test__feed_argument():
    feed = Feed('url')
    assert _feed_argument(feed) == feed.url
    assert _feed_argument(feed.url) == feed.url
    assert _resource_argument((feed.url,)) == (feed.url,)


@pytest.mark.parametrize('feed', BAD_FEED_ARGUMENTS + WILDCARD_ARGUMENTS)
def test__feed_argument_valueerror(feed):
    with pytest.raises(ValueError):
        _feed_argument(feed)


def test__entry_argument():
    feed = Feed('url')
    entry = Entry('entry', 'updated', feed=feed)
    entry_tuple = feed.url, entry.id
    assert _entry_argument(entry) == entry_tuple
    assert _entry_argument(entry_tuple) == entry_tuple


@pytest.mark.parametrize('entry', BAD_ENTRY_ARGUMENTS + WILDCARD_ARGUMENTS)
def test__entry_argument_valueerror(entry):
    with pytest.raises(ValueError):
        _entry_argument(entry)


def test__resource_argument():
    feed = Feed('url')
    entry = Entry('entry', 'updated', feed=feed)
    entry_tuple = feed.url, entry.id
    assert _resource_argument(()) == ()
    assert _resource_argument(feed) == (feed.url,)
    assert _resource_argument(feed.url) == (feed.url,)
    assert _resource_argument((feed.url,)) == (feed.url,)
    assert _resource_argument(entry) == entry_tuple
    assert _resource_argument(entry_tuple) == entry_tuple


@pytest.mark.parametrize('resource', BAD_RESOURCE_ARGUMENTS + WILDCARD_ARGUMENTS)
def test__resource_argument_valueerror(resource):
    with pytest.raises(ValueError):
        _resource_argument(resource)


def test_resource_id():
    assert Feed('url').resource_id == ('url',)
    assert Entry('entry', 'updated', feed=Feed('url')).resource_id == ('url', 'entry')
    assert EntrySearchResult('url', 'entry').resource_id == ('url', 'entry')
    assert FeedData('url').resource_id == ('url',)
    assert EntryData('url', 'entry', 'updated').resource_id == ('url', 'entry')
    assert FeedError('url').resource_id == ('url',)
    assert EntryError('url', 'entry').resource_id == ('url', 'entry')


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


def test_entry_updated_not_none():
    entry = Entry('id', datetime(2021, 12, 21))

    # will be entry.updated or entry.first_updated at some point
    assert entry.updated_not_none == entry.updated


def entry_with_feed_title(feed=None, user=None, source=None):
    return Entry(
        'entry',
        feed=Feed('feed', title=feed, user_title=user),
        source=EntrySource(title=source) if source else None,
    )


@pytest.mark.parametrize(
    'entry, title',
    [
        (entry_with_feed_title(), None),
        (entry_with_feed_title(feed='feed'), 'feed'),
        (entry_with_feed_title(user='user'), 'user'),
        (entry_with_feed_title(source='source'), 'source'),
        (entry_with_feed_title(feed='feed', user='user'), 'user'),
        (entry_with_feed_title(feed='feed', source='source'), 'source (feed)'),
        (
            entry_with_feed_title(feed='feed', user='user', source='source'),
            'source (user)',
        ),
        (entry_with_feed_title(feed='feed', source='feed'), 'feed'),
        (entry_with_feed_title(feed='feed', user='user', source='user'), 'user'),
        (entry_with_feed_title(feed='feed', user='user', source='feed'), 'user'),
    ],
)
def test_entry_feed_resolved_title(entry, title):
    assert entry.feed_resolved_title == title


@pytest.mark.parametrize(
    'entry_kwargs, kwargs, expected',
    [
        ({}, {}, None),
        (dict(summary='summary'), {}, Content('summary')),
        (dict(content=[Content('content')]), {}, Content('content')),
        (dict(summary='summary', content=[Content('content')]), {}, Content('content')),
        (
            dict(summary='summary', content=[Content('content')]),
            dict(prefer_summary=False),
            Content('content'),
        ),
        (
            dict(summary='summary', content=[Content('content')]),
            dict(prefer_summary=True),
            Content('summary'),
        ),
        (
            dict(
                content=[
                    Content('notype'),
                    Content('html', type='text/html'),
                    Content('plain', type='text/plain'),
                ]
            ),
            {},
            Content('html', type='text/html'),
        ),
        (
            dict(content=[Content('notype'), Content('plain', type='text/plain')]),
            {},
            Content('plain', type='text/plain'),
        ),
        (
            dict(content=[Content('notype'), Content('unknown', type='text/unknown')]),
            {},
            Content('notype'),
        ),
    ],
)
def test_entry_get_content(entry_kwargs, kwargs, expected):
    assert Entry('id', **entry_kwargs).get_content(**kwargs) == expected


@pytest.mark.parametrize(
    'content, expected',
    [
        (Content('value'), True),
        (Content('value', 'text/html'), True),
        (Content('value', 'text/xhtml'), True),
        (Content('value', 'text/plain'), False),
        (Content('value', 'unknown'), False),
    ],
)
def test_content_is_html(content, expected):
    assert content.is_html == expected


def test_updated_feed_properties():
    feed = UpdatedFeed('url', new=1, modified=2, unmodified=3)
    assert feed.total == 6


def test_update_result_properties():
    feed = UpdatedFeed('url', 0, 1)
    result = UpdateResult('url', feed)
    assert result.updated_feed is feed
    assert result.error is None
    assert result.not_modified is False

    feed = UpdatedFeed('url', 0, 0)
    result = UpdateResult('url', feed)
    assert result.updated_feed is feed
    assert result.error is None
    assert result.not_modified is True

    result = UpdateResult('url', None)
    assert result.updated_feed is None
    assert result.error is None
    assert result.not_modified is True

    exc = Exception('error')
    result = UpdateResult('url', exc)
    assert result.updated_feed is None
    assert result.error is exc
    assert result.not_modified is False
