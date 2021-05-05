from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Generic
from typing import Iterable
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

from ._hash_utils import get_hash
from ._vendor.functools import cached_property
from .types import _entry_argument
from .types import _feed_argument
from .types import _namedtuple_compat
from .types import Content
from .types import Enclosure
from .types import Entry
from .types import EntryInput
from .types import ExceptionInfo
from .types import Feed
from .types import FeedInput
from .types import TagFilterInput

# Private API
# https://github.com/lemon24/reader/issues/111

# structure similar to
# https://github.com/lemon24/reader/issues/159#issuecomment-612512033


@dataclass(frozen=True)
class FeedData(_namedtuple_compat):

    """Feed data that comes from the feed.

    Attributes are a subset of those of Feed.

    """

    url: str
    updated: Optional[datetime] = None
    title: Optional[str] = None
    link: Optional[str] = None
    author: Optional[str] = None

    def as_feed(self, **kwargs: object) -> Feed:
        """For testing."""
        attrs = dict(self.__dict__)
        attrs.pop('hash', None)
        attrs.update(kwargs)
        return Feed(**attrs)

    @property
    def object_id(self) -> str:
        return self.url

    _hash_exclude_ = frozenset({'url', 'updated'})

    @cached_property
    def hash(self) -> bytes:
        return get_hash(self)


_UpdatedType = TypeVar('_UpdatedType', datetime, Optional[datetime])


@dataclass(frozen=True)
class EntryData(Generic[_UpdatedType], _namedtuple_compat):

    """Entry data that comes from the feed.

    Attributes are a subset of those of Entry.

    The natural thing to use would have been generics, but pleasing Python,
    mypy and Sphinx all at the same time is not possible at the moment,
    and the workarounds are just as bad or worse.

    We should be able to use generics once/if this is resolved:
    https://github.com/sphinx-doc/sphinx/issues/7450

    ...however, it may be better to just have entry be a separate
    plain dataclass -- help(Entry) works weird with concrete generics.

    We can't subclass Entry because the attribute types become less specific.

    We can't use a subclass for the common attributes because it confuses
    Sphinx: https://github.com/sphinx-doc/sphinx/issues/741

    An implementation using generics is available here:
    https://github.com/lemon24/reader/blob/62eb72563b94d78d8860519424103e3c3c1c013d/src/reader/core/types.py#L78-L241

    """

    #: The feed URL.
    feed_url: str

    # WARNING: When changing attributes, keep Entry and EntryData in sync.

    id: str

    # Entries returned by the parser have .updated Optional[datetime];
    # entries sent to the storage always have .updatd set (not optional).
    updated: _UpdatedType

    title: Optional[str] = None
    link: Optional[str] = None
    author: Optional[str] = None
    published: Optional[datetime] = None
    summary: Optional[str] = None
    content: Sequence[Content] = ()
    enclosures: Sequence[Enclosure] = ()

    def as_entry(self, **kwargs: object) -> Entry:
        """For testing."""
        attrs = dict(self.__dict__)
        feed_url = attrs.pop('feed_url')
        attrs.pop('hash', None)
        attrs.update(kwargs)
        attrs.setdefault('original_feed_url', feed_url)
        return Entry(**attrs)

    @property
    def object_id(self) -> Tuple[str, str]:
        return self.feed_url, self.id

    _hash_exclude_ = frozenset({'feed_url', 'id', 'updated'})

    @cached_property
    def hash(self) -> bytes:
        return get_hash(self)


class ParsedFeed(NamedTuple):

    feed: FeedData
    # TODO: wrap entries in iter(entries) to ensure stuff doesn't rely on it being a list
    entries: Iterable[EntryData[Optional[datetime]]]
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None


class FeedForUpdate(NamedTuple):

    """Update-relevant information about an exiting feed, from Storage."""

    url: str

    #: The date the feed was last updated, according to the feed.
    updated: Optional[datetime]

    http_etag: Optional[str]
    http_last_modified: Optional[str]

    #: Whether the next update should update *all* entries,
    #: regardless of their .updated.
    stale: bool

    #: The date the feed was last updated, according to reader; none if never.
    last_updated: Optional[datetime]

    #: Whether the feed had an exception at the last update.
    last_exception: bool

    #: The hash of the corresponding FeedData.
    hash: Optional[bytes]


class EntryForUpdate(NamedTuple):

    """Update-relevant information about an existing entry, from Storage."""

    #: The date the entry was last updated, according to the entry.
    updated: datetime

    #: The hash of the corresponding EntryData.
    hash: Optional[bytes]

    #: The number of updates due to a different ``hash``
    #: since the last time ``updated`` changed.
    hash_changed: Optional[int]


class FeedUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

    url: str

    #: The time at the start of updating this feed.
    last_updated: Optional[datetime]

    feed: Optional[FeedData] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None

    # TODO: Is there a better way of modeling/enforcing these? A sort of tagged union, maybe? (last_updated should be non-optional then)

    #: Cause of ParseError, if any; if set, everything else except url should be None.
    last_exception: Optional[ExceptionInfo] = None


class EntryUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

    #: The entry.
    entry: EntryData[datetime]

    #: The time at the start of updating this feed (start of update_feed
    #: in update_feed, the start of each feed update in update_feeds).
    last_updated: datetime

    #: The time at the start of updating this batch of feeds (start of
    #: update_feed in update_feed, start of update_feeds in update_feeds);
    #: None if the entry already exists.
    first_updated_epoch: Optional[datetime]

    #: The index of the entry in the feed (zero-based).
    feed_order: int

    #: Same as EntryForUpdate.hash_changed.
    hash_changed: Optional[int]

    @property
    def new(self) -> bool:
        """Whether the entry is new or not."""
        return self.first_updated_epoch is not None


# TODO: these should probably be in storage.py (along with some of the above)


TagFilter = Sequence[Sequence[Union[bool, Tuple[bool, str]]]]


def tag_filter_argument(tags: TagFilterInput, name: str = 'tags') -> TagFilter:
    if tags is None:
        return []
    if isinstance(tags, bool):
        return [[tags]]
    if not isinstance(tags, Sequence) or isinstance(tags, str):
        raise ValueError(f"{name} must be none, bool, or a non-string sequence")

    def normalize_tag(tag: Union[str, bool]) -> Union[bool, Tuple[bool, str]]:
        if isinstance(tag, bool):
            return tag

        if not isinstance(tag, str):
            raise ValueError(
                f"the elements of {name} must be strings, bool or string/bool sequences"
            )

        is_negation = False
        if tag.startswith('-'):
            is_negation = True
            tag = tag[1:]

        if not tag:
            raise ValueError("tag strings must be non-empty")

        return is_negation, tag

    rv = []
    for subtags in tags:
        if isinstance(subtags, (bool, str)):
            rv.append([normalize_tag(subtags)])
            continue

        if not isinstance(subtags, Sequence):
            raise ValueError(
                f"the elements of {name} must be strings, bool or string/bool sequences"
            )

        if not subtags:
            continue

        rv.append(list(map(normalize_tag, subtags)))

    return rv


_EFO = TypeVar('_EFO', bound='EntryFilterOptions')


class EntryFilterOptions(NamedTuple):

    """Options for filtering the results of the "get entry" storage methods."""

    feed_url: Optional[str] = None
    entry_id: Optional[str] = None
    read: Optional[bool] = None
    important: Optional[bool] = None
    has_enclosures: Optional[bool] = None
    feed_tags: TagFilter = ()

    @classmethod
    def from_args(
        cls: Type[_EFO],
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        feed_tags: TagFilterInput = None,
    ) -> _EFO:
        feed_url = _feed_argument(feed) if feed is not None else None

        # TODO: should we allow specifying both feed and entry?
        if entry is None:
            entry_id = None
        else:
            feed_url, entry_id = _entry_argument(entry)

        if read not in (None, False, True):
            raise ValueError("read should be one of (None, False, True)")
        if important not in (None, False, True):
            raise ValueError("important should be one of (None, False, True)")
        if has_enclosures not in (None, False, True):
            raise ValueError("has_enclosures should be one of (None, False, True)")

        feed_tag_filter = tag_filter_argument(feed_tags, 'feed_tags')

        return cls(feed_url, entry_id, read, important, has_enclosures, feed_tag_filter)


_FFO = TypeVar('_FFO', bound='FeedFilterOptions')


class FeedFilterOptions(NamedTuple):

    """Options for filtering the results of the "get feed" storage methods."""

    feed_url: Optional[str] = None
    tags: TagFilter = ()
    broken: Optional[bool] = None
    updates_enabled: Optional[bool] = None

    @classmethod
    def from_args(
        cls: Type[_FFO],
        feed: Optional[FeedInput] = None,
        tags: TagFilterInput = None,
        broken: Optional[bool] = None,
        updates_enabled: Optional[bool] = None,
    ) -> _FFO:
        feed_url = _feed_argument(feed) if feed is not None else None
        tag_filter = tag_filter_argument(tags)

        if broken not in (None, False, True):
            raise ValueError("broken should be one of (None, False, True)")
        if updates_enabled not in (None, False, True):
            raise ValueError("updates_enabled should be one of (None, False, True)")

        return cls(feed_url, tag_filter, broken, updates_enabled)


@dataclass(frozen=True)
class NameScheme(_namedtuple_compat):
    reader_prefix: str
    plugin_prefix: str
    separator: str

    @classmethod
    def from_value(cls, value: Mapping[str, str]) -> 'NameScheme':
        # Use is validation.
        self = cls(**value)
        self.make_reader_name('key')
        self.make_plugin_name('name', 'key')
        return self

    def make_reader_name(self, key: str) -> str:
        return self.reader_prefix + key

    def make_plugin_name(self, plugin_name: str, key: Optional[str] = None) -> str:
        rv = self.plugin_prefix + plugin_name
        if key is not None:
            rv += self.separator + key
        return rv


DEFAULT_RESERVED_NAME_SCHEME = MappingProxyType(
    {
        'reader_prefix': '.reader.',
        'plugin_prefix': '.plugin.',
        'separator': '.',
    }
)
