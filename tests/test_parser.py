from datetime import datetime

import pytest
import feedgen.feed

from reader.parser import parse
from reader.exceptions import ParseError, NotModified

from fakeparser import Parser


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


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse(monkeypatch, tmpdir, feed_type):
    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry_one = parser.entry(1, 1, datetime(2010, 1, 1))
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1))
    entries = [entry_one, entry_two]
    write_feed(feed_type, feed, entries)

    (
        expected_feed,
        expected_entries,
        expected_http_etag,
        expected_http_last_modified,
    ) = parse(feed.url)
    expected_entries = sorted(expected_entries, key=lambda e: e.updated)

    assert feed == expected_feed
    assert entries == expected_entries
    assert expected_http_etag is None
    assert expected_http_last_modified is None

