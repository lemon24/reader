"""
Test reader lifecycle – creation, usage, closing.

TODO: Should arguably be done against Storage/LocalConnectionFactory instead,
but until we have a different implementation it's simpler this way
(and most of the tests should apply to all Storages anyway).

"""

import asyncio
import concurrent.futures
import functools
import sqlite3
import sys
import threading
import time

import pytest

from reader import SearchError
from reader import StorageError
from utils import rename_argument


# paths for which different connections see the same database
PATHS_SHARED = ['db.sqlite']
# paths for which different connections see a private database
PATHS_PRIVATE = [':memory:']
PATHS_ALL = PATHS_SHARED + PATHS_PRIVATE


class MyConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = False
        self.statements = []

    def close(self):
        super().close()
        self.closed = True

    def execute(self, sql, *args, **kwargs):
        rv = super().execute(sql, *args, **kwargs)
        self.statements.append(sql)
        return rv


@pytest.fixture
def make_reader(make_reader, parser, monkeypatch, tmp_path):
    monkeypatch.setattr('reader._storage._base.CONNECTION_CLS', MyConnection)

    monkeypatch.chdir(tmp_path)

    def make_reader_with_data(path):
        reader = make_reader(path)
        feed = parser.feed(1)
        parser.entry(1, 1, title='entry')
        reader.add_feed(feed)
        reader.update_feeds()
        reader.update_search()
        return reader

    return make_reader_with_data


@pytest.fixture(params=PATHS_ALL)
def reader_all(make_reader, request):
    return make_reader(request.param)


@pytest.fixture(params=PATHS_SHARED)
def reader_shared(make_reader, request):
    return make_reader(request.param)


@pytest.fixture(params=PATHS_PRIVATE)
def reader_private(make_reader, request):
    return make_reader(request.param)


def check_usage(reader):
    reader.set_tag((), 'tag')
    assert len(list(reader.get_entries())) == 1
    assert len(list(reader.search_entries('entry'))) == 1


def check_usage_error(reader, message_fragment):
    # TODO: Maybe parametrize with all the methods.

    with pytest.raises(StorageError) as excinfo:
        reader.set_tag((), 'tag')
    assert message_fragment in excinfo.value.message

    with pytest.raises(StorageError) as excinfo:
        list(reader.get_entries())
    assert message_fragment in excinfo.value.message

    with pytest.raises(SearchError) as excinfo:
        list(reader.search_entries('entry'))
    assert message_fragment in excinfo.value.message


def run_in_thread(fn):
    @functools.wraps(fn)
    @pytest.mark.filterwarnings('error::pytest.PytestUnhandledThreadExceptionWarning')
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        thread.join()

    return wrapper


def check_direct_usage(reader):
    db = reader._storage.get_db()

    check_usage(reader)
    assert not db.closed

    # no exception
    reader.close()
    assert db.closed

    # close() can be called repeatedly
    reader.close()


@rename_argument('reader', 'reader_shared')
def test_main_thread_direct_usage_shared(reader):
    check_direct_usage(reader)

    # the reader can be reused
    check_usage(reader)


@rename_argument('reader', 'reader_private')
def test_main_thread_direct_usage_private(reader):
    check_direct_usage(reader)

    # the reader *cannot* be reused
    check_usage_error(reader, "cannot reuse")


@run_in_thread
@rename_argument('reader', 'reader_shared')
def test_other_thread_direct_usage_shared(reader):
    check_direct_usage(reader)

    # the reader can be reused
    check_usage(reader)


@run_in_thread
@rename_argument('reader', 'reader_private')
def test_other_thread_direct_usage_private(reader):
    check_usage_error(reader, 'cannot use')


def check_with_usage(reader):
    with reader as result:
        assert result is reader
        # no exception
        check_usage(reader)
        db = reader._storage.get_db()

    assert db.closed

    # the reader can be reused after with
    with reader as result:
        check_usage(reader)

    # close() can be called after with block
    reader.close()

    # the reader can be reused after close()
    with reader as result:
        check_usage(reader)


@rename_argument('reader', 'reader_shared')
def test_main_thread_with_usage_shared(reader):
    check_with_usage(reader)


@rename_argument('reader', 'reader_private')
def test_main_thread_with_usage_private(reader):
    with reader as result:
        assert result is reader
        # no exception
        check_usage(reader)
        db = reader._storage.get_db()

    # close() is *not* called
    assert not db.closed

    # the reader can be reused after with
    with reader as result:
        check_usage(reader)

    reader.close()

    # close() can be called repeatedly
    reader.close()

    # the reader *cannot* be reused after close()
    check_usage_error(reader, "cannot reuse")


@run_in_thread
@rename_argument('reader', 'reader_shared')
def test_other_thread_with_usage_shared(reader):
    check_with_usage(reader)


@run_in_thread
@rename_argument('reader', 'reader_private')
def test_other_thread_with_usage_private(reader):
    with pytest.raises(StorageError) as excinfo:
        with reader:
            pass
    assert 'cannot use' in excinfo.value.message


@rename_argument('reader', 'reader_shared')
def test_asyncio_shared(reader):
    async def main():
        loop = asyncio.get_event_loop()
        executor_coro = loop.run_in_executor(None, check_usage, reader)
        check_usage(reader)
        await executor_coro

    asyncio.run(main())


@rename_argument('reader', 'reader_private')
def test_asyncio_private(reader):
    async def main():
        loop = asyncio.get_event_loop()
        executor_coro = loop.run_in_executor(
            None, check_usage_error, reader, 'cannot use'
        )
        check_usage(reader)
        await executor_coro

    asyncio.run(main())


def count_optimize_calls(statements):
    statements = (s.lower().strip() for s in statements)
    return sum(1 for s in statements if s == 'pragma optimize;')


@rename_argument('reader', 'reader_shared')
def test_thread_pool_executor_shared(reader):
    executor = concurrent.futures.ThreadPoolExecutor(2)
    future = executor.submit(check_usage, reader)
    future.result()
    executor.shutdown()


@pytest.mark.slow
@rename_argument('reader', 'reader_shared')
def test_optimize_direct_usage(reader):
    reader._storage.get_db().statements = statements = []

    for _ in range(1000):
        reader.set_tag((), 'tag')
    assert 1 < count_optimize_calls(statements) < 7

    statements.clear()

    for _ in range(1000):
        reader.set_tag((), 'tag')
    assert 0 < count_optimize_calls(statements) < 3


@rename_argument('reader', 'reader_shared')
def test_optimize_close(reader):
    reader._storage.get_db().statements = statements = []

    reader.close()

    assert count_optimize_calls(statements) == 1


@rename_argument('reader', 'reader_shared')
def test_optimize_with(reader):
    reader._storage.get_db().statements = statements = []

    with reader:
        pass

    assert count_optimize_calls(statements) == 1


@pytest.mark.skipif("sys.implementation.name != 'cpython'")
@pytest.mark.slow
@rename_argument('reader', 'reader_shared')
def test_optimize_thread_end(reader):
    statements = []

    def target():
        reader._storage.get_db().statements = statements

    threading.Thread(target=target).start()
    for _ in range(40):
        time.sleep(0.05)
        if count_optimize_calls(statements):
            break

    # must sleep; if we assign the thread to a variable to join() it,
    # the finalizer is called atexit instead, and this test fails ...

    assert count_optimize_calls(statements) == 1
