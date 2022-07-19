from contextlib import contextmanager
from datetime import datetime

import pytest
from fakeparser import Parser
from fakeparser import ParserThatRemembers
from utils import naive_datetime
from utils import utc_datetime

from reader import Entry
from reader import EntryNotFoundError
from reader import Feed
from reader import FeedNotFoundError
from reader import make_reader
from reader import ParseError
from reader._parser import RetrieveResult
from reader._types import EntryData
from reader._types import FeedData
from reader._types import FeedFilterOptions


@pytest.mark.parametrize('entry_updated', [utc_datetime(2010, 1, 1), None])
def test_update_stale(reader, call_update_method, entry_updated):
    """When a feed is marked as stale feeds/entries should be updated
    regardless of their .updated or caching headers.

    """
    from utils import utc_datetime as datetime

    parser = ParserThatRemembers()
    parser.http_etag = 'etag'
    parser.http_last_modified = 'last-modified'
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, entry_updated)

    with pytest.raises(FeedNotFoundError):
        reader._storage.mark_as_stale(feed.url)

    reader.add_feed(feed.url)

    reader._now = lambda: naive_datetime(2010, 1, 1)
    call_update_method(reader, feed.url)

    assert set((f.url, f.title, f.last_updated) for f in reader.get_feeds()) == {
        (feed.url, feed.title, datetime(2010, 1, 1))
    }
    assert set((e.id, e.title, e.last_updated) for e in reader.get_entries()) == {
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
        reader._now = lambda: naive_datetime(2010, 1, 2)
        call_update_method(reader, feed.url)
        assert set((f.url, f.title, f.last_updated) for f in reader.get_feeds()) == {
            (feed.url, feed.title, datetime(2010, 1, 1))
        }
        assert set((e.id, e.title, e.last_updated) for e in reader.get_entries()) == {
            (entry.id, entry.title, datetime(2010, 1, 1))
        }

    # but it does if we mark the feed as stale
    parser.calls[:] = []
    reader._storage.mark_as_stale(feed.url)
    reader._now = lambda: naive_datetime(2010, 1, 3)
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]
    assert set((f.url, f.title, f.last_updated) for f in reader.get_feeds()) == {
        (feed.url, feed.title, datetime(2010, 1, 3))
    }
    assert set((e.id, e.title, e.last_updated) for e in reader.get_entries()) == {
        (entry.id, entry.title, datetime(2010, 1, 3))
    }


def test_update_parse(reader, call_update_method):
    """Updated feeds should pass caching headers back to ._parser()."""
    from utils import utc_datetime as datetime

    parser = ParserThatRemembers()
    parser.http_etag = 'etag'
    parser.http_last_modified = 'last-modified'
    reader._parser = parser

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, None, None)]

    parser.calls[:] = []
    call_update_method(reader, feed.url)
    assert parser.calls == [(feed.url, 'etag', 'last-modified')]


def test_make_reader_storage(storage):
    reader = make_reader('', _storage=storage)
    assert reader._storage is storage


def test_delete_entries(reader):
    """While Storage.delete_entries() is a storage method,
    we care how it interacts with updates etc.,
    and it will be called by plugins.

    """
    from utils import utc_datetime as datetime

    reader._parser = parser = Parser()
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


class CustomRetriever:
    slow_to_read = False

    @contextmanager
    def __call__(self, url, http_etag, *_, **__):
        yield RetrieveResult('file', 'x.test', http_etag=http_etag.upper())

    def validate_url(self, url):
        pass

    def process_feed_for_update(self, feed):
        assert feed.http_etag is None
        return feed._replace(http_etag='etag')


class CustomParser:
    http_accept = 'x.test'

    def __call__(self, url, file, headers):
        feed = FeedData(url, title=file.upper())
        entries = [EntryData(url, 'id', title='entry')]
        return feed, entries

    def process_entry_pairs(self, url, pairs):
        for new, old in pairs:
            yield new._replace(title=new.title.upper()), old


def test_retriever_parser_process_hooks(reader):
    """Test retriever.process_feed_for_update() and
    parser.process_entry_pairs() get called
    (both private, but used by plugins).

    """
    reader._parser.mount_retriever('test:', CustomRetriever())
    reader._parser.mount_parser_by_mime_type(CustomParser())

    reader.add_feed('test:one')
    reader.update_feeds()

    (feed_for_update,) = reader._storage.get_feeds_for_update(
        FeedFilterOptions('test:one')
    )
    assert feed_for_update.http_etag == 'ETAG'

    (entry,) = reader.get_entries()
    assert entry.title == 'ENTRY'
    assert entry.feed.title == 'FILE'


def test_retriever_process_feed_for_update_parse_error(reader):
    cause = Exception('bar')

    def process_feed_for_update(feed):
        raise ParseError(feed.url, 'foo') from cause

    retriever = CustomRetriever()
    retriever.process_feed_for_update = process_feed_for_update

    reader._parser.mount_retriever('test:', retriever)
    reader._parser.mount_parser_by_mime_type(CustomParser())

    reader.add_feed('test:one')

    with pytest.raises(ParseError) as excinfo:
        reader.update_feed('test:one')
    assert 'foo' == excinfo.value.message
    assert excinfo.value.__cause__ is cause

    (feed,) = reader.get_feeds()
    assert feed.last_exception is not None
    assert feed.last_exception.type_name == 'builtins.Exception'
    assert feed.last_exception.value_str == 'bar'
