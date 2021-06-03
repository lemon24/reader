from datetime import datetime

import pytest
from fakeparser import Parser

from reader import EntryError
from reader import EntryNotFoundError
from reader import FeedMetadataNotFoundError
from reader import FeedNotFoundError


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
