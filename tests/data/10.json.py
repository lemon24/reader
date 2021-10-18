import datetime

from reader import Content
from reader import Enclosure
from reader._types import EntryData
from reader._types import FeedData


feed = FeedData(
    url='{}10.json'.format(url_base),
    version='json10',
)

entries = []
