from dataclasses import dataclass

import pytest

from reader import Entry
from reader import Feed
from reader.core.types import _namedtuple_compat
from reader.core.types import entry_argument
from reader.core.types import feed_argument


def test_namedtuple_compat():
    @dataclass(frozen=True)
    class Object(_namedtuple_compat):
        one: int
        two: int = None

    assert Object._make((1, 2)) == Object(1, 2)
    with pytest.raises(TypeError):
        Object._make((1,))
    with pytest.raises(TypeError):
        Object._make((1, 2, 3))

    assert Object(1, 1)._replace(two=2) == Object(1, 2)

    assert Object(1, 2)._asdict() == {'one': 1, 'two': 2}


def test_feed_argument():
    feed = Feed('url')
    assert feed_argument(feed) == feed.url
    assert feed_argument(feed.url) == feed.url
    with pytest.raises(ValueError):
        feed_argument(1)


def test_entry_argument():
    feed = Feed('url')
    entry = Entry('entry', 'updated', feed=feed)
    entry_tuple = feed.url, entry.id
    assert entry_argument(entry) == entry_tuple
    assert entry_argument(entry_tuple) == entry_tuple
    with pytest.raises(ValueError):
        entry_argument(entry._replace(feed=None))
    with pytest.raises(ValueError):
        entry_argument(1)
    with pytest.raises(ValueError):
        entry_argument('ab')
    with pytest.raises(ValueError):
        entry_argument((1, 'b'))
    with pytest.raises(ValueError):
        entry_argument(('a', 2))
    with pytest.raises(ValueError):
        entry_argument(('a', 'b', 'c'))
