"""
Reusable fixtures (by someone using reader).

"""

from contextlib import closing
from functools import wraps

import pytest

from fakeparser import Parser
from reader import make_reader as original_make_reader


@pytest.fixture
def make_reader(request):
    @wraps(original_make_reader)
    def make_reader(*args, **kwargs):
        reader = original_make_reader(*args, **kwargs)
        request.addfinalizer(reader.close)

        if 'parser' in request.fixturenames:
            reader._parser = request.getfixturevalue('parser')

        if 'noscheduled' in request.keywords:
            reader._scheduled_override = False

        return reader

    return make_reader


@pytest.fixture
def reader(request):
    with closing(original_make_reader(':memory:', feed_root='')) as reader:

        if 'parser' in request.fixturenames:
            reader._parser = request.getfixturevalue('parser')

        if 'noscheduled' in request.keywords:
            reader._scheduled_override = False

        yield reader


@pytest.fixture
def parser():
    return Parser()
