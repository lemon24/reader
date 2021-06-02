import pytest

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
