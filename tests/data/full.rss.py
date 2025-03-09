import datetime

from reader import Content
from reader import Enclosure
from reader import EntrySource
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url=f'{url_base}full.rss',
    updated=datetime.datetime(2010, 9, 6, 0, 1, tzinfo=datetime.UTC),
    title='RSS Title',
    link='http://www.example.com/main.html',
    author='Example editor (me@example.com)',
    subtitle='This is an example of an RSS feed',
    version='rss20',
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='7bd204c6-1655-4c27-aeee-53f933c5395f',
        updated=None,
        title='Example entry',
        link='http://www.example.com/blog/post/1',
        author='Example editor',
        published=datetime.datetime(2009, 9, 6, 16, 20, tzinfo=datetime.UTC),
        summary='Here is some text containing an interesting description.',
        content=(
            # the text/plain type comes from feedparser
            Content(value='Example content', type='text/plain'),
        ),
        enclosures=(
            Enclosure(href='http://example.com/enclosure'),
            Enclosure(href='http://example.com/enclosure-with-type', type='image/jpeg'),
            Enclosure(href='http://example.com/enclosure-with-length', length=100000),
            Enclosure(href='http://example.com/enclosure-with-bad-length'),
        ),
        source=EntrySource(url='http://example.com/source.xml', title='Source Title'),
    ),
    EntryData(
        feed_url=feed.url,
        id='00000000-1655-4c27-aeee-00000000',
        updated=None,
        published=datetime.datetime(2009, 9, 6, 0, 0, 0, tzinfo=datetime.UTC),
        title='Example entry, again',
    ),
    EntryData(
        feed_url=feed.url,
        id='source:only-url',
        source=EntrySource(url='only-url'),
    ),
    EntryData(
        feed_url=feed.url,
        id='source:only-title',
        source=EntrySource(title='only-title'),
    ),
    EntryData(
        feed_url=feed.url,
        id='source:empty',
    ),
]
