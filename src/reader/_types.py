from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from enum import Enum
from functools import cached_property
from types import SimpleNamespace
from typing import Any
from typing import cast
from typing import get_args
from typing import Literal
from typing import NamedTuple
from typing import overload
from typing import Protocol
from typing import runtime_checkable
from typing import Self
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
from .types import EntrySearchSort
from .types import EntrySort
from .types import EntrySource
from .types import ExceptionInfo
from .types import Feed
from .types import FeedCounts
from .types import FeedInput
from .types import FeedSort
from .types import JSONType
from .types import MISSING
from .types import MissingType
from .types import ResourceId
from .types import TagFilterInput
from .types import TristateFilterInput


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

    # WARNING: When changing attributes, keep Feed, FeedData and EntrySource in sync.

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
    source: EntrySource | None = None

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
    source_obj = getattr(obj, 'source', None)
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
        source=source_from_obj(source_obj) if source_obj else None,
    )


def entry_update_intent_from_obj(obj: object) -> EntryUpdateIntent:
    if isinstance(obj, Mapping):  # pragma: no cover
        obj = SimpleNamespace(**obj)
    return EntryUpdateIntent(
        entry=entry_data_from_obj(obj),
        last_updated=_getattr_datetime(obj, 'last_updated'),
        first_updated=_getattr_datetime(obj, 'added'),
        first_updated_epoch=_getattr_datetime(obj, 'added'),
        recent_sort=_getattr_datetime(obj, 'recent_sort'),
        added_by=_getattr_entry_added_by(obj, 'added_by'),
        original_feed_url=_getattr_optional(obj, 'original_feed_url', str),
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


def source_from_obj(obj: object) -> EntrySource:
    if isinstance(obj, Mapping):
        obj = SimpleNamespace(**obj)
    return EntrySource(
        url=_getattr_optional(obj, 'url', str),
        updated=_getattr_optional_datetime(obj, 'updated'),
        title=_getattr_optional(obj, 'title', str),
        link=_getattr_optional(obj, 'link', str),
        author=_getattr_optional(obj, 'author', str),
        subtitle=_getattr_optional(obj, 'subtitle', str),
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


def _getattr_datetime(obj: object, name: str) -> datetime:
    value = _getattr(obj, name, datetime)
    return value.astimezone(timezone.utc)


def _getattr_optional_datetime(obj: object, name: str) -> datetime | None:
    value = _getattr_optional(obj, name, datetime)
    if value is None:
        return value
    return value.astimezone(timezone.utc)


def _getattr_entry_added_by(obj: object, name: str) -> EntryAddedBy:
    value = _getattr(obj, name, str)
    values = get_args(EntryAddedBy)
    if value not in values:  # pragma: no cover
        raise ValueError(
            f"bad value for {name}; expected one of {values!r}, got {value!r}"
        )
    return cast(EntryAddedBy, value)


class FeedForUpdate(NamedTuple):
    """Update-relevant information about an existing feed, from Storage."""

    #: The feed URL.
    url: str

    #: The date the feed was last updated, according to the feed.
    updated: datetime | None = None

    #: Caching info from the last update.
    caching_info: JSONType | None = None

    #: Whether the next update should update *all* entries,
    #: regardless of their :attr:`hash` or :attr:`updated`.
    stale: bool = False

    #: The date the feed was last updated, according to reader; none if never.
    last_updated: datetime | None = None

    #: Whether the feed had an exception at the last update.
    last_exception: bool = False

    #: The :attr:`~FeedData.hash` of the corresponding FeedData.
    hash: bytes | None = None


class EntryForUpdate(NamedTuple):
    """Update-relevant information about an existing entry, from Storage."""

    #: From the last :attr:`EntryUpdateIntent.first_updated`.
    first_updated: datetime

    #: From the last :attr:`EntryUpdateIntent.first_updated_epoch`.
    first_updated_epoch: datetime

    #: From the last :attr:`EntryUpdateIntent.recent_sort`.
    recent_sort: datetime

    #: The date the entry was last updated, according to the entry.
    updated: datetime | None

    #: The :attr:`~EntryData.hash` of the corresponding EntryData.
    hash: bytes | None

    #: The number of updates due to a different ``hash``
    #: since the last time ``updated`` changed.
    hash_changed: int | None


class FeedUpdateIntent(NamedTuple):
    """Data passed to Storage to record a feed update attempt,
    regardless of the outcome.

    """

    #: The feed URL.
    url: str

    #: The time at the start of updating this feed.
    last_retrieved: datetime

    #: The earliest time the feed will next be updated.
    update_after: datetime

    #: One of:
    #: feed data and metadata (the feed was updated),
    #: None (the feed is unchanged)
    #: the cause of :exc:`.UpdateError`, if one happened.
    value: FeedToUpdate | None | ExceptionInfo


class FeedToUpdate(NamedTuple):
    """Data passed to Storage when (successfully) updating a feed."""

    #: The feed data.
    feed: FeedData

    #: The time at the start of updating this feed.
    last_updated: datetime

    #: Caching info passed back to the retriever on the next update.
    #: See :attr:`ParsedFeed.caching_info` for details.
    caching_info: JSONType | None = None


class EntryUpdateIntent(NamedTuple):
    """Data passed to Storage when updating an entry."""

    #: The entry data.
    entry: EntryData

    #: The time at the start of updating the feed
    #: (start of :meth:`~.Reader.update_feed` in :meth:`~.Reader.update_feed`,
    #: start of each feed update in :meth:`~.Reader.update_feeds`).
    last_updated: datetime

    #: First :attr:`last_updated` (sets :attr:`.Entry.added`).
    #: The value from :class:`EntryForUpdate` if the entry already exists.
    first_updated: datetime

    #: The time at the start of updating this batch of feeds
    #: (start of :meth:`~.Reader.update_feed` in :meth:`~.Reader.update_feed`,
    #: start of :meth:`~.Reader.update_feeds` in :meth:`~.Reader.update_feeds`).
    #: The value from :class:`EntryForUpdate` if the entry already exists.
    first_updated_epoch: datetime

    #: Sort key for the :meth:`~.Reader.get_entries` ``recent`` sort order.
    #: The value from :class:`EntryForUpdate` if the entry already exists.
    recent_sort: datetime

    #: The index of the entry in the feed (zero-based).
    feed_order: int = 0

    #: Same as :attr:`EntryForUpdate.hash_changed`.
    hash_changed: int | None = 0

    #: Same as :attr:`.Entry.added_by`.
    added_by: EntryAddedBy = 'feed'

    #: Same as :attr:`.Entry.original_feed_url`.
    #: Usually does not need to be set.
    original_feed_url: str | None = None

    # using a proxy like `first_updated == last_updated` instead of new
    # doesn't work because it can be true for modified entries sometimes
    # (e.g. repeated updates on platforms with low-precision time,
    # like update_feeds_iter() tests on Windows on GitHub Actions)

    #: Whether the entry is new.
    #: Used for hooks and UpdatedFeed counts, should not be used by storage.
    new: bool = True


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
    source: str | None = None
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
        source: FeedInput | None = None,
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

        source_url = _feed_argument(source) if source is not None else None

        tag_filter = tag_filter_argument(tags)
        feed_tag_filter = tag_filter_argument(feed_tags, 'feed_tags')

        return cls(
            feed_url,
            entry_id,
            read,
            important_filter,
            has_enclosures,
            source_url,
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
    update_after: datetime | None = None

    @classmethod
    def from_args(
        cls,
        now: datetime,
        feed: FeedInput | None = None,
        tags: TagFilterInput = None,
        broken: bool | None = None,
        updates_enabled: bool | None = None,
        new: bool | None = None,
        scheduled: bool = False,
    ) -> Self:
        feed_url = _feed_argument(feed) if feed is not None else None
        tag_filter = tag_filter_argument(tags)

        if broken not in (None, False, True):
            raise ValueError("broken should be one of (None, False, True)")
        if updates_enabled not in (None, False, True):
            raise ValueError("updates_enabled should be one of (None, False, True)")
        if new not in (None, False, True):
            raise ValueError("new should be one of (None, False, True)")
        if scheduled not in (False, True):
            raise ValueError("scheduled should be one of (False, True)")

        update_after = now if scheduled else None

        return cls(feed_url, tag_filter, broken, updates_enabled, new, update_after)


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


class UpdateHooks:
    def __init__(self, target: Any):
        self.target = target
        self.hooks: dict[str, list[Callable[..., None]]] = defaultdict(list)

    def run(
        self,
        when: str,
        resource_id: tuple[str, ...] | None,
        *args: Any,
        return_exceptions: bool = False,
    ) -> list[SingleUpdateHookError]:
        rv = []
        for hook in self.hooks[when]:
            try:
                hook(self.target, *args)
            except Exception as e:
                wrapper = SingleUpdateHookError(when, hook, resource_id)
                wrapper.__cause__ = e
                if not return_exceptions:
                    raise wrapper
                rv.append(wrapper)
        return rv

    def group(self, message: str) -> _UpdateHookErrorGrouper:
        return _UpdateHookErrorGrouper(self, message)


class _UpdateHookErrorGrouper:
    def __init__(self, hooks: UpdateHooks, message: str):
        self.hooks = hooks
        self.message = message
        self.exceptions: list[UpdateHookError] = []
        self.seen_dedupe_keys: set[Any] = set()

    def run(
        self,
        when: str,
        resource_id: tuple[str, ...] | None,
        *args: Any,
        limit: int = 0,
    ) -> None:
        for exc in self.hooks.run(when, resource_id, *args, return_exceptions=True):
            self.add(exc, resource_id, limit)

    def add(self, exc: UpdateHookError, dedupe_key: Any = None, limit: int = 0) -> None:
        # TODO: test error deduping; also, the logic may not be correct?
        if limit and dedupe_key not in self.seen_dedupe_keys:  # pragma: no cover
            if len(self.seen_dedupe_keys) >= limit:
                log.error("too many hook errors; discarding exception", exc_info=exc)
                return
            self.seen_dedupe_keys.add(dedupe_key)
        self.exceptions.append(exc)

    def close(self) -> None:
        if self.exceptions:
            raise UpdateHookErrorGroup(self.message, self.exceptions)

    def __enter__(self) -> _UpdateHookErrorGrouper:
        return self

    def __exit__(self, _: Any, exc: BaseException, __: Any) -> None:
        # bare SingleUpdateHookError was intended to raise, don't catch it
        if isinstance(exc, UpdateHookErrorGroup):
            self.add(exc)
        self.close()


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

        For tag filters, implementations should optimize the single-tag case
        such that listing by tag does not have to go through all the feeds.

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

        For tag filters, implementations should optimize the single-tag case
        such that listing by tag does not have to go through all the entries.

        Additionally, implementations may choose to not implement tag filters
        more complicated than flat OR (``[['one', 'two', ...]]``) or flat AND
        (``[['one'], ['two'], ...]``), and raise StorageError instead.

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
        If you need support for this, please :ref:`open an issue <issues>`.

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
        sort: EntrySearchSort,
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


@runtime_checkable
class ChangeTrackingStorageType(StorageType, Protocol):
    """A storage that can track changes to the text content of resources."""

    @property
    def changes(self) -> ChangeTrackerType:
        """The change tracker associated with this storage."""


class ChangeTrackerType(Protocol):  # pragma: no cover
    """Storage API used to keep the full-text search index in sync.

    ----

    The sync model works as follows.

    Each resource to be indexed has a sequence that changes
    every time its text content changes.
    The sequence can be a global counter, a random number,
    or a high-precision timestamp;
    the only requirement is that it won't be used again
    (or it's extremely unlikely that will happen).

    Each sequence change gets recorded.
    Updates are recorded as pairs of
    :attr:`~Action.DELETE` + :attr:`~Action.INSERT` changes
    with the old / new sequences, respectively.

    :meth:`SearchType.update` gets changes and processes them.
    For :attr:`~Action.INSERT`,
    the resource is indexed only if the change sequence
    matches the current main storage sequence;
    otherwise, the change is ignored.
    For :attr:`~Action.DELETE`,
    the resource is deleted only if the change sequence
    matches the search index sequence.
    (This means that, during updates,
    multiple versions of a resource may appear in the index,
    with different sequences.)
    Processed changes are marked as done,
    regardless of the action taken. Pseudocode::

        while changes := self.storage.changes.get():
            self._process_changes(changes)
            self.storage.changes.done(changes)

    Enabling change tracking sets the sequence of all resources
    and adds matching :attr:`~Action.INSERT` changes
    to allow backfilling the search index.
    The sequence may be :const:`None` when change tracking is disabled.
    There is no guarantee the sequence of a resource remains the same
    when change tracking is disabled and then enabled again.

    .. seealso::

        The model was validated using property-based testing
        in `this gist <https://gist.github.com/lemon24/558955ad82ba2e4f50c0184c630c668c>`_.

    ----

    The entry sequence is exposed as :attr:`.Entry._sequence`,
    and should change when
    the entry :attr:`~.Entry.title`, :attr:`~.Entry.summary`,
    or :attr:`~.Entry.content` change,
    or when its feed's :attr:`~.Feed.title` or :attr:`~.Feed.user_title` change.

    As of version |version|, only entry changes are tracked,
    but the API supports tracking feeds and tags in the future;
    search implementations should ignore
    changes to resources they do not support
    (but still mark them as done!).

    Any method can raise :exc:`.StorageError`.

    """

    def enable(self) -> None:
        """Enable change tracking.

        A no-op and reasonably fast if change tracking is already enabled.

        """

    def disable(self) -> None:
        """Disable change tracking.

        A no-op if change tracking is already disabled.

        """

    def get(
        self, action: Action | None = None, limit: int | None = None
    ) -> list[Change]:
        """Return the next batch of changes, if any.

        Args:
            action: Only return changes of this type.
            limit: Return at most this many changes;
                may return fewer, depending on storage internal limits.
                If none, reasonable limit should be used (hundreds).

        Returns:
            A batch of changes.

        Raises:
            ChangeTrackingNotEnabledError

        """

    def done(self, changes: list[Change]) -> None:
        """Mark changes as done. Ignore unknown changes.

        Args:
            changes:

        Raises:
            ChangeTrackingNotEnabledError
            ValueError: If more changes than :meth:`get` returns are passed;
                ``done(get())`` should always work.

        """


@dataclass(frozen=True)
class Change:
    """A change to be applied to the search index.

    The change can be of an entry, a feed, or a resource tag.

    """

    #: Action to take.
    action: Action
    #: Resource/tag sequence.
    sequence: bytes
    #: Resource id.
    resource_id: ResourceId
    #: Tag key, if the change is about a tag.
    tag_key: str | None = None


class Action(Enum):
    """Action to take."""

    #: The resource needs to be added to the search index.
    INSERT = 1
    #: The resource needs to be deleted from the search index.
    DELETE = 2
