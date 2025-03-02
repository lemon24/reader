from reader import Enclosure
from utils import utc_datetime as datetime


def test_plugin(make_reader, parser):
    reader = make_reader(':memory:', plugins=['reader.enclosure_dedupe'])

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.entry(
        1,
        2,
        datetime(2010, 1, 1),
        enclosures=(Enclosure('href'), Enclosure('another one')),
    )
    three = parser.entry(
        1,
        3,
        datetime(2010, 1, 1),
        enclosures=(Enclosure('href', 'text', 1), Enclosure('href', 'json', 2)),
    )

    reader.add_feed(feed.url)
    reader.update_feeds()

    assert {(e.id, e.enclosures) for e in reader.get_entries()} == {
        (one.id, one.enclosures),
        (two.id, two.enclosures),
        (three.id, (Enclosure('href', 'text', 1),)),
    }
