from collections import OrderedDict
from datetime import datetime
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Sequence
from typing import Union

import attr


class attrs_namedtuple_compat:
    @classmethod
    def _make(cls, iterable):
        iterable = tuple(iterable)
        attrs_len = len(attr.fields(cls))
        if len(iterable) != attrs_len:
            raise TypeError(
                'Expected %d arguments, got %d' % (attrs_len, len(iterable))
            )
        return cls(*iterable)

    def _replace(self, **kwargs):
        return attr.evolve(self, **kwargs)

    def _asdict(self, recurse=False):
        return attr.asdict(self, recurse=recurse, dict_factory=OrderedDict)


# Public API


@attr.s(slots=True, frozen=True, auto_attribs=True)
class Feed(attrs_namedtuple_compat):

    """Data type representing a feed."""

    #: The URL of the feed.
    url: str

    #: The date the feed was last updated.
    updated: Optional[datetime] = None

    #: The title of the feed.
    title: Optional[str] = None

    #: The URL of a page associated with the feed.
    link: Optional[str] = None

    #: The author of the feed.
    author: Optional[str] = None

    #: User-defined feed title.
    user_title: Optional[str] = None


@attr.s(slots=True, frozen=True, auto_attribs=True)
class Entry(attrs_namedtuple_compat):

    """Data type representing an entry."""

    #: Entry identifier.
    id: str

    # Entries returned by the parser always have updated set.
    # I tried modeling this through typing, but it's too complicated.

    #: The date the entry was last updated.
    updated: Optional[datetime]

    #: The title of the entry.
    title: Optional[str] = None

    #: The URL of a page associated with the entry.
    link: Optional[str] = None

    #: The author of the feed.
    author: Optional[str] = None

    #: The date the entry was first published.
    published: Optional[datetime] = None

    #: A summary of the entry.
    summary: Optional[str] = None

    #: Full content of the entry.
    #: A sequence of :class:`Content` objects.
    content: Sequence['Content'] = ()

    #: External files associated with the entry.
    #: A sequence of :class:`Enclosure` objects.
    enclosures: Sequence['Enclosure'] = ()

    #: Whether the entry was read or not.
    read: bool = False

    #: Whether the entry is important or not.
    important: bool = False

    #: The entry's feed.
    feed: Optional[Feed] = None


@attr.s(slots=True, frozen=True, auto_attribs=True)
class Content(attrs_namedtuple_compat):

    """Data type representing a piece of content."""

    #: The content value.
    value: str

    #: The content type.
    type: Optional[str] = None

    #: The content language.
    language: Optional[str] = None


@attr.s(slots=True, frozen=True, auto_attribs=True)
class Enclosure(attrs_namedtuple_compat):

    """Data type representing an external file."""

    #: The file URL.
    href: str

    #: The file content type.
    type: Optional[str] = None

    #: The file length.
    length: Optional[int] = None


# Private API
# https://github.com/lemon24/reader/issues/111


class ParsedFeed(NamedTuple):

    feed: Feed
    http_etag: Optional[str]
    http_last_modified: Optional[str]


class ParseResult(NamedTuple):

    parsed_feed: ParsedFeed
    entries: Iterable[Entry]

    # compatibility

    @property
    def feed(self):
        return self.parsed_feed.feed

    @property
    def http_etag(self):
        return self.parsed_feed.http_etag

    @property
    def http_last_modified(self):
        return self.parsed_feed.http_last_modified


class FeedForUpdate(NamedTuple):

    url: str
    updated: datetime
    http_etag: Optional[str]
    http_last_modified: Optional[str]
    stale: bool
    last_updated: datetime


class EntryForUpdate(NamedTuple):

    updated: datetime


class FeedUpdateIntent(NamedTuple):

    url: str
    feed: Feed
    http_etag: Optional[str]
    http_last_modified: Optional[str]
    last_updated: datetime


class EntryUpdateIntent(NamedTuple):
    """An entry with additional data to be passed to Storage
    when updating a feed.

    """

    #: The feed URL.
    url: str

    #: The entry.
    entry: Entry

    #: The time at the start of updating this feed (start of update_feed
    #: in update_feed, the start of each feed update in update_feeds).
    last_updated: datetime

    #: The time at the start of updating this batch of feeds (start of
    #: update_feed in update_feed, start of update_feeds in update_feeds);
    #: None if the entry already exists.
    first_updated_epoch: Optional[datetime]

    #: The index of the entry in the feed (zero-based).
    feed_order: int


class UpdatedEntry(NamedTuple):

    entry: Entry
    new: bool


class UpdateResult(NamedTuple):

    #: The entries that were updated.
    entries: Iterable[UpdatedEntry]


# https://github.com/python/typing/issues/182
JSONValue = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]
JSONType = Union[Dict[str, JSONValue], List[JSONValue]]
