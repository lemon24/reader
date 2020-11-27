import builtins
import datetime
import itertools
import logging
import warnings
from typing import Any
from typing import Callable
from typing import Collection
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import overload
from typing import Tuple
from typing import TypeVar
from typing import Union

import reader._updater
from ._parser import default_parser
from ._parser import Parser
from ._search import Search
from ._storage import Storage
from ._types import EntryData
from ._types import EntryFilterOptions
from ._types import EntryUpdateIntent
from ._types import FeedFilterOptions
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._types import ParsedFeed
from ._utils import make_noop_context_manager
from ._utils import make_pool_map
from ._utils import zero_or_one
from .exceptions import _NotModified
from .exceptions import EntryNotFoundError
from .exceptions import FeedNotFoundError
from .exceptions import MetadataNotFoundError
from .exceptions import ParseError
from .types import _entry_argument
from .types import _feed_argument
from .types import Entry
from .types import EntryCounts
from .types import EntryInput
from .types import EntrySearchCounts
from .types import EntrySearchResult
from .types import EntrySortOrder
from .types import Feed
from .types import FeedCounts
from .types import FeedInput
from .types import FeedSortOrder
from .types import JSONType
from .types import MISSING
from .types import MissingType
from .types import SearchSortOrder
from .types import TagFilterInput


log = logging.getLogger('reader')


_T = TypeVar('_T')
_U = TypeVar('_U')


_PostEntryAddPluginType = Callable[['Reader', EntryData[datetime.datetime]], None]


def make_reader(
    url: str,
    *,
    feed_root: Optional[str] = '',
    _storage: Optional[Storage] = None,
    _storage_factory: Any = None,
) -> 'Reader':
    """Create a new :class:`Reader`.

    *reader* can optionally parse local files, with the feed URL either
    a bare path or a file URI.

    The interpretation of local feed URLs depends on the value of the
    feed ``feed_root`` argument.
    It can be one of the following:

    ``None``

        No local file parsing. Updating local feeds will fail.

    ``''`` (the empty string)

        Full filesystem access. This should be used only if the source of
        feed URLs is trusted.

        Both absolute and relative feed paths are supported.
        The current working directory is used normally
        (as if the path was passed to :func:`open`).

        Example: Assuming the current working directory is ``/feeds``,
        all of the following feed URLs correspond to ``/feeds/feed.xml``:
        ``feed.xml``, ``/feeds/feed.xml``, ``file:feed.xml``,
        and ``file:/feeds/feed.xml``.

    ``'/path/to/feed/root'`` (any non-empty string)

        An absolute path; all feed URLs are interpreted as relative to it.
        This can be used if the source  of feed URLs is untrusted.

        Feed paths must be relative. The current working directory is ignored.

        Example: Assuming the feed root is ``/feeds``, feed URLs
        ``feed.xml`` and ``file:feed.xml`` correspond to ``/feeds/feed.xml``.
        ``/feed.xml`` and ``file:/feed.xml`` are both errors.

        Relative paths pointing outside the feed root are errors,
        to prevent directory traversal attacks. Note that symbolic links
        inside the feed root *can* point outside it.

        The root and feed paths are joined and normalized with no regard for
        symbolic links; see :func:`os.path.normpath` for details.

        Accessing device files on Windows is an error.

    Args:
        url (str): Path to the reader database.
        feed_root (str or None):
            Directory where to look for local feeds.
            One of ``None`` (don't open local feeds),
            ``''`` (full filesystem access; default), or
            ``'/path/to/feed/root'`` (an absolute path that feed paths are relative to).

    Returns:
        Reader: The reader.

    Raises:
        StorageError

    .. versionadded:: 1.6
        The ``feed_root`` keyword argument.

    .. versionchanged:: 2.0
        The default ``feed_root`` behavior will change from
        *full filesystem access* (``''``) to
        *don't open local feeds* (``None``).

    """

    # If we ever need to change the signature of make_reader(),
    # or support additional storage/search implementations,
    # we'll need to do the wiring differently.
    #
    # See this comment for details on how it should evolve:
    # https://github.com/lemon24/reader/issues/168#issuecomment-642002049

    storage = _storage or Storage(url, factory=_storage_factory)

    # For now, we're using a storage-bound search provider.
    search = Search(storage)

    parser = default_parser(feed_root)

    reader = Reader(storage, search, parser, _called_directly=False)
    return reader


# If we ever want to implement metrics for Reader, see this comment:
# https://github.com/lemon24/reader/issues/68#issuecomment-450025175
# TODO: gather all the design notes in one place


class Reader:

    """A feed reader.

    Persists feed and entry state, provides operations on them,
    and stores configuration.


    .. important::

        Reader objects should be created using :func:`make_reader`; the Reader
        constructor is not stable yet and may change without any notice.


    The :class:`Reader` object is not thread safe;
    its methods should be called only from the thread that created it.
    To access the same database from multiple threads,
    create one instance in each thread.

    """

    def __init__(
        self,
        _storage: Storage,
        _search: Search,
        _parser: Parser,
        _called_directly: bool = True,
    ):
        self._storage = _storage
        self._search = _search
        self._parser = _parser
        self._updater = reader._updater
        self._post_entry_add_plugins: Collection[_PostEntryAddPluginType] = []

        if _called_directly:
            warnings.warn(
                "Reader objects should be created using make_reader(); the Reader "
                "constructor is not stable yet and may change without any notice.",
            )

    def close(self) -> None:
        """Close this :class:`Reader`.

        Releases any underlying resources associated with the reader.

        The reader becomes unusable from this point forward;
        a :exc:`ReaderError` will be raised if any other method is called.

        Raises:
            ReaderError

        """
        self._storage.close()

    def add_feed(self, feed: FeedInput) -> None:
        """Add a new feed.

        Feed updates are enabled by default.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedExistsError
            StorageError

        """
        url = _feed_argument(feed)
        now = self._now()
        self._storage.add_feed(url, now)

    def remove_feed(self, feed: FeedInput) -> None:
        """Remove a feed.

        Also removes all of the feed's entries, metadata, and tags.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = _feed_argument(feed)
        self._storage.remove_feed(url)

    def change_feed_url(self, old: FeedInput, new: FeedInput) -> None:
        """Change the URL of a feed.

        User-defined feed attributes are preserved:
        :attr:`~Feed.added`, :attr:`~Feed.user_title`.
        Feed-defined feed attributes are also preserved,
        at least until the next update:
        :attr:`~Feed.title`, :attr:`~Feed.link`, :attr:`~Feed.author`
        (except :attr:`~Feed.updated`, which gets set to None).
        All other feed attributes are set to their default values.

        The entries, tags and metadata are preserved.

        Args:
            old (str or Feed): The old feed; must exist.
            new (str or Feed): The new feed; must not exist.

        Raises:
            FeedNotFoundError: If ``old`` does not exist.
            FeedExistsError: If ``new`` already exists.
            StorageError

        .. versionadded:: 1.8

        """
        self._storage.change_feed_url(_feed_argument(old), _feed_argument(new))

    def get_feeds(
        self,
        *,
        feed: Optional[FeedInput] = None,
        tags: TagFilterInput = None,
        broken: Optional[bool] = None,
        updates_enabled: Optional[bool] = None,
        sort: FeedSortOrder = 'title',
    ) -> Iterable[Feed]:
        """Get all or some of the feeds.

        The ``tags`` argument can be a list of one or more feed tags.
        Multiple tags are interpreted as a conjunction (AND).
        To use a disjunction (OR), use a nested list.
        To negate a tag, prefix the tag value with a minus sign (``-``).
        Examples:

        ``['one']``

            one

        ``['one', 'two']``
        ``[['one'], ['two']]``

            one AND two

        ``[['one', 'two']]``

            one OR two

        ``[['one', 'two'], 'three']``

            (one OR two) AND three

        ``['one', '-two']``

            one AND NOT two

        Special values :const:`True` and :const:`False`
        match feeds with any tags and no tags, respectively.

        ``True``
        ``[True]``

            *any tags*

        ``False``
        ``[False]``

            *no tags*

        ``[True, '-one']``

            *any tags* AND NOT one

        ``[[False, 'one']]``

            *no tags* OR one

        Args:
            feed (str or Feed or None): Only return the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only return feeds matching these tags.
            broken (bool or None): Only return broken / healthy feeds.
            updates_enabled (bool or None):
                Only return feeds that have updates enabled / disabled.
            sort (str): How to order feeds; one of ``'title'`` (by
                :attr:`~Feed.user_title` or :attr:`~Feed.title`, case
                insensitive; default), or ``'added'`` (last added first).

        Yields:
            :class:`Feed`: Sorted according to ``sort``.

        Raises:
            StorageError

        .. versionadded:: 1.7
            The ``tags`` keyword argument.

        .. versionadded:: 1.7
            The ``broken`` keyword argument.

        .. versionadded:: 1.11
            The ``updates_enabled`` keyword argument.

        """
        filter_options = FeedFilterOptions.from_args(
            feed, tags, broken, updates_enabled
        )

        if sort not in ('title', 'added'):
            raise ValueError("sort should be one of ('title', 'added')")

        return self._storage.get_feeds(filter_options, sort)

    @overload
    def get_feed(self, feed: FeedInput) -> Feed:  # pragma: no cover
        ...

    @overload
    def get_feed(
        self, feed: FeedInput, default: _T
    ) -> Union[Feed, _T]:  # pragma: no cover
        ...

    def get_feed(
        self, feed: FeedInput, default: Union[MissingType, _T] = MISSING
    ) -> Union[Feed, _T]:
        """Get a feed.

        Like ``next(iter(reader.get_feeds(feed=feed)), default)``,
        but raises a custom exception instead of :exc:`StopIteration`.

        Arguments:
            feed (str or Feed): The feed URL.
            default: Returned if given and the feed does not exist.

        Returns:
            Feed: The feed.

        Raises:
            FeedNotFoundError
            StorageError

        """
        return zero_or_one(
            self.get_feeds(feed=feed),
            lambda: FeedNotFoundError(_feed_argument(feed)),
            default,
        )

    def get_feed_counts(
        self,
        *,
        feed: Optional[FeedInput] = None,
        tags: TagFilterInput = None,
        broken: Optional[bool] = None,
        updates_enabled: Optional[bool] = None,
    ) -> FeedCounts:
        """Count all or some of the feeds.

        See :meth:`~Reader.get_feeds()` for details on how filtering works.

        Args:
            feed (str or Feed or None): Only count the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only count feeds matching these tags.
            broken (bool or None): Only count broken / healthy feeds.
            updates_enabled (bool or None):
                Only count feeds that have updates enabled / disabled.

        Returns:
            :class:`FeedCounts`:

        Raises:
            StorageError

        .. versionadded:: 1.11

        """
        filter_options = FeedFilterOptions.from_args(
            feed, tags, broken, updates_enabled
        )
        return self._storage.get_feed_counts(filter_options)

    def set_feed_user_title(self, feed: FeedInput, title: Optional[str]) -> None:
        """Set a user-defined title for a feed.

        Args:
            feed (str or Feed): The feed URL.
            title (str or None): The title, or None to remove the current title.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = _feed_argument(feed)
        return self._storage.set_feed_user_title(url, title)

    def enable_feed_updates(self, feed: FeedInput) -> None:
        """Enable updates for a feed.

        See :meth:`~Reader.update_feeds` for details.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.11

        """
        url = _feed_argument(feed)
        self._storage.set_feed_updates_enabled(url, True)

    def disable_feed_updates(self, feed: FeedInput) -> None:
        """Disable updates for a feed.

        See :meth:`~Reader.update_feeds` for details.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.11

        """
        url = _feed_argument(feed)
        self._storage.set_feed_updates_enabled(url, False)

    def update_feeds(self, new_only: bool = False, workers: int = 1) -> None:
        """Update all the feeds that have updates enabled.

        Silently skip feeds that raise :exc:`ParseError`.

        Args:
            new_only (bool): Only update feeds that have never been updated.
            workers (int): Number of threads to use when getting the feeds.

        Raises:
            StorageError

        .. versionchanged:: 1.11
            Only update the feeds that have updates enabled.

        """

        if workers < 1:
            raise ValueError("workers must be a positive integer")

        make_map = (
            make_noop_context_manager(builtins.map)
            if workers == 1
            else make_pool_map(workers)
        )

        with make_map as map:
            exceptions = self._update_feeds(new_only=new_only, map=map)

            for exc in exceptions:
                if not exc:
                    continue
                if isinstance(exc, FeedNotFoundError):
                    log.info("update feed %r: feed removed during update", exc.url)
                elif isinstance(exc, ParseError):
                    log.exception(
                        "update feed %r: error while getting/parsing feed, "
                        "skipping; exception: %r",
                        exc.url,
                        exc.__cause__,
                        exc_info=exc,
                    )
                else:
                    raise exc

    def update_feed(self, feed: FeedInput) -> None:
        """Update a single feed.

        The feed will be updated even if updates are disabled for it.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            ParseError
            StorageError

        """
        url = _feed_argument(feed)
        exc = zero_or_one(
            self._update_feeds(url=url, enabled_only=False),
            lambda: FeedNotFoundError(url),
        )
        if exc:
            raise exc

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.utcnow()

    # The type of map should be
    #
    #   Callable[[Callable[[_T], _U], Iterable[_T]], Iterator[_U]]
    #
    # but mypy gets confused; known issue:
    #
    # https://github.com/python/mypy/issues/1317
    # https://github.com/python/mypy/issues/6697

    def _update_feeds(
        self,
        url: Optional[str] = None,
        new_only: bool = False,
        enabled_only: bool = True,
        map: Callable[[Callable[[Any], Any], Iterable[Any]], Iterator[Any]] = map,
    ) -> Iterator[Optional[Exception]]:

        # global_now is used as first_updated_epoch for all new entries,
        # so that the subset of new entries from an update appears before
        # all others and the entries in it are sorted by published/updated;
        # if we used last_updated (now) for this, they would be sorted
        # by feed order first (due to now increasing for each feed).
        #
        # A side effect of relying first_updated_epoch for ordering is that
        # for the second of two new feeds updated in the same update_feeds()
        # call, first_updated_epoch != last_updated.
        #
        global_now = self._now()

        # Excluding the special exception handling,
        # this function is a pipeline that looks somewhat like this:
        #
        #   self._storage.get_feeds_for_update \
        #   | self._updater.process_old_feed \
        #   | xargs -n1 -P $workers self._parse_feed_for_update \
        #   | self._get_entries_for_update \
        #   | self._updater.make_update_intents \
        #   | self._update_feed
        #
        # Since we only need _parse_feed_for_update to run in parallel,
        # everything after that is in a single for loop for readability.
        #
        # It may make sense to also have _get_entries_for_update run in
        # parallel with a different (slower) storage, but for now we're good.

        feeds_for_update = self._storage.get_feeds_for_update(
            url, new_only, enabled_only
        )
        feeds_for_update = builtins.map(
            self._updater.process_old_feed, feeds_for_update
        )

        pairs = map(self._parse_feed_for_update, feeds_for_update)

        for feed_for_update, parse_result in pairs:

            try:
                # give storage a chance to consume the entries in a streaming fashion;
                parsed_entries = itertools.tee(
                    parse_result.entries
                    if not isinstance(parse_result, Exception)
                    else ()
                )
                entry_pairs = zip(
                    parsed_entries[0],
                    self._storage.get_entries_for_update(
                        (e.feed_url, e.id) for e in parsed_entries[1]
                    ),
                )

                now = self._now()
                (
                    feed_to_update,
                    entries_to_update,
                    exception,
                ) = self._updater.make_update_intents(
                    feed_for_update, now, global_now, parse_result, entry_pairs
                )

                self._update_feed(feed_to_update, entries_to_update)
                yield exception
            except Exception as e:
                yield e

    def _parse_feed_for_update(
        self, feed: FeedForUpdate
    ) -> Tuple[FeedForUpdate, Union[ParsedFeed, ParseError, _NotModified]]:
        try:
            return feed, self._parser(feed.url, feed.http_etag, feed.http_last_modified)
        except (ParseError, _NotModified) as e:
            log.debug(
                "_parse_feed_for_update exception, traceback follows", exc_info=True
            )
            return feed, e

    def _update_feed(
        self,
        feed_to_update: Optional[FeedUpdateIntent],
        entries_to_update: Iterable[EntryUpdateIntent],
    ) -> None:
        if feed_to_update:
            if entries_to_update:
                self._storage.add_or_update_entries(entries_to_update)
            self._storage.update_feed(feed_to_update)

        # if feed_for_update.url != parsed_feed.feed.url, the feed was redirected.
        # TODO: Maybe handle redirects somehow else (e.g. change URL if permanent).

        for entry in entries_to_update:
            if not entry.new:
                continue
            for plugin in self._post_entry_add_plugins:
                plugin(self, entry.entry)

    def get_entries(
        self,
        *,
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        feed_tags: TagFilterInput = None,
        sort: EntrySortOrder = 'recent',
    ) -> Iterable[Entry]:
        """Get all or some of the entries.

        Entries are sorted according to ``sort``. Possible values:

        ``'recent'``

            Most recent first. Currently, that means:

            * by import date for entries published less than 7 days ago
            * by published date otherwise (if an entry does not have
              :attr:`~Entry.published`, :attr:`~Entry.updated` is used)

            This is to make sure newly imported entries appear at the top
            regardless of when the feed says they were published
            (sometimes, it lies by a day or two).

            .. note::

                The algorithm for "recent" is a heuristic and may change over time.

        ``'random'``

            Random. At at most 256 entries will be returned.

            .. versionadded:: 1.2

        Args:
            feed (str or Feed or None): Only return the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only return the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only return (un)read entries.
            important (bool or None): Only return (un)important entries.
            has_enclosures (bool or None): Only return entries that (don't)
                have enclosures.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only return the entries from feeds matching these tags;
                works like the :meth:`~Reader.get_feeds()` ``tags`` argument.
            sort (str): How to order entries; one of ``'recent'`` (default)
                or ``'random'``.

        Yields:
            :class:`Entry`: Sorted according to ``sort``.

        Raises:
            StorageError

        .. versionadded:: 1.2
            The ``sort`` keyword argument.

        .. versionadded:: 1.7
            The ``feed_tags`` keyword argument.

        """

        # If we ever implement pagination, consider following the guidance in
        # https://specs.openstack.org/openstack/api-wg/guidelines/pagination_filter_sort.html

        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )
        if sort not in ('recent', 'random'):
            raise ValueError("sort should be one of ('recent', 'random')")
        now = self._now()
        return self._storage.get_entries(now, filter_options, sort)

    @overload
    def get_entry(self, entry: EntryInput) -> Entry:  # pragma: no cover
        ...

    @overload
    def get_entry(
        self, entry: EntryInput, default: _T
    ) -> Union[Entry, _T]:  # pragma: no cover
        ...

    def get_entry(
        self, entry: EntryInput, default: Union[MissingType, _T] = MISSING
    ) -> Union[Entry, _T]:
        """Get an entry.

        Like ``next(iter(reader.get_entries(entry=entry)), default)``,
        but raises a custom exception instead of :exc:`StopIteration`.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.
            default: Returned if given and the entry does not exist.

        Returns:
            Entry: The entry.

        Raises:
            EntryNotFoundError
            StorageError

        """
        return zero_or_one(
            self.get_entries(entry=entry),
            lambda: EntryNotFoundError(*_entry_argument(entry)),
            default,
        )

    def get_entry_counts(
        self,
        *,
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        feed_tags: TagFilterInput = None,
    ) -> EntryCounts:
        """Count all or some of the entries.

        See :meth:`~Reader.get_entries()` for details on how filtering works.

        Args:
            feed (str or Feed or None): Only count the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only count the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only count (un)read entries.
            important (bool or None): Only count (un)important entries.
            has_enclosures (bool or None): Only count entries that (don't)
                have enclosures.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only count the entries from feeds matching these tags.

        Returns:
            :class:`EntryCounts`:

        Raises:
            StorageError

        .. versionadded:: 1.11

        """

        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )
        return self._storage.get_entry_counts(filter_options)

    def mark_as_read(self, entry: EntryInput) -> None:
        """Mark an entry as read.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, True)

    def mark_as_unread(self, entry: EntryInput) -> None:
        """Mark an entry as unread.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, False)

    def mark_as_important(self, entry: EntryInput) -> None:
        """Mark an entry as important.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_important_unimportant(feed_url, entry_id, True)

    def mark_as_unimportant(self, entry: EntryInput) -> None:
        """Mark an entry as unimportant.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_important_unimportant(feed_url, entry_id, False)

    def iter_feed_metadata(
        self, feed: FeedInput, *, key: Optional[str] = None,
    ) -> Iterable[Tuple[str, JSONType]]:
        """Get all or some of the metadata values for a feed.

        Args:
            feed (str or Feed): The feed URL.
            key (str or None): Only return the metadata for this key.

        Yields:
            tuple(str, JSONType): Key-value pairs, in undefined order.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            StorageError

        """
        feed_url = _feed_argument(feed)
        return self._storage.iter_feed_metadata(feed_url, key)

    @overload
    def get_feed_metadata(
        self, feed: FeedInput, key: str
    ) -> JSONType:  # pragma: no cover
        ...

    @overload
    def get_feed_metadata(
        self, feed: FeedInput, key: str, default: _T
    ) -> Union[JSONType, _T]:  # pragma: no cover
        ...

    def get_feed_metadata(
        self, feed: FeedInput, key: str, default: Union[MissingType, _T] = MISSING
    ) -> Union[JSONType, _T]:
        """Get metadata for a feed.

        Like ``next(iter(reader.get_feed_metadata(feed, key=key)), default)``,
        but raises a custom exception instead of :exc:`StopIteration`.

        Args:
            feed (str or Feed): The feed URL.
            key (str): The key of the metadata to retrieve.
            default: Returned if given and no metadata exists for `key`.

        Returns:
            JSONType: The metadata value.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            MetadataNotFoundError
            StorageError

        """
        return zero_or_one(
            (v for _, v in self.iter_feed_metadata(feed, key=key)),
            lambda: MetadataNotFoundError(_feed_argument(feed), key),
            default,
        )

    def set_feed_metadata(self, feed: FeedInput, key: str, value: JSONType) -> None:
        """Set metadata for a feed.

        Args:
            feed (str or Feed): The feed URL.
            key (str): The key of the metadata to set.
            value (JSONType): The value of the metadata to set.
                JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            FeedNotFoundError
            StorageError

        """
        feed_url = _feed_argument(feed)
        self._storage.set_feed_metadata(feed_url, key, value)

    def delete_feed_metadata(self, feed: FeedInput, key: str) -> None:
        """Delete metadata for a feed.

        Args:
            feed (str or Feed): The feed URL.
            key (str): The key of the metadata to delete.

        Raises:
            MetadataNotFoundError
            StorageError

        """
        feed_url = _feed_argument(feed)
        self._storage.delete_feed_metadata(feed_url, key)

    def enable_search(self) -> None:
        """Enable full-text search.

        Calling this method if search is already enabled is a no-op.

        Raises:
            SearchError
            StorageError

        """
        return self._search.enable()

    def disable_search(self) -> None:
        """Disable full-text search.

        Calling this method if search is already disabled is a no-op.

        Raises:
            SearchError

        """
        return self._search.disable()

    def is_search_enabled(self) -> bool:
        """Check if full-text search is enabled.

        Returns:
            bool: Whether search is enabled or not.

        Raises:
            SearchError

        """
        return self._search.is_enabled()

    def update_search(self) -> None:
        """Update the full-text search index.

        Search must be enabled to call this method.

        Raises:
            SearchNotEnabledError
            SearchError
            StorageError

        """
        return self._search.update()

    def search_entries(
        self,
        query: str,
        *,
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        feed_tags: TagFilterInput = None,
        sort: SearchSortOrder = 'relevant',
    ) -> Iterable[EntrySearchResult]:
        """Get entries matching a full-text search query.

        Entries are sorted according to ``sort``. Possible values:

        ``'relevant'``

            Most relevant first.

        ``'recent'``

            Most recent first. See :meth:`~Reader.get_entries()`
            for details on what *recent* means.

            .. versionadded:: 1.4

        ``'random'``

            Random. At at most 256 entries will be returned.

            .. versionadded:: 1.10

        Note:
            The query syntax is dependent on the search provider.

            The default (and for now, only) search provider is SQLite FTS5.
            You can find more details on its query syntax here:
            https://www.sqlite.org/fts5.html#full_text_query_syntax

            The columns available in queries are:

            * ``title``: the entry title
            * ``feed``: the feed title
            * ``content``: the entry main text content;
              this includes the summary and the value of contents that have
              text/(x)html, text/plain or missing content types

            Query examples:

            * ``hello internet``: entries that match "hello" and "internet"
            * ``hello NOT internet``: entries that match "hello" but do not
              match "internet"
            * ``hello feed: cortex``: entries that match "hello" anywhere,
              and their feed title matches "cortex"
            * ``hello NOT feed: internet``: entries that match "hello" anywhere,
              and their feed title does not match "internet"

        Search must be enabled to call this method.

        Args:
            query (str): The search query.
            feed (str or Feed or None): Only search the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only search for the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only search (un)read entries.
            important (bool or None): Only search (un)important entries.
            has_enclosures (bool or None): Only search entries that (don't)
                have enclosures.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only return the entries from feeds matching these tags;
                works like the :meth:`~Reader.get_feeds()` ``tags`` argument.
            sort (str): How to order results; one of ``'relevant'`` (default),
                ``'recent'``, or ``'random'``.

        Yields:
            :class:`EntrySearchResult`: Sorted according to ``sort``.

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            SearchError
            StorageError

        .. versionadded:: 1.4
            The ``sort`` keyword argument.

        .. versionadded:: 1.7
            The ``feed_tags`` keyword argument.

        """
        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )
        if sort not in ('relevant', 'recent', 'random'):
            raise ValueError("sort should be one of ('relevant', 'recent', 'random')")
        now = self._now()
        return self._search.search_entries(query, now, filter_options, sort)

    def search_entry_counts(
        self,
        query: str,
        *,
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        feed_tags: TagFilterInput = None,
    ) -> EntrySearchCounts:
        """Count entries matching a full-text search query.

        See :meth:`~Reader.search_entries()` for details on how
        the query syntax and filtering work.

        Search must be enabled to call this method.

        Args:
            query (str): The search query.
            feed (str or Feed or None): Only count the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only count the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only count (un)read entries.
            important (bool or None): Only count (un)important entries.
            has_enclosures (bool or None): Only count entries that (don't)
                have enclosures.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only count the entries from feeds matching these tags.

        Returns:
            :class:`EntrySearchCounts`:

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            SearchError
            StorageError

        .. versionadded:: 1.11

        """

        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )
        return self._search.search_entry_counts(query, filter_options)

    def add_feed_tag(self, feed: FeedInput, tag: str) -> None:
        """Add a tag to a feed.

        Adding a tag that the feed already has is a no-op.

        Args:
            feed (str or Feed): The feed URL.
            tag (str): The tag to add.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.7

        """
        feed_url = _feed_argument(feed)
        self._storage.add_feed_tag(feed_url, tag)

    def remove_feed_tag(self, feed: FeedInput, tag: str) -> None:
        """Remove a tag from a feed.

        Removing a tag that the feed does not have is a no-op.

        Args:
            feed (str or Feed): The feed URL.
            tag (str): The tag to remove.

        Raises:
            StorageError

        .. versionadded:: 1.7

        """
        feed_url = _feed_argument(feed)
        self._storage.remove_feed_tag(feed_url, tag)

    def get_feed_tags(self, feed: Optional[FeedInput] = None) -> Iterable[str]:
        """Get all or some of the feed tags.

        Args:
            feed (str or Feed or None): Only return the tags for this feed.

        Yields:
            str: The tags, in alphabetical order.

        Raises:
            StorageError

        .. versionadded:: 1.7

        """
        feed_url = _feed_argument(feed) if feed is not None else feed
        return self._storage.get_feed_tags(feed_url)
