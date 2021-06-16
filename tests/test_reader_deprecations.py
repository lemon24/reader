from datetime import datetime

import pytest
from fakeparser import Parser

from reader import EntryError
from reader import EntryNotFoundError
from reader.types import UpdatedFeed


@pytest.mark.parametrize('cls', [EntryError, EntryNotFoundError])
def test_entry_error_url(cls):
    exc = cls('feed', 'id')
    with pytest.deprecated_call():
        assert exc.url == 'feed'


@pytest.mark.parametrize('name', ['update_feeds', 'update_feeds_iter'])
def test_update_feeds_new_only(reader, name):
    reader._parser = Parser()
    method = getattr(reader, name)

    with pytest.raises(TypeError):
        list(method(new=True, new_only=True) or ())

    class MyError(Exception):
        pass

    def get_feeds_for_update(url=None, new=None, enabled_only=False):
        raise MyError(new)

    reader._storage.get_feeds_for_update = get_feeds_for_update

    with pytest.raises(MyError) as excinfo, pytest.deprecated_call():
        list(method(new_only=True) or ())
    assert excinfo.value.args[0] is True

    with pytest.raises(MyError) as excinfo, pytest.deprecated_call():
        list(method(new_only=False) or ())
    assert excinfo.value.args[0] is None


def test_updated_feed_updated():
    feed = UpdatedFeed('url', 1, 2)

    with pytest.deprecated_call():
        feed.updated

    assert feed.updated == feed.modified
