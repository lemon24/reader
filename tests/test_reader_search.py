from datetime import datetime

import pytest
from fakeparser import Parser

from reader import EntrySearchResult
from reader import ReaderError
from reader.core.storage import strip_html


def test_nothing_is_actually_working_searchwise(reader):
    with pytest.raises(Exception):
        reader.update_search()
    with pytest.raises(Exception):
        list(reader.search_entries('one'))


def test_search_disabled_by_default(reader):
    assert not reader.is_search_enabled()


def test_enable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()


@pytest.mark.xfail(strict=True, reason="TODO: shouldn't fail")
def test_enable_search_already_enabled(reader):
    reader.enable_search()
    reader.enable_search()


def test_disable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()
    reader.disable_search()
    assert not reader.is_search_enabled()


@pytest.mark.xfail(strict=True, reason="TODO: shouldn't fail")
def test_disable_search_already_disabled(reader):
    reader.disable_search()


def test_update_search(reader):
    reader.enable_search()
    reader.update_search()


@pytest.mark.xfail(strict=True, reason="TODO: should fail")
def test_update_search_fails_if_not_enabled(reader):
    with pytest.raises(ReaderError):
        reader.update_search()


def test_strip_html():
    assert strip_html(None) == None
    assert strip_html(10) == 10
    assert strip_html(11.2) == 11.2
    assert strip_html(b'aaaa') == b'aaaa'
    assert strip_html(b'aa<br>aa') == b'aa<br>aa'

    assert strip_html('aaaa') == 'aaaa'
    with pytest.xfail(reason="TODO: implement this"):
        assert strip_html('aa<br>aa') == 'aa aa'

    # TODO: more better tests once implemented


def test_search_entries_basic(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 1, 1), title='two')

    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    set(reader.search_entries('zero')) == set()
    set(reader.search_entries('one')) == {
        EntrySearchResult(one.id, feed.url, one.title)
    }
    set(reader.search_entries('two')) == {
        EntrySearchResult(two.id, feed.url, two.title)
    }
