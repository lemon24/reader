import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url='{}relative.atom'.format(url_base), link='{}file.html'.format(rel_base)
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
        updated=None,
        link='{}entries/entry.html'.format(rel_base),
        summary='one <a href="{}target">two</a> three'.format(rel_base),
        content=(
            Content(
                value='<script>evil</script> content', type='text/plain', language=None
            ),
            Content(value='content', type='text/html', language=None),
        ),
        enclosures=(
            # the text/html type comes from feedparser
            Enclosure(
                href='{}enclosure?q=a#fragment'.format(rel_base), type='text/html'
            ),
        ),
    )
]
