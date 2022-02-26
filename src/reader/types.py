import dataclasses
import enum
import re
import traceback
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Iterable
from typing import List
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import overload
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

from typing_extensions import Literal
from typing_extensions import Protocol
from typing_extensions import runtime_checkable

from reader.exceptions import ReaderError


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

    def _asdict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# See https://github.com/lemon24/reader/issues/159 for a discussion
# of how feed- and entry-like objects are uniquely identified, and
# how to keep it consistent.

# See https://github.com/lemon24/reader/issues/153#issuecomment-620228329
# for how the feed and entry attributes should match the Atom spec.


# Public API


@dataclass(frozen=True)
class Feed(_namedtuple_compat):

    """Data type representing a feed.

    All :class:`~datetime.datetime` attributes are timezone-aware,
    with the timezone set to :attr:`~datetime.timezone.utc`.

    .. versionchanged:: 2.0
        :class:`~datetime.datetime` attributes are now timezone-aware;
        prior to 2.0, they were naive datetimes representing UTC times.

    """

    #: The URL of the feed.
    url: str

    #: The date the feed was last updated, according to the feed.
    updated: Optional[datetime] = None

    #: The title of the feed.
    title: Optional[str] = None

    #: The URL of a page associated with the feed.
    link: Optional[str] = None

    #: The author of the feed.
    author: Optional[str] = None

    #: A description or subtitle for the feed.
    #:
    #: .. versionadded:: 2.4
    subtitle: Optional[str] = None

    #: The feed type and version.
    #:
    #: For Atom and RSS, provided by `feedparser`_ (e.g. ``atom10``, ``rss20``);
    #: `full list <https://feedparser.readthedocs.io/en/latest/version-detection.html>`_.
    #:
    #: For JSON Feed:
    #:
    #: ``json10``
    #:  `JSON Feed 1.0 <https://www.jsonfeed.org/version/1/>`_
    #:
    #: ``json11``
    #:  `JSON Feed 1.1 <https://www.jsonfeed.org/version/1.1/>`_
    #:
    #: ``json``
    #:  JSON Feed (unknown or unrecognized version)
    #:
    #: Plugins may add other versions.
    #:
    #: .. versionadded:: 2.4
    version: Optional[str] = None

    #: User-defined feed title.
    user_title: Optional[str] = None

    # added is required, but we want it after feed data; the cast is for mypy.

    #: The date when the feed was added.
    #:
    #: .. versionadded:: 1.3
    added: datetime = cast(datetime, None)

    #: The date when the feed was last retrieved by reader.
    #:
    #: .. versionadded:: 1.3
    last_updated: Optional[datetime] = None

    #: If a :exc:`ParseError` happend during the last update, its cause.
    #:
    #: .. versionadded:: 1.3
    last_exception: Optional['ExceptionInfo'] = None

    #: Whether updates are enabled for this feed.
    #:
    #: .. versionadded:: 1.11
    updates_enabled: bool = True

    @property
    def object_id(self) -> str:
        """Alias for :attr:`~Feed.url`.

        .. versionadded:: 1.12

        """
        return self.url


_EI = TypeVar('_EI', bound='ExceptionInfo')


@dataclass(frozen=True)
class ExceptionInfo(_namedtuple_compat):

    """Data type representing information about an exception.

    .. versionadded:: 1.3

    """

    # Similar to traceback.TracebackException and boltons.tbutils.ExceptionInfo.
    # If ever make this richer, we might as well use one of them.

    #: The fully qualified name of the exception type.
    type_name: str

    #: String representation of the exception value.
    value_str: str

    #: String representation of the exception traceback.
    traceback_str: str

    @classmethod
    def from_exception(cls: Type[_EI], exc: BaseException) -> _EI:
        return cls(
            f'{type(exc).__module__}.{type(exc).__qualname__}',
            str(exc),
            ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )


EntryAddedBy = Literal['feed', 'user']


@dataclass(frozen=True)
class Entry(_namedtuple_compat):

    """Data type representing an entry.

    All :class:`~datetime.datetime` attributes are timezone-aware,
    with the timezone set to :attr:`~datetime.timezone.utc`.

    .. versionchanged:: 2.0
        :class:`~datetime.datetime` attributes are now timezone-aware;
        prior to 2.0, they were naive datetimes representing UTC times.

    """

    # WARNING: When changing attributes, keep Entry, EntryData and entry_data_from_obj in sync.

    @property
    def feed_url(self) -> str:
        """The feed URL."""
        return self.feed.url

    # TODO: .id will still be set to some default value if the entry doesn't have it; document this.

    #: The entry id.
    id: str

    #: The date the entry was last updated, according to the feed.
    #:
    #: .. versionchanged:: 2.0
    #:  May be :const:`None` in some cases.
    #:  In a future version, will be :const:`None` if missing in the feed;
    #:  use :attr:`updated_not_none` for the pre-2.0 behavior.
    #:
    #: .. versionchanged:: 2.5
    #:  Is now :const:`None` if missing in the feed;
    #:  use :attr:`updated_not_none` for the pre-2.5 behavior.
    #:
    updated: Optional[datetime] = None

    #: The title of the entry.
    title: Optional[str] = None

    #: The URL of a page associated with the entry.
    link: Optional[str] = None

    #: The author of the feed.
    author: Optional[str] = None

    #: The date the entry was published, according to the feed.
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

    #: The date when :attr:`read` was last set by the user;
    #: :const:`None` if that never happened,
    #: or the entry predates the date being recorded.
    #:
    #: .. versionadded:: 2.2
    read_modified: Optional[datetime] = None

    #: Whether the entry is important or not.
    important: bool = False

    #: The date when :attr:`important` was last set by the user;
    #: :const:`None` if that never happened,
    #: or the entry predates the date being recorded.
    #:
    #: .. versionadded:: 2.2
    important_modified: Optional[datetime] = None

    #: The date when the entry was added (first updated) to reader.
    #:
    #: .. versionadded:: 2.5
    added: datetime = cast(datetime, None)

    #: The source of the entry. One of ``'feed'``, ``'user'``.
    #:
    #: Other values may be added in the future.
    #:
    #: .. versionadded:: 2.5
    added_by: EntryAddedBy = cast(EntryAddedBy, None)

    #: The date when the entry was last updated by reader.
    #:
    #: .. versionadded:: 1.3
    last_updated: datetime = cast(datetime, None)

    #: The URL of the original feed of the entry.
    #:
    #: If the feed URL never changed, the same as :attr:`~Entry.feed_url`.
    #:
    #: .. versionadded:: 1.8
    original_feed_url: str = cast(str, None)

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

    @property
    def object_id(self) -> Tuple[str, str]:
        """Alias for (:attr:`~Entry.feed_url`, :attr:`~Entry.id`).

        .. versionadded:: 1.12

        """
        return self.feed_url, self.id

    @property
    def updated_not_none(self) -> datetime:
        """Like :attr:`updated`, but guaranteed to be set (not None).

        If the entry `updated` is missing in the feed,
        defaults to when the entry was first `added`.

        .. versionadded:: 2.0
            Identical to the behavior of :attr:`updated` before 2.0.

        """
        return self.updated or self.added


@dataclass(frozen=True)
class Content(_namedtuple_compat):

    """Data type representing a piece of content."""

    # WARNING: When changing attributes, keep content_from_obj in sync.

    #: The content value.
    value: str

    #: The content type.
    type: Optional[str] = None

    #: The content language.
    language: Optional[str] = None


@dataclass(frozen=True)
class Enclosure(_namedtuple_compat):

    """Data type representing an external file."""

    # WARNING: When changing attributes, keep content_from_obj in sync.

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
            str: The parts (always an odd number);
            parts with odd indexes are highlighted,
            parts with even indexes are not.

        """
        start = 0

        for highlight in self.highlights:
            yield self.value[start : highlight.start]
            yield self.value[highlight]
            start = highlight.stop

        yield self.value[start:]

    def apply(
        self,
        before: str,
        after: str,
        func: Optional[Callable[[str], str]] = None,
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
class EntrySearchResult(_namedtuple_compat):

    """Data type representing the result of an entry search.

    :attr:`metadata` and :attr:`content` are dicts where
    the key is the path of an entry attribute,
    and the value is a :class:`HighlightedString` snippet
    corresponding to that attribute, with HTML stripped.

    >>> result = next(reader.search_entries('hello internet'))
    >>> result.metadata['.title'].value
    'A Recent Hello Internet'
    >>> reader.get_entry(result).title
    'A Recent Hello Internet'

    """

    #: The feed URL.
    feed_url: str

    #: The entry id.
    id: str

    #: Matching entry metadata, in arbitrary order.
    #: Currently entry.title and entry.feed.user_title/.title.
    metadata: Mapping[str, HighlightedString] = MappingProxyType({})

    #: Matching entry content, sorted by relevance.
    #: Any of entry.summary and entry.content[].value.
    content: Mapping[str, HighlightedString] = MappingProxyType({})

    # TODO: entry: Optional[Entry]; model it through typing if possible

    @property
    def object_id(self) -> Tuple[str, str]:
        """Alias for (:attr:`~EntrySearchResult.feed_url`, :attr:`~EntrySearchResult.id`).

        .. versionadded:: 1.12

        """
        return self.feed_url, self.id


class EntryUpdateStatus(enum.Enum):

    """Enum representing how an entry was updated.

    .. versionadded:: 1.20

    """

    #: The entry did not previously exist in storage.
    NEW = 'new'

    #: The entry existed in storage,
    #: but had different data from the one in the feed file.
    MODIFIED = 'modified'


# Semi-public API (typing support)


# TODO: Could we use some kind of str-compatible enum here?
#
# Yes:
#
# class Order(enum.Enum):
#    TITLE = 'title'
#    ADDED = 'added'
#
# The public methods should then take Union[str, Order],
# and use the value _only_ as Order(arg) for validation.
# Having the arguments typed as Literals is silly anyway,
# because we sometimes get them dynamically, e.g.
# https://github.com/lemon24/reader/blob/1.18/src/reader/_app/__init__.py#L151
#
FeedSortOrder = Literal['title', 'added']
EntrySortOrder = Literal['recent', 'random']
SearchSortOrder = Literal['relevant', 'recent', 'random']


# https://github.com/python/typing/issues/182
# TODO: allow JSONType to be str, int, ...
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


# https://github.com/lemon24/reader/issues/266#issuecomment-1013739526
GlobalInput = Tuple[()]
FeedInput = Union[str, FeedLike]
EntryInput = Union[Tuple[str, str], EntryLike]
ResourceInput = Union[GlobalInput, FeedInput, EntryInput]
AnyResourceInput = Union[ResourceInput, None, Tuple[None], Tuple[None, None]]
ResourceId = Union[Tuple[()], Tuple[str], Tuple[str, str]]
AnyResourceId = Union[ResourceId, None, Tuple[None], Tuple[None, None]]


def _feed_argument(feed: FeedInput) -> str:
    if isinstance(feed, FeedLike):
        rv = feed.url
    elif isinstance(feed, tuple) and len(feed) == 1:
        rv = feed[0]
    else:
        rv = feed
    if isinstance(rv, str):
        return rv
    raise ValueError(f'invalid feed argument: {feed!r}')


def _entry_argument(entry: EntryInput) -> Tuple[str, str]:
    if isinstance(entry, EntryLike):
        rv = _feed_argument(entry.feed_url), entry.id
    elif isinstance(entry, tuple) and len(entry) == 2:
        rv = entry
    else:
        rv = None
    if rv:
        feed_url, entry_id = rv
        if isinstance(feed_url, str) and isinstance(entry_id, str):
            return rv
    raise ValueError(f'invalid entry argument: {entry!r}')


@overload
def _resource_argument(resource: GlobalInput) -> Tuple[()]:
    ...  # pragma: no cover


@overload
def _resource_argument(resource: FeedInput) -> Tuple[str]:
    ...  # pragma: no cover


@overload
def _resource_argument(resource: EntryInput) -> Tuple[str, str]:
    ...  # pragma: no cover


def _resource_argument(resource: ResourceInput) -> ResourceId:
    if isinstance(resource, tuple) and len(resource) == 0:
        return resource
    try:
        return (_feed_argument(resource),)  # type: ignore[arg-type]
    except ValueError:
        pass
    try:
        return _entry_argument(resource)  # type: ignore[arg-type]
    except ValueError:
        pass
    raise ValueError(f"invalid resource argument: {resource!r}")


# str explicitly excluded, to allow for a string-based query language;
# https://github.com/lemon24/reader/issues/184#issuecomment-689587006
TagFilterInput = Union[
    None, bool, Sequence[Union[str, bool, Sequence[Union[str, bool]]]]
]


class MissingType:
    def __repr__(self) -> str:
        return "no value"


#: Sentinel object used to detect if the `default` argument was provided."""
MISSING = MissingType()


@dataclass(frozen=True)
class FeedCounts(_namedtuple_compat):

    """Count information about feeds.

    .. versionadded:: 1.11

    """

    #: Total number of feeds.
    total: Optional[int] = None

    #: Number of broken feeds.
    broken: Optional[int] = None

    #: Number of feeds that have updates enabled.
    updates_enabled: Optional[int] = None


@dataclass(frozen=True)
class EntryCounts(_namedtuple_compat):

    """Count information about entries.

    .. versionadded:: 1.11

    """

    #: Total number of entries.
    total: Optional[int] = None

    #: Number of read entries.
    read: Optional[int] = None

    #: Number of important entries.
    important: Optional[int] = None

    #: Number of entries that have enclosures.
    has_enclosures: Optional[int] = None

    # TODO: make averages a rich tuple
    # https://github.com/lemon24/reader/issues/249#issuecomment-894624989

    #: Average entries per day during the last 1, 3, 12 months, as a 3-tuple.
    #:
    #: .. versionadded:: 2.1
    #:
    averages: Optional[Tuple[float, float, float]] = None


@dataclass(frozen=True)
class EntrySearchCounts(_namedtuple_compat):

    """Count information about entry search results.

    .. versionadded:: 1.11

    """

    # This could have inherited EntryCounts,
    # but attribute docstrings won't show show up with autoclass;
    # https://github.com/sphinx-doc/sphinx/issues/741

    # We do want a different type in case we additional attributes
    # related to search stuff (what matched etc.)

    #: Total number of entries.
    total: Optional[int] = None

    #: Number of read entries.
    read: Optional[int] = None

    #: Number of important entries.
    important: Optional[int] = None

    #: Number of entries that have enclosures.
    has_enclosures: Optional[int] = None

    #: Average entries per day during the last 1, 3, 12 months, as a 3-tuple.
    #:
    #: .. versionadded:: 2.1
    #:
    averages: Optional[Tuple[float, float, float]] = None


@dataclass(frozen=True)
class UpdatedFeed:
    """The result of a successful feed update.

    .. versionadded:: 1.14

    .. versionchanged:: 1.19
        The ``updated`` argument/attribute was renamed to ``modified``.

    """

    #: The URL of the feed.
    url: str

    #: The number of new entries
    #: (entries that did not previously exist in storage).
    new: int

    #: The number of modified entries
    #: (entries that existed in storage,
    #: but had different data than the corresponding feed file entry.)
    modified: int


class UpdateResult(NamedTuple):
    """Named tuple representing the result of a feed update.

    .. versionadded:: 1.14

    """

    #: The URL of the feed.
    url: str

    #: One of:
    #:
    #: :class:`UpdatedFeed`
    #:
    #:  If the update was successful; a summary of the updated feed.
    #:
    #: :obj:`None`
    #:
    #:  If the server indicated the feed has not changed
    #:  since the last update without returning any data.
    #:
    #: :exc:`ReaderError`
    #:
    #:  If there was an error while updating the feed.
    #:
    value: Union[UpdatedFeed, None, ReaderError]

    # The exception type is ReaderError and not ParseError
    # to allow suppressing new errors without breaking the API:
    # adding a new type to the union breaks the API,
    # not raising an exception type anymore doesn't.
    # Currently, storage or plugin-raised exceptions
    # prevent updates for the following feeds (:issue:`218`),
    # but that's not necessarily by design.

    @property
    def updated_feed(self) -> Optional[UpdatedFeed]:
        """The updated feed, if the update was successful, :const:`None` otherwise.

        .. versionadded:: 2.1

        """
        return self.value if not isinstance(self.value, Exception) else None

    @property
    def error(self) -> Optional[ReaderError]:
        """The exception, if there was an error, :const:`None` otherwise.

        .. versionadded:: 2.1

        """
        return self.value if isinstance(self.value, Exception) else None

    @property
    def not_modified(self) -> bool:
        """True if the feed has not changed
        (either because the server returned no data,
        or because the data didn't change),
        false otherwise.

        .. versionadded:: 2.1

        """
        if self.error:
            return False
        if not self.updated_feed:
            return True
        return not (self.updated_feed.new or self.updated_feed.modified)
