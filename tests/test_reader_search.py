from datetime import datetime

import pytest
from fakeparser import Parser

from reader import Content
from reader import Enclosure
from reader import EntrySearchResult
from reader import Reader
from reader import ReaderError
from reader import SearchNotEnabledError


def test_search_disabled_by_default(reader):
    assert not reader.is_search_enabled()


def test_enable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()


def test_enable_search_already_enabled(reader):
    reader.enable_search()
    reader.enable_search()


def test_disable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()
    reader.disable_search()
    assert not reader.is_search_enabled()


def test_disable_search_already_disabled(reader):
    reader.disable_search()


def test_update_search(reader):
    reader.enable_search()
    reader.update_search()


def test_update_search_fails_if_not_enabled(reader):
    with pytest.raises(SearchNotEnabledError):
        reader.update_search()


def test_search_entries_fails_if_not_enabled(reader):
    with pytest.raises(SearchNotEnabledError):
        list(reader.search_entries('one'))


def test_search_entries_basic(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 1, 1), title='two')

    # FIXME: a few more, with summary and content(s)

    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()

    list(reader.search_entries('one')) == []

    reader.update_search()

    list(reader.search_entries('zero')) == []
    list(reader.search_entries('one')) == [
        EntrySearchResult(one.id, feed.url, one.title)
    ]
    list(reader.search_entries('two')) == [
        EntrySearchResult(two.id, feed.url, two.title)
    ]


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

    [(e.id, e.feed) for e in reader.search_entries('one')] == [
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

    [(e.id, e.feed) for e in reader.search_entries('one')] == [
        (three.id, feed.url),
        (one.id, feed.url),
    ]


@pytest.mark.parametrize(
    'chunk_size',
    [
        # the default
        Reader._get_entries_chunk_size,
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

    # TODO: rename Reader._get_entries_chunk_size to something more generic
    reader._get_entries_chunk_size = chunk_size

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

    rv = [(e.id, e.feed) for e in reader.search_entries('one')]

    assert rv[:2] == [(entry_two.id, feed_two.url), (entry_one.id, feed_one.url)]

    # TODO: how do we check these have the same exact rank?
    assert sorted(rv[2:]) == [
        (entry_three.id, feed_two.url),
        (entry_four.id, feed_two.url),
        (entry_five.id, feed_two.url),
        (entry_six.id, feed_two.url),
    ]


# END order tests


# TODO: maybe we can unify these with test_get_entries_{read,important,...}
# BEGIN filtering tests


def test_search_entries_read(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 2, 1), title='one')
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    reader.mark_as_read((feed.url, one.id))

    def search(**kwargs):
        return {(e.id, e.feed) for e in reader.search_entries('one', **kwargs)}

    assert search() == {(one.id, feed.url), (two.id, feed.url)}
    assert search(read=None) == {(one.id, feed.url), (two.id, feed.url)}
    assert search(read=True) == {(one.id, feed.url)}
    assert search(read=False) == {(two.id, feed.url)}

    with pytest.raises(ValueError):
        search(read='bad read')


def test_search_entries_important(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 2, 1), title='one')
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    reader.mark_as_important((feed.url, one.id))

    def search(**kwargs):
        return {(e.id, e.feed) for e in reader.search_entries('one', **kwargs)}

    assert search() == {(one.id, feed.url), (two.id, feed.url)}
    assert search(important=None) == {(one.id, feed.url), (two.id, feed.url)}
    assert search(important=True) == {(one.id, feed.url)}
    assert search(important=False) == {(two.id, feed.url)}

    with pytest.raises(ValueError):
        search(important='bad important')


def test_search_entries_has_enclosures(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(
        1, 1, datetime(2010, 1, 1), title='one', enclosures=[Enclosure('http://e2')]
    )
    two = parser.entry(1, 2, datetime(2010, 2, 1), title='one')
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    reader.mark_as_important((feed.url, one.id))

    def search(**kwargs):
        return {(e.id, e.feed) for e in reader.search_entries('one', **kwargs)}

    assert search() == {(one.id, feed.url), (two.id, feed.url)}
    assert search(has_enclosures=None) == {(one.id, feed.url), (two.id, feed.url)}
    assert search(has_enclosures=True) == {(one.id, feed.url)}
    assert search(has_enclosures=False) == {(two.id, feed.url)}

    with pytest.raises(ValueError):
        search(has_enclosures='bad has enclosures')


def test_search_entries_feed_url(reader, feed_arg):
    parser = Parser()
    reader._parser = parser

    one = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.feed(2, datetime(2010, 2, 1))
    entry_two = parser.entry(2, 2, datetime(2010, 2, 1), title='one')
    reader.add_feed(one.url)
    reader.add_feed(two.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    def search(**kwargs):
        return {(e.id, e.feed) for e in reader.search_entries('one', **kwargs)}

    assert search() == {(entry_one.id, one.url), (entry_two.id, two.url)}
    assert search(feed=None) == {(entry_one.id, one.url), (entry_two.id, two.url)}
    assert search(feed=feed_arg(one)) == {(entry_one.id, one.url)}
    assert search(feed=feed_arg(two)) == {(entry_two.id, two.url)}

    # TODO: Should this raise an exception?
    assert search(feed='bad feed') == set()


def test_search_entries_entry(reader, entry_arg):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 2, 1))
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    one = one._replace(feed=feed)
    two = two._replace(feed=feed)

    def search(**kwargs):
        return {(e.id, e.feed) for e in reader.search_entries('one', **kwargs)}

    assert search() == {(one.id, feed.url)}
    assert search(entry=None) == {(one.id, feed.url)}
    assert search(entry=entry_arg(one)) == {(one.id, feed.url)}
    assert search(entry=entry_arg(two)) == set()


# END filtering tests
