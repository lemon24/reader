from datetime import datetime

from reader.plugins.enclosure_dedupe import enclosure_dedupe
from reader import Enclosure

from fakeparser import Parser


def test_enclosure_dedupe(reader):
    reader._parser = parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.entry(1, 2, datetime(2010, 1, 1), enclosures=(
        Enclosure('href'), Enclosure('another one'),
    ))
    three = parser.entry(1, 3, datetime(2010, 1, 1), enclosures=(
        Enclosure('href', 'text', 1), Enclosure('href', 'json', 2),
    ))

    reader.add_feed(feed.url)
    reader.update_feeds()

    enclosure_dedupe(reader)

    assert set(reader.get_entries()) == {
        one._replace(feed=feed),
        two._replace(feed=feed),
        three._replace(feed=feed, enclosures=(Enclosure('href', 'text', 1), )),
    }


