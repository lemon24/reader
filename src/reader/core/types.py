from collections import OrderedDict
from collections import namedtuple
from typing import Sequence, Optional
from datetime import datetime

import attr


class attrs_namedtuple_compat:

    @classmethod
    def _make(cls, iterable):
        iterable = tuple(iterable)
        attrs_len = len(attr.fields(cls))
        if len(iterable) != attrs_len:
            raise TypeError('Expected %d arguments, got %d' % (attrs_len, len(iterable)))
        return cls(*iterable)

    def _replace(self, **kwargs):
        return attr.evolve(self, **kwargs)

    def _asdict(self, recurse=False):
        return attr.asdict(self, recurse=recurse, dict_factory=OrderedDict)


# Public API


@attr.s(slots=True, frozen=True)
class Feed(attrs_namedtuple_compat):

    """Data type representing a feed."""

    #: The URL of the feed.
    url = attr.ib(type=str)

    #: The date the feed was last updated.
    updated = attr.ib(type=Optional[datetime], default=None)

    #: The title of the feed.
    title = attr.ib(type=Optional[str], default=None)

    #: The URL of a page associated with the feed.
    link = attr.ib(type=Optional[str], default=None)

    #: The author of the feed.
    author = attr.ib(type=Optional[str], default=None)

    #: User-defined feed title.
    user_title = attr.ib(type=Optional[str], default=None)


@attr.s(slots=True, frozen=True)
class Entry(attrs_namedtuple_compat):

    """Data type representing an entry."""

    #: Entry identifier.
    id = attr.ib(type=str)

    #: The date the entry was last updated.
    updated = attr.ib(type=datetime)

    #: The title of the entry.
    title = attr.ib(type=Optional[str], default=None)

    #: The URL of a page associated with the entry.
    link = attr.ib(type=Optional[str], default=None)

    #: The author of the feed.
    author = attr.ib(type=Optional[str], default=None)

    #: The date the entry was first published.
    published = attr.ib(type=Optional[datetime], default=None)

    #: A summary of the entry.
    summary = attr.ib(type=Optional[str], default=None)

    #: Full content of the entry.
    #: A sequence of :class:`Content` objects.
    content = attr.ib(type=Sequence['Content'], default=())

    #: External files associated with the entry.
    #: A sequence of :class:`Enclosure` objects.
    enclosures = attr.ib(type=Sequence['Enclosure'], default=())

    #: Whether the entry was read or not.
    read = attr.ib(type=bool, default=False)

    #: The entry's feed.
    feed = attr.ib(type=Optional[Feed], default=None)


@attr.s(slots=True, frozen=True)
class Content(attrs_namedtuple_compat):

    """Data type representing a piece of content."""

    #: The content value.
    value = attr.ib(type=str)

    #: The content type.
    type = attr.ib(type=Optional[str], default=None)

    #: The content language.
    language = attr.ib(type=Optional[str], default=None)


@attr.s(slots=True, frozen=True)
class Enclosure(attrs_namedtuple_compat):

    """Data type representing an external file."""

    #: The file URL.
    href = attr.ib(type=str)

    #: The file content type.
    type = attr.ib(type=Optional[str], default=None)

    #: The file length.
    length = attr.ib(type=Optional[int], default=None)


# Private API
# https://github.com/lemon24/reader/issues/111

# TODO: Use type annotations for private API types.


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


FeedForUpdate = namedtuple('FeedForUpdate', 'url updated http_etag http_last_modified stale last_updated')
EntryForUpdate = namedtuple('EntryForUpdate', 'updated')


FeedUpdateIntent = namedtuple('FeedUpdateIntent', 'url feed http_etag http_last_modified last_updated')
EntryUpdateIntent = namedtuple('EntryUpdateIntent', 'url entry last_updated first_updated')

UpdatedEntry = namedtuple('UpdatedEntry', 'entry new')
UpdateResult = namedtuple('UpdateResult', 'url entries')


