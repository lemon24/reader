import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url=f'{url_base}unknown.json',
    version='json',
)

entries = []
