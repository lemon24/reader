from datetime import datetime

import pytest
import feedgen.feed

from reader.db import open_db
from reader.reader import Reader, Feed, Entry


FEED = Feed(
    'feed.xml',
    'Feed',
    'http://www.example.com/',
    datetime(2010, 1, 1),
)

ENTRY = Entry(
    'http://www.example.com/1',
    'Entry',
    'http://www.example.com/1',
    datetime(2010, 1, 1),
    datetime(2010, 1, 1),
    None,
)


@pytest.fixture
def reader(monkeypatch, tmpdir):
    monkeypatch.chdir(tmpdir)
    return Reader(open_db(':memory:'))


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
            fe.updated(utc(entry.updated))
        if entry.published:
            fe.published(utc(entry.published))

        for enclosure in entry.enclosures or ():
            fe.enclosure(enclosure['href'], enclosure['length'], enclosure['type'])

    if type == 'atom':
        fg.atom_file(feed.url, pretty=True)
    elif type == 'rss':
        fg.rss_file(feed.url, pretty=True)


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_roundtrip(reader, feed_type):
    write_feed(feed_type, FEED, [ENTRY])

    reader.add_feed(FEED.url)
    reader.update_feeds()

    assert list(reader.get_entries()) == [(FEED, ENTRY)]


def make_feed(number, updated):
    return Feed(
        'feed-{}.xml'.format(number),
        'Feed #{}'.format(number),
        'http://www.example.com/{}'.format(number),
        updated,
    )

def make_entry(number, updated, **kwargs):
    return Entry(
        'http://www.example.com/entries/{}'.format(number),
        'Entry #{}'.format(number),
        'http://www.example.com/entries/{}'.format(number),
        updated,
        kwargs.get('published', updated),
        None,
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


@pytest.mark.xfail
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

