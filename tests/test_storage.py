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

    def open_db(*args):
        raise db_error_cls("whatever")

    monkeypatch.setattr(Storage, '_open_db', staticmethod(open_db))

    with pytest.raises(StorageError):
        Storage(db_path)


def test_path(db_path):
    storage = Storage(db_path)
    assert storage.path == db_path


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

def get_entries(storage, _, __):
    list(storage.get_entries('all', None, False))

def get_entries_chunk_size_zero(storage, _, __):
    list(storage.get_entries('all', None, False, chunk_size=0))

@pytest.mark.slow
@pytest.mark.parametrize('do_stuff', [
    # TODO: also test __init__; need to be able to pass connect(timeout=0)
    # for it, otherwise the test will take 5 seconds

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
    get_entries,
    get_entries_chunk_size_zero,

])
def test_errors_locked(db_path, do_stuff):
    """All methods should raise StorageError when the database is locked.

    """
    storage = Storage(db_path)
    storage.db.execute("PRAGMA busy_timeout = 0;")

    feed = Feed('one')
    entry = Entry('two_entry', datetime(2010, 1, 2))
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

