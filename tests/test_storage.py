from datetime import datetime
import threading
import sqlite3

import pytest

from reader.core.storage import Storage
from reader.core.types import EntryForUpdate
from reader import StorageError
import reader.core.sqlite_utils

from reader import Feed, Entry, FeedNotFoundError


def test_storage_errors_open(tmpdir):
    # try to open a directory
    with pytest.raises(StorageError):
        Storage(str(tmpdir))


@pytest.mark.parametrize('db_error_cls', reader.core.sqlite_utils.db_errors)
def test_db_errors(monkeypatch, db_path, db_error_cls):
    """...sqlite_utils.DBError subclasses should be wrapped in StorageError."""
    def open_db(*args, **kwargs):
        raise db_error_cls("whatever")

    monkeypatch.setattr(Storage, 'open_db', staticmethod(open_db))

    with pytest.raises(StorageError):
        Storage(db_path)


def test_path(db_path):
    storage = Storage(db_path)
    assert storage.path == db_path


def test_timeout(monkeypatch, db_path):
    """Storage.__init__ must pass timeout= to open_db."""

    def open_db(*args, timeout=None):
        open_db.timeout = timeout

    monkeypatch.setattr(Storage, 'open_db', staticmethod(open_db))

    timeout = object()
    Storage(db_path, timeout)

    assert open_db.timeout is timeout


def init(storage, _, __):
    Storage(storage.path, timeout=0)

def add_feed(storage, feed, __):
    storage.add_feed(feed.url + '_')

def remove_feed(storage, feed, __):
    storage.remove_feed(feed.url)

def get_feeds(storage, _, __):
    list(storage.get_feeds())

def get_feeds_for_update(storage, _, __):
    list(storage.get_feeds_for_update())

def get_entries_for_update(storage, feed, entry):
    storage.get_entries_for_update([(feed.url, entry.id)])

def set_feed_user_title(storage, feed, __):
    storage.set_feed_user_title(feed.url, 'title')

def mark_as_stale(storage, feed, __):
    storage.mark_as_stale(feed.url)

def mark_as_read_unread(storage, feed, entry):
    storage.mark_as_read_unread(feed.url, entry.id, 1)

def update_feed(storage, feed, entry):
    storage.update_feed(feed.url, feed, None, None, entry.updated)

def update_feed_last_updated(storage, feed, entry):
    storage.update_feed(feed.url, None, None, None, entry.updated)

def add_or_update_entry(storage, feed, entry):
    storage.add_or_update_entry(feed.url, entry, entry.updated, None)

def add_or_update_entries(storage, feed, entry):
    storage.add_or_update_entries([(feed.url, entry, entry.updated, None)])

def get_entries_chunk_size_0(storage, _, __):
    list(storage.get_entries('all', None, None, chunk_size=0, now=datetime(2010, 1, 1)))

def get_entries_chunk_size_1(storage, _, __):
    list(storage.get_entries('all', None, None, chunk_size=1, now=datetime(2010, 1, 1)))

@pytest.mark.slow
@pytest.mark.parametrize('do_stuff', [
    init,
    add_feed,
    remove_feed,
    get_feeds,
    get_feeds_for_update,
    get_entries_for_update,
    set_feed_user_title,
    mark_as_stale,
    mark_as_read_unread,
    update_feed,
    update_feed_last_updated,
    add_or_update_entry,
    add_or_update_entries,
    get_entries_chunk_size_0,
    get_entries_chunk_size_1,
])
def test_errors_locked(db_path, do_stuff):
    """All methods should raise StorageError when the database is locked.

    """
    storage = Storage(db_path)
    storage.db.execute("PRAGMA busy_timeout = 0;")

    feed = Feed('one')
    entry = Entry('entry', datetime(2010, 1, 2))
    storage.add_feed(feed.url)
    storage.add_or_update_entry(feed.url, entry, entry.updated, None)

    in_transaction = threading.Event()
    can_return_from_transaction = threading.Event()

    def target():
        storage = Storage(db_path)
        storage.db.isolation_level = None
        storage.db.execute("BEGIN EXCLUSIVE;")
        in_transaction.set()
        can_return_from_transaction.wait()
        storage.db.execute("ROLLBACK;")

    thread = threading.Thread(target=target)
    thread.start()

    in_transaction.wait()

    try:
        with pytest.raises(StorageError) as excinfo:
            do_stuff(storage, feed, entry)
        assert 'locked' in str(excinfo.value.__cause__)
    finally:
        can_return_from_transaction.set()
        thread.join()


def iter_get_feeds(storage):
    return storage.get_feeds()

def iter_get_feeds_for_update(storage):
    return storage.get_feeds_for_update()

def iter_get_entries_chunk_size_0(storage):
    return storage.get_entries('all', None, None, chunk_size=0, now=datetime(2010, 1, 1))

def iter_get_entries_chunk_size_1(storage):
    return storage.get_entries('all', None, None, chunk_size=1, now=datetime(2010, 1, 1))

def iter_get_entries_chunk_size_2(storage):
    return storage.get_entries('all', None, None, chunk_size=2, now=datetime(2010, 1, 1))

def iter_get_entries_chunk_size_3(storage):
    return storage.get_entries('all', None, None, chunk_size=3, now=datetime(2010, 1, 1))

@pytest.mark.slow
@pytest.mark.parametrize('iter_stuff', [
    iter_get_feeds,
    iter_get_feeds_for_update,
    pytest.param(
        iter_get_entries_chunk_size_0,
        marks=pytest.mark.xfail(raises=StorageError, strict=True)),
    iter_get_entries_chunk_size_1,
    iter_get_entries_chunk_size_2,
    iter_get_entries_chunk_size_3,
])
def test_iter_locked(db_path, iter_stuff):
    """Methods that return an iterable shouldn't block the underlying storage
    if the iterable is not consumed.

    """
    storage = Storage(db_path)

    feed = Feed('one')
    entry = Entry('entry', datetime(2010, 1, 2))
    storage.add_feed(feed.url)
    storage.add_or_update_entry(feed.url, entry, entry.updated, None)
    storage.add_feed('two')
    storage.add_or_update_entry('two', entry, entry.updated, None)

    rv = iter_stuff(storage)
    next(rv)

    # shouldn't raise an exception
    storage = Storage(db_path, timeout=0)
    storage.mark_as_read_unread(feed.url, entry.id, 1)
    storage = Storage(db_path, timeout=0)
    storage.mark_as_read_unread(feed.url, entry.id, 0)


def test_update_feed_last_updated_not_found(db_path):
    storage = Storage(db_path)
    with pytest.raises(FeedNotFoundError):
        storage.update_feed('inexistent-feed', None, None, None, datetime(2010, 1, 2))


@pytest.mark.parametrize('entry_count', [
    # We assume the query uses 2 parameters per entry (feed URL and entry ID).

    # variable_number defaults to 999 when compiling SQLite from sources
    int(999 / 2) + 1,

    # variable_number defaults to 250000 in Ubuntu 18.04 -provided SQLite
    pytest.param(int(250000 / 2) + 1, marks=pytest.mark.slow),
])
def test_get_entries_for_update_param_limit(entry_count):
    """get_entries_for_update() should work even if the number of query
    parameters goes over the variable_number SQLite run-time limit.

    https://github.com/lemon24/reader/issues/109

    """
    storage = Storage(':memory:')

    # shouldn't raise an exception
    list(storage.get_entries_for_update(
        ('feed', 'entry-{}'.format(i))
        for i in range(entry_count)
    ))


class StorageNoGetEntriesForUpdateFallback(Storage):

    def _get_entries_for_update_n_queries(self, _):
        assert False, "shouldn't get called"

class StorageAlwaysGetEntriesForUpdateFallback(Storage):

    def _get_entries_for_update_one_query(self, _):
        raise sqlite3.OperationalError("too many SQL variables")

@pytest.mark.parametrize('storage_cls', [
    StorageNoGetEntriesForUpdateFallback,
    StorageAlwaysGetEntriesForUpdateFallback,
])
def test_get_entries_for_update(storage_cls):
    storage = storage_cls(':memory:')
    storage.add_feed('feed')
    storage.add_or_update_entry(
        'feed', Entry('one', datetime(2010, 1, 1),), datetime(2010, 1, 2), None)

    assert list(storage.get_entries_for_update([
        ('feed', 'one'),
        ('feed', 'two'),
    ])) == [
        EntryForUpdate(datetime(2010, 1, 1)),
        None,
    ]


