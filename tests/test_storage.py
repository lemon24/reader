import sqlite3
import threading
from datetime import datetime
from unittest.mock import ANY
from unittest.mock import MagicMock

import pytest
from utils import rename_argument

import reader._sqlite_utils
from reader import EntryNotFoundError
from reader import FeedNotFoundError
from reader import InvalidSearchQueryError
from reader import MetadataNotFoundError
from reader import StorageError
from reader._sqlite_utils import DBError
from reader._sqlite_utils import require_version
from reader._storage import Storage
from reader._types import EntryData
from reader._types import EntryFilterOptions
from reader._types import EntryForUpdate
from reader._types import EntryUpdateIntent
from reader._types import FeedData
from reader._types import FeedUpdateIntent


def test_storage_errors_connect(tmpdir):
    # try to open a directory
    with pytest.raises(StorageError) as excinfo:
        Storage(str(tmpdir))
    assert isinstance(excinfo.value.__cause__, sqlite3.OperationalError)
    assert 'while opening' in excinfo.value.message


@pytest.mark.parametrize('db_error_cls', reader._sqlite_utils.db_errors)
def test_db_errors(db_path, db_error_cls):
    """..._sqlite_utils.DBError subclasses should be wrapped in StorageError."""

    class MyStorage(Storage):
        @staticmethod
        def setup_db(*args, **kwargs):
            raise db_error_cls("whatever")

    with pytest.raises(StorageError) as excinfo:
        MyStorage(db_path)
    assert excinfo.value.__cause__ is None
    assert 'whatever' in excinfo.value.message


def test_path(db_path):
    storage = Storage(db_path)
    assert storage.path == db_path


def test_timeout(db_path):
    """Storage.__init__ must pass timeout= to connect."""

    expected_timeout = None

    class MyStorage(Storage):
        @classmethod
        def connect(cls, *args, **kwargs):
            nonlocal expected_timeout
            expected_timeout = kwargs.get('timeout')
            return super().connect(*args, **kwargs)

    MyStorage(db_path, 19)

    assert expected_timeout == 19


def test_close():
    storage = Storage(':memory:')

    storage.db.execute('values (1)')

    storage.close()
    # no-op a second time
    storage.close()

    with pytest.raises(sqlite3.ProgrammingError):
        storage.db.execute('values (1)')


def test_close_error():
    class Connection(sqlite3.Connection):
        pass

    def execute(*args):
        raise sqlite3.ProgrammingError('unexpected error')

    storage = Storage(':memory:', factory=Connection)
    storage.db.execute = execute

    # should not be StorageError, because it's likely a bug
    with pytest.raises(sqlite3.ProgrammingError):
        storage.close()


def init(storage, _, __):
    Storage(storage.path, timeout=0)


def add_feed(storage, feed, __):
    storage.add_feed(feed.url + '_', datetime(2010, 1, 1))


def remove_feed(storage, feed, __):
    storage.remove_feed(feed.url)


def get_feeds(storage, _, __):
    list(storage.get_feeds())


def get_feeds_for_update(storage, _, __):
    list(storage.get_feeds_for_update())


def get_entries_for_update(storage, feed, entry):
    list(storage.get_entries_for_update([(feed.url, entry.id)]))


def set_feed_user_title(storage, feed, __):
    storage.set_feed_user_title(feed.url, 'title')


def set_feed_updates_enabled(storage, feed, __):
    storage.set_feed_updates_enabled(feed.url, 1)


def mark_as_stale(storage, feed, __):
    storage.mark_as_stale(feed.url)


def mark_as_read_unread(storage, feed, entry):
    storage.mark_as_read_unread(feed.url, entry.id, 1)


def update_feed(storage, feed, entry):
    storage.update_feed(FeedUpdateIntent(feed.url, entry.updated, feed=feed))


def update_feed_last_updated(storage, feed, entry):
    storage.update_feed(FeedUpdateIntent(feed.url, entry.updated))


def add_or_update_entry(storage, feed, entry):
    storage.add_or_update_entry(
        EntryUpdateIntent(entry, entry.updated, datetime(2010, 1, 1), 0)
    )


def add_or_update_entries(storage, feed, entry):
    storage.add_or_update_entries(
        [EntryUpdateIntent(entry, entry.updated, datetime(2010, 1, 1), 0)]
    )


def get_entries_chunk_size_0(storage, _, __):
    list(storage.get_entries_page(chunk_size=0, now=datetime(2010, 1, 1)))


def get_entries_chunk_size_1(storage, _, __):
    list(storage.get_entries_page(chunk_size=1, now=datetime(2010, 1, 1)))


def iter_feed_metadata(storage, feed, __):
    list(storage.iter_feed_metadata(feed.url))


def set_feed_metadata(storage, feed, __):
    storage.set_feed_metadata(feed.url, 'key', 'value')


def delete_feed_metadata(storage, feed, __):
    storage.delete_feed_metadata(feed.url, 'key')


def add_feed_tag(storage, feed, __):
    storage.add_feed_tag(feed.url, 'tag')


def remove_feed_tag(storage, feed, __):
    storage.remove_feed_tag(feed.url, 'tag')


def get_feed_tags(storage, feed, __):
    list(storage.get_feed_tags(feed.url))


def get_feed_counts(storage, _, __):
    storage.get_feed_counts()


def get_entry_counts(storage, _, __):
    storage.get_entry_counts(),


@pytest.mark.slow
@pytest.mark.parametrize(
    'do_stuff',
    [
        init,
        add_feed,
        remove_feed,
        get_feeds,
        get_feeds_for_update,
        get_entries_for_update,
        set_feed_user_title,
        set_feed_updates_enabled,
        mark_as_stale,
        mark_as_read_unread,
        update_feed,
        update_feed_last_updated,
        add_or_update_entry,
        add_or_update_entries,
        get_entries_chunk_size_0,
        get_entries_chunk_size_1,
        iter_feed_metadata,
        set_feed_metadata,
        delete_feed_metadata,
        add_feed_tag,
        remove_feed_tag,
        get_feed_tags,
        get_feed_counts,
        get_entry_counts,
    ],
)
def test_errors_locked(db_path, do_stuff):
    """All methods should raise StorageError when the database is locked."""

    check_errors_locked(db_path, None, do_stuff, StorageError)


def check_errors_locked(db_path, pre_stuff, do_stuff, exc_type):
    """Actual implementation of test_errors_locked, so it can be reused."""

    # WAL provides more concurrency; some things won't to block with it enabled.
    storage = Storage(db_path, wal_enabled=False)
    storage.db.execute("PRAGMA busy_timeout = 0;")

    feed = FeedData('one')
    entry = EntryData('one', 'entry', datetime(2010, 1, 2))
    storage.add_feed(feed.url, datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(entry, entry.updated, datetime(2010, 1, 1), 0)
    )

    in_transaction = threading.Event()
    can_return_from_transaction = threading.Event()

    def target():
        storage = Storage(db_path, wal_enabled=False)
        storage.db.isolation_level = None
        storage.db.execute("BEGIN EXCLUSIVE;")
        in_transaction.set()
        can_return_from_transaction.wait()
        storage.db.execute("ROLLBACK;")

    if pre_stuff:
        pre_stuff(storage, feed, entry)

    thread = threading.Thread(target=target)
    thread.start()

    in_transaction.wait()

    try:
        with pytest.raises(exc_type) as excinfo:
            do_stuff(storage, feed, entry)
        assert 'locked' in str(excinfo.value.__cause__)
    finally:
        can_return_from_transaction.set()
        thread.join()


def iter_get_feeds(storage):
    return storage.get_feeds_page(chunk_size=1)


def iter_get_feeds_for_update(storage):
    return storage.get_feeds_for_update()


def iter_pagination_chunk_size_0(storage):
    return storage.get_entries_page(chunk_size=0, now=datetime(2010, 1, 1))


def iter_pagination_chunk_size_1(storage):
    return storage.get_entries_page(chunk_size=1, now=datetime(2010, 1, 1))


def iter_pagination_chunk_size_2(storage):
    return storage.get_entries_page(chunk_size=2, now=datetime(2010, 1, 1))


def iter_pagination_chunk_size_3(storage):
    return storage.get_entries_page(chunk_size=3, now=datetime(2010, 1, 1))


def iter_iter_feed_metadata(storage):
    return storage.iter_feed_metadata_page('two', chunk_size=1)


def iter_get_feed_tags(storage):
    return storage.get_feed_tags('two')


@pytest.mark.slow
@pytest.mark.parametrize(
    'iter_stuff',
    [
        iter_get_feeds,
        iter_get_feeds_for_update,
        pytest.param(
            iter_pagination_chunk_size_0,
            marks=pytest.mark.xfail(raises=StorageError, strict=True),
        ),
        iter_pagination_chunk_size_1,
        iter_pagination_chunk_size_2,
        iter_pagination_chunk_size_3,
        iter_iter_feed_metadata,
        iter_get_feed_tags,
    ],
)
def test_iter_locked(db_path, iter_stuff):
    """Methods that return an iterable shouldn't block the underlying storage
    if the iterable is not consumed."""
    check_iter_locked(db_path, None, iter_stuff)


def check_iter_locked(db_path, pre_stuff, iter_stuff):
    """Actual implementation of test_errors_locked, so it can be reused."""

    # WAL provides more concurrency; some things won't to block with it enabled.
    storage = Storage(db_path, wal_enabled=False)

    feed = FeedData('one')
    entry = EntryData('one', 'entry', datetime(2010, 1, 1), title='entry')
    storage.add_feed(feed.url, datetime(2010, 1, 2))
    storage.add_or_update_entry(
        EntryUpdateIntent(entry, entry.updated, datetime(2010, 1, 1), 0)
    )
    storage.add_feed('two', datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            entry._replace(feed_url='two'), entry.updated, datetime(2010, 1, 1), 0
        )
    )
    storage.set_feed_metadata('two', '1', 1)
    storage.set_feed_metadata('two', '2', 2)
    storage.add_feed_tag('two', '1')
    storage.add_feed_tag('two', '2')

    if pre_stuff:
        pre_stuff(storage)

    rv = iter_stuff(storage)
    next(rv)

    # shouldn't raise an exception
    storage = Storage(db_path, timeout=0, wal_enabled=False)
    storage.mark_as_read_unread(feed.url, entry.id, 1)
    storage = Storage(db_path, timeout=0)
    storage.mark_as_read_unread(feed.url, entry.id, 0)


def test_update_feed_last_updated_not_found(db_path):
    storage = Storage(db_path)
    with pytest.raises(FeedNotFoundError):
        storage.update_feed(FeedUpdateIntent('inexistent-feed', datetime(2010, 1, 2)))


@pytest.mark.parametrize(
    'entry_count',
    [
        # We assume the query uses 2 parameters per entry (feed URL and entry ID).
        #
        # variable_number defaults to 999 when compiling SQLite from sources
        int(999 / 2) + 1,
        # variable_number defaults to 250000 in Ubuntu 18.04 -provided SQLite
        pytest.param(
            int(250000 / 2) + 1,
            marks=(
                pytest.mark.slow,
                # Fails on PyPy3 7.3.1 *only when running with --cov* with:
                #   _sqlite3.InterfaceError: Error binding parameter :feed_url - probably unsupported type.
                # but not CPython or PyPy3 7.2.0 (on macOS, at least).
                pytest.mark.xfail(
                    "sys.implementation.name == 'pypy' "
                    "and sys.pypy_version_info[:2] == (7, 3)",
                ),
            ),
        ),
    ],
)
def test_get_entries_for_update_param_limit(entry_count):
    """get_entries_for_update() should work even if the number of query
    parameters goes over the variable_number SQLite run-time limit.

    https://github.com/lemon24/reader/issues/109

    """
    storage = Storage(':memory:')

    # shouldn't raise an exception
    list(
        storage.get_entries_for_update(
            ('feed', 'entry-{}'.format(i)) for i in range(entry_count)
        )
    )
    list(
        storage.get_entries_for_update(
            ('feed', 'entry-{}'.format(i)) for i in range(entry_count)
        )
    )


class StorageNoGetEntriesForUpdateFallback(Storage):
    def _get_entries_for_update_n_queries(self, _):
        assert False, "shouldn't get called"


class StorageAlwaysGetEntriesForUpdateFallback(Storage):
    def _get_entries_for_update_one_query(self, _):
        raise sqlite3.OperationalError("too many SQL variables")


@pytest.mark.parametrize(
    'storage_cls',
    [StorageNoGetEntriesForUpdateFallback, StorageAlwaysGetEntriesForUpdateFallback],
)
def test_get_entries_for_update(storage_cls):
    storage = storage_cls(':memory:')
    storage.add_feed('feed', datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'one', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 1),
            0,
        )
    )

    assert list(storage.get_entries_for_update([('feed', 'one'), ('feed', 'two')])) == [
        EntryForUpdate(datetime(2010, 1, 1)),
        None,
    ]


@pytest.fixture
def storage():
    return Storage(':memory:')


def test_entry_remains_read_after_update(storage_with_two_entries):
    storage = storage_with_two_entries
    storage.mark_as_read_unread('feed', 'one', True)

    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'one', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            0,
        )
    )

    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(read=True)
        )
    } == {'one'}


@pytest.fixture
def storage_with_two_entries(storage):
    storage.add_feed('feed', datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'one', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            0,
        )
    )
    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'two', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            1,
        )
    )
    return storage


@rename_argument('storage', 'storage_with_two_entries')
def test_important_unimportant_by_default(storage):
    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(important=False)
        )
    } == {'one', 'two'}


@rename_argument('storage', 'storage_with_two_entries')
def test_important_get_entries(storage):
    storage.mark_as_important_unimportant('feed', 'one', True)

    assert {e.id for e in storage.get_entries(now=datetime(2010, 1, 1))} == {
        'one',
        'two',
    }
    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(important=None)
        )
    } == {'one', 'two'}
    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(important=True)
        )
    } == {'one'}
    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(important=False)
        )
    } == {'two'}


@rename_argument('storage', 'storage_with_two_entries')
def test_important_entry_remains_important_after_update(storage):
    storage.mark_as_important_unimportant('feed', 'one', True)

    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'one', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            0,
        )
    )

    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(important=True)
        )
    } == {'one'}


@rename_argument('storage', 'storage_with_two_entries')
def test_important_entry_important(storage):
    storage.mark_as_important_unimportant('feed', 'one', True)

    assert {e.id: e.important for e in storage.get_entries(datetime(2010, 1, 1))} == {
        'one': True,
        'two': False,
    }


@rename_argument('storage', 'storage_with_two_entries')
def test_important_mark_as_unimportant(storage):
    storage.mark_as_important_unimportant('feed', 'one', True)
    storage.mark_as_important_unimportant('feed', 'one', False)

    assert {
        e.id
        for e in storage.get_entries(
            datetime(2010, 1, 1), EntryFilterOptions(important=True)
        )
    } == set()


def test_important_mark_entry_not_found(storage):
    with pytest.raises(EntryNotFoundError):
        storage.mark_as_important_unimportant('feed', 'one', True)


def test_minimum_sqlite_version(db_path, monkeypatch):
    mock = MagicMock(wraps=require_version, side_effect=DBError)
    monkeypatch.setattr('reader._sqlite_utils.require_version', mock)

    with pytest.raises(StorageError):
        Storage(db_path)

    mock.assert_called_with(ANY, (3, 15))
