import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url='{}invalid.json'.format(url_base),
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='2',
        updated=None,
        enclosures=(
            Enclosure(href='control'),
            Enclosure(href='float size', length=100),
            Enclosure(href='non-number size'),
        ),
    ),
    EntryData(
        feed_url=feed.url,
        id='3.1415',
        title='float id',
        updated=None,
    ),
    EntryData(
        feed_url=feed.url,
        id='author name',
        updated=None,
    ),
    EntryData(
        feed_url=feed.url,
        id='author url',
        updated=None,
    ),
    EntryData(
        feed_url=feed.url,
        id='author name fallback',
        updated=None,
        author='mailto:joe@example.com',
    ),
    EntryData(
        feed_url=feed.url,
        id='author empty dict',
        updated=None,
    ),
    EntryData(
        feed_url=feed.url,
        id='author empty list',
        updated=None,
    ),
    EntryData(
        feed_url=feed.url,
        id='second author is good',
        updated=None,
        author='Jane',
    ),
]
