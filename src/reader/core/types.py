import dataclasses
import re
import warnings
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Generic
from typing import Iterable
from typing import List
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

from typing_extensions import Literal
from typing_extensions import Protocol
from typing_extensions import runtime_checkable


_T = TypeVar('_T')


class _namedtuple_compat:

    """Add namedtuple-like methods to a dataclass."""

    # TODO: can we get rid of _namedtuple_compat?

    @classmethod
    def _make(cls: Type[_T], iterable: Iterable[Any]) -> _T:
        iterable = tuple(iterable)
        attrs_len = len(dataclasses.fields(cls))
        if len(iterable) != attrs_len:
            raise TypeError(
                'Expected %d arguments, got %d' % (attrs_len, len(iterable))
            )
        return cls(*iterable)

    _replace = dataclasses.replace

    # FIXME: this recurses, unlike namedtuple._asdict; remove it
    _asdict = dataclasses.asdict


# See https://github.com/lemon24/reader/issues/159 for a discussion
# of how feed- and entry-like objects are uniquely identified, and
# how to keep it consistent.


# Public API


@dataclass(frozen=True)
class Feed(_namedtuple_compat):

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


@dataclass(frozen=True)
class Entry(_namedtuple_compat):

    """Data type representing an entry."""

    # WARNING: When changing attributes, keep Entry and EntryData in sync.

    @property
    def feed_url(self) -> str:
        """The feed url."""
        return self.feed.url

    #: The entry id.
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

    #: Whether the entry is important or not.
    important: bool = False

    # feed should not have a default, but I'd prefer objects that aren't
    # entry data to be at the end, and dataclasses don't support keyword-only
    # arguments yet.
    #
    # We could use a null object as the default (Feed('')), but None
    # increases the chance we'll catch feed= not being set at runtime;
    # we don't check for it in __post_init__ because it's still useful
    # to have it None in tests. The cast is to please mypy.

    #: The entry's feed.
    feed: Feed = cast(Feed, None)


@dataclass(frozen=True)
class Content(_namedtuple_compat):

    """Data type representing a piece of content."""

    #: The content value.
    value: str

    #: The content type.
    type: Optional[str] = None

    #: The content language.
    language: Optional[str] = None


@dataclass(frozen=True)
class Enclosure(_namedtuple_compat):

    """Data type representing an external file."""

    #: The file URL.
    href: str

    #: The file content type.
    type: Optional[str] = None

    #: The file length.
    length: Optional[int] = None


_HS = TypeVar('_HS', bound='HighlightedString')


@dataclass(frozen=True)
class HighlightedString:

    """A string that has some of its parts highlighted."""

    # TODO: show if we're at the start/end of the value

    #: The underlying string.
    value: str = ''

    #: The highlights; non-overlapping slices with positive start/stop
    #: and None step.
    highlights: Sequence[slice] = ()

    def __post_init__(self) -> None:
        for highlight in self.highlights:
            reason = ''

            if highlight.start is None or highlight.stop is None:
                reason = 'start and stop must not be None'
            elif highlight.step is not None:
                reason = 'step must be None'
            elif highlight.start < 0 or highlight.stop < 0:
                reason = 'start and stop must be equal to or greater than 0'
            elif highlight.start > len(self.value) or highlight.stop > len(self.value):
                reason = (
                    'start and stop must be less than or equal to the string length'
                )
            elif highlight.start > highlight.stop:
                reason = 'start must be not be greater than stop'

            if reason:
                raise ValueError(f'invalid highlight: {reason}: {highlight}')

        highlights = sorted(self.highlights, key=lambda s: (s.start, s.stop))

        prev_highlight = None
        for highlight in highlights:
            if not prev_highlight:
                prev_highlight = highlight
                continue

            if prev_highlight.stop > highlight.start:
                raise ValueError(
                    f'highlights must not overlap: {prev_highlight}, {highlight}'
                )

        object.__setattr__(self, 'highlights', tuple(highlights))

    def __str__(self) -> str:
        return self.value

    @classmethod
    def extract(cls: Type[_HS], text: str, before: str, after: str) -> _HS:
        """Extract highlights with before/after markers from text.

        >>> HighlightedString.extract( '>one< two', '>', '<')
        HighlightedString(value='one two', highlights=(slice(0, 3, None),))

        Args:
            text (str): The original text, with highlights marked by ``before`` and ``after``.
            before (str): Highlight start marker.
            after (str): Highlight stop marker.

        Returns:
            HighlightedString: A highlighted string.

        """
        pattern = f"({'|'.join(re.escape(s) for s in (before, after))})"

        parts = []
        slices = []

        index = 0
        start = None

        for part in re.split(pattern, text):
            if part == before:
                if start is not None:
                    raise ValueError("highlight start marker in highlight")
                start = index
                continue

            if part == after:
                if start is None:
                    raise ValueError("unmatched highlight end marker")
                slices.append(slice(start, index))
                start = None
                continue

            parts.append(part)
            index += len(part)

        if start is not None:
            raise ValueError("highlight is never closed")

        return cls(''.join(parts), tuple(slices))

    def split(self) -> Iterable[str]:
        """Split the highlighted string into parts.

        >>> list(HighlightedString('abcd', [slice(1, 3)]))
        ['a', 'bc', 'd']

        Yields:
            str: The parts. Parts with even indexes are highlighted,
            parts with odd indexes are not.

        """
        start = 0

        for highlight in self.highlights:
            yield self.value[start : highlight.start]
            yield self.value[highlight]
            start = highlight.stop

        yield self.value[start:]

    def apply(
        self, before: str, after: str, func: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Apply before/end markers on the highlighted string.

        The opposite of :meth:`extract`.

        >>> HighlightedString('abcd', [slice(1, 3)]).apply('>', '<')
        'a>bc<d'
        >>> HighlightedString('abcd', [slice(1, 3)]).apply('>', '<', str.upper)
        'A>BC<D'

        Args:
            before (str): Highlight start marker.
            after (str): Highlight stop marker.
            func (callable((str), str) or none): If given, a function
                to apply to the string parts before adding the markers.

        Returns:
            str: The string, with highlights marked by ``before`` and ``after``.

        """

        def inner() -> Iterable[str]:
            for index, part in enumerate(self.split()):
                if index % 2 == 1:
                    yield before
                if func:
                    part = func(part)
                yield part
                if index % 2 == 1:
                    yield after

        return ''.join(inner())


@dataclass(frozen=True)
class EntrySearchResult:

    """Data type representing the result of an entry search.

    .. todo::

        Explain what .metadata and .content are keyed by.

    """

    #: The feed URL.
    feed_url: str

    #: The entry id.
    id: str

    #: Matching entry metadata, in arbitrary order.
    #: Currently entry.title and entry.feed.user_title/.title.
    metadata: Mapping[str, HighlightedString] = MappingProxyType({})

    #: Matching entry content, sorted by relevance.
    #: Content is any of entry.summary and entry.content[].value.
    content: Mapping[str, HighlightedString] = MappingProxyType({})

    @property
    def feed(self) -> str:
        """The feed URL.

        :deprecated: Use :attr:`feed_url` instead.

        """
        # TODO: remove me after 0.22
        warnings.warn(
            "EntrySearchResult.feed is deprecated and will be removed after "
            "reader 0.22. Use EntrySearchResult.feed_url instead.",
            DeprecationWarning,
        )
        return self.feed_url

    # TODO: entry: Optional[Entry]; model it through typing if possible


# Semi-public API (typing support)


# TODO: Could we use some kind of str-compatible enum here?
FeedSortOrder = Literal['title', 'added']


# https://github.com/python/typing/issues/182
JSONValue = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]
JSONType = Union[Dict[str, JSONValue], List[JSONValue]]


# Using protocols here so we have both duck typing and type checking.
# Simply catching AttributeError (e.g. on feed.url) is not enough for mypy,
# see https://github.com/python/mypy/issues/8056.


@runtime_checkable
class FeedLike(Protocol):

    # We don't use "url: str" because we don't care if url is writable.

    @property
    def url(self) -> str:  # pragma: no cover
        ...


@runtime_checkable
class EntryLike(Protocol):
    @property
    def id(self) -> str:  # pragma: no cover
        ...

    @property
    def feed_url(self) -> str:  # pragma: no cover
        ...


FeedInput = Union[str, FeedLike]
EntryInput = Union[Tuple[str, str], EntryLike]


def feed_argument(feed: FeedInput) -> str:
    if isinstance(feed, FeedLike):
        return feed.url
    if isinstance(feed, str):
        return feed
    raise ValueError(f'invalid feed argument: {feed!r}')


def entry_argument(entry: EntryInput) -> Tuple[str, str]:
    if isinstance(entry, EntryLike):
        return feed_argument(entry.feed_url), entry.id
    if isinstance(entry, tuple) and len(entry) == 2:
        feed_url, entry_id = entry
        if isinstance(feed_url, str) and isinstance(entry_id, str):
            return entry
    raise ValueError(f'invalid entry argument: {entry!r}')


# Private API
# https://github.com/lemon24/reader/issues/111

# structure similar to
# https://github.com/lemon24/reader/issues/159#issuecomment-612512033


class FeedData(Feed):

    """Future-proofing alias."""

    def as_feed(self) -> Feed:
        """For testing."""
        return Feed(**self.__dict__)


_UpdatedType = TypeVar('_UpdatedType', datetime, Optional[datetime])


@dataclass(frozen=True)
class EntryData(Generic[_UpdatedType], _namedtuple_compat):

    """Like Entry, but .updated is less strict and .feed is missing.

    The natural thing to use would have been generics, but pleasing Python,
    mypy and Sphinx all at the same time is not possible at the moment,
    and the workarounds are just as bad or worse.

    We should be able to use generics once/if this is resolved:
    https://github.com/sphinx-doc/sphinx/issues/7450

    ...however, it may be better to just have entry be a separate
    plain dataclass -- help(Entry) works weird with concrete generics.

    We can't use subclass Entry because the attribute types become less specific.

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
    content: Sequence['Content'] = ()
    enclosures: Sequence['Enclosure'] = ()

    # TODO: are.read and .important used? maybe delete them if not
    read: bool = False
    important: bool = False

    def as_entry(self, **kwargs: object) -> Entry:
        """For testing."""
        attrs = dict(self.__dict__)
        attrs.pop('feed_url')
        attrs.update(kwargs)
        return Entry(**attrs)


class ParsedFeed(NamedTuple):

    feed: FeedData
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


class EntryForUpdate(NamedTuple):

    """Update-relevant information about an existing entry, from Storage."""

    #: The date the entry was last updated, according to the entry.
    updated: datetime


class FeedUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

    url: str

    #: The time at the start of updating this feed.
    last_updated: datetime

    feed: Optional[FeedData] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None


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


class UpdatedEntry(NamedTuple):

    entry: EntryData[datetime]
    new: bool


class UpdateResult(NamedTuple):

    #: The entries that were updated.
    entries: Iterable[UpdatedEntry]


# TODO: these should probably be in storage.py (along with some of the above)


_EFO = TypeVar('_EFO', bound='EntryFilterOptions')


class EntryFilterOptions(NamedTuple):

    """Options for filtering the results of the "get entry" storage methods."""

    feed_url: Optional[str] = None
    entry_id: Optional[str] = None
    read: Optional[bool] = None
    important: Optional[bool] = None
    has_enclosures: Optional[bool] = None

    @classmethod
    def from_args(
        cls: Type[_EFO],
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
    ) -> _EFO:
        feed_url = feed_argument(feed) if feed is not None else None

        # TODO: should we allow specifying both feed and entry?
        if entry is None:
            entry_id = None
        else:
            feed_url, entry_id = entry_argument(entry)

        if read not in (None, False, True):
            raise ValueError("read should be one of (None, False, True)")
        if important not in (None, False, True):
            raise ValueError("important should be one of (None, False, True)")
        if has_enclosures not in (None, False, True):
            raise ValueError("has_enclosures should be one of (None, False, True)")

        return cls(feed_url, entry_id, read, important, has_enclosures)
