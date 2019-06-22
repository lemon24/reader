import datetime

from reader import Content
from reader import Enclosure
from reader import Entry
from reader import Feed


feed = Feed(url='{}relative.atom'.format(url_base), link='{}file.html'.format(rel_base))

entries = [
    Entry(
        id='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
        updated=None,
        link='{}entries/entry.html'.format(rel_base),
        enclosures=(
            # the text/html type comes from feedparser
            Enclosure(
                href='{}enclosure?q=a#fragment'.format(rel_base), type='text/html'
            ),
        ),
    )
]
