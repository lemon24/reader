import datetime

from reader import Content
from reader import Enclosure
from reader import EntrySource
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url=f'{url_base}full.atom',
    updated=datetime.datetime(2003, 12, 13, 18, 30, 2, tzinfo=datetime.UTC),
    title='Example Feed',
    link='http://example.org/',
    author='John Doe',
    subtitle='all your examples are belong to us',
    version='atom10',
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
        updated=datetime.datetime(2003, 12, 13, 18, 30, 2, tzinfo=datetime.UTC),
        title='Atom-Powered Robots Run Amok',
        link='http://example.org/2003/12/13/atom03',
        author='John Doe',
        published=datetime.datetime(2003, 12, 13, 17, 17, 51, tzinfo=datetime.UTC),
        summary='Some text.',
        content=(
            # the text/plain type comes from feedparser
            Content(value='content', type='text/plain'),
            Content(value='content with type', type='text/whatever'),
            Content(value='content with lang', type='text/plain', language='en'),
        ),
        enclosures=(
            # the text/html type comes from feedparser
            Enclosure(href='http://example.org/enclosure', type='text/html'),
            Enclosure(
                href='http://example.org/enclosure-with-type', type='text/whatever'
            ),
            Enclosure(
                href='http://example.org/enclosure-with-length',
                type='text/html',
                length=1000,
            ),
            Enclosure(
                href='http://example.org/enclosure-with-bad-length', type='text/html'
            ),
        )
        + (
            # feedparser resolves empty href to the base,
            # but only for Atom, and only if the base has a scheme(?);
            # document this (somewhat pointless) behavior
            (Enclosure(href=feed.url, type='text/html'),)
            if feed.url.startswith('http')
            else ()
        ),
        source=EntrySource(
            url='http://example.org/source.xml',
            updated=datetime.datetime(2003, 12, 13, 18, 30, 2, tzinfo=datetime.UTC),
            title='Source Title',
            link='http://example.org/source',
            author='Source Author',
            subtitle='source subtitle',
        ),
    ),
    EntryData(
        feed_url=feed.url,
        id='urn:uuid:00000000-cfb8-4ebb-aaaa-00000000000',
        updated=datetime.datetime(2003, 12, 13, 0, 0, 0, tzinfo=datetime.UTC),
        title='Atom-Powered Robots Run Amok Again',
        # link comes from feedparser
        link='urn:uuid:00000000-cfb8-4ebb-aaaa-00000000000',
    ),
    EntryData(
        feed_url=feed.url,
        id='source:only-url',
        # link comes from feedparser
        link='source:only-url',
        source=EntrySource(url='only:url'),
    ),
    EntryData(
        feed_url=feed.url,
        id='source:only-title',
        # link comes from feedparser
        link='source:only-title',
        source=EntrySource(title='only-title'),
    ),
    EntryData(
        feed_url=feed.url,
        id='source:empty',
        # link comes from feedparser
        link='source:empty',
    ),
]
