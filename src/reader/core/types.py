from collections import namedtuple
from collections import OrderedDict
from datetime import datetime
from typing import Optional
from typing import Sequence

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

    #: The date the entry was last updated.
    updated: datetime

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

# TODO: Use type annotations for private API types.
# TODO: After deprecating 3.6, use typing.NamedTuple instead.


ParsedFeed = namedtuple('ParsedFeed', 'feed http_etag http_last_modified')

ParseResult = namedtuple('ParseResult', 'parsed_feed entries')


class ParseResult(ParseResult):

    __slots__ = ()

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


FeedForUpdate = namedtuple(
    'FeedForUpdate', 'url updated http_etag http_last_modified stale last_updated'
)

EntryForUpdate = namedtuple('EntryForUpdate', 'updated')


FeedUpdateIntent = namedtuple(
    'FeedUpdateIntent', 'url feed http_etag http_last_modified last_updated'
)

EntryUpdateIntent = namedtuple(
    'EntryUpdateIntent', 'url entry last_updated first_updated_epoch feed_order'
)
EntryUpdateIntent.__doc__ = """\
An entry with additional data to be passed to Storage when updating a feed.

Attributes:
    url (str): The feed URL.
    entry (Entry): The entry.
    last_updated (datetime):
        The time at the start of updating this feed (start of update_feed
        in update_feed, the start of each feed update in update_feeds).
    first_updated_epoch (datetime or None):
        The time at the start of updating this batch of feeds (start of
        update_feed in update_feed, start of update_feeds in update_feeds);
        None if the entry already exists.
    feed_order (int): The index of the entry in the feed (zero-based).

"""

UpdatedEntry = namedtuple('UpdatedEntry', 'entry new')

UpdateResult = namedtuple('UpdateResult', 'url entries')
