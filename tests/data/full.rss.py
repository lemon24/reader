import datetime

from reader import Feed, Entry, Content, Enclosure


feed = Feed(
    url='full.rss',
    updated=datetime.datetime(2010, 9, 6, 0, 1),
    title='RSS Title',
    link='http://www.example.com/main.html',
    author='Example editor (me@example.com)',
)

entries = [
    Entry(
        id='7bd204c6-1655-4c27-aeee-53f933c5395f',
        updated=datetime.datetime(2009, 9, 6, 16, 20),
        title='Example entry',
        link='http://www.example.com/blog/post/1',
        author='Example editor',
        published=None,
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
    ),
    Entry(
        id='00000000-1655-4c27-aeee-00000000',
        updated=datetime.datetime(2009, 9, 6, 0, 0, 0),
        title='Example entry, again',
    ),
]

