from unittest.mock import ANY
from unittest.mock import MagicMock

import bs4
import pytest
from fakeparser import Parser
from utils import utc_datetime as datetime

from reader import Content
from reader import HighlightedString
from reader import InvalidSearchQueryError
from reader import SearchError
from reader import StorageError
from reader._search import Search
from reader._search import strip_html
from reader._sqlite_utils import DBError
from reader._sqlite_utils import require_version


STRIP_HTML_DATA = [(i, i) for i in [None, 10, 11.2, b'aabb', b'aa<br>bb']] + [
    ('aabb', 'aabb'),
    ('aa<br>bb', 'aa\nbb'),
]


@pytest.mark.parametrize('input, expected_output', STRIP_HTML_DATA)
def test_strip_html(input, expected_output):
    output = strip_html(input)
    if isinstance(output, str):
        output = '\n'.join(output.split())

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
    list(Search(storage).search_entries_page('entry', chunk_size=0))


def search_entries_chunk_size_1(storage, _, __):
    list(Search(storage).search_entries_page('entry', chunk_size=1))


def search_entry_counts(storage, _, __):
    Search(storage).search_entry_counts('entry', now=datetime(2010, 1, 1))


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
    return Search(storage).search_entries_page('entry', chunk_size=0)


def iter_search_entries_chunk_size_1(storage):
    return Search(storage).search_entries_page('entry', chunk_size=1)


def iter_search_entries_chunk_size_2(storage):
    return Search(storage).search_entries_page('entry', chunk_size=2)


def iter_search_entries_chunk_size_3(storage):
    return Search(storage).search_entries_page('entry', chunk_size=3)


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
        next(search.search_entries(query))
    except StopIteration:
        raise ActuallyOK


def call_search_entry_counts(search, query):
    search.search_entry_counts(query, datetime(2010, 1, 1))
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
    search = Search(storage)
    search.enable()

    mock = MagicMock(wraps=require_version, side_effect=DBError('version'))
    monkeypatch.setattr('reader._search.require_version', mock)

    with pytest.raises(SearchError) as excinfo:
        search.enable()
    assert 'version' in excinfo.value.message
    mock.assert_called_with(ANY, (3, 18))

    mock.reset_mock()

    with pytest.raises(SearchError) as excinfo:
        search.update()
    assert 'version' in excinfo.value.message
    mock.assert_called_with(ANY, (3, 18))


# TODO: test FTS5 column names
