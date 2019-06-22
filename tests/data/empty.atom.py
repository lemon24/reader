import datetime

from reader import Content
from reader import Enclosure
from reader import Entry
from reader import Feed


feed = Feed(url='{}empty.atom'.format(url_base))

entries = [
    Entry(
        id='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
        updated=None,
        # added by feedparser
        link='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
    )
]
