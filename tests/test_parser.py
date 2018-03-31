from datetime import datetime

import pytest
import feedgen.feed
import feedparser

from reader.parser import parse
from reader.exceptions import ParseError, NotModified
from reader.types import Content, Enclosure

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
            fe.enclosure(enclosure.href, str(enclosure.length), enclosure.type)

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
    entry_two = parser.entry(1, 2, datetime(2010, 2, 1),

        # Can't figure out how to do this with feedgen
        # (the summary and the content get mixed up
        # and don't know how to pass the language).
        #summary='summary',
        #content=(
            #Content('value3', 'type', 'en'),
            #Content('value2'),
        #),

        enclosures=(
            Enclosure('http://e1', 'type', 1000),

            # Can't figure out how to get this with feedgen
            # (it forces type to 'text/html' and length to 0).
            #Enclosure('http://e2'),
        ),
    )
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


def test_parse_error(monkeypatch, tmpdir):
    """parse() should reraise most feedparser exceptions."""

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    write_feed('atom', feed, [])

    feedparser_exception = Exception("whatever")
    old_feedparser_parse = feedparser.parse
    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser_exception
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    with pytest.raises(ParseError) as excinfo:
        parse(feed.url)

    assert excinfo.value.__cause__ is feedparser_exception


def test_parse_character_encoding_override(monkeypatch, tmpdir):
    """parse() should not reraise feedparser.CharacterEncodingOverride."""

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    write_feed('atom', feed, [])

    old_feedparser_parse = feedparser.parse
    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser.CharacterEncodingOverride("whatever")
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    # shouldn't raise an exception
    parse(feed.url)


def test_parse_not_modified(monkeypatch, tmpdir):
    """parse() should raise NotModified for unchanged feeds."""

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    write_feed('atom', feed, [])

    old_feedparser_parse = feedparser.parse
    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['status'] = 304
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    with pytest.raises(NotModified):
        parse(feed.url)

