import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url='{}empty.json'.format(url_base),
)

entries = [
    EntryData(
        feed_url=feed.url,
        id='1',
        updated=None,
        content=(
            Content(
                value='content',
                type='text/plain',
            ),
        ),
    ),
]
