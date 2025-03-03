import os
import sqlite3
import sys
import threading
from unittest.mock import ANY
from unittest.mock import MagicMock

import pytest

import reader._storage._sqlite_utils
from reader import EntryNotFoundError
from reader import FeedNotFoundError
from reader import InvalidSearchQueryError
from reader import StorageError
from reader._storage import Storage
from reader._storage._sqlite_utils import DBError
from reader._storage._sqlite_utils import HeavyMigration
from reader._storage._sqlite_utils import require_version
from reader._types import EntryData
from reader._types import EntryFilter
from reader._types import EntryForUpdate
from reader._types import EntryUpdateIntent
from reader._types import FeedData
from reader._types import FeedToUpdate
from reader._types import FeedUpdateIntent
from utils import Blocking
from utils import rename_argument
from utils import utc_datetime as datetime


def test_storage_errors_connect(tmp_path):
    # try to open a directory
    with pytest.raises(StorageError) as excinfo:
        Storage(str(tmp_path))
    assert isinstance(excinfo.value.__cause__, sqlite3.OperationalError)
    assert 'while opening' in excinfo.value.message


@pytest.mark.parametrize('db_error_cls', reader._storage._sqlite_utils.db_errors)
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


def test_database_error_open_invalid(db_path):
    with open(db_path, 'w') as f:
        f.write('not a database')

    with pytest.raises(StorageError) as excinfo:
        Storage(db_path)

    assert isinstance(excinfo.value.__cause__, sqlite3.DatabaseError)


@pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"),
    reason="overwriting doesn't work on Windows",
)
def test_database_error_overwritten(db_path):
    storage = Storage(db_path)

    for suffix in ['', '-wal', '-shm']:
        with open(db_path + suffix, 'w') as f:
            f.write('not a database')

    # TODO: should we test all methods here (like test_errors_locked)?

    with pytest.raises(StorageError) as excinfo:
        storage.add_feed('one', datetime(2010, 1, 1))

    assert isinstance(excinfo.value.__cause__, sqlite3.DatabaseError)

    with pytest.raises(StorageError) as excinfo:
        # hopefully this closes the file, even if we get DatabaseError
        storage.close()


@pytest.mark.parametrize('exc_type', [sqlite3.DatabaseError, sqlite3.ProgrammingError])
def test_database_error_other(exc_type):
    # for some reason, this test doesn't cover both branches of
    # "if type(e) is sqlite3.DatabaseError:" in wrap_exceptions

    exc = exc_type('whatever')

    class MyStorage(Storage):
        @staticmethod
        def setup_db(*args, **kwargs):
            raise exc

    with pytest.raises(sqlite3.Error) as excinfo:
        MyStorage(':memory:')
    assert excinfo.value is exc


def test_database_error_permissions(db_path):
    for suffix in ['', '-wal', '-shm']:
        path = db_path + suffix
        with open(path, 'w') as f:
            pass
        os.chmod(db_path + suffix, 0)

    with pytest.raises(StorageError) as excinfo:
        Storage(db_path)


def test_timeout(db_path, monkeypatch):
    """Storage.__init__ must pass timeout= to connect."""

    original_connect = sqlite3.connect

    def connect(*args, **kwargs):
        connect.expected_timeout = kwargs.get('timeout')
        return original_connect(*args, **kwargs)

    monkeypatch.setattr('sqlite3.connect', connect)
    Storage(db_path, 19)

    assert connect.expected_timeout == 19


def test_close(monkeypatch):
    close_called = False

    class Connection(sqlite3.Connection):
        def close(self):
            super().close()
            nonlocal close_called
            close_called = True

    monkeypatch.setattr('reader._storage._base.CONNECTION_CLS', Connection)

    storage = Storage(':memory:')
    storage.get_db().execute('values (1)')

    storage.close()
    assert close_called

    # no-op a second time
    storage.close()


def test_close_error(monkeypatch):
    class Connection(sqlite3.Connection):
        pass

    def execute(*args):
        raise sqlite3.ProgrammingError('unexpected error')

    monkeypatch.setattr('reader._storage._base.CONNECTION_CLS', Connection)

    storage = Storage(':memory:')
    storage.get_db().execute = execute

    # should not be StorageError, because it's likely a bug
    with pytest.raises(sqlite3.ProgrammingError):
        storage.close()


def init(storage, _, __):
    Storage(storage.factory.path, timeout=0)


def add_feed(storage, feed, __):
    storage.add_feed(feed.url + '_', datetime(2010, 1, 1))


def delete_feed(storage, feed, __):
    storage.delete_feed(feed.url)


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


def set_feed_stale(storage, feed, __):
    storage.set_feed_stale(feed.url, True)


def set_entry_read(storage, feed, entry):
    storage.set_entry_read(entry.resource_id, 1, None)


def set_entry_important(storage, feed, entry):
    storage.set_entry_important(entry.resource_id, 1, None)


def get_entry_recent_sort(storage, feed, entry):
    storage.get_entry_recent_sort(entry.resource_id)


def set_entry_recent_sort(storage, feed, entry):
    storage.set_entry_recent_sort(entry.resource_id, datetime(2010, 1, 1))


def update_feed(storage, feed, entry):
    storage.update_feed(
        FeedUpdateIntent(
            feed.url,
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            FeedToUpdate(feed, entry.updated),
        )
    )


def add_or_update_entry(storage, feed, entry):
    storage.add_or_update_entry(
        EntryUpdateIntent(
            entry,
            entry.updated,
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
        )
    )


def add_or_update_entries(storage, feed, entry):
    storage.add_or_update_entries(
        [
            EntryUpdateIntent(
                entry,
                entry.updated,
                datetime(2010, 1, 1),
                datetime(2010, 1, 1),
                datetime(2010, 1, 1),
            )
        ]
    )


def add_entry(storage, feed, entry):
    storage.add_entry(
        EntryUpdateIntent(
            entry,
            entry.updated,
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
        )
    )


def delete_entries(storage, feed, entry):
    storage.delete_entries([entry.resource_id])


def get_entries(storage, _, __):
    list(storage.get_entries())


def get_tags(storage, feed, __):
    list(storage.get_tags((feed.url,)))


def set_tag(storage, feed, __):
    storage.set_tag((feed.url,), 'key', 'value')


def delete_tag(storage, feed, __):
    storage.delete_tag((feed.url,), 'key')


def get_feed_counts(storage, _, __):
    storage.get_feed_counts()


def get_entry_counts(storage, _, __):
    storage.get_entry_counts(now=datetime(2010, 1, 1)),


@pytest.mark.slow
@pytest.mark.parametrize(
    'do_stuff',
    [
        init,
        add_feed,
        delete_feed,
        get_feeds,
        get_feeds_for_update,
        get_entries_for_update,
        set_feed_user_title,
        set_feed_updates_enabled,
        set_feed_stale,
        set_entry_read,
        set_entry_important,
        get_entry_recent_sort,
        set_entry_recent_sort,
        update_feed,
        add_or_update_entry,
        add_or_update_entries,
        add_entry,
        delete_entries,
        get_entries,
        get_tags,
        set_tag,
        delete_tag,
        get_feed_counts,
        get_entry_counts,
    ],
)
def test_errors_locked(db_path, do_stuff):
    """All methods should raise StorageError when the database is locked."""

    check_errors_locked(db_path, None, do_stuff, StorageError)


def check_errors_locked(db_path, pre_stuff, do_stuff, exc_type):
    """Actual implementation of test_errors_locked, so it can be reused."""

    storage = Storage(db_path)
    # WAL provides more concurrency; some things won't to block with it enabled.
    storage.close()
    storage.get_db().execute("PRAGMA journal_mode = DELETE;").close()

    storage.get_db().execute("PRAGMA busy_timeout = 0;")

    feed = FeedData('one')
    entry = EntryData('one', 'entry', datetime(2010, 1, 2))
    storage.add_feed(feed.url, datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            entry,
            entry.updated,
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            0,
            0,
        )
    )

    block = Blocking()

    def target():
        storage = Storage(db_path)
        db = storage.get_db()
        db.isolation_level = None
        db.execute("BEGIN EXCLUSIVE;")
        block()
        db.execute("ROLLBACK;")

    if pre_stuff:
        pre_stuff(storage)

    thread = threading.Thread(target=target)
    thread.start()

    with block:
        with pytest.raises(exc_type) as excinfo:
            do_stuff(storage, feed, entry)
        assert 'locked' in str(excinfo.value.__cause__)

    thread.join()


def iter_get_feeds(storage):
    return storage.get_feeds()


def iter_get_feeds_for_update(storage):
    return storage.get_feeds_for_update()


def iter_get_entries(storage):
    return storage.get_entries()


def iter_get_tags(storage):
    return storage.get_tags(('two',))


@pytest.mark.slow
@pytest.mark.parametrize(
    'iter_stuff',
    [
        iter_get_feeds,
        iter_get_feeds_for_update,
        iter_get_entries,
        iter_get_tags,
    ],
)
def test_iter_locked(db_path, iter_stuff, chunk_size):
    """Methods that return an iterable shouldn't block the underlying storage
    if the iterable is not consumed."""
    check_iter_locked(db_path, None, iter_stuff, chunk_size)


def check_iter_locked(db_path, pre_stuff, iter_stuff, chunk_size):
    """Actual implementation of test_errors_locked, so it can be reused."""

    storage = Storage(db_path)
    # WAL provides more concurrency; some things won't to block with it enabled.
    storage.close()
    storage.get_db().execute("PRAGMA journal_mode = DELETE;").close()

    feed = FeedData('one')
    entry = EntryData('one', 'entry', datetime(2010, 1, 1), title='entry')
    storage.add_feed(feed.url, datetime(2010, 1, 2))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            entry,
            entry.updated,
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            0,
            0,
        )
    )
    storage.add_feed('two', datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            entry._replace(feed_url='two'),
            entry.updated,
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            datetime(2010, 1, 1),
            0,
            0,
        )
    )
    storage.set_tag(('two',), '1', 1)
    storage.set_tag(('two',), '2', 2)

    if pre_stuff:
        pre_stuff(storage)

    rv = iter_stuff(storage)
    next(rv)

    # shouldn't raise an exception
    storage = Storage(db_path, timeout=0)
    storage.set_entry_read((feed.url, entry.id), 1, None)
    storage = Storage(db_path, timeout=0)
    storage.set_entry_read((feed.url, entry.id), 0, None)


@pytest.fixture
def storage():
    return Storage(':memory:')


@pytest.fixture
def storage_with_two_entries(storage):
    storage.add_feed('feed', datetime(2010, 1, 1))
    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'one', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            0,
            0,
        )
    )
    storage.add_or_update_entry(
        EntryUpdateIntent(
            EntryData('feed', 'two', datetime(2010, 1, 1)),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            datetime(2010, 1, 2),
            1,
            0,
        )
    )
    return storage


@rename_argument('storage', 'storage_with_two_entries')
def test_important_unimportant_by_default(storage):
    assert {e.id for e in storage.get_entries(EntryFilter(important='nottrue'))} == {
        'one',
        'two',
    }


@rename_argument('storage', 'storage_with_two_entries')
def test_important_get_entries(storage):
    storage.set_entry_important(('feed', 'one'), True, datetime(2010, 1, 2))

    assert {e.id for e in storage.get_entries()} == {
        'one',
        'two',
    }
    assert {e.id for e in storage.get_entries(EntryFilter(important='any'))} == {
        'one',
        'two',
    }
    assert {e.id for e in storage.get_entries(EntryFilter(important='istrue'))} == {
        'one'
    }
    assert {e.id for e in storage.get_entries(EntryFilter(important='nottrue'))} == {
        'two'
    }


@rename_argument('storage', 'storage_with_two_entries')
def test_important_entry_important(storage):
    storage.set_entry_important(('feed', 'one'), True, None)

    assert {e.id: e.important for e in storage.get_entries()} == {
        'one': True,
        'two': None,
    }


@rename_argument('storage', 'storage_with_two_entries')
def test_important_mark_as_unimportant(storage):
    storage.set_entry_important(('feed', 'one'), True, None)
    storage.set_entry_important(('feed', 'one'), False, None)

    assert {e.id for e in storage.get_entries(EntryFilter(important='istrue'))} == set()


def test_important_mark_entry_not_found(storage):
    with pytest.raises(EntryNotFoundError):
        storage.set_entry_important(('feed', 'one'), True, None)


def test_minimum_sqlite_version(db_path, monkeypatch):
    mock = MagicMock(wraps=require_version, side_effect=DBError)
    monkeypatch.setattr('reader._storage._sqlite_utils.require_version', mock)

    with pytest.raises(StorageError):
        Storage(db_path)

    mock.assert_called_with(ANY, (3, 18))


MIGRATION_MINIMUM_VERSION = 29


def test_migration_minimum_version(db_path, request):
    """Sanity check: older versions *do* cause an error."""

    storage = Storage(db_path)
    request.addfinalizer(storage.close)

    assert HeavyMigration.get_version(storage.get_db()) >= MIGRATION_MINIMUM_VERSION

    HeavyMigration.set_version(storage.get_db(), MIGRATION_MINIMUM_VERSION - 1)

    with pytest.raises(StorageError) as excinfo:
        Storage(db_path)

    assert 'no migration' in str(excinfo.value)
    assert '://reader.readthedocs.io/en/latest/changelog.html' in str(excinfo.value)


@rename_argument('storage', 'storage_with_two_entries')
def test_get_set_recent_sort(storage):
    assert storage.get_entry_recent_sort(('feed', 'one')) == datetime(2010, 1, 2)

    storage.set_entry_recent_sort(('feed', 'one'), datetime(2010, 1, 3))
    assert storage.get_entry_recent_sort(('feed', 'one')) == datetime(2010, 1, 3)

    with pytest.raises(EntryNotFoundError) as excinfo:
        storage.get_entry_recent_sort(('feed', 'xxx'))
    assert excinfo.value.resource_id == ('feed', 'xxx')

    with pytest.raises(EntryNotFoundError) as excinfo:
        storage.set_entry_recent_sort(('feed', 'xxx'), datetime(2010, 1, 1))
    assert excinfo.value.resource_id == ('feed', 'xxx')


def test_application_id(storage):
    id = storage.factory().execute('pragma application_id').fetchone()[0]
    assert id == int.from_bytes(b'read', 'big')
