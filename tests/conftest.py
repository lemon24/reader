import os
import sqlite3
import sys
from contextlib import closing
from functools import wraps

import py.path
import pytest
import reader_methods
from utils import monkeypatch_tz
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


def pytest_runtest_setup(item):
    # lxml fails to build in various places,
    # see the comments in setup.cfg for details.
    for mark in item.iter_markers(name="requires_lxml"):
        no_lxml = [
            # currently, we have lxml wheels on all supported platforms;
            # last in bbe1deee5eee800291b5a0e83fc4ab1cb949445c
        ]
        if any(no_lxml):
            pytest.skip("test requires lxml")


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
    with closing(original_make_reader(':memory:', feed_root='')) as reader:
        yield reader


@pytest.fixture
def storage():
    with closing(Storage(':memory:')) as storage:
        yield storage


# TODO: move to reader_methods
# TODO: s/call_update_method/update_feed/
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


@pytest.fixture(
    params=[
        # the default
        Storage.chunk_size,
        # rough result size (order of magnitude)
        1,
        pytest.param(2, marks=pytest.mark.slow),
        # unchunked query, likely to be ok
        pytest.param(0, marks=pytest.mark.slow),
    ]
)
def chunk_size(request):
    return request.param


@pytest.fixture(
    params=[
        # defaults not included
        reader_methods.get_entries_recent,
        reader_methods.get_entries_random,
        reader_methods.search_entries_relevant,
        reader_methods.search_entries_recent,
        reader_methods.search_entries_random,
    ],
)
def get_entries(request):
    yield request.param


@pytest.fixture(
    params=[
        pytest.param(reader_methods.get_entries, marks=pytest.mark.slow),
        reader_methods.get_entries_recent,
        pytest.param(
            reader_methods.get_entries_recent_paginated, marks=pytest.mark.slow
        ),
        reader_methods.search_entries_recent,
        pytest.param(
            reader_methods.search_entries_recent_paginated, marks=pytest.mark.slow
        ),
    ],
)
def get_entries_recent(request):
    yield request.param
