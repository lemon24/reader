import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url=f'{url_base}relative.rss',
    link=f'{rel_base}file.html',
    version='rss20',
)

entries = [
    EntryData(
        feed_url=feed.url,
        id=f'{rel_base}7bd204c6-1655-4c27-aeee-53f933c5395f',
        updated=None,
        link=f'{rel_base}blog/post/1',
        summary=f'one <a href="{rel_base}target">two</a> three',
        content=(
            Content(
                value='<script>evil</script> content', type='text/plain', language=None
            ),
            Content(value='content', type='text/html', language=None),
        ),
        enclosures=(
            # for RSS feedparser doesn't make relative links absolute
            # (it does for Atom)
            Enclosure(href='enclosure?q=a#fragment'),
        ),
    )
]
