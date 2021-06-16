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


def test_updated_feed_updated():
    feed = UpdatedFeed('url', 1, 2)

    with pytest.deprecated_call():
        feed.updated

    assert feed.updated == feed.modified
