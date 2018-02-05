from datetime import datetime
from itertools import chain
from collections import OrderedDict

import pytest
import feedgen.feed

from reader.reader import Reader, Feed, Entry


@pytest.fixture
def reader(monkeypatch, tmpdir):
    monkeypatch.chdir(tmpdir)
    return Reader(':memory:')


def write_feed(type, feed, entries):

    def utc(dt):
        import datetime
        return dt.replace(tzinfo=datetime.timezone(datetime.timedelta()))

    fg = feedgen.feed.FeedGenerator()

    if type == 'atom':
        fg.id(feed.link)
    fg.title(feed.title)
    if feed.link:
        fg.link(href=feed.link)
    if feed.updated:
        fg.updated(utc(feed.updated))
    if type == 'rss':
        fg.description('description')

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry.id)
        fe.title(entry.title)
        if entry.link:
            fe.link(href=entry.link)
        if entry.updated:
            if type == 'atom':
                fe.updated(utc(entry.updated))
            elif type == 'rss':
                fe.published(utc(entry.updated))
        if entry.published:
            if type == 'atom':
                fe.published(utc(entry.published))
            elif type == 'rss':
                assert False, "RSS doesn't support published"

        for enclosure in entry.enclosures or ():
            fe.enclosure(enclosure['href'], enclosure['length'], enclosure['type'])

    if type == 'atom':
        fg.atom_file(feed.url, pretty=True)
    elif type == 'rss':
        fg.rss_file(feed.url, pretty=True)


def make_feed(number, updated):
    return Feed(
        'feed-{}.xml'.format(number),
        'Feed #{}'.format(number),
        'http://www.example.com/{}'.format(number),
        updated,
    )

def make_entry(number, updated, published=None):
    return Entry(
        'http://www.example.com/entries/{}'.format(number),
        'Entry #{}'.format(number),
        'http://www.example.com/entries/{}'.format(number),
        updated,
        published,
        None,
        None,
        None,
        False,
    )


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_update_feed_updated(reader, feed_type):
    """A feed should be processed only if it is newer than the stored one."""

    old_feed = make_feed(1, datetime(2010, 1, 1))
    new_feed = old_feed._replace(updated=datetime(2010, 1, 2))
    entry_one = make_entry(1, datetime(2010, 1, 1))
    entry_two = make_entry(2, datetime(2010, 2, 1))

    reader.add_feed(old_feed.url)

    write_feed(feed_type, old_feed, [entry_one])
    reader.update_feeds()
    assert set(reader.get_entries()) == {(old_feed, entry_one)}

    write_feed(feed_type, old_feed, [entry_one, entry_two])
    reader.update_feeds()
    assert set(reader.get_entries()) == {(old_feed, entry_one)}

    write_feed(feed_type, new_feed, [entry_one, entry_two])
    reader.update_feeds()
    assert set(reader.get_entries()) == {(new_feed, entry_one), (new_feed, entry_two)}


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_update_entry_updated(reader, feed_type):
    """An entry should be updated only if it is newer than the stored one."""

    feed = make_feed(1, datetime(2010, 1, 1))
    old_entry = make_entry(1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)

    write_feed(feed_type, feed, [old_entry])
    reader.update_feeds()
    assert set(reader.get_entries()) == {(feed, old_entry)}

    feed = feed._replace(updated=datetime(2010, 1, 2))
    new_entry = old_entry._replace(title='New Entry')
    write_feed(feed_type, feed, [new_entry])
    reader.update_feeds()
    assert set(reader.get_entries()) == {(feed, old_entry)}

    feed = feed._replace(updated=datetime(2010, 1, 3))
    new_entry = new_entry._replace(updated=datetime(2010, 1, 2))
    write_feed(feed_type, feed, [new_entry])
    reader.update_feeds()

    assert set(reader.get_entries()) == {(feed, new_entry)}


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_mark_as_read_unread(reader, feed_type):

    feed = make_feed(1, datetime(2010, 1, 1))
    entry = make_entry(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    write_feed(feed_type, feed, [entry])
    reader.update_feeds()

    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_read(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_read(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert entry.read

    reader.mark_as_unread(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read

    reader.mark_as_unread(feed.url, entry.id)
    (feed, entry), = list(reader.get_entries())
    assert not entry.read


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_add_remove_feed(reader, feed_type):

    feed = make_feed(1, datetime(2010, 1, 1))
    entry = make_entry(1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    write_feed(feed_type, feed, [entry])
    reader.update_feeds()

    assert set(reader.get_entries()) == {(feed, entry)}

    reader.remove_feed(feed.url)
    assert set(reader.get_entries()) == set()


@pytest.mark.slow
def test_mark_as_read_during_update_feeds(monkeypatch, tmpdir):
    monkeypatch.chdir(tmpdir)
    db_path = str(tmpdir.join('db.sqlite'))

    feed = make_feed(1, datetime(2010, 1, 1))
    entry = make_entry(1, datetime(2010, 1, 1))
    write_feed('rss', feed, [entry])
    feed2 = make_feed(2, datetime(2010, 1, 1))
    write_feed('rss', feed2, [])

    reader = Reader(db_path)
    reader.add_feed(feed.url)
    reader.add_feed(feed2.url)
    reader.update_feeds()

    import threading

    class BozoFeed(dict):
        bozo = True

    in_feedparser_parse = threading.Event()
    can_return_from_feedparser_parse = threading.Event()

    def fake_feedparser_parse(*args, **kwargs):
        in_feedparser_parse.set()
        can_return_from_feedparser_parse.wait()
        return BozoFeed()

    monkeypatch.setattr('feedparser.parse', fake_feedparser_parse)

    t = threading.Thread(target=lambda: Reader(db_path).update_feeds())
    t.start()

    in_feedparser_parse.wait()

    try:
        # shouldn't raise an exception
        reader.mark_as_read(feed.url, entry.id)
    finally:
        can_return_from_feedparser_parse.set()
        t.join()


class FeedWriter:

    def __init__(self, number, type):
        self.number = number
        self.type = type
        self.updated = None
        self.entries = OrderedDict()

    def entry(self, number, *args, **kwargs):
        self.entries[number] = make_entry(number, *args, **kwargs)

    def get_feed(self):
        return make_feed(self.number, self.updated)

    def get_tuples(self):
        feed = self.get_feed()
        for entry in self.entries.values():
            yield feed, entry

    def write(self):
        write_feed(self.type, self.get_feed(), self.entries.values())


@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test
    0,                                  # unchunked query
])
def test_get_entries_order(reader, chunk_size):
    reader._get_entries_chunk_size = chunk_size

    one = FeedWriter(1, 'rss')
    two = FeedWriter(2, 'atom')

    reader.add_feed(two.get_feed().url)

    two.entry(1, datetime(2010, 1, 1))
    two.entry(4, datetime(2010, 1, 4))
    two.updated = datetime(2010, 1, 4)
    two.write()

    reader.update_feeds()

    reader.add_feed(one.get_feed().url)

    one.entry(1, datetime(2010, 1, 2))
    one.updated = datetime(2010, 1, 2)
    one.write()

    reader.update_feeds()

    two.entry(1, datetime(2010, 1, 5))
    two.entry(2, datetime(2010, 1, 2))
    two.updated = datetime(2010, 1, 5)
    two.write()

    reader.update_feeds()

    one.entry(2, datetime(2010, 1, 2))
    one.entry(4, datetime(2010, 1, 3))
    one.entry(3, datetime(2010, 1, 4))
    one.updated = datetime(2010, 1, 6)
    one.write()
    two.entry(3, datetime(2010, 1, 2))
    two.entry(5, datetime(2010, 1, 3))
    two.updated = datetime(2010, 1, 6)
    two.write()

    reader.update_feeds()

    expected = sorted(
        chain(one.get_tuples(), two.get_tuples()),
        key=lambda t: (t[1].updated, t[0].url, t[1].id),
        reverse=True)

    assert list(reader.get_entries()) == expected


@pytest.mark.slow
@pytest.mark.parametrize('chunk_size', [
    Reader._get_entries_chunk_size,     # the default
    1, 2, 3, 8,                         # rough result size for this test

    # check unchunked queries still blocks writes
    pytest.param(0, marks=pytest.mark.xfail(raises=Exception, strict=True)),
])
def test_mark_as_read_during_get_entries(monkeypatch, tmpdir, chunk_size):
    monkeypatch.chdir(tmpdir)
    db_path = str(tmpdir.join('db.sqlite'))

    feed = make_feed(1, datetime(2010, 1, 1))
    entry = make_entry(1, datetime(2010, 1, 1))
    entry2 = make_entry(2, datetime(2010, 1, 2))
    entry3 = make_entry(3, datetime(2010, 1, 3))
    write_feed('rss', feed, [entry, entry2, entry3])

    reader = Reader(db_path)
    reader.add_feed(feed.url)
    reader.update_feeds()

    reader._get_entries_chunk_size = chunk_size

    entries = reader.get_entries(_unread_only=True)
    next(entries)

    # shouldn't raise an exception
    Reader(db_path).mark_as_read(feed.url, entry.id)
    Reader(db_path).mark_as_unread(feed.url, entry.id)

    # just a sanity check
    assert len(list(entries)) == 3 - 1


def test_get_feeds(reader):
    one = make_feed(1, datetime(2010, 1, 1))
    two = make_feed(2, datetime(2010, 1, 2))

    reader.add_feed(one.url)
    reader.add_feed(two.url)

    assert set(reader.get_feeds()) == {
        Feed(f.url, None, None, None) for f in (one, two)
    }, "only url should be set for feeds not yet updated"

    write_feed('rss', one, [])
    write_feed('atom', two, [])
    reader.update_feeds()

    assert set(reader.get_feeds()) == {one, two}


def test_get_feed(reader):
    feed = make_feed(1, datetime(2010, 1, 1))

    assert reader.get_feed(feed.url) == None

    reader.add_feed(feed.url)

    assert reader.get_feed(feed.url) == Feed(feed.url, None, None, None)

    write_feed('rss', feed, [])
    reader.update_feeds()

    assert reader.get_feed(feed.url) == feed

