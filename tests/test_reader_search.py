import threading
from datetime import datetime

import pytest
from fakeparser import Parser
from utils import rename_argument

from reader import Content
from reader import Enclosure
from reader import EntrySearchCounts
from reader import EntrySearchResult
from reader import FeedNotFoundError
from reader import HighlightedString
from reader import Reader
from reader import ReaderError
from reader import SearchError
from reader import SearchNotEnabledError
from reader import StorageError
from reader._search import Search
from reader._storage import Storage


def test_closed(reader):
    reader.close()
    # TODO: Maybe parametrize with all the methods
    # (also, unify with test_reader.py::test_closed)
    with pytest.raises(SearchError) as excinfo:
        reader.is_search_enabled()
    assert 'closed' in excinfo.value.message


@pytest.fixture(params=[False, True], ids=['without_entries', 'with_entries'])
def reader_without_and_with_entries(request, reader):
    if not request.param:
        return reader

    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        title='feed one',
        summary='summary',
        content=[Content('content'), Content('another content')],
    )
    parser.entry(1, 2, datetime(2010, 1, 1), title='feed one')
    parser.entry(1, 3, datetime(2010, 1, 1), title='feed one')
    parser.entry(1, 4, datetime(2010, 1, 1), title='feed one')
    parser.entry(1, 5, datetime(2010, 1, 1), title='feed one')

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


with_sort = pytest.mark.parametrize('sort', ['relevant', 'recent'])


@rename_argument('reader', 'reader_without_and_with_entries')
@with_sort
@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 2, 0])
def test_update_search_feeds_change_after_enable(reader, sort, chunk_size):
    reader._search.storage.chunk_size = chunk_size
    reader.enable_search()
    reader.update_search()

    try:
        reader.delete_feed('1')
    except FeedNotFoundError:
        pass

    parser = Parser()
    reader._parser = parser

    parser.feed(1, datetime(2010, 1, 2))
    parser.entry(1, 2, datetime(2010, 1, 2), title='feed one changed')
    parser.entry(1, 6, datetime(2010, 1, 2), title='feed one new')
    parser.feed(2, datetime(2010, 1, 1))
    parser.entry(2, 1, datetime(2010, 1, 1), title='feed two')
    parser.entry(2, 2, datetime(2010, 1, 1), title='feed two')
    parser.entry(2, 3, datetime(2010, 1, 1), title='feed two')

    reader.add_feed('1')
    reader.add_feed('2')
    reader.update_feeds()

    reader.update_search()

    assert {(e.id, e.feed_url, e.title) for e in reader.get_entries()} == {
        (e.id, e.feed_url, e.metadata['.title'].value)
        for e in reader.search_entries('feed', sort=sort)
    }

    # no title, shouldn't come up in search
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.update_feeds()
    reader.get_entry(entry)

    # TODO: Should this be in test_search.py?
    # Other implementations may update the index as soon as an entry is updated,
    # and have a noop update_search().

    assert (entry.id, entry.feed_url) not in {
        (e.id, e.feed_url) for e in reader.search_entries('feed', sort=sort)
    }


UPDATE_TRIGGERS_DATA = {
    "no entry": [
        (lambda r: None, None),
    ],
    "after insert on entries": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
    ],
    "after delete on entries": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: (
                r.delete_feed('1'),
                r._parser.entries[1].pop(1),
                r.add_feed('1'),
            ),
            None,
        ),
    ],
    "after update on entries: title": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 2), title='entry new'),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 3), title=None),
            ['.feed.title'],
        ),
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 4), title='another'),
            ['.title', '.feed.title'],
        ),
    ],
    "after update on entries: summary": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 2), summary='old'),
            ['.title', '.feed.title', '.summary'],
        ),
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 3), summary='new'),
            ['.title', '.feed.title', '.summary'],
        ),
    ],
    "after update on entries: content": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: r._parser.entry(
                1, 1, datetime(2010, 1, 2), content=[Content('old')]
            ),
            ['.title', '.feed.title', '.content[0].value'],
        ),
        (
            lambda r: r._parser.entry(
                1, 1, datetime(2010, 1, 3), content=[Content('new')]
            ),
            ['.title', '.feed.title', '.content[0].value'],
        ),
        (
            lambda r: r._parser.entry(
                1,
                1,
                datetime(2010, 1, 4),
                content=[Content('new'), Content('another one')],
            ),
            ['.title', '.feed.title', '.content[0].value', '.content[1].value'],
        ),
        (
            lambda r: r._parser.entry(
                1, 1, datetime(2010, 1, 5), content=[Content('another one')]
            ),
            ['.title', '.feed.title', '.content[0].value'],
        ),
    ],
    "after update on feeds: title": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: (
                r._parser.feed(1, datetime(2010, 1, 2), title='new'),
                r._parser.entry(1, 1, datetime(2010, 1, 2)),
            ),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: (
                r._parser.feed(1, datetime(2010, 1, 3), title=None),
                r._parser.entry(1, 1, datetime(2010, 1, 3)),
            ),
            ['.title'],
        ),
        (
            lambda r: (
                r._parser.feed(1, datetime(2010, 1, 4), title='another'),
                r._parser.entry(1, 1, datetime(2010, 1, 4)),
            ),
            ['.title', '.feed.title'],
        ),
    ],
    "after update on feeds: user_title": [
        (
            lambda r: r._parser.entry(1, 1, datetime(2010, 1, 1)),
            ['.title', '.feed.title'],
        ),
        (
            lambda r: (
                r.set_feed_user_title('1', 'user'),
                r._parser.entry(1, 1, datetime(2010, 1, 2)),
            ),
            ['.title', '.feed.user_title'],
        ),
        (
            lambda r: (
                r.set_feed_user_title('1', None),
                r._parser.entry(1, 1, datetime(2010, 1, 3)),
            ),
            ['.title', '.feed.title'],
        ),
    ],
}


@pytest.mark.parametrize(
    'data', list(UPDATE_TRIGGERS_DATA.values()), ids=list(UPDATE_TRIGGERS_DATA)
)
def test_update_triggers(reader, data):
    """update_search() should update the search index
    if the indexed fields change.

    """
    reader._parser = parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader.enable_search()

    for i, (do_stuff, paths) in enumerate(data):
        do_stuff(reader)
        reader.update_feeds()
        reader.update_search()

        entry_data = {
            (e.feed_url, e.id): {p: eval(f"e{p}", dict(e=e, p=p)) for p in paths}
            for e in reader.get_entries()
        }

        result_data = {
            (r.feed_url, r.id): {
                p: hl.value for p, hl in {**r.metadata, **r.content}.items()
            }
            for r in reader.search_entries('entry OR feed')
        }

        assert entry_data == result_data, f"change {i}"


@pytest.mark.parametrize('set_user_title', [False, True])
def test_update_triggers_no_change(db_path, make_reader, monkeypatch, set_user_title):
    """update_search() should *not* update the search index
    if anything else except the indexed fields changes.

    """
    from reader._search import Search

    strip_html_called = 0

    class MySearch(Search):
        @staticmethod
        def strip_html(*args, **kwargs):
            nonlocal strip_html_called
            strip_html_called += 1
            return Search.strip_html(*args, **kwargs)

    # TODO: remove monkeypatching when make_reader() gets a search_cls argument
    monkeypatch.setattr('reader.core.Search', MySearch)

    reader = make_reader(db_path)
    reader._parser = parser = Parser()

    reader._parser = parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1), title='feed')
    entry = parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        title='entry',
        summary='summary',
        content=[Content('content')],
    )

    reader.add_feed(feed.url)
    reader.update_feeds()
    if set_user_title:
        reader.set_feed_user_title(feed, 'user title')

    reader.enable_search()
    reader.update_search()

    assert strip_html_called > 0
    strip_html_called = 0

    (old_result,) = reader.search_entries('entry OR feed')

    feed = parser.feed(
        1, datetime(2010, 1, 2), title='feed', link='link', author='author'
    )

    """
    entry = parser.entry(
        1, 1, datetime(2010, 1, 2),
        title='entry',
        summary='summary',
        content=[Content('content')],
        link='link', author='author',
        published=datetime(2010, 1, 2),
        enclosures=[Enclosure('enclosure')],
    )
    """
    # NOTE: As of 1.4, updating entries normally (above) uses INSERT OR REPLACE.
    # REPLACE == DELETE + INSERT (https://www.sqlite.org/lang_conflict.html),
    # so updating the entry normally *will not* fire the ON UPDATE trigger,
    # but the ON DELETE and ON INSERT ones (basically, the ON UPDATE trigger
    # never fires at the moment).
    #
    # Meanwhile, we do a (more intrusive/brittle) manual update:
    with reader._search.db as db:
        db.execute(
            """
            UPDATE entries
            SET (
                title,
                link,
                updated,
                author,
                published,
                summary,
                content,
                enclosures
            ) = (
                'entry',
                'http://www.example.com/entries/1',
                '2010-01-02 00:00:00',
                'author',
                '2010-01-02 00:00:00',
                'summary',
                '[{"value": "content", "type": null, "language": null}]',
                '[{"href": "enclosure", "type": null, "length": null}]'
            )
            WHERE (id, feed) = ('1, 1', '1');
            """
        )
    # TODO: Change this test when updating entries uses UPDATE instead of INSERT OR REPLACE

    reader.mark_entry_as_read(entry)
    reader.mark_entry_as_important(entry)

    reader.update_feeds()
    if set_user_title:
        reader.set_feed_user_title(feed, 'user title')

    reader.update_search()

    (new_result,) = reader.search_entries('entry OR feed')

    assert old_result == new_result
    assert strip_html_called == 0


@rename_argument('reader', 'reader_without_and_with_entries')
def test_update_search_fails_if_not_enabled(reader):
    with pytest.raises(SearchNotEnabledError) as excinfo:
        reader.update_search()
    assert excinfo.value.__cause__ is None
    assert excinfo.value.message


@rename_argument('reader', 'reader_without_and_with_entries')
@with_sort
def test_search_entries_fails_if_not_enabled(reader, sort):
    with pytest.raises(SearchNotEnabledError) as excinfo:
        list(reader.search_entries('one', sort=sort))
    assert excinfo.value.__cause__ is None
    assert excinfo.value.message


@rename_argument('reader', 'reader_without_and_with_entries')
def test_search_entry_counts_fails_if_not_enabled(reader):
    with pytest.raises(SearchNotEnabledError) as excinfo:
        list(reader.search_entry_counts('one'))
    assert excinfo.value.__cause__ is None
    assert excinfo.value.message


@with_sort
def test_search_entries_basic(reader, sort):
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
        # The emoji is to catch a bug in the json_extract() SQLite function.
        # As of reader 1.4 we're not using it anymore, and the workaround
        # was removed; we keep the emoji in case of regressions.
        # Bug: https://bugs.python.org/issue38749
        # Workaround and more details: https://github.com/lemon24/reader/blob/d4363f683fc18ca12f597809ceca4e7dbd0a303a/src/reader/_sqlite_utils.py#L332
        content=[Content('three 🤩 content')],
    )

    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()

    assert list(reader.search_entries('one')) == []

    reader.update_search()

    search = lambda *a, **kw: reader.search_entries(*a, sort=sort, **kw)
    search_counts = lambda *a, **kw: reader.search_entry_counts(*a, **kw)

    # TODO: the asserts below look parametrizable

    assert list(search('zero')) == []
    assert search_counts('zero') == EntrySearchCounts(0, 0, 0, 0)
    assert list(search('one')) == [
        EntrySearchResult(
            feed.url,
            one.id,
            {
                '.title': HighlightedString(one.title, (slice(0, 3),)),
                '.feed.title': HighlightedString(feed.title),
            },
        )
    ]
    assert search_counts('one') == EntrySearchCounts(1, 0, 0, 0)
    assert list(search('two')) == [
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
    assert list(search('three')) == [
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

    feed_two = parser.feed(2, datetime(2010, 1, 2))
    feed_two_entry = parser.entry(2, 1, datetime(2010, 1, 2), title=None)
    feed_three = parser.feed(3, datetime(2010, 1, 1), title=None)
    feed_three_entry = parser.entry(3, 1, datetime(2010, 1, 1), title='entry summary')

    reader.add_feed(feed_two.url)
    reader.add_feed(feed_three)
    reader.set_feed_user_title(feed_two, 'a summary of things')

    reader.update_feeds()
    feed_two_entry = reader.get_entry((feed_two.url, feed_two_entry.id))

    reader.update_search()

    # We can't use a set here because the dicts in EntrySearchResult aren't hashable.
    assert {(e.feed_url, e.id): e for e in search('summary')} == {
        (e.feed_url, e.id): e
        for e in [
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
    }
    assert search_counts('summary') == EntrySearchCounts(3, 0, 0, 0)


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


@pytest.mark.parametrize(
    'chunk_size',
    [
        # the default
        Storage.chunk_size,
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
    """Entry title beats feed title beats entry content/summary."""

    # TODO: may need fixing once we finish tuning the weights (it should fail)

    reader._search.storage.chunk_size = chunk_size

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


def test_search_entries_order_content(reader):
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        summary='word word',
        content=[
            Content('word'),
            Content('does not match'),
            Content('word word word word'),
            Content('word word word'),
        ],
    )

    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    # there should be exactly one result
    (rv,) = reader.search_entries('word')
    assert list(rv.content) == [
        '.content[2].value',
        '.content[3].value',
        '.summary',
        '.content[0].value',
    ]


def test_search_entries_order_content_recent(reader):
    """When sort='recent' is used, the .content of any individual result
    should still be sorted by relevance.

    """
    parser = Parser()
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        title='word',
        content=[Content('word word'), Content('word'), Content('word word word')],
    )
    two = parser.entry(1, 2, datetime(2010, 1, 2), summary='word')

    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    # sanity check, one is more relevant
    assert [e.id for e in reader.search_entries('word')] == ['1, 1', '1, 2']

    results = list(reader.search_entries('word', sort='recent'))
    # two is first because of updated
    assert [e.id for e in results] == ['1, 2', '1, 1']
    # but within 1, the content keys are sorted by relevance;
    assert list(results[1].content) == [
        '.content[2].value',
        '.content[0].value',
        '.content[1].value',
    ]


# END order tests


def test_search_entries_sort_error(reader):
    reader.enable_search()
    with pytest.raises(ValueError):
        set(reader.search_entries('one', sort='bad sort'))


# BEGIN concurrency tests


def test_update_search_entry_changed_during_strip_html(
    db_path, make_reader, monkeypatch
):
    """Test the entry can't remain out of sync if it changes
    during reader.update_search() in a strip_html() call.

    https://github.com/lemon24/reader/issues/175#issuecomment-652489019

    """
    # This is a very intrusive test, maybe we should move it somewhere else.

    reader = make_reader(db_path)
    parser = reader._parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1), title='one')
    parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader.enable_search()
    reader.update_search()

    feed = parser.feed(1, datetime(2010, 1, 2), title='two')
    parser.entry(1, 1, datetime(2010, 1, 2), title='two')
    reader.update_feed(feed.url)

    in_strip_html = threading.Event()
    can_return_from_strip_html = threading.Event()

    def target():
        # can't use fixture because it would run close() in a different thread
        from reader import make_reader
        from reader._search import Search

        # strip_html() may or may not be used a SQLite user-defined function,
        # hence the whole subclassing thing
        class MySearch(Search):
            @staticmethod
            def strip_html(*args, **kwargs):
                in_strip_html.set()
                can_return_from_strip_html.wait()
                return Search.strip_html(*args, **kwargs)

        # TODO: remove monkeypatching when make_reader() gets a search_cls argument
        monkeypatch.setattr('reader.core.Search', MySearch)

        reader = make_reader(db_path)
        try:
            reader.update_search()
        finally:
            reader.close()

    thread = threading.Thread(target=target)
    thread.start()

    in_strip_html.wait()

    try:
        feed = parser.feed(1, datetime(2010, 1, 3), title='three')
        parser.entry(1, 1, datetime(2010, 1, 3), title='three')
        reader._storage.db.execute("PRAGMA busy_timeout = 0;")
        reader.update_feed(feed.url)
        expected_title = 'three'
    except StorageError:
        expected_title = 'two'
    finally:
        can_return_from_strip_html.set()
        thread.join()

    reader.update_search()

    (entry,) = reader.get_entries()
    (result,) = reader.search_entries('one OR two OR three')
    assert entry.title == result.metadata['.title'].value == expected_title


def test_update_search_entry_changed_between_insert_loops(
    db_path, make_reader, monkeypatch
):
    """Test the entry can't be added twice to the search index if it changes
    during reader.update_search() between two insert loops.

    The scenario is:

    * entry has to_update set
    * _delete_from_search removes it from search
    * loop 1 of _insert_into_search finds entry and inserts it into search,
      clears to_update
    * entry has to_update set (if to_update is set because the feed changed,
      last_updated does not change; even if it did, it doesn't matter,
      since the transaction only spans a single loop)
    * loop 2 of _insert_into_search finds entry and inserts it into search
      again, clears to_update
    * loop 3 of _insert_into_search doesn't find any entry, returns

    https://github.com/lemon24/reader/issues/175#issuecomment-654213853

    """
    # This is a very intrusive test, maybe we should move it somewhere else.

    reader = make_reader(db_path)
    reader.enable_search()

    parser = reader._parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1), summary='one')
    reader.add_feed(feed.url)
    reader.update_feeds()

    in_insert_chunk = threading.Event()
    can_return_from_insert_chunk = threading.Event()

    def target():
        # can't use fixture because it would run close() in a different thread
        from reader import make_reader

        reader = make_reader(db_path)
        original_insert_chunk = reader._search._insert_into_search_one_chunk

        loop = 0

        def insert_chunk(*args, **kwargs):
            nonlocal loop
            if loop == 1:
                in_insert_chunk.set()
                can_return_from_insert_chunk.wait()
            loop += 1
            return original_insert_chunk(*args, **kwargs)

        reader._search._insert_into_search_one_chunk = insert_chunk

        try:
            reader.update_search()
        finally:
            reader.close()

    thread = threading.Thread(target=target)
    thread.start()

    in_insert_chunk.wait()

    try:
        feed = parser.feed(1, datetime(2010, 1, 2))
        parser.entry(1, 1, datetime(2010, 1, 2), summary='two')
        reader.update_feed(feed.url)
    finally:
        can_return_from_insert_chunk.set()
        thread.join()

    (result,) = reader.search_entries('entry')
    assert len(result.content) == 1

    ((rowcount,),) = reader._search.db.execute("select count(*) from entries_search;")
    assert rowcount == 1


def test_update_search_concurrent_calls(db_path, make_reader, monkeypatch):
    """Test concurrent calls to reader.update_search() don't interfere
    with one another.

    https://github.com/lemon24/reader/issues/175#issuecomment-652489019

    """
    # This is a very intrusive test, maybe we should move it somewhere else.

    reader = make_reader(db_path)
    parser = reader._parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1), title='feed')
    parser.entry(
        1,
        1,
        datetime(2010, 1, 1),
        title='entry',
        summary='summary',
        content=[Content('content')],
    )
    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.enable_search()

    barrier = threading.Barrier(2)

    def target():
        # can't use fixture because it would run close() in a different thread
        from reader import make_reader
        from reader._search import Search

        class MySearch(Search):
            @staticmethod
            def strip_html(*args, **kwargs):
                barrier.wait()
                return Search.strip_html(*args, **kwargs)

        # TODO: remove monkeypatching when make_reader() gets a search_cls argument
        monkeypatch.setattr('reader.core.Search', MySearch)

        reader = make_reader(db_path)
        try:
            reader.update_search()
        finally:
            reader.close()

    threads = [threading.Thread(target=target) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    (result,) = reader.search_entries('entry')
    assert len(result.content) == 2

    ((rowcount,),) = reader._search.db.execute("select count(*) from entries_search;")
    assert rowcount == 2


# END concurrency tests
