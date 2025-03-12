from __future__ import annotations

import dataclasses
import enum
import re
import traceback
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from types import MappingProxyType
from typing import Any
from typing import cast
from typing import Literal
from typing import NamedTuple
from typing import overload
from typing import Protocol
from typing import Self
from typing import TypedDict
from typing import Union

from reader.exceptions import UpdateError


# can't be defined here because of circular imports
from reader._utils import MISSING as MISSING  # isort: skip # noqa: F401
from reader._utils import MissingType as MissingType  # isort: skip # noqa: F401


class _namedtuple_compat:
    """Add namedtuple-like methods to a dataclass."""

    # TODO: can we get rid of _namedtuple_compat?

    def _replace(self, **kargs: Any) -> Self:
        return dataclasses.replace(self, **kargs)  # type: ignore[type-var]

    def _asdict(self) -> dict[str, Any]:
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

    # WARNING: When changing attributes, keep Feed, FeedData and EntrySource in sync.

    #: The URL of the feed.
    url: str

    #: The date the feed was last updated, according to the feed.
    updated: datetime | None = None

    #: The title of the feed.
    title: str | None = None

    #: The URL of a page associated with the feed.
    link: str | None = None

    #: The author of the feed.
    author: str | None = None

    #: A description or subtitle for the feed.
    #:
    #: .. versionadded:: 2.4
    subtitle: str | None = None

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
    version: str | None = None

    #: User-defined feed title.
    user_title: str | None = None

    # added is required, but we want it after feed data; the cast is for mypy.

    #: The date when the feed was added.
    #:
    #: .. versionadded:: 1.3
    added: datetime = cast(datetime, None)

    #: The date when the feed was last (successfully) updated by reader.
    #:
    #: .. versionadded:: 1.3
    last_updated: datetime | None = None

    #: If a :exc:`UpdateError` happened during the last update, its details.
    #:
    #: .. versionadded:: 1.3
    #:
    #: .. versionchanged:: 3.9
    #:  Store the details of any :exc:`UpdateError` (except hook errors),
    #:  not just the ``__cause__`` of :exc:`ParseError`\s.
    #:
    last_exception: ExceptionInfo | None = None

    #: Whether updates are enabled for this feed.
    #:
    #: .. versionadded:: 1.11
    updates_enabled: bool = True

    #: The earliest time the feed will next be updated
    #: (when using scheduled updates).
    #:
    #: .. versionadded:: 3.13
    update_after: datetime | None = None

    #: The date when the feed was last retrieved by reader,
    #: regardless of the outcome.
    #:
    #: .. versionadded:: 3.13
    last_retrieved: datetime | None = None

    @property
    def resource_id(self) -> tuple[str]:
        """Alias for (:attr:`~url`,).

        .. versionadded:: 2.17

        """
        return (self.url,)

    @property
    def resolved_title(self) -> str | None:
        """:attr:`user_title` or :attr:`title`.

        .. versionadded:: 3.16

        """
        return self.user_title or self.title


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
    def from_exception(cls, exc: BaseException) -> Self:
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
    updated: datetime | None = None

    #: The title of the entry.
    title: str | None = None

    #: The URL of a page associated with the entry.
    link: str | None = None

    #: The author of the feed.
    author: str | None = None

    #: The date the entry was published, according to the feed.
    published: datetime | None = None

    #: A summary of the entry.
    summary: str | None = None

    #: Full content of the entry.
    #: A sequence of :class:`Content` objects.
    content: Sequence[Content] = ()

    #: External files associated with the entry.
    #: A sequence of :class:`Enclosure` objects.
    enclosures: Sequence[Enclosure] = ()

    #: Metadata of the source feed if the entry is a copy.
    #:
    #: .. versionadded:: 3.16
    source: EntrySource | None = None

    #: Whether the entry was read or not.
    read: bool = False

    #: The date when :attr:`read` was last set by the user;
    #: :const:`None` if that never happened,
    #: or the entry predates the date being recorded.
    #:
    #: .. versionadded:: 2.2
    read_modified: datetime | None = None

    #: Whether the entry is important or not.
    #: :const:`None` means not set.
    #: :const:`False` means "explicitly unimportant".
    #:
    #: .. versionchanged:: 3.5
    #:  :attr:`important` is now an optional :class:`bool`,
    #:  and defaults to :const:`None`.
    important: bool | None = None

    #: The date when :attr:`important` was last set by the user;
    #: :const:`None` if that never happened,
    #: or the entry predates the date being recorded.
    #:
    #: .. versionadded:: 2.2
    important_modified: datetime | None = None

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

    #: Change sequence.
    #:
    #: May be :const:`None` when change tracking is disabled.
    #:
    #: .. admonition:: Unstable
    #:
    #:  This field is part of the unstable :ref:`change tracking API <changes>`.
    #:
    _sequence: bytes | None = None

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
    def resource_id(self) -> tuple[str, str]:
        """Alias for (:attr:`~feed_url`, :attr:`~id`).

        .. versionadded:: 2.17

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

    def get_content(self, *, prefer_summary: bool = False) -> Content | None:
        """Return a text content OR the summary.

        Prefer HTML content, when available.

        Args:
            prefer_summary (bool): Return summary, if available.

        Returns:
            Content or none: The content, if found.

        .. versionadded:: 2.12

        """
        return _get_entry_content(self, prefer_summary)

    @property
    def feed_resolved_title(self) -> str | None:
        """Feed :attr:`~Feed.resolved_title`, source :attr:`~EntrySource.title`,
        or ``"{source} ({feed})"`` if both are present and different.

        .. versionadded:: 3.16

        .. versionchanged:: 3.17
            Return both the source and feed titles only if they are different.

        """
        title = self.feed.resolved_title
        source = self.source
        source_title = source.title if source else None
        if self.feed.title == source_title:
            source_title = None
        if title == source_title:
            source_title = None
        if not source_title:
            return title
        if not title:
            return source_title
        return f"{source_title} ({title})"


@dataclass(frozen=True)
class Content(_namedtuple_compat):
    """Data type representing a piece of content."""

    # WARNING: When changing attributes, keep content_from_obj in sync.

    #: The content value.
    value: str

    #: The content type.
    type: str | None = None

    #: The content language.
    language: str | None = None

    @property
    def is_html(self) -> bool:
        """Whether the content is (X)HTML.

        True if the content does not have a type.

        .. versionadded:: 2.12
        """
        if self.type:
            return self.type in _HTML_CONTENT_TYPES
        return True


_PREFERRED_CONTENT_TYPES = ['text/html', 'text/xhtml', 'text/plain', None]
_HTML_CONTENT_TYPES = {'text/html', 'text/xhtml'}
_HTML_CONTENT_TYPE = 'text/html'


def _get_entry_content(entry: Entry, prefer_summary: bool = False) -> Content | None:
    # TODO: Make this public; Entry should be a protocol, Content should be generic.
    # TODO: Use the type from .summary_detail (when we get it).

    if prefer_summary and entry.summary:
        return Content(entry.summary)

    for type in _PREFERRED_CONTENT_TYPES:
        for content in entry.content:
            if content.type == type and content.value:
                return content

    if entry.summary:
        return Content(entry.summary)

    return None


@dataclass(frozen=True)
class Enclosure(_namedtuple_compat):
    """Data type representing an external file."""

    # WARNING: When changing attributes, keep enclosure_from_obj in sync.

    #: The file URL.
    href: str

    #: The file content type.
    type: str | None = None

    #: The file length.
    length: int | None = None


@dataclass(frozen=True)
class EntrySource(_namedtuple_compat):
    """Metadata of a source feed (used with :attr:`Entry.source`).

    .. versionadded:: 3.16

    """

    # WARNING: When changing attributes, keep Feed, FeedData and EntrySource in sync.

    # url is optional because we can't trust feeds to have it;
    # RSS url is required, but Atom link[rel=self] is not:
    # "a feed SHOULD contain a link back to the feed itself".

    #: The URL of the feed.
    url: str | None = None

    #: The date the feed was last updated, according to the feed.
    updated: datetime | None = None

    #: The title of the feed.
    title: str | None = None

    #: The URL of a page associated with the feed.
    link: str | None = None

    #: The author of the feed.
    author: str | None = None

    #: A description or subtitle for the feed.
    subtitle: str | None = None


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
    def extract(cls, text: str, before: str, after: str) -> Self:
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
        func: Callable[[str], str] | None = None,
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
    #: Currently entry.title and entry.feed.user_title/.title /
    #: entry.source.title / entry.feed_resolved_title.
    metadata: Mapping[str, HighlightedString] = field(
        default_factory=lambda: MappingProxyType({}),
    )

    #: Matching entry content, sorted by relevance.
    #: Any of entry.summary and entry.content[].value.
    content: Mapping[str, HighlightedString] = field(
        default_factory=lambda: MappingProxyType({}),
    )

    # TODO: entry: Optional[Entry]; model it through typing if possible

    @property
    def resource_id(self) -> tuple[str, str]:
        """Alias for (:attr:`~feed_url`, :attr:`~id`).

        .. versionadded:: 2.17

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


class FeedSort(enum.StrEnum):
    """How to order feeds.

    .. versionadded:: 3.18

    """

    #: By :attr:`~Feed.resolved_title`, case insensitive.
    TITLE = 'title'

    #: By :attr:`~Feed.added`, last added first.
    ADDED = 'added'


class EntrySort(enum.StrEnum):
    """How to order entries.

    .. versionadded:: 3.18

    """

    #: Most recent first. That is:
    #:
    #: * by published date for entries imported on the first update
    #:   (if an entry does not have :attr:`~Entry.published`,
    #:   :attr:`~Entry.updated` is used)
    #: * by added date for entries imported after that
    #:
    #: This is to make sure newly imported entries appear at the top
    #: regardless of when the feed says they were published,
    #: while not having all the old entries at the top for new feeds.
    #:
    #: .. note::
    #:
    #: The algorithm for "recent" is a heuristic and may change over time.
    #:
    #: .. versionchanged:: 3.1
    #:  Sort entries by added date most of the time,
    #:  with the exception of those imported on the first update.
    #:  Previously, entries would be sorted by added
    #:  only if they were published less than 7 days ago.
    #:
    RECENT = 'recent'

    #: Random (shuffle). Return at most 256 entries.
    #:
    #: .. versionadded:: 1.2
    #:
    RANDOM = 'random'


class EntrySearchSort(enum.StrEnum):
    """How to order entry search results.

    .. versionadded:: 3.18

    """

    #: Most relevant first.
    RELEVANT = 'relevant'

    #: Most recent first. See :data:`EntrySort.RECENT` for details.
    #:
    #: .. versionadded:: 1.4
    #:
    RECENT = 'recent'

    #: Random (shuffle). See :data:`EntrySort.RANDOM` for details.
    #:
    #: .. versionadded:: 1.10
    #:
    RANDOM = 'random'


# Semi-public API (typing support)


# https://github.com/python/typing/issues/182
# TODO: allow JSONType to be str, int, ...
JSONValue = Union[str, int, float, bool, None, dict[str, Any], list[Any]]
JSONType = Union[dict[str, JSONValue], list[JSONValue]]


# Using protocols here so we have both duck typing and type checking.
# Simply catching AttributeError (e.g. on feed.url) is not enough for mypy,
# see https://github.com/python/mypy/issues/8056.


class FeedLike(Protocol):
    # We don't use "url: str" because we don't care if url is writable.

    @property
    def url(self) -> str:  # pragma: no cover
        ...


class EntryLike(Protocol):
    @property
    def id(self) -> str:  # pragma: no cover
        ...

    @property
    def feed_url(self) -> str:  # pragma: no cover
        ...


# https://github.com/lemon24/reader/issues/266#issuecomment-1013739526
GlobalInput = tuple[()]
FeedInput = Union[str, FeedLike]
EntryInput = Union[tuple[str, str], EntryLike]
ResourceInput = Union[GlobalInput, FeedInput, EntryInput]
AnyResourceInput = Union[ResourceInput, None, tuple[None], tuple[None, None]]
ResourceId = Union[tuple[()], tuple[str], tuple[str, str]]
AnyResourceId = Union[ResourceId, None, tuple[None], tuple[None, None]]


def _feed_argument(feed: FeedInput) -> str:
    try:
        rv = feed.url  # type: ignore[union-attr]
    except AttributeError:
        if isinstance(feed, tuple) and len(feed) == 1:
            rv = feed[0]
        else:
            rv = feed
    if isinstance(rv, str):
        return rv
    raise ValueError(f'invalid feed argument: {feed!r}')


def _entry_argument(entry: EntryInput) -> tuple[str, str]:
    try:
        rv = entry.feed_url, entry.id  # type: ignore[union-attr]
    except AttributeError:
        if isinstance(entry, tuple) and len(entry) == 2:
            rv = entry
        else:
            rv = None
    if rv:
        feed_url, entry_id = rv
        if isinstance(feed_url, str) and isinstance(entry_id, str):
            return rv
    raise ValueError(f'invalid entry argument: {entry!r}')


@overload
def _resource_argument(resource: GlobalInput) -> tuple[()]: ...  # pragma: no cover


@overload
def _resource_argument(resource: FeedInput) -> tuple[str]: ...  # pragma: no cover


@overload
def _resource_argument(resource: EntryInput) -> tuple[str, str]: ...  # pragma: no cover


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

#: Possible values for filtering resources by their tags.
#:
#: Tag filters consist of a list of one or more tags.
#: Multiple tags are interpreted as a conjunction (AND).
#: To use a disjunction (OR), use a nested list.
#: To negate a tag, prefix the tag value with a minus sign (``-``).
#: Examples:
#:
#: ``['one']``
#:
#:     one
#:
#: ``['one', 'two']``
#: ``[['one'], ['two']]``
#:
#:     one AND two
#:
#: ``[['one', 'two']]``
#:
#:     one OR two
#:
#: ``[['one', 'two'], 'three']``
#:
#:     (one OR two) AND three
#:
#: ``['one', '-two']``
#:
#:     one AND NOT two
#:
#: Special values :const:`True` and :const:`False`
#: match resources with any tags and no tags, respectively.
#:
#: ``True``
#: ``[True]``
#:
#:     *any tags*
#:
#: ``False``
#: ``[False]``
#:
#:     *no tags*
#:
#: ``[True, '-one']``
#:
#:     *any tags* AND NOT one
#:
#: ``[[False, 'one']]``
#:
#:     *no tags* OR one
#:
#: .. versionadded:: 3.11
#:
TagFilterInput = Union[
    None, bool, Sequence[Union[str, bool, Sequence[Union[str, bool]]]]
]

#: Possible values for options that filter items by an optional boolean
#: attribute (one that can be either true, false, or not set).
#:
#: :const:`None` selects all items.
#: :const:`True` and :const:`False` select items based of the attribute's
#: truth value (a :const:`None` attribute is treated as false).
#:
#: For more precise filtering, use one of the following string filters:
#:
#: ==================== =============== =======================
#: attribute values     string filter   optional bool filter
#: ==================== =============== =======================
#: True                 istrue          True
#: False                isfalse
#: None                 notset
#: False, None          nottrue         False
#: True, None           notfalse
#: True, False          isset
#: True, False, None    any             None
#: ==================== =============== =======================
#:
#: .. versionadded:: 3.5
#:
TristateFilterInput = Literal[
    None,
    True,
    False,
    'istrue',
    'isfalse',
    'notset',
    'nottrue',
    'notfalse',
    'isset',
    'any',
]


@dataclass(frozen=True)
class FeedCounts(_namedtuple_compat):
    """Count information about feeds.

    .. versionadded:: 1.11

    """

    #: Total number of feeds.
    total: int | None = None

    #: Number of broken feeds.
    broken: int | None = None

    #: Number of feeds that have updates enabled.
    updates_enabled: int | None = None


@dataclass(frozen=True)
class EntryCounts(_namedtuple_compat):
    """Count information about entries.

    .. versionadded:: 1.11

    """

    #: Total number of entries.
    total: int | None = None

    #: Number of read entries.
    read: int | None = None

    #: Number of important entries.
    important: int | None = None

    #: Number of unimportant entries.
    #:
    #: .. versionadded:: 3.14
    #:
    unimportant: int | None = None

    #: Number of entries that have enclosures.
    has_enclosures: int | None = None

    # TODO: make averages a rich tuple
    # https://github.com/lemon24/reader/issues/249#issuecomment-894624989

    #: Average entries per day during the last 1, 3, 12 months, as a 3-tuple.
    #:
    #: .. versionadded:: 2.1
    #:
    averages: tuple[float, float, float] | None = None


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
    total: int | None = None

    #: Number of read entries.
    read: int | None = None

    #: Number of important entries.
    important: int | None = None

    #: Number of unimportant entries.
    #:
    #: .. versionadded:: 3.14
    #:
    unimportant: int | None = None

    #: Number of entries that have enclosures.
    has_enclosures: int | None = None

    #: Average entries per day during the last 1, 3, 12 months, as a 3-tuple.
    #:
    #: .. versionadded:: 2.1
    #:
    averages: tuple[float, float, float] | None = None


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
    #:
    #: .. versionchanged:: 3.2
    #:  This field is now optional, and defaults to 0.
    new: int = 0

    #: The number of modified entries
    #: (entries that existed in storage,
    #: but had different data than the corresponding feed file entry.)
    #:
    #: .. versionchanged:: 3.2
    #:  This field is now optional, and defaults to 0.
    modified: int = 0

    #: The number of unmodified entries
    #: (entries that existed in storage,
    #: but had the same data in the corresponding feed file entry.)
    #:
    #: .. versionadded:: 3.2
    unmodified: int = 0

    @property
    def total(self) -> int:
        """The total number of entries in the retrieved feed.

        .. versionadded:: 3.2

        """
        return self.new + self.modified + self.unmodified


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
    #: :exc:`UpdateError`
    #:
    #:  If there was an error while updating the feed.
    #:
    #: .. versionchanged:: 3.8
    #:  Narrow down the error type from :exc:`ReaderError` to :exc:`UpdateError`.
    #:
    value: UpdatedFeed | None | UpdateError

    # The exception type is UpdateError and not ParseError
    # to allow suppressing new errors without breaking the API:
    # adding a new type to the union breaks the API,
    # not raising an exception type anymore doesn't.

    @property
    def updated_feed(self) -> UpdatedFeed | None:
        """The updated feed, if the update was successful, :const:`None` otherwise.

        .. versionadded:: 2.1

        """
        return self.value if not isinstance(self.value, Exception) else None

    @property
    def error(self) -> UpdateError | None:
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


class UpdateConfig(TypedDict, total=False):
    """Schema for the ``.reader.update`` config tag
    that controls :ref:`scheduled updates <scheduled>`
    (see :ref:`reserved names` for details on the key prefix).

    Individual config keys may be missing;
    per-feed values override global values override default values.
    Invalid values are silently treated as missing.
    The default config is::

        {'interval': 60, 'jitter': 0}

    For example, given::

        >>> reader.set_tag((), '.reader.update', {'interval': 120})
        >>> reader.set_tag('http://example.com/feed', '.reader.update', {'jitter': 100})

    ...the config for ``http://example.com/feed`` ends up being::

        {
            # no per-feed value; fall back to global value
            'interval' 120,
            # invalid feed value (100 not between 0.0 and 1.0);
            # no global value; fall back to default value
            'jitter': 0,
        }

    .. versionadded:: 3.13

    """

    #: Update interval, in minutes.
    interval: int

    #: Update jitter, as a ratio of :attr:`interval`, between 0.0 and 1.0.
    jitter: float
