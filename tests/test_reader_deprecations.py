from datetime import datetime

import pytest
from fakeparser import Parser

from reader import EntryError
from reader import EntryNotFoundError
from reader import FeedMetadataNotFoundError
from reader import FeedNotFoundError
from reader.types import UpdatedFeed


def test_feed_metadata(reader):
    reader.add_feed('feed')

    with pytest.deprecated_call():
        assert set(reader.iter_feed_metadata('feed')) == set()
    with pytest.deprecated_call():
        assert reader.get_feed_metadata('feed', 'key', None) is None
    with pytest.deprecated_call():
        assert reader.get_feed_metadata('feed', 'key', 0) == 0

    with pytest.raises(TypeError):
        reader.get_feed_metadata('feed', 'key', 'too', 'many')

    with pytest.deprecated_call():
        reader.set_feed_metadata('feed', 'key', 'value')
    with pytest.deprecated_call():
        assert set(reader.iter_feed_metadata('feed')) == {('key', 'value')}

    with pytest.deprecated_call():
        assert reader.get_feed_metadata('feed', 'key') == 'value'

    with pytest.deprecated_call():
        reader.delete_feed_metadata('feed', 'key')

    with pytest.deprecated_call():
        assert set(reader.iter_feed_metadata('feed')) == set()
    with pytest.raises(FeedMetadataNotFoundError), pytest.deprecated_call():
        reader.get_feed_metadata('feed', 'key')


def test_remove_feed(reader):
    with pytest.raises(FeedNotFoundError), pytest.deprecated_call():
        reader.remove_feed('feed')

    reader.add_feed('feed')

    with pytest.deprecated_call():
        reader.remove_feed('feed')


def test_mark_as(reader):
    reader._parser = parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(feed)
    reader.update_feeds()

    with pytest.deprecated_call():
        reader.mark_as_read(entry)
    assert reader.get_entry(entry).read

    with pytest.deprecated_call():
        reader.mark_as_unread(entry)
    assert not reader.get_entry(entry).read

    with pytest.deprecated_call():
        reader.mark_as_important(entry)
    assert reader.get_entry(entry).important

    with pytest.deprecated_call():
        reader.mark_as_unimportant(entry)
    assert not reader.get_entry(entry).important


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
