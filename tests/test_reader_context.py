import functools
from threading import Thread
from unittest.mock import patch

import pytest
from fakeparser import Parser
from utils import rename_argument

from reader import SearchError
from reader import StorageError


# paths for which different connections see the same database
PATHS_SHARED = ['db.sqlite']
# paths for which different connections see a private database
PATHS_PRIVATE = [':memory:']
PATHS_ALL = PATHS_SHARED + PATHS_PRIVATE


@pytest.fixture
def make_reader(make_reader, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def make_reader_with_data(path):
        reader = make_reader(path)
        reader._parser = parser = Parser()
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


def check_with_usage(reader):
    with reader as result:
        assert result is reader
        # no exception
        check_usage(reader)


def check_usage_error(reader, message_fragment):
    # TODO: Maybe parametrize with all the methods.

    with pytest.raises(StorageError) as excinfo:
        reader.set_tag((), 'tag')
    assert message_fragment in excinfo.value.message

    with pytest.raises(StorageError):
        list(reader.get_entries())
    assert message_fragment in excinfo.value.message

    with pytest.raises(SearchError):
        list(reader.search_entries('entry'))
    assert message_fragment in excinfo.value.message


def run_in_thread(fn):
    @functools.wraps(fn)
    @pytest.mark.filterwarnings('error::pytest.PytestUnhandledThreadExceptionWarning')
    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        thread.join()

    return wrapper


@rename_argument('reader', 'reader_all')
def test_main_thread_close(reader):
    with patch.object(reader, '_storage', wraps=reader._storage):
        # no exception
        reader.close()
        reader._storage.close.assert_called()

    check_usage_error(reader, 'operation on closed database')

    # calling close() again is a no-op
    reader.close()


@rename_argument('reader', 'reader_all')
def test_main_thread_direct_usage(reader):
    check_usage(reader)
    reader.close()
    check_usage_error(reader, 'operation on closed database')

    # calling close() is a no-op
    reader.close()


@rename_argument('reader', 'reader_all')
def test_main_thread_with_usage(reader):
    check_with_usage(reader)
    check_usage_error(reader, 'operation on closed database')

    # calling close() is a no-op
    reader.close()


@run_in_thread
@rename_argument('reader', 'reader_all')
def test_other_thread_close(reader):
    with pytest.raises(StorageError) as excinfo:
        reader.close()
    assert 'context manager' in str(excinfo.value)


@run_in_thread
@rename_argument('reader', 'reader_all')
def test_other_thread_direct_usage(reader):
    check_usage_error(reader, 'context manager')


@run_in_thread
@rename_argument('reader', 'reader_shared')
def test_other_thread_with_usage_shared(reader):
    check_with_usage(reader)
    check_usage_error(reader, 'operation on closed database')


@run_in_thread
@rename_argument('reader', 'reader_private')
def test_other_thread_with_usage_private(reader):
    with reader:
        check_usage_error(reader, 'private database')
