import pytest

from reader import Reader


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true",
                     default=False, help="run slow tests")

def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture
def reader():
    return Reader(':memory:')


def call_update_feeds(reader, _):
    reader.update_feeds()

def call_update_feed(reader, url):
    reader.update_feed(url)

@pytest.fixture(params=[call_update_feeds, call_update_feed])
def call_update_method(request):
    return request.param


@pytest.fixture
def db_path(tmpdir):
    return str(tmpdir.join('db.sqlite'))


