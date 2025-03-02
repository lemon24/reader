import os
import pathlib
import sqlite3
import sys
from contextlib import closing
from functools import wraps

import pytest

import reader_methods
from fakeparser import Parser
from reader import make_reader as original_make_reader
from reader._storage import Storage
from utils import monkeypatch_tz
from utils import reload_module


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_collection_modifyitems(config, items):  # pragma: no cover
    apply_runslow(config, items)


def apply_runslow(config, items):  # pragma: no cover
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


def pytest_runtest_setup(item):
    # lxml fails to build in various places,
    # see the comments in pyproject.toml for details.
    for mark in item.iter_markers(name="requires_lxml"):
        try:
            import lxml
        except ImportError:
            pytest.skip("test requires lxml")

    # getting intermittent Flask-context-related errors on pypy:
    #   AssertionError: Popped wrong app context.
    #   RuntimeError: Working outside of request context.
    for mark in item.iter_markers(name="apptest"):
        if sys.implementation.name == 'pypy':
            pytest.skip("flask tests are flaky on pypy")


@pytest.fixture(autouse=True, scope="session")
def no_sqlite3_adapters(request):
    # bring about the removal of deprecated sqlite3 default adapters
    # (adapters cannot be disabled per-connection like converters)
    # https://github.com/lemon24/reader/issues/321
    # TODO: remove this once sqlite3 default adapters are removed
    original_adapters = sqlite3.adapters.copy()
    sqlite3.adapters.clear()
    request.addfinalizer(lambda: sqlite3.adapters.update(original_adapters))


@pytest.fixture
def make_reader(request):
    @wraps(original_make_reader)
    def make_reader(*args, **kwargs):
        reader = original_make_reader(*args, **kwargs)
        request.addfinalizer(reader.close)

        if 'parser' in request.fixturenames:
            reader._parser = request.getfixturevalue('parser')

        return reader

    return make_reader


@pytest.fixture
def reader(request):
    with closing(original_make_reader(':memory:', feed_root='')) as reader:

        if 'parser' in request.fixturenames:
            reader._parser = request.getfixturevalue('parser')

        yield reader


@pytest.fixture
def storage():
    with closing(Storage(':memory:')) as storage:
        yield storage


@pytest.fixture
def parser():
    return Parser()


def slow(*args, **kwargs):
    return pytest.param(*args, **kwargs, marks=pytest.mark.slow)


@pytest.fixture(
    params=[
        m if 'workers' not in m.__name__ else slow(m)
        for m in reader_methods.update_feed_methods
    ]
)
def update_feed(request):
    return request.param


@pytest.fixture(
    params=[
        m if 'workers' not in m.__name__ else slow(m)
        for m in reader_methods.update_feeds_iter_methods
    ]
)
def update_feeds_iter(request):
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
def db_path(tmp_path):
    return str(tmp_path.joinpath('db.sqlite'))


@pytest.fixture
def root_dir(tests_dir):
    return tests_dir.parent


@pytest.fixture
def tests_dir():
    return pathlib.Path(__file__).parent


@pytest.fixture
def data_dir(tests_dir):
    return tests_dir.joinpath('data')


@pytest.fixture(
    params=[
        # the default
        Storage.chunk_size,
        # rough result size (order of magnitude)
        1,
        slow(2),
    ]
)
def chunk_size(request):
    return request.param


@pytest.fixture(
    params=[
        reader_methods.get_entries_recent,
        slow(reader_methods.get_entries_random),
        reader_methods.search_entries_relevant,
        slow(reader_methods.search_entries_recent),
        slow(reader_methods.search_entries_random),
    ]
)
def get_entries(request):
    yield request.param


@pytest.fixture(
    params=[
        slow(reader_methods.get_entries),
        reader_methods.get_entries_recent,
        slow(reader_methods.get_entries_recent_paginated),
        reader_methods.search_entries_recent,
        slow(reader_methods.search_entries_recent_paginated),
    ],
)
def get_entries_recent(request):
    yield request.param


@pytest.fixture(
    params=[
        reader_methods.get_entry_counts,
        reader_methods.search_entry_counts,
    ]
)
def get_entry_counts(request):
    yield request.param
