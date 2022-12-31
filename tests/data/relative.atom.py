import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url=f'{url_base}relative.atom',
    link=f'{rel_base}file.html',
    version='atom10',
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a',
        updated=None,
        link=f'{rel_base}entries/entry.html',
        summary=f'one <a href="{rel_base}target">two</a> three',
        content=(
            Content(
                value='<script>evil</script> content', type='text/plain', language=None
            ),
            Content(value='content', type='text/html', language=None),
        ),
        enclosures=(
            # the text/html type comes from feedparser
            Enclosure(href=f'{rel_base}enclosure?q=a#fragment', type='text/html'),
        ),
    )
]
