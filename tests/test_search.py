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
from reader._storage import Storage
from reader._storage._search import Search
from reader._storage._sqlite_utils import DBError
from reader._storage._sqlite_utils import require_version
from utils import utc_datetime as datetime


STRIP_HTML_DATA = [(i, i) for i in [None, 10, 11.2, b'aabb', b'aa<br>bb']] + [
    ('aabb', 'aabb'),
    ('aa<br>bb', 'aa\nbb'),
]


@pytest.mark.parametrize('input, expected_output', STRIP_HTML_DATA)
def test_strip_html(input, expected_output):
    output = Search.strip_html(input)
    if isinstance(output, str):
        output = '\n'.join(output.split())

    assert output == expected_output


def enable_search(storage, _, __):
    storage.search.enable()


def disable_search(storage, _, __):
    storage.search.disable()


def is_search_enabled(storage, _, __):
    storage.search.is_enabled()


def update_search(storage, _, __):
    storage.search.update()


def search_entries(storage, _, __):
    list(storage.search.search_entries('entry'))


def search_entry_counts(storage, _, __):
    storage.search.search_entry_counts('entry', now=datetime(2010, 1, 1))


def set_search(storage):
    storage.search = search = Search(storage)


def set_search_and_enable(storage):
    set_search(storage)
    storage.search.enable()


@pytest.mark.slow
@pytest.mark.parametrize(
    'pre_stuff, do_stuff',
    [
        (set_search, enable_search),
        (set_search, disable_search),
        pytest.param(
            set_search, is_search_enabled, marks=pytest.mark.xfail(strict=True)
        ),
        (set_search_and_enable, update_search),
        (set_search_and_enable, search_entries),
        (set_search_and_enable, search_entry_counts),
    ],
)
def test_errors_locked(db_path, pre_stuff, do_stuff):
    """All methods should raise SearchError when the database is locked."""

    from test_storage import check_errors_locked

    check_errors_locked(db_path, pre_stuff, do_stuff, (SearchError, StorageError))


def set_search_and_update(storage):
    set_search_and_enable(storage)
    storage.search.update()


def iter_search_entries(storage):
    return storage.search.search_entries('entry')


@pytest.mark.slow
@pytest.mark.parametrize('iter_stuff', [iter_search_entries])
def test_iter_locked(db_path, iter_stuff, chunk_size):
    """Methods that return an iterable shouldn't block the underlying storage
    if the iterable is not consumed.

    """
    from test_storage import check_iter_locked

    check_iter_locked(db_path, set_search_and_update, iter_stuff, chunk_size)


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


# TODO: test FTS5 column names


def test_memory_storage_has_no_attached_database(storage):
    search = Search(storage)
    search.enable()
    db = storage.factory()

    databases = {r[1:3] for r in db.execute('pragma database_list')}
    assert databases == {('main', '')}

    search_schema = {r[0] for r in db.execute('select name from main.sqlite_master')}
    assert 'entries_search' in search_schema
    assert 'entries_search_sync_state' in search_schema

    search.disable()

    search_schema = {r[0] for r in db.execute('select name from main.sqlite_master')}
    assert 'entries_search' not in search_schema
    assert 'entries_search_sync_state' not in search_schema


def test_disk_storage_has_attached_database(db_path, request):
    storage = Storage(db_path)
    request.addfinalizer(storage.close)

    search = Search(storage)
    search.enable()
    db = storage.factory()

    databases = {r[1:3] for r in db.execute('pragma database_list')}
    assert databases == {('main', db_path), ('search', db_path + '.search')}

    main_schema = {r[0] for r in db.execute('select name from main.sqlite_master')}
    assert 'entries_search' not in main_schema
    assert 'entries_search_sync_state' not in main_schema

    search_schema = {r[0] for r in db.execute('select name from search.sqlite_master')}
    assert 'entries_search' in search_schema
    assert 'entries_search_sync_state' in search_schema

    search.disable()

    search_schema = {r[0] for r in db.execute('select name from main.sqlite_master')}
    assert 'entries_search' not in search_schema
    assert 'entries_search_sync_state' not in search_schema

    # check the VACUUM actually happened; may be brittle
    assert db.execute('pragma search.page_count').fetchone() == (1,)


def test_application_id(db_path, request):
    storage = Storage(db_path)
    request.addfinalizer(storage.close)
    search = Search(storage)
    id = storage.factory().execute('pragma search.application_id').fetchone()[0]
    assert id == int.from_bytes(b'reaD', 'big')
