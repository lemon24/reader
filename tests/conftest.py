import sqlite3
import sys
from contextlib import closing
from functools import wraps

import py.path
import pytest
from utils import reload_module

from reader import make_reader as original_make_reader
from reader._storage import Storage


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_collection_modifyitems(config, items):  # pragma: no cover
    apply_runslow(config, items)
    apply_flaky_pypy_sqlite3(items)


def apply_runslow(config, items):  # pragma: no cover
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


def apply_flaky_pypy_sqlite3(items):  # pragma: no cover
    # getting intermittent sqlite3 errors on pypy;
    # https://github.com/lemon24/reader/issues/199#issuecomment-716475686

    if sys.implementation.name != 'pypy':
        return

    def rerun_filter(err, *args):
        return issubclass(err[0], sqlite3.InterfaceError)

    sqlite3_flaky = pytest.mark.flaky(rerun_filter=rerun_filter, max_runs=10)
    for item in items:
        item.add_marker(sqlite3_flaky)


@pytest.fixture
def make_reader(request):
    @wraps(original_make_reader)
    def make_reader(*args, **kwargs):
        reader = original_make_reader(*args, **kwargs)
        request.addfinalizer(reader.close)
        return reader

    return make_reader


@pytest.fixture
def reader():
    with closing(original_make_reader(':memory:')) as reader:
        yield reader


@pytest.fixture
def storage():
    with closing(Storage(':memory:')) as storage:
        yield storage


def call_update_feeds(reader, _):
    reader.update_feeds()


def call_update_feeds_workers(reader, _):
    reader.update_feeds(workers=2)


def call_update_feeds_iter(reader, _):
    for _ in reader.update_feeds_iter():
        pass


def call_update_feeds_iter_workers(reader, _):
    for _ in reader.update_feeds_iter(workers=2):
        pass


def call_update_feed(reader, url):
    reader.update_feed(url)


@pytest.fixture(
    params=[
        call_update_feeds,
        pytest.param(call_update_feeds_workers, marks=pytest.mark.slow),
        call_update_feeds_iter,
        pytest.param(call_update_feeds_iter_workers, marks=pytest.mark.slow),
        call_update_feed,
    ]
)
def call_update_method(request):
    return request.param


def feed_arg_as_str(feed):
    return feed.url


def feed_arg_as_feed(feed):
    return feed


@pytest.fixture(params=[feed_arg_as_str, feed_arg_as_feed])
def feed_arg(request):
    return request.param


def entry_arg_as_tuple(entry):
    return entry.feed.url, entry.id


def entry_arg_as_entry(entry):
    return entry


@pytest.fixture(params=[entry_arg_as_tuple, entry_arg_as_entry])
def entry_arg(request):
    return request.param


@pytest.fixture
def db_path(tmpdir):
    return str(tmpdir.join('db.sqlite'))


@pytest.fixture
def data_dir():
    return py.path.local(__file__).dirpath().join('data')
