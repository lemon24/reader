from __future__ import annotations

import logging
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from enum import Enum
from functools import cached_property
from types import MappingProxyType
from types import SimpleNamespace
from typing import Any
from typing import Generic
from typing import get_args
from typing import Literal
from typing import NamedTuple
from typing import overload
from typing import Protocol
from typing import runtime_checkable
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

from ._hash_utils import get_hash
from .exceptions import SingleUpdateHookError
from .exceptions import UpdateHookError
from .exceptions import UpdateHookErrorGroup
from .types import _entry_argument
from .types import _feed_argument
from .types import _namedtuple_compat
from .types import AnyResourceId
from .types import Content
from .types import Enclosure
from .types import Entry
from .types import EntryAddedBy
from .types import EntryCounts
from .types import EntryInput
from .types import EntrySearchCounts
from .types import EntrySearchResult
from .types import EntrySort
from .types import ExceptionInfo
from .types import Feed
from .types import FeedCounts
from .types import FeedInput
from .types import FeedSort
from .types import JSONType
from .types import MISSING
from .types import MissingType
from .types import ResourceId
from .types import SearchSortOrder
from .types import TagFilterInput
from .types import TristateFilterInput

if TYPE_CHECKING:  # pragma: no cover
    from typing_extensions import Self


log = logging.getLogger("reader")

# Private API
# https://github.com/lemon24/reader/issues/111

# structure similar to
# https://github.com/lemon24/reader/issues/159#issuecomment-612512033


_T = TypeVar('_T')


@dataclass(frozen=True)
class FeedData(_namedtuple_compat):

    """Feed data that comes from the feed.

    Attributes are a subset of those of :class:`~reader.Feed`.

    """

    url: str
    updated: datetime | None = None
    title: str | None = None
    link: str | None = None
    author: str | None = None
    subtitle: str | None = None
    version: str | None = None

    def as_feed(self, **kwargs: object) -> Feed:
        """Convert this to a feed; kwargs override attributes.

        Returns:
            :class:`~reader.Feed`.

        """
        attrs = dict(self.__dict__)
        attrs.pop('hash', None)
        attrs.update(kwargs)
        return Feed(**attrs)

    @property
    def resource_id(self) -> tuple[str]:
        return (self.url,)

    _hash_exclude_ = frozenset({'url', 'updated'})

    @cached_property
    def hash(self) -> bytes:
        return get_hash(self)


@dataclass(frozen=True)
class EntryData(_namedtuple_compat):

    """Entry data that comes from the feed.

    Attributes are a subset of those of :class:`~reader.Entry`.

    """

    # This is not generic anymore, as of 2.5, and will likely never be.
    #
    # TODO: Make Entry a subclass of EntryData, make Feed a subclass of FeedData.
    #
    # It may still not be possible to use it as a subclass, though, because:
    #
    # * help(Entry) may not work
    # * Sphinx/autodoc may not work: https://github.com/sphinx-doc/sphinx/issues/741 (closed)
    # * as_entry(), hash() must not be inherited

    feed_url: str

    # WARNING: When changing attributes, keep Entry, EntryData, and entry_data_from_obj in sync.

    id: str
    updated: datetime | None = None
    title: str | None = None
    link: str | None = None
    author: str | None = None
    published: datetime | None = None
    summary: str | None = None
    content: Sequence[Content] = ()
    enclosures: Sequence[Enclosure] = ()

    def as_entry(self, **kwargs: object) -> Entry:
        """Convert this to an entry; kwargs override attributes.

        Returns:
            :class:`~reader.Entry`.

        """
        attrs = dict(self.__dict__)
        feed_url = attrs.pop('feed_url')
        attrs.pop('hash', None)
        attrs.update(kwargs)
        attrs.setdefault('original_feed_url', feed_url)
        attrs.setdefault('added_by', 'feed')
        return Entry(**attrs)

    @property
    def resource_id(self) -> tuple[str, str]:
        return self.feed_url, self.id

    _hash_exclude_ = frozenset({'feed_url', 'id', 'updated'})

    @cached_property
    def hash(self) -> bytes:
        return get_hash(self)


def entry_data_from_obj(obj: object) -> EntryData:
    """Union[EntryDataLikeProtocol, EntryDataTypedDict] -> EntryData

    Naive datetimes are normalized by passing them to
    :meth:`~datetime.datetime.astimezone`.

    """
    if isinstance(obj, Mapping):
        obj = SimpleNamespace(**obj)
    return EntryData(
        feed_url=_getattr(obj, 'feed_url', str),
        id=_getattr(obj, 'id', str),
        updated=_getattr_optional_datetime(obj, 'updated'),
        title=_getattr_optional(obj, 'title', str),
        link=_getattr_optional(obj, 'link', str),
        author=_getattr_optional(obj, 'author', str),
        published=_getattr_optional_datetime(obj, 'published'),
        summary=_getattr_optional(obj, 'summary', str),
        content=tuple(content_from_obj(o) for o in getattr(obj, 'content', ())),
        enclosures=tuple(enclosure_from_obj(o) for o in getattr(obj, 'enclosures', ())),
    )


def content_from_obj(obj: object) -> Content:
    if isinstance(obj, Mapping):
        obj = SimpleNamespace(**obj)
    return Content(
        value=_getattr(obj, 'value', str),
        type=_getattr_optional(obj, 'type', str),
        language=_getattr_optional(obj, 'language', str),
    )


def enclosure_from_obj(obj: object) -> Enclosure:
    if isinstance(obj, Mapping):
        obj = SimpleNamespace(**obj)
    return Enclosure(
        href=_getattr(obj, 'href', str),
        type=_getattr_optional(obj, 'type', str),
        length=_getattr_optional(obj, 'length', int),
    )


def _getattr(obj: object, name: str, type: type[_T]) -> _T:
    # will raise AttributeError implicitly
    value = getattr(obj, name)
    if not isinstance(value, type):
        raise TypeError(
            f"bad type for {name}; expected {type.__name__} instance, got {value!r}"
        )
    return value


def _getattr_optional(obj: object, name: str, type: type[_T]) -> _T | None:
    value = getattr(obj, name, None)
    if value is None:
        return value
    if not isinstance(value, type):
        raise TypeError(
            f"bad type for {name}; expected {type.__name__} instance, got {value!r}"
        )
    return value


def _getattr_optional_datetime(obj: object, name: str) -> datetime | None:
    value = _getattr_optional(obj, name, datetime)
    if value is None:
        return value
    return value.astimezone(timezone.utc)


class ParsedFeed(NamedTuple):
    """A parsed feed."""

    #: The feed.
    feed: FeedData
    # TODO: wrap entries in iter(entries) to ensure stuff doesn't rely on it being a list
    # TODO: make entries a list (may simplify _update code)
    #: Iterable of entries.
    entries: Iterable[EntryData]
    #: The HTTP ``ETag`` header associated with the feed resource.
    #: Passed back to the retriever on the next update.
    http_etag: str | None = None
    #: The HTTP ``Last-Modified`` header associated with the feed resource.
    #: Passed back to the retriever on the next update.
    http_last_modified: str | None = None
    #: The MIME type of the feed resource.
    #: Used by :meth:`~reader._parser.Parser.process_entry_pairs`
    #: to select an appropriate parser.
    mime_type: str | None = None


class FeedForUpdate(NamedTuple):

    """Update-relevant information about an existing feed, from Storage."""

    #: The feed URL.
    url: str

    #: The date the feed was last updated, according to the feed.
    updated: datetime | None

    #: The HTTP ``ETag`` header from the last update.
    http_etag: str | None

    #: The HTTP ``Last-Modified`` header from the last update.
    http_last_modified: str | None

    #: Whether the next update should update *all* entries,
    #: regardless of their :attr:`hash` or :attr:`updated`.
    stale: bool

    #: The date the feed was last updated, according to reader; none if never.
    last_updated: datetime | None

    #: Whether the feed had an exception at the last update.
    last_exception: bool

    #: The :attr:`~FeedData.hash` of the corresponding FeedData.
    hash: bytes | None


class EntryForUpdate(NamedTuple):

    """Update-relevant information about an existing entry, from Storage."""

    #: The date the entry was last updated, according to the entry.
    updated: datetime | None

    #: The date the entry was published, according to the entry.
    published: datetime | None

    #: The :attr:`~EntryData.hash` of the corresponding EntryData.
    hash: bytes | None

    #: The number of updates due to a different ``hash``
    #: since the last time ``updated`` changed.
    hash_changed: int | None


class FeedUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

    #: The feed URL.
    url: str

    #: The time at the start of updating this feed.
    last_updated: datetime | None

    #: The feed data, if any.
    feed: FeedData | None = None

    #: The feed's ``ETag`` header;
    #: see :attr:`ParsedFeed.http_etag` for details.
    #:
    #: .. admonition:: Unstable
    #:
    #:  :attr:`http_etag` and :attr:`http_last_modified`
    #:  may be grouped in a single attribute in the future.
    #:
    http_etag: str | None = None

    #: The feed's ``Last-Modified`` header;
    #: see :attr:`ParsedFeed.http_last_modified` for details.
    http_last_modified: str | None = None

    # TODO: Is there a better way of modeling/enforcing these? A sort of tagged union, maybe? (last_updated should be non-optional then)

    #: Cause of :exc:`.UpdateError`, if any;
    #: if set, everything else except :attr:`url` should be :const:`None`.
    last_exception: ExceptionInfo | None = None


class EntryUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

    #: The entry data.
    entry: EntryData

    #: The time at the start of updating the feed
    #: (start of :meth:`~.Reader.update_feed` in :meth:`~.Reader.update_feed`,
    #: start of each feed update in :meth:`~.Reader.update_feeds`).
    last_updated: datetime

    #: First :attr:`last_updated` (sets :attr:`.Entry.added`).
    #: :const:`None` if the entry already exists.
    first_updated: datetime | None

    #: The time at the start of updating this batch of feeds
    #: (start of :meth:`~.Reader.update_feed` in :meth:`~.Reader.update_feed`,
    #: start of :meth:`~.Reader.update_feeds` in :meth:`~.Reader.update_feeds`).
    #: :const:`None` if the entry already exists.
    first_updated_epoch: datetime | None

    #: Sort key for the :meth:`~.Reader.get_entries` ``recent`` sort order.
    recent_sort: datetime | None

    #: The index of the entry in the feed (zero-based).
    feed_order: int = 0

    #: Same as :attr:`EntryForUpdate.hash_changed`.
    hash_changed: int | None = 0

    #: Same as :attr:`.Entry.added_by`.
    added_by: EntryAddedBy = 'feed'

    @property
    def new(self) -> bool:
        """Whether the entry is new or not."""
        return self.first_updated_epoch is not None


#: Like the ``tags`` argument of :meth:`.Reader.get_feeds`, except:
#:
#: * only the full mutiple-tags-with-disjunction form is used
#: * tags are represented as *(is negated, tag name)* tuples
#:   (the ``-`` prefix is stripped)
#:
#: Assuming a ``tag_filter_argument()`` function
#: that converts :meth:`~.Reader.get_feeds` tags to :data:`TagFilter`:
#:
#: >>> tag_filter_argument(['one'])
#: [[(False, 'one')]]
#: >>> tag_filter_argument(['one', 'two'])
#: [[(False, 'one')], [(False, 'two')]]
#: >>> tag_filter_argument([['one', 'two']])
#: [[(False, 'one'), (False, 'two')]]
#: >>> tag_filter_argument(['one', '-two'])
#: [[(False, 'one')], [(True, 'two')]]
#: >>> tag_filter_argument(True)
#: [[True]]
#:
TagFilter = Sequence[Sequence[Union[bool, tuple[bool, str]]]]


def tag_filter_argument(tags: TagFilterInput, name: str = 'tags') -> TagFilter:
    if tags is None:
        return []
    if isinstance(tags, bool):
        return [[tags]]
    if not isinstance(tags, Sequence) or isinstance(tags, str):
        raise ValueError(f"{name} must be none, bool, or a non-string sequence")

    def normalize_tag(tag: str | bool) -> bool | tuple[bool, str]:
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
            subtags = [subtags]
        elif not isinstance(subtags, Sequence):
            raise ValueError(
                f"the elements of {name} must be strings, bool or string/bool sequences"
            )

        if not subtags:
            continue

        rv.append(list(map(normalize_tag, subtags)))

    return unique_tags(rv)


def unique_tags(tags: TagFilter) -> TagFilter:
    # ಠ_ಠ this wouldn't be needed if we used frozensets
    # (but they make examples and tests look bad)

    rv = []
    rv_seen = set()

    for subtags in tags:
        subtags_rv = []
        subtags_seen = set()
        for tag in subtags:
            if tag not in subtags_seen:
                subtags_rv.append(tag)
                subtags_seen.add(tag)

        subtags_seen_frozen = frozenset(subtags_seen)
        if subtags_seen_frozen not in rv_seen:
            rv.append(subtags_rv)
            rv_seen.add(subtags_seen_frozen)

    return rv


#: Like :data:`.TristateFilterInput`, but without bool/None aliases.
TristateFilter = Literal[
    'istrue',
    'isfalse',
    'notset',
    'nottrue',
    'notfalse',
    'isset',
    'any',
]


def tristate_filter_argument(value: TristateFilterInput, name: str) -> TristateFilter:
    # https://github.com/lemon24/reader/issues/254#issuecomment-1435648359
    if value is None:
        return 'any'
    if value == True:  # noqa: E712
        return 'istrue'
    if value == False:  # noqa: E712
        return 'nottrue'
    args = get_args(TristateFilter)
    if value in args:
        return value
    raise ValueError(f"{name} must be none, bool, or one of {args}")


class EntryFilter(NamedTuple):

    """Options for filtering the results entry list operations.

    See the :meth:`.Reader.get_entries()` docstring for detailed semantics.

    """

    feed_url: str | None = None
    entry_id: str | None = None
    read: bool | None = None
    important: TristateFilter = 'any'
    has_enclosures: bool | None = None
    tags: TagFilter = ()
    feed_tags: TagFilter = ()

    @classmethod
    def from_args(
        cls,
        feed: FeedInput | None = None,
        entry: EntryInput | None = None,
        read: bool | None = None,
        important: TristateFilterInput = None,
        has_enclosures: bool | None = None,
        tags: TagFilterInput = None,
        feed_tags: TagFilterInput = None,
    ) -> Self:
        feed_url = _feed_argument(feed) if feed is not None else None

        # TODO: should we allow specifying both feed and entry?
        if entry is None:
            entry_id = None
        else:
            feed_url, entry_id = _entry_argument(entry)

        if read not in (None, False, True):
            raise ValueError("read should be one of (None, False, True)")

        important_filter = tristate_filter_argument(important, 'important')
        if has_enclosures not in (None, False, True):
            raise ValueError("has_enclosures should be one of (None, False, True)")

        tag_filter = tag_filter_argument(tags)
        feed_tag_filter = tag_filter_argument(feed_tags, 'feed_tags')

        return cls(
            feed_url,
            entry_id,
            read,
            important_filter,
            has_enclosures,
            tag_filter,
            feed_tag_filter,
        )


class FeedFilter(NamedTuple):

    """Options for filtering the results feed list operations.

    See the :meth:`.Reader.get_feeds()` docstring for detailed semantics.

    """

    feed_url: str | None = None
    tags: TagFilter = ()
    broken: bool | None = None
    updates_enabled: bool | None = None
    new: bool | None = None

    @classmethod
    def from_args(
        cls,
        feed: FeedInput | None = None,
        tags: TagFilterInput = None,
        broken: bool | None = None,
        updates_enabled: bool | None = None,
        new: bool | None = None,
    ) -> Self:
        feed_url = _feed_argument(feed) if feed is not None else None
        tag_filter = tag_filter_argument(tags)

        if broken not in (None, False, True):
            raise ValueError("broken should be one of (None, False, True)")
        if updates_enabled not in (None, False, True):
            raise ValueError("updates_enabled should be one of (None, False, True)")
        if new not in (None, False, True):
            raise ValueError("new should be one of (None, False, True)")

        return cls(feed_url, tag_filter, broken, updates_enabled, new)


@dataclass(frozen=True)
class NameScheme(_namedtuple_compat):
    reader_prefix: str
    plugin_prefix: str
    separator: str

    @classmethod
    def from_value(cls, value: Mapping[str, str]) -> Self:
        # Use is validation.
        self = cls(**value)
        self.make_reader_name('key')
        self.make_plugin_name('name', 'key')
        return self

    def make_reader_name(self, key: str) -> str:
        return self.reader_prefix + key

    def make_plugin_name(self, plugin_name: str, key: str | None = None) -> str:
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


UpdateHook = Callable[..., None]
UpdateHookType = Literal[
    'before_feeds_update',
    'before_feed_update',
    'after_entry_update',
    'after_feed_update',
    'after_feeds_update',
]


class UpdateHooks(dict[UpdateHookType, list[UpdateHook]], Generic[_T]):
    def __init__(self, target: _T):
        super().__init__()
        self.target = target

    def __missing__(self, key: UpdateHookType) -> list[UpdateHook]:
        return self.setdefault(key, [])

    def run(
        self, when: UpdateHookType, resource_id: tuple[str, ...] | None, *args: Any
    ) -> None:
        for hook in self[when]:
            try:
                hook(self.target, *args)
            except Exception as e:
                raise SingleUpdateHookError(when, hook, resource_id) from e

    def group(self, message: str) -> _UpdateHookErrorGrouper:
        return _UpdateHookErrorGrouper(self, message)


class _UpdateHookErrorGrouper:
    def __init__(self, hooks: UpdateHooks[Any], message: str):
        self.hooks = hooks
        self.message = message
        self.exceptions: list[UpdateHookError] = []
        self.seen_dedupe_keys: set[Any] = set()

    def run(
        self,
        when: UpdateHookType,
        resource_id: tuple[str, ...] | None,
        *args: Any,
        limit: int = 0,
    ) -> None:
        for hook in self.hooks[when]:
            try:
                hook(self.hooks.target, *args)
            except Exception as e:
                exc = SingleUpdateHookError(when, hook, resource_id)
                exc.__cause__ = e
                self.add(exc, resource_id, limit)

    def add(self, exc: UpdateHookError, dedupe_key: Any = None, limit: int = 0) -> None:
        if limit and dedupe_key not in self.seen_dedupe_keys:  # pragma: no cover
            if len(self.seen_dedupe_keys) >= limit:
                log.error("too many hook errors; discarding exception", exc_info=exc)
                return
            self.seen_dedupe_keys.add(dedupe_key)
        self.exceptions.append(exc)

    def close(self) -> None:
        if self.exceptions:
            raise UpdateHookErrorGroup(self.message, self.exceptions)


class StorageType(Protocol):  # pragma: no cover
    r"""Storage DAO protocol.

    For methods with :class:`.Reader` correspondents,
    see the Reader docstrings for detailed semantics.

    Any method can raise :exc:`.StorageError`.

    The behaviors described in :ref:`lifecycle` and :ref:`threading`
    are implemented at the storage level; specifically:

    * The storage can be used directly, without :meth:`__enter__`\ing it.
      There is no guarantee :meth:`close` will be called at the end.
    * The storage can be reused after :meth:`__exit__` / :meth:`close`.
    * The storage can be used from multiple threads,
      either directly, or as a context manager.
      Closing the storage in one thread should not close it in another thread.

    Schema migrations are transparent to :class:`.Reader`.
    The current storage implementation does them at initialization,
    but others may require them to happen out-of-band with user intervention.

    All :class:`~datetime.datetime` attributes
    of all parameters and return values are timezone-aware,
    with the timezone set to :attr:`~datetime.timezone.utc`.

    .. admonition:: Unstable

        In the future, implementations will be required
        to accept datetimes with any timezone.

    Methods, grouped by topic:

    object lifecycle
        :meth:`__enter__`
        :meth:`__exit__`
        :meth:`close`

    feeds
        :meth:`add_feed`
        :meth:`delete_feed`
        :meth:`change_feed_url`
        :meth:`get_feeds`
        :meth:`get_feed_counts`
        :meth:`set_feed_user_title`
        :meth:`set_feed_updates_enabled`

    entries
        :meth:`add_entry`
        :meth:`delete_entries`
        :meth:`get_entries`
        :meth:`get_entry_counts`
        :meth:`set_entry_read`
        :meth:`set_entry_important`

    tags
        :meth:`get_tags`
        :meth:`set_tag`
        :meth:`delete_tag`

    update
        :meth:`get_feeds_for_update`
        :meth:`update_feed`
        :meth:`set_feed_stale`
        :meth:`get_entries_for_update`
        :meth:`add_or_update_entries`
        :meth:`get_entry_recent_sort`
        :meth:`set_entry_recent_sort`

    """

    def __enter__(self) -> None:
        """Called when :class:`.Reader` is used as a context manager."""

    def __exit__(self, *_: Any) -> None:
        """Called when :class:`.Reader` is used as a context manager."""

    def close(self) -> None:
        """Called by :meth:`.Reader.close`."""

    def add_feed(self, url: str, /, added: datetime) -> None:
        """Called by :meth:`.Reader.add_feed`.

        Args:
            url
            added: :attr:`.Feed.added`

        Raises:
            FeedExistsError

        """

    def delete_feed(self, url: str, /) -> None:
        """Called by :meth:`.Reader.delete_feed`.

        Args:
            url

        Raises:
            FeedNotFoundError

        """

    def change_feed_url(self, old: str, new: str, /) -> None:
        """Called by :meth:`.Reader.change_feed_url`.

        Args:
            old
            new

        Raises:
            FeedNotFoundError

        """

    def get_feeds(
        self,
        filter: FeedFilter,
        sort: FeedSort,
        limit: int | None,
        starting_after: str | None,
    ) -> Iterable[Feed]:
        """Called by :meth:`.Reader.get_feeds`.

        Args:
            filter
            sort
            limit
            starting_after

        Returns:
            A lazy iterable.

        Raises:
            FeedNotFoundError: If ``starting_after`` does not exist.

        """

    def get_feed_counts(self, filter: FeedFilter) -> FeedCounts:
        """Called by :meth:`.Reader.get_feed_counts`.

        Args:
            filter

        Returns:
            The counts.

        """

    def set_feed_user_title(self, url: str, title: str | None, /) -> None:
        """Called by :meth:`.Reader.set_feed_user_title`.

        Args:
            url
            title

        Raises:
            FeedNotFoundError

        """

    def set_feed_updates_enabled(self, url: str, enabled: bool, /) -> None:
        """Called by :meth:`.Reader.enable_feed_updates` and
        :meth:`.Reader.disable_feed_updates`.

        Args:
            url
            enabled

        Raises:
            FeedNotFoundError

        """

    def add_entry(self, intent: EntryUpdateIntent, /) -> None:
        """Called by :meth:`.Reader.add_entry`.

        Args:
            intent

        Raises:
            EntryExistsError
            FeedNotFoundError

        """

    def delete_entries(
        self, entries: Iterable[tuple[str, str]], /, *, added_by: str | None
    ) -> None:
        r"""Called by :meth:`.Reader.delete_entry`.

        Also called by plugins like :mod:`.entry_dedupe`.

        Args:
            entries:
                A list of :attr:`.Entry.resource_id`\s.
            added_by:
                If given, only delete the entries if their
                :attr:`~.Entry.added_by` is equal to this.

        Raises:
            EntryNotFoundError: An entry does not exist.
            EntryError: An entry ``added_by`` is different from the given one.

        """

    def get_entries(
        self,
        filter: EntryFilter,
        sort: EntrySort,
        limit: int | None,
        starting_after: tuple[str, str] | None,
    ) -> Iterable[Entry]:
        """Called by :meth:`.Reader.get_entries`.

        Args:
            filter
            sort
            limit
            starting_after

        Returns:
            A lazy iterable.

        Raises:
            EntryNotFoundError: If ``starting_after`` does not exist.

        """

    def get_entry_counts(self, now: datetime, filter: EntryFilter) -> EntryCounts:
        """Called by :meth:`.Reader.get_entry_counts`.

        .. admonition:: Unstable

            In order to expose better feed interaction statistics,
            this method will need to return more granular data.

        .. admonition:: Unstable

            In order to support :meth:`~SearchType.search_entry_counts`
            of search implementations that are not bound to a storage,
            this method will need to take an ``entries`` argument.

        Args:
            now: Time :attr:`~.EntryCounts.averages` is relative to.
            filter

        Returns:
            The counts.

        """

    def set_entry_read(
        self,
        entry: tuple[str, str],
        read: bool,
        modified: datetime | None,
        /,
    ) -> None:
        """Called by :meth:`.Reader.set_entry_read`.

        Args:
            entry
            read
            modified

        Raises:
            EntryNotFoundError

        """

    def set_entry_important(
        self,
        entry: tuple[str, str],
        important: bool | None,
        modified: datetime | None,
        /,
    ) -> None:
        """Called by :meth:`.Reader.set_entry_important`.

        Args:
            entry
            important
            modified

        Raises:
            EntryNotFoundError

        """

    def get_tags(
        self, resource_id: AnyResourceId, key: str | None = None, /  # noqa: W504
    ) -> Iterable[tuple[str, JSONType]]:
        """Called by :meth:`.Reader.get_tags`.

        Also called by :meth:`.Reader.get_tag_keys`.

        .. admonition:: Unstable

            A dedicated ``get_tag_keys()`` method will be added in the future.

        .. admonition:: Unstable

            Both this method and ``get_tag_keys()`` will allow filtering by prefix (include/exclude),
            case sensitive and insensitive; implementations should allow for this.

        Args:
            resource_id
            key

        Returns:
            A lazy iterable.

        """

    @overload
    def set_tag(self, resource_id: ResourceId, key: str, /) -> None:  # pragma: no cover
        ...

    @overload
    def set_tag(
        self, resource_id: ResourceId, key: str, value: JSONType, /  # noqa: W504
    ) -> None:  # pragma: no cover
        ...

    def set_tag(
        self,
        resource_id: ResourceId,
        key: str,
        value: MissingType | JSONType = MISSING,
        /,
    ) -> None:
        """Called by :meth:`.Reader.set_tag`.

        Args:
            resource_id
            key
            value

        Raises:
            ResourceNotFoundError

        """

    def delete_tag(self, resource_id: ResourceId, key: str, /) -> None:
        """Called by :meth:`.Reader.delete_tag`.

        Args:
            resource_id
            key

        Raises:
            TagNotFoundError

        """

    def get_feeds_for_update(self, filter: FeedFilter) -> Iterable[FeedForUpdate]:
        """Called by update logic.

        Args:
            filter

        Returns:
            A lazy iterable.

        """

    def update_feed(self, intent: FeedUpdateIntent, /) -> None:
        """Called by update logic.

        Args:
            intent

        Raises:
            FeedNotFoundError

        """

    def set_feed_stale(self, url: str, stale: bool, /) -> None:
        """Used by update logic tests.

        Args:
            url
            stale: :attr:`.FeedForUpdate.stale`

        Raises:
            FeedNotFoundError

        """

    def get_entries_for_update(
        self, entries: Iterable[tuple[str, str]], /  # noqa: W504
    ) -> Iterable[EntryForUpdate | None]:
        """Called by update logic.

        Args:
            entries

        Returns:
            An iterable of entry or None (if an entry does not exist),
            matching the order of the input iterable.

        """

    def add_or_update_entries(self, intents: Iterable[EntryUpdateIntent], /) -> None:
        """Called by update logic.

        Args:
            intents

        Raises:
            FeedNotFoundError

        """

    def get_entry_recent_sort(self, entry: tuple[str, str], /) -> datetime:
        """Get :attr:`EntryUpdateIntent.recent_sort`.

        Used by plugins like :mod:`~.entry_dedupe`.

        Args:
            entry

        Returns:
            entry :attr:`~EntryUpdateIntent.recent_sort`

        Raises:
            EntryNotFoundError

        """

    def set_entry_recent_sort(
        self, entry: tuple[str, str], recent_sort: datetime, /  # noqa: W504
    ) -> None:
        """Set :attr:`EntryUpdateIntent.recent_sort`.

        Used by plugins like :mod:`~.entry_dedupe`.

        Args:
            entry
            recent_sort

        Raises:
            EntryNotFoundError

        """


@runtime_checkable
class BoundSearchStorageType(StorageType, Protocol):

    """A storage that can create a storage-bound search provider."""

    def make_search(self) -> SearchType:
        """Create a search provider.

        Returns:
            A search provider.

        """


class SearchType(Protocol):  # pragma: no cover

    """Search DAO protocol.

    Any method can raise :exc:`.SearchError`.

    There are two sets of methods that may be called at different times:

    management methods
        :meth:`enable`
        :meth:`disable`
        :meth:`is_enabled`
        :meth:`update`

    read-only methods
        :meth:`search_entries`
        :meth:`search_entry_counts`

    .. admonition:: Unstable

        In the future, search may receive object lifecycle methods (context manager + ``close()``),
        to support implementations that do not share state with the storage.
        If you need support for this, please open a issue.

    """

    def enable(self) -> None:
        """Called by :meth:`.Reader.enable_search`.

        A no-op and reasonably fast if search is already enabled.

        Checks if all dependencies needed for :meth:`update` are available,
        raises :exc:`.SearchError` if not.

        Raises:
            StorageError

        """

    def disable(self) -> None:
        """Called by :meth:`.Reader.disable_search`."""

    def is_enabled(self) -> bool:
        """Called by :meth:`.Reader.is_search_enabled`.

        Not called otherwise.

        Returns:
            Whether search is enabled or not.

        """

    def update(self) -> None:
        """Called by :meth:`.Reader.update_search`.

        Should not enable search automatically (handled by :class:`.Reader`).

        Raises:
            SearchNotEnabledError
            StorageError

        """

    def search_entries(
        self,
        query: str,
        /,
        filter: EntryFilter,
        sort: SearchSortOrder,
        limit: int | None,
        starting_after: tuple[str, str] | None,
    ) -> Iterable[EntrySearchResult]:
        """Called by :meth:`.Reader.search_entries`.

        Args:
            query
            filter
            sort
            limit
            starting_after

        Returns:
            A lazy iterable.

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            EntryNotFoundError: If ``starting_after`` does not exist.

        """

    def search_entry_counts(
        self, query: str, /, now: datetime, filter: EntryFilter
    ) -> EntrySearchCounts:
        """Called by :meth:`.Reader.search_entry_counts`.

        Args:
            query
            now: Time :attr:`~.EntrySearchCounts.averages` is relative to.
            filter

        Returns:
            The counts.

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            StorageError

        """


class Action(Enum):
    # FIXME: docstring
    INSERT = 1
    DELETE = 2


@dataclass(frozen=True)
class Change:
    # FIXME: docstring
    action: Action
    sequence: bytes
    feed_url: str | None = None
    entry_id: str | None = None
    tag_key: str | None = None
