import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url='{}relative.rss'.format(url_base), link='{}file.html'.format(rel_base)
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='7bd204c6-1655-4c27-aeee-53f933c5395f',
        updated=None,
        link='{}blog/post/1'.format(rel_base),
        summary='one <a href="{}target">two</a> three'.format(rel_base),
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
