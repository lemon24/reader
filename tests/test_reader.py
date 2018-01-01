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
def reader():
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
def test_roundtrip(tmpdir, monkeypatch, reader, feed_type):
    monkeypatch.chdir(tmpdir)

    write_feed(feed_type, FEED, [ENTRY])

    reader.add_feed(FEED.url)
    reader.update_feeds()

    assert list(reader.get_entries()) == [(FEED, ENTRY)]

