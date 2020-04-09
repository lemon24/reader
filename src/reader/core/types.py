import dataclasses
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any
from typing import Callable
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


# The Entry version we're giving the users (Entry) has stricter types than
# the one we use internally (ParsedEntry); the natural thing to use here is
# generics.
#
# But, we need to please Python, mypy and Sphinx all at the same time.
#
# Things I tried:
#
# * Plain type aliases ("Entry = _Entry[datetime]") break Sphinx (no docs
#   get generated); managed to kinda make this work with a few hacks
#   and setting Entry.__doc__ by hand (below).
#
# * Subclasses of any kind break Sphinx because of
#   <https://github.com/sphinx-doc/sphinx/issues/741>.
#
#   Also, if we do use subclasses, we have to re-implement __eq__,
#   because the one we get from dataclass only works with the exact type.
#
# * Making ParsedEntry a subclass of Entry and changing the type of .updated
#   (no generics) breaks mypy, because child members must have the same
#   type as in the parent.
#
# * Creating ParsedEntry dynamically with dataclasses.make_dataclass()
#   confuses mypy; may be fixed in <https://github.com/python/mypy/issues/6063>.
#
# * Modifying the source of Entry to create ParsedEntry via exec()
#   also confuses mypy (it's even more magic).
#
# Things I did not try:
#
# * Duplicating the full definition of Entry into ParsedEntry. OTOH, we're
#   already partly doing this in the docstring we set by hand; one could argue
#   that duplicating the definition is better than the hacks we do bleow.
#
# Update: I cut https://github.com/sphinx-doc/sphinx/issues/7450
# for better generic handling.


_EntryUpdatedType = TypeVar('_EntryUpdatedType', datetime, Optional[datetime])


@dataclass(frozen=True)
class _Entry(Generic[_EntryUpdatedType], _namedtuple_compat):

    """Generic entry type.

    There are some differences between the entries we use internally
    and the ones we return to people.

    See Entry.__doc__ below for what the attributes mean.

    """

    id: str

    # Entries returned by the parser have updated Optional[Datetime];
    # before storing an entry, it is always datetime.
    updated: _EntryUpdatedType

    title: Optional[str] = None
    link: Optional[str] = None
    author: Optional[str] = None
    published: Optional[datetime] = None
    summary: Optional[str] = None
    content: Sequence['Content'] = ()
    enclosures: Sequence['Enclosure'] = ()
    read: bool = False
    important: bool = False

    # TODO: Model .feed always being set for get_entries() entries through typing.
    feed: Optional[Feed] = None


Entry = _Entry[datetime]

# If not set, Sphinx will not pick up none of __doc__ / '#:' before comments /
# '"""' after comments.
#
# If set to "something", the Sphinx docstrings is "alias of 'something'",
# likely because of <https://github.com/sphinx-doc/sphinx/issues/4422>.
#
Entry.__name__ = 'Entry'

# If not set, we get Sphinx warnings.
#
# With object.__mro__ we lose the signature in the Sphinx doc.
# If set to _Entry.__mro__ we get the signature of typing._GenericAlias.
# Setting __signature__ = inspect.signature(_Entry) also didn't work.
#
Entry.__mro__ = object.__mro__

# This works for Sphinx, but help(Entry) remains broken.
#
Entry.__doc__ = """

Data type representing an entry.

.. attribute:: id
    :type: str

    Entry identifier.

.. attribute:: updated
    :type: datetime

    The date the entry was last updated.

.. attribute:: title
    :type: Optional[str]
    :value: None

    The title of the entry.

.. attribute:: link
    :type: Optional[str]
    :value: None

    The URL of a page associated with the entry.

.. attribute:: author
    :type: Optional[str]
    :value: None

    The author of the feed.

.. attribute:: published
    :type: Optional[datetime]
    :value: None

    The date the entry was first published.

.. attribute:: summary
    :type: Optional[str]
    :value: None

    A summary of the entry.

.. attribute:: content
    :type: Sequence['Content']
    :value: ()

    Full content of the entry.
    A sequence of :class:`Content` objects.

.. attribute:: enclosures
    :type: Sequence['Enclosure']
    :value: ()

    External files associated with the entry.
    A sequence of :class:`Enclosure` objects.

.. attribute:: read
    :type: bool
    :value: False

    Whether the entry was read or not.

.. attribute:: important
    :type: bool
    :value: False

    Whether the entry is important or not.

"""


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

    # FIXME: don't like the names of id/feed; they don't resemble anything;
    # like this, an EntrySearchResult is a valid entry_argument, though

    #: The entry id.
    id: str

    #: The feed URL.
    feed: str

    #: Matching entry metadata, in arbitrary order.
    #: Currently entry.title and entry.feed.user_title/.title.
    metadata: Mapping[str, HighlightedString] = MappingProxyType({})

    #: Matching entry content, sorted by relevance.
    #: Content is any of entry.summary and entry.content[].value.
    content: Mapping[str, HighlightedString] = MappingProxyType({})

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
    def feed(self) -> FeedLike:  # pragma: no cover
        ...


FeedInput = Union[str, FeedLike]
EntryInput = Union[Tuple[str, str], EntryLike]


def feed_argument(feed: FeedInput) -> str:
    if isinstance(feed, FeedLike):
        return feed.url
    if isinstance(feed, str):
        return feed
    raise ValueError('feed')


def entry_argument(entry: EntryInput) -> Tuple[str, str]:
    if isinstance(entry, EntryLike):
        return feed_argument(entry.feed), entry.id
    if isinstance(entry, tuple) and len(entry) == 2:
        feed_url, entry_id = entry
        if isinstance(feed_url, str) and isinstance(entry_id, str):
            return entry
    raise ValueError('entry')


# Private API
# https://github.com/lemon24/reader/issues/111


class ParsedFeed(NamedTuple):

    feed: Feed
    http_etag: Optional[str]
    http_last_modified: Optional[str]


ParsedEntry = _Entry[Optional[datetime]]


class ParseResult(NamedTuple):

    parsed_feed: ParsedFeed
    entries: Iterable[ParsedEntry]

    # compatibility / convenience

    @property
    def feed(self) -> Feed:
        return self.parsed_feed.feed

    @property
    def http_etag(self) -> Optional[str]:
        return self.parsed_feed.http_etag

    @property
    def http_last_modified(self) -> Optional[str]:
        return self.parsed_feed.http_last_modified


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

    """Update-relevant information about an exiting entry, from Storage."""

    #: The date the entry was last updated, according to the entry.
    updated: datetime


class FeedUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

    url: str

    #: The time at the start of updating this feed.
    last_updated: datetime

    feed: Optional[Feed] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None


class EntryUpdateIntent(NamedTuple):

    """Data to be passed to Storage when updating a feed."""

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
