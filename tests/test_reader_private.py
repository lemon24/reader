import io
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import Mock

import pytest

from fakeparser import Parser
from reader import Entry
from reader import EntryNotFoundError
from reader import Feed
from reader import FeedNotFoundError
from reader import make_reader
from reader import ParseError
from reader._parser import RetrievedFeed
from reader._types import EntryData
from reader._types import FeedData
from reader._types import FeedFilter
from utils import utc_datetime
from utils import utc_datetime as datetime


@pytest.mark.parametrize('entry_updated', [utc_datetime(2010, 1, 1), None])
def test_update_stale(reader, parser, update_feed, entry_updated):
    """When a feed is marked as stale feeds/entries should be updated
    regardless of their .updated or caching headers.

    """
    parser.retrieve = Mock(wraps=parser.retrieve)
    parser.caching_info = 'caching'

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, entry_updated)

    with pytest.raises(FeedNotFoundError):
        reader._storage.set_feed_stale(feed.url, True)

    reader.add_feed(feed.url)

    reader._now = lambda: datetime(2010, 1, 1)
    update_feed(reader, feed.url)

    assert {(f.url, f.title, f.last_updated) for f in reader.get_feeds()} == {
        (feed.url, feed.title, datetime(2010, 1, 1))
    }
    assert {(e.id, e.title, e.last_updated) for e in reader.get_entries()} == {
        (entry.id, entry.title, datetime(2010, 1, 1))
    }

    # we can't change feed/entry here because their hash would change,
    # resulting in an update;
    # the only way to check they were updated is through last_updated

    # should we deprecate the staleness API? maybe:
    # https://github.com/lemon24/reader/issues/179#issuecomment-663840297
    # OTOH, we may still want an update to happen for other side-effects,
    # even if the hash doesn't change

    if entry_updated:
        # nothing changes after update
        reader._now = lambda: datetime(2010, 1, 2)
        update_feed(reader, feed.url)
        assert {(f.url, f.title, f.last_updated) for f in reader.get_feeds()} == {
            (feed.url, feed.title, datetime(2010, 1, 1))
        }
        assert {(e.id, e.title, e.last_updated) for e in reader.get_entries()} == {
            (entry.id, entry.title, datetime(2010, 1, 1))
        }

    # but it does if we mark the feed as stale
    parser.retrieve.reset_mock()
    reader._storage.set_feed_stale(feed.url, True)
    reader._now = lambda: datetime(2010, 1, 3)
    update_feed(reader, feed.url)
    parser.retrieve.assert_called_once_with(feed.url, None)
    assert {(f.url, f.title, f.last_updated) for f in reader.get_feeds()} == {
        (feed.url, feed.title, datetime(2010, 1, 3))
    }
    assert {(e.id, e.title, e.last_updated) for e in reader.get_entries()} == {
        (entry.id, entry.title, datetime(2010, 1, 3))
    }


def test_update_parse(reader, parser, update_feed):
    """Updated feeds should pass caching headers back to ._parser()."""
    parser.retrieve = Mock(wraps=parser.retrieve)
    parser.caching_info = 'caching'

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    update_feed(reader, feed.url)
    parser.retrieve.assert_called_once_with(feed.url, None)

    parser.retrieve.reset_mock()
    update_feed(reader, feed.url)
    parser.retrieve.assert_called_once_with(feed.url, 'caching')


def test_make_reader_storage(storage):
    reader = make_reader('', _storage=storage)
    assert reader._storage is storage


def test_delete_entries(reader, parser):
    """While Storage.delete_entries() is a storage method,
    we care how it interacts with updates etc.,
    and it will be called by plugins.

    """
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)

    def get_entry_ids():
        return [e.id for e in reader.get_entries()]

    with pytest.raises(EntryNotFoundError) as excinfo:
        reader._storage.delete_entries([entry.resource_id])
    assert (excinfo.value.feed_url, excinfo.value.id) == entry.resource_id
    assert 'no such entry' in excinfo.value.message

    assert get_entry_ids() == []

    reader.update_feeds()
    assert get_entry_ids() == ['1, 1']

    reader._storage.delete_entries([entry.resource_id])
    assert get_entry_ids() == []

    with pytest.raises(EntryNotFoundError) as excinfo:
        reader._storage.delete_entries([entry.resource_id])

    del parser.entries[1][1]
    reader.update_feeds()
    assert get_entry_ids() == []

    parser.entries[1][1] = entry
    reader.update_feeds()
    assert get_entry_ids() == ['1, 1']


# TODO: move CustomRetriever and CustomParser to fakes.py


class CustomRetriever:
    slow_to_read = False

    def __call__(self, url, caching_info, *_):
        self.before_enter(url)
        return self._make_cm(url, caching_info)

    @contextmanager
    def _make_cm(self, url, caching_info):
        self.after_enter(url)
        yield RetrievedFeed(
            io.BytesIO(b'file'),
            'x.test',
            caching_info.upper() if caching_info else None,
            slow_to_read=self.slow_to_read,
        )

    def before_enter(self, url):
        pass

    def after_enter(self, url):
        pass

    def validate_url(self, url):
        pass

    def process_feed_for_update(self, feed):
        assert feed.caching_info is None
        return feed._replace(caching_info='etag')


class CustomParser:
    accept = 'x.test'

    def __call__(self, url, file, headers):
        self.in_call(url)
        feed = FeedData(url, title=file.read().decode().upper())

        def make_entries():
            self.in_entries_iter(url)
            yield EntryData(url, 'id', title='entry')

        return feed, make_entries()

    def in_entries_iter(self, url):
        pass

    def in_call(self, url):
        pass

    def process_entry_pairs(self, url, pairs):
        self.in_entry_pairs_iter(url)
        for new, old in pairs:
            yield new._replace(title=new.title.upper()), old

    def in_entry_pairs_iter(self, url):
        pass


def test_retriever_parser_process_hooks(reader):
    """Test retriever.process_feed_for_update() and
    parser.process_entry_pairs() get called
    (both private, but used by plugins).

    """
    reader._parser.mount_retriever('test:', CustomRetriever())
    reader._parser.mount_parser_by_mime_type(CustomParser())

    reader.add_feed('test:one')
    reader.update_feeds()

    (feed_for_update,) = reader._storage.get_feeds_for_update(FeedFilter('test:one'))
    assert feed_for_update.caching_info == 'ETAG'

    (entry,) = reader.get_entries()
    assert entry.title == 'ENTRY'
    assert entry.feed.title == 'FILE'


def setup_custom(reader, target_name, method_name, slow_to_read):
    retriever = CustomRetriever()
    reader._parser.mount_retriever('test:', retriever)
    parser = CustomParser()
    reader._parser.mount_parser_by_mime_type(parser)

    for feed_id in 1, 2, 3:
        reader.add_feed(f'test:{feed_id}')

    target = locals()[target_name]
    method = getattr(target, method_name)

    def raise_exc(obj, *args):
        url = getattr(obj, 'url', obj)
        if '1' in url:
            raise raise_exc.exc
        return method(obj, *args)

    raise_exc.exc = None

    setattr(target, method_name, raise_exc)

    retriever.slow_to_read = slow_to_read

    return retriever, parser, raise_exc


RETRIEVER_PARSER_METHOD_PARAMS = [
    ('retriever', 'before_enter', False, 'unexpected error during retriever'),
    ('retriever', 'after_enter', False, 'unexpected error during retriever'),
    ('retriever', 'after_enter', True, 'unexpected error during retriever'),
    (
        'retriever',
        'process_feed_for_update',
        False,
        'unexpected error during retriever.process_feed_for_update()',
    ),
    ('parser', 'in_call', False, 'unexpected error during parser'),
    ('parser', 'in_entries_iter', False, 'unexpected error during parser'),
    (
        'parser',
        'process_entry_pairs',
        False,
        'unexpected error during parser.process_entry_pairs()',
    ),
    (
        'parser',
        'in_entry_pairs_iter',
        False,
        'unexpected error during parser.process_entry_pairs()',
    ),
]


@pytest.mark.parametrize(
    'target, method, slow_to_read, message', RETRIEVER_PARSER_METHOD_PARAMS
)
def test_retriever_parser_unexpected_error(
    reader, update_feeds_iter, target, method, slow_to_read, message
):
    retriever, parser, raise_exc = setup_custom(reader, target, method, slow_to_read)
    raise_exc.exc = exc = RuntimeError('error')

    rv = {int(r.url.rpartition(':')[2]): r for r in update_feeds_iter(reader)}

    assert isinstance(rv[1].error, ParseError)
    assert rv[1].error.message == message
    assert rv[1].error.__cause__ is exc
    if rv[2].error:
        raise rv[2].error
    assert rv[2].updated_feed
    if rv[3].error:
        raise rv[3].error
    assert rv[3].updated_feed


@pytest.mark.parametrize(
    'target, method, slow_to_read', [t[:-1] for t in RETRIEVER_PARSER_METHOD_PARAMS]
)
def test_retriever_parser_parse_error(
    reader, update_feeds_iter, target, method, slow_to_read
):
    retriever, parser, raise_exc = setup_custom(reader, target, method, slow_to_read)
    raise_exc.exc = exc = ParseError('x')

    rv = {int(r.url.rpartition(':')[2]): r for r in update_feeds_iter(reader)}

    assert isinstance(rv[1].error, ParseError)
    assert rv[1].error is exc
    if rv[2].error:
        raise rv[2].error
    assert rv[2].updated_feed
    if rv[3].error:
        raise rv[3].error
    assert rv[3].updated_feed
