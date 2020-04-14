from datetime import datetime

import pytest
from fakeparser import Parser
from utils import rename_argument

from reader import Content
from reader import Enclosure
from reader import EntrySearchResult
from reader import HighlightedString
from reader import Reader
from reader import ReaderError
from reader import SearchNotEnabledError


@pytest.fixture(params=[False, True], ids=['without_entries', 'with_entries'])
def reader_without_and_with_entries(request, reader):
    if not request.param:
        return reader

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')

    reader.add_feed(feed.url)
    reader.update_feeds()

    return reader


@rename_argument('reader', 'reader_without_and_with_entries')
def test_search_disabled_by_default(reader):
    assert not reader.is_search_enabled()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_enable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_enable_search_already_enabled(reader):
    reader.enable_search()
    reader.enable_search()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_disable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()
    reader.disable_search()
    assert not reader.is_search_enabled()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_disable_search_already_disabled(reader):
    reader.disable_search()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_update_search(reader):
    reader.enable_search()
    reader.update_search()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_update_search_fails_if_not_enabled(reader):
    with pytest.raises(SearchNotEnabledError):
        reader.update_search()


@rename_argument('reader', 'reader_without_and_with_entries')
def test_search_entries_fails_if_not_enabled(reader):
    with pytest.raises(SearchNotEnabledError):
        list(reader.search_entries('one'))


def test_search_entries_basic(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 1, 1), title='two', summary='summary')
    three = parser.entry(
        1,
        3,
        datetime(2010, 1, 1),
        title='shall not be named',
        summary='does not match',
        content=[Content('three content')],
    )

    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()

    assert list(reader.search_entries('one')) == []

    reader.update_search()

    # TODO: the asserts below look parametrizable

    assert list(reader.search_entries('zero')) == []
    assert list(reader.search_entries('one')) == [
        EntrySearchResult(
            feed.url,
            one.id,
            {
                '.title': HighlightedString(one.title, (slice(0, 3),)),
                '.feed.title': HighlightedString(feed.title),
            },
        )
    ]
    assert list(reader.search_entries('two')) == [
        EntrySearchResult(
            feed.url,
            two.id,
            {
                '.title': HighlightedString(two.title, (slice(0, 3),)),
                '.feed.title': HighlightedString(feed.title),
            },
            {'.summary': HighlightedString('summary')},
        )
    ]
    assert list(reader.search_entries('three')) == [
        EntrySearchResult(
            feed.url,
            three.id,
            {
                '.title': HighlightedString(three.title),
                '.feed.title': HighlightedString(feed.title),
            },
            {
                '.content[0].value': HighlightedString(
                    three.content[0].value, (slice(0, 5),)
                )
            },
        )
    ]

    # TODO: fix inconsistent naming

    feed_two = parser.feed(2, datetime(2010, 1, 1))
    feed_two_entry = parser.entry(2, 1, datetime(2010, 1, 1), title=None)
    feed_three = parser.feed(3, datetime(2010, 1, 1), title=None)
    feed_three_entry = parser.entry(3, 1, datetime(2010, 1, 1), title='entry summary')

    reader.add_feed(feed_two.url)
    reader.add_feed(feed_three)
    reader.set_feed_user_title(feed_two, 'a summary of things')

    reader.update_feeds()
    feed_two_entry = reader.get_entry((feed_two.url, feed_two_entry.id))

    reader.update_search()

    # TODO: we're also testing for order here, and maybe we shouldn't
    assert list(reader.search_entries('summary')) == [
        EntrySearchResult(
            feed_three.url,
            feed_three_entry.id,
            {'.title': HighlightedString(feed_three_entry.title, (slice(6, 13),))},
        ),
        EntrySearchResult(
            feed_two.url,
            feed_two_entry.id,
            {
                '.feed.user_title': HighlightedString(
                    feed_two_entry.feed.user_title, (slice(2, 9),)
                )
            },
        ),
        EntrySearchResult(
            feed.url,
            two.id,
            {
                '.title': HighlightedString(two.title),
                '.feed.title': HighlightedString(feed.title),
            },
            {'.summary': HighlightedString(two.summary, (slice(0, 7),))},
        ),
    ]


# search_entries() filtering is tested in test_reader.py::test_entries_filtering{,_error}


# TODO: fix duplication in these order tests
# BEGIN order tests


def test_search_entries_order_title_summary_beats_title(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 1, 1), title='two')
    three = parser.entry(1, 3, datetime(2010, 1, 1), title='one', summary='one')

    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    assert [(e.id, e.feed_url) for e in reader.search_entries('one')] == [
        (three.id, feed.url),
        (one.id, feed.url),
    ]


def test_search_entries_order_title_content_beats_title(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 1, 1), title='two')
    three = parser.entry(
        1, 3, datetime(2010, 1, 1), title='one', content=[Content('one')]
    )

    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    assert [(e.id, e.feed_url) for e in reader.search_entries('one')] == [
        (three.id, feed.url),
        (one.id, feed.url),
    ]


def test_search_entries_order_content(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        summary='word word',
        content=[Content('word'), Content('does not match'), Content('word word word')],
    )

    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    # there should be exactly one result
    (rv,) = reader.search_entries('word')

    assert list(rv.content) == ['.content[2].value', '.summary', '.content[0].value']


@pytest.mark.parametrize(
    'chunk_size',
    [
        # the default
        Reader._pagination_chunk_size,
        # rough result size for this test
        1,
        2,
        3,
        8,
        # unchunked query
        0,
    ],
)
def test_search_entries_order_weights(reader, chunk_size):
    """entry title beats feed title beats entry content/summary."""

    # TODO: may need fixing once we finish tuning the weights (it should fail)

    reader._pagination_chunk_size = chunk_size

    parser = Parser()
    reader._parser = parser

    feed_one = parser.feed(1, datetime(2010, 1, 1), title='one')
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    feed_two = parser.feed(2, datetime(2010, 1, 1), title='two')
    entry_two = parser.entry(2, 2, datetime(2010, 1, 1), title='one')
    entry_three = parser.entry(2, 3, datetime(2010, 1, 1), content=[Content('one')])
    entry_four = parser.entry(2, 4, datetime(2010, 1, 1), summary='one')
    entry_five = parser.entry(2, 5, datetime(2010, 1, 1), content=[Content('one')] * 2)
    entry_six = parser.entry(
        2, 6, datetime(2010, 1, 1), summary='one', content=[Content('one')]
    )
    entry_seven = parser.entry(2, 7, datetime(2010, 1, 1), title="does not match")

    reader.add_feed(feed_one.url)
    reader.add_feed(feed_two.url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    rv = [(e.id, e.feed_url) for e in reader.search_entries('one')]

    assert rv[:2] == [(entry_two.id, feed_two.url), (entry_one.id, feed_one.url)]

    # TODO: how do we check these have the same exact rank?
    assert sorted(rv[2:]) == [
        (entry_three.id, feed_two.url),
        (entry_four.id, feed_two.url),
        (entry_five.id, feed_two.url),
        (entry_six.id, feed_two.url),
    ]


# END order tests
