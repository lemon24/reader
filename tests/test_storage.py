from datetime import datetime
import threading

import pytest

from reader.storage import Storage
from reader.exceptions import StorageError
import reader.db

from reader import Feed, Entry


def test_storage_errors_open(tmpdir):
    # try to open a directory
    with pytest.raises(StorageError):
        Storage(str(tmpdir))


@pytest.mark.parametrize('db_error_cls', reader.db.db_errors)
def test_db_errors(monkeypatch, db_path, db_error_cls):
    """reader.db.DBError subclasses should be wrapped in StorageError."""

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

def get_entry_for_update(storage, feed, entry):
    storage.get_entry_for_update(feed.url, entry.id)

def set_feed_user_title(storage, feed, __):
    storage.set_feed_user_title(feed.url, 'title')

def mark_as_stale(storage, feed, __):
    storage.mark_as_stale(feed.url)

def mark_as_read_unread(storage, feed, entry):
    storage.mark_as_read_unread(feed.url, entry.id, 1)

def update_feed(storage, feed, entry):
    storage.update_feed(feed.url, feed, None, None, entry.updated)

def add_or_update_entry(storage, feed, entry):
    storage.add_or_update_entry(feed.url, entry, entry.updated, entry.updated)

def get_entries_chunk_size_0(storage, _, __):
    list(storage.get_entries('all', None, None, chunk_size=0))

def get_entries_chunk_size_1(storage, _, __):
    list(storage.get_entries('all', None, None, chunk_size=1))

@pytest.mark.slow
@pytest.mark.parametrize('do_stuff', [
    init,
    add_feed,
    remove_feed,
    get_feeds,
    get_feeds_for_update,
    get_entry_for_update,
    set_feed_user_title,
    mark_as_stale,
    mark_as_read_unread,
    update_feed,
    add_or_update_entry,
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
    storage.add_or_update_entry(feed.url, entry, entry.updated, entry.updated)

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
    return storage.get_entries('all', None, None, chunk_size=0)

def iter_get_entries_chunk_size_1(storage):
    return storage.get_entries('all', None, None, chunk_size=1)

def iter_get_entries_chunk_size_2(storage):
    return storage.get_entries('all', None, None, chunk_size=2)

def iter_get_entries_chunk_size_3(storage):
    return storage.get_entries('all', None, None, chunk_size=3)

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
    storage.add_or_update_entry(feed.url, entry, entry.updated, entry.updated)
    storage.add_feed('two')
    storage.add_or_update_entry('two', entry, entry.updated, entry.updated)

    rv = iter_stuff(storage)
    next(rv)

    # shouldn't raise an exception
    storage = Storage(db_path, timeout=0)
    storage.mark_as_read_unread(feed.url, entry.id, 1)
    storage = Storage(db_path, timeout=0)
    storage.mark_as_read_unread(feed.url, entry.id, 0)

