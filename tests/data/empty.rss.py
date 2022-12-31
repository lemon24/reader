import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(url=f'{url_base}empty.rss', version='rss20')

entries = [
    EntryData(
        feed_url=feed.url, id='7bd204c6-1655-4c27-aeee-53f933c5395f', updated=None
    )
]
