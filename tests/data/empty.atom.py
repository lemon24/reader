import datetime

from reader import Feed, Entry, Content, Enclosure


feed = Feed(
    url='{}empty.atom'.format(url_base),
)

entries = [
    Entry(
        id='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
        updated=None,
        # added by feedparser
        link='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
    ),
]

