import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url=f'{url_base}full.json',
    updated=None,
    title='My Example Feed',
    link='https://example.org/',
    author='Joe',
    subtitle='The Best Example Feed',
    version='json11',
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='2',
        updated=datetime.datetime(2020, 1, 4, 0, 0, tzinfo=datetime.UTC),
        title="Title",
        link="https://example.org/second-item",
        author="mailto:joe@example.com",
        published=datetime.datetime(2020, 1, 2, 21, 0, tzinfo=datetime.UTC),
        summary="A summary",
        content=(
            Content(
                value='Content with <a href="http://example.com/">link</a>',
                type='text/html',
                language='de',
            ),
            Content(
                value='Content with no link',
                type='text/plain',
                language='de',
            ),
        ),
        enclosures=(
            Enclosure(
                href='http://example.com/downloads/file.m4a',
                type='audio/x-m4a',
                length=12345678,
            ),
            Enclosure(
                href='http://example.com/downloads/another.mp3', type=None, length=None
            ),
        ),
    ),
    EntryData(
        feed_url=feed.url,
        id='1',
        updated=None,
        title=None,
        link='https://example.org/initial-post',
        author='Jane',
        published=datetime.datetime(2020, 1, 2, 12, 0, tzinfo=datetime.UTC),
        summary=None,
        content=(
            Content(value='<p>Hello, world!</p>', type='text/html', language='en'),
        ),
        enclosures=(),
    ),
]
