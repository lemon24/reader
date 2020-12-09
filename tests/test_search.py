from datetime import datetime
from unittest.mock import ANY
from unittest.mock import MagicMock

import bs4
import pytest
from fakeparser import Parser

from reader import Content
from reader import HighlightedString
from reader import InvalidSearchQueryError
from reader import SearchError
from reader import StorageError
from reader._search import Search
from reader._search import strip_html
from reader._sqlite_utils import DBError
from reader._sqlite_utils import require_version


def test_bs4_import_error(storage, monkeypatch):
    search = Search(storage)
    search.enable()
    monkeypatch.setattr('reader._search.bs4', None)
    monkeypatch.setattr('reader._search.bs4_import_error', ImportError('reason'))

    with pytest.raises(SearchError) as excinfo:
        search.update()
    assert 'search dependencies' in str(excinfo.value.message)
    assert isinstance(excinfo.value.__cause__, ImportError)


STRIP_HTML_DATA = [(i, i) for i in [None, 10, 11.2, b'aabb', b'aa<br>bb']] + [
    ('aabb', 'aabb'),
    ('aa<br>bb', 'aa\nbb'),
    ('aa<p>bb', 'aa\nbb'),
    ('<script>ss</script>bb', 'bb'),
    ('<noscript>ss</noscript>bb', 'bb'),
    ('<style>ss</style>bb', 'bb'),
    ('<title>ss</title>bb', 'bb'),
    ('aa<script>ss</script>bb', 'aa\nbb'),
    ('aa<noscript>ss</noscript>bb', 'aa\nbb'),
    ('aa<style>ss</style>bb', 'aa\nbb'),
    ('aa<title>tt</title>bb', 'aa\nbb'),
    ('<head><script>ss</script></head>bb', 'bb'),
    ('<head><noscript>ss</noscript>bb', 'bb'),
    ('<head><style>ss</style></head>bb', 'bb'),
    ('<head><title>tt</title>bb', 'bb'),
    ('<head>aa<script>ss</script>bb', 'aa\nbb'),
    ('<head>aa<noscript>ss</noscript></head>bb', 'aa\nbb'),
    ('<head>aa<style>ss</style>bb', 'aa\nbb'),
    ('<head>aa<title>tt</title></head>bb', 'aa\nbb'),
    (
        """
        <head>
            aa
            <title>tt</title>
            <p>bb
            <script>ss</script>
            <b>cc
            <noscript>nn</noscript>
            <style>ss</style>
            dd
        </head>
        ee
        """,
        'aa\nbb\ncc\ndd\nee',
    ),
]


@pytest.mark.parametrize('input, expected_output', STRIP_HTML_DATA)
# We test all bs4 parsers, since we don't know/care what the user has installed.
@pytest.mark.parametrize(
    'features',
    [
        None,
        # lxml fails to build on pypy, see the comments in setup.py for details.
        pytest.param(
            'lxml', marks=pytest.mark.skipif("sys.implementation.name == 'pypy'")
        ),
        'html.parser',
        'html5lib',
    ],
)
def test_strip_html(input, expected_output, features):
    output = strip_html(input, features)
    if isinstance(output, str):
        output = '\n'.join(output.split())

    # Special-case different <noscript> handling by html5lib.
    # https://www.crummy.com/software/BeautifulSoup/bs4/doc/#differences-between-parsers
    is_html5lib = any(
        [
            features == 'html5lib',
            features is None
            and 'html5lib' in type(bs4.BeautifulSoup('').builder).__module__,
        ]
    )
    if is_html5lib and isinstance(input, str) and '<noscript>' in input:
        assert '<noscript>' not in output
        return

    assert output == expected_output


def enable_search(storage, _, __):
    Search(storage).enable()


def disable_search(storage, _, __):
    Search(storage).disable()


def is_search_enabled(storage, _, __):
    Search(storage).is_enabled()


def update_search(storage, _, __):
    Search(storage).update()


def search_entries_chunk_size_0(storage, _, __):
    list(
        Search(storage).search_entries_page('entry', datetime(2010, 1, 1), chunk_size=0)
    )


def search_entries_chunk_size_1(storage, _, __):
    list(
        Search(storage).search_entries_page('entry', datetime(2010, 1, 1), chunk_size=1)
    )


def search_entry_counts(storage, _, __):
    Search(storage).search_entry_counts('entry')


def search_entry_last(storage, feed, entry):
    Search(storage).search_entry_last('entry', (feed.url, entry.id))


@pytest.mark.slow
@pytest.mark.parametrize(
    'pre_stuff, do_stuff',
    [
        (None, enable_search),
        (None, disable_search),
        (None, is_search_enabled),
        (enable_search, update_search),
        (enable_search, search_entries_chunk_size_0),
        (enable_search, search_entries_chunk_size_1),
        (enable_search, search_entry_counts),
        (enable_search, search_entry_last),
    ],
)
def test_errors_locked(db_path, pre_stuff, do_stuff):
    """All methods should raise SearchError when the database is locked."""

    from test_storage import check_errors_locked

    check_errors_locked(db_path, pre_stuff, do_stuff, SearchError)


def enable_and_update_search(storage):
    search = Search(storage)
    search.enable()
    search.update()


def iter_search_entries_chunk_size_0(storage):
    return Search(storage).search_entries_page(
        'entry', datetime(2010, 1, 1), chunk_size=0
    )


def iter_search_entries_chunk_size_1(storage):
    return Search(storage).search_entries_page(
        'entry', datetime(2010, 1, 1), chunk_size=1
    )


def iter_search_entries_chunk_size_2(storage):
    return Search(storage).search_entries_page(
        'entry', datetime(2010, 1, 1), chunk_size=2
    )


def iter_search_entries_chunk_size_3(storage):
    return Search(storage).search_entries_page(
        'entry', datetime(2010, 1, 1), chunk_size=3
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    'iter_stuff',
    [
        pytest.param(
            iter_search_entries_chunk_size_0,
            marks=pytest.mark.xfail(raises=StorageError, strict=True),
        ),
        iter_search_entries_chunk_size_1,
        iter_search_entries_chunk_size_2,
        iter_search_entries_chunk_size_3,
    ],
)
def test_iter_locked(db_path, iter_stuff):
    """Methods that return an iterable shouldn't block the underlying storage
    if the iterable is not consumed.

    """
    from test_storage import check_iter_locked

    check_iter_locked(db_path, enable_and_update_search, iter_stuff)


class ActuallyOK(Exception):
    pass


def call_search_entries(search, query):
    try:
        next(search.search_entries(query, datetime(2010, 1, 1)))
    except StopIteration:
        raise ActuallyOK


def call_search_entry_counts(search, query):
    search.search_entry_counts(query)
    raise ActuallyOK


@pytest.mark.parametrize(
    'query, exc_type',
    [
        ('\x00', InvalidSearchQueryError),
        ('"', InvalidSearchQueryError),
        # For some reason, on CPython * works when the filtering is inside
        # the CTE (it didn't when it was outside), hence the ActuallyOK.
        # On PyPy 7.3.1 we still get a InvalidSearchQueryError.
        # We're fine as long as we don't get another exception.
        ('*', (ActuallyOK, InvalidSearchQueryError)),
        ('O:', InvalidSearchQueryError),
        ('*p', InvalidSearchQueryError),
    ],
)
@pytest.mark.parametrize(
    'call_method',
    [
        call_search_entries,
        call_search_entry_counts,
    ],
)
def test_invalid_search_query_error(storage, query, exc_type, call_method):
    # We're not testing this in test_reader_search.py because
    # the invalid query strings are search-provider-dependent.
    search = Search(storage)
    search.enable()
    with pytest.raises(exc_type) as excinfo:
        call_method(search, query)
    if isinstance(exc_type, tuple) and ActuallyOK in exc_type:
        return
    assert excinfo.value.message
    assert excinfo.value.__cause__ is None


def test_minimum_sqlite_version(storage, monkeypatch):
    mock = MagicMock(wraps=require_version, side_effect=DBError('version'))
    monkeypatch.setattr('reader._search.require_version', mock)

    search = Search(storage)
    search.enable()

    with pytest.raises(SearchError) as excinfo:
        search.update()
    assert 'version' in excinfo.value.message

    mock.assert_called_with(ANY, (3, 18))


# TODO: test FTS5 column names
