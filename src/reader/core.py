import builtins
import itertools
import logging
import numbers
import warnings
from contextlib import nullcontext
from datetime import datetime
from types import MappingProxyType
from typing import Any
from typing import Callable
from typing import Collection
from typing import Iterable
from typing import Iterator
from typing import Mapping
from typing import MutableSequence
from typing import Optional
from typing import overload
from typing import Tuple
from typing import TypeVar
from typing import Union

import reader._updater
from ._parser import default_parser
from ._parser import Parser
from ._parser import SESSION_TIMEOUT
from ._requests_utils import TimeoutType
from ._search import Search
from ._storage import Storage
from ._types import DEFAULT_RESERVED_NAME_SCHEME
from ._types import EntryData
from ._types import EntryFilterOptions
from ._types import EntryUpdateIntent
from ._types import FeedFilterOptions
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._types import NameScheme
from ._types import ParsedFeed
from ._utils import deprecated_wrapper
from ._utils import make_pool_map
from ._utils import zero_or_one
from .exceptions import EntryNotFoundError
from .exceptions import FeedMetadataNotFoundError
from .exceptions import FeedNotFoundError
from .exceptions import InvalidPluginError
from .exceptions import ParseError
from .plugins import _DEFAULT_PLUGINS
from .plugins import _PLUGINS
from .types import _entry_argument
from .types import _feed_argument
from .types import Entry
from .types import EntryCounts
from .types import EntryInput
from .types import EntrySearchCounts
from .types import EntrySearchResult
from .types import EntrySortOrder
from .types import EntryUpdateStatus
from .types import Feed
from .types import FeedCounts
from .types import FeedInput
from .types import FeedSortOrder
from .types import JSONType
from .types import MISSING
from .types import MissingType
from .types import SearchSortOrder
from .types import TagFilterInput
from .types import UpdatedFeed
from .types import UpdateResult


log = logging.getLogger('reader')


_T = TypeVar('_T')
_U = TypeVar('_U')

ReaderPluginType = Callable[['Reader'], None]
AfterEntryUpdateHook = Callable[
    ['Reader', EntryData[datetime], EntryUpdateStatus], None
]
_PostFeedUpdatePluginType = Callable[['Reader', str], None]


def make_reader(
    url: str,
    *,
    feed_root: Optional[str] = '',
    plugins: Iterable[Union[str, ReaderPluginType]] = _DEFAULT_PLUGINS,
    session_timeout: TimeoutType = SESSION_TIMEOUT,
    reserved_name_scheme: Mapping[str, str] = DEFAULT_RESERVED_NAME_SCHEME,
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

        plugins (iterable(str or callable(Reader)) or None):
            An iterable of built-in plugin names or
            `plugin(reader) --> None` callables.
            The callables are called with the reader object
            before it is returned.
            Exceptions from plugin code will propagate to the caller.
            The only plugin used by default is ``reader.ua_fallback``.

        session_timeout (float or tuple(float, float) or None):
            When retrieving HTTP(S) feeds,
            how many seconds to wait for the server to send data,
            as a float, or a (connect timeout, read timeout) tuple.
            Passed to the underlying `Requests session`_.

        reserved_name_scheme (dict(str, str) or None):
            Value for :attr:`~Reader.reserved_name_scheme`.
            The prefixes default to ``.reader.``/``.plugin.``,
            and the separator to ``.``

    .. _Requests session: https://requests.readthedocs.io/en/master/user/advanced/#timeouts

    Returns:
        Reader: The reader.

    Raises:
        StorageError
        InvalidPluginError: If an invalid plugin name is passed to ``plugins``.

    .. versionadded:: 1.6
        The ``feed_root`` keyword argument.

    .. versionchanged:: 2.0
        The default ``feed_root`` behavior will change from
        *full filesystem access* (``''``) to
        *don't open local feeds* (``None``).

    .. versionadded:: 1.14
        The ``session_timeout`` keyword argument,
        with a default of (3.05, 60) seconds;
        the previous behavior was to *never time out*.

    .. versionadded:: 1.16
        The ``plugins`` keyword argument. Using an invalid plugin name
        raises :exc:`InvalidPluginError`, a :exc:`ValueError` subclass.

    .. versionadded:: 1.17
        The ``reserved_name_scheme`` argument.

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

    parser = default_parser(feed_root, session_timeout=session_timeout)

    reader = Reader(
        storage, search, parser, reserved_name_scheme, _called_directly=False
    )

    for plugin in plugins:
        if isinstance(plugin, str):
            if plugin not in _PLUGINS:
                raise InvalidPluginError(f"no such built-in plugin: {plugin!r}")

            plugin_func = _PLUGINS[plugin]
        else:
            plugin_func = plugin

        try:
            plugin_func(reader)  # type: ignore
        except Exception:  # pragma: no cover
            # TODO: this whole branch is not tested
            reader.close()
            # TODO: this should raise a custom exception (but can't because of backwards compatibility)
            raise

    return reader


class Reader:

    """A feed reader.

    Persists feed and entry state, provides operations on them,
    and stores configuration.

    Currently, the following feed types are supported:

    * Atom (provided by `feedparser`_)
    * RSS (provided by `feedparser`_)
    * JSON Feed

    .. _feedparser: https://feedparser.readthedocs.io/en/latest/


    .. important::

        Reader objects should be created using :func:`make_reader`; the Reader
        constructor is not stable yet and may change without any notice.

    .. important::

        The :class:`Reader` object is not thread safe;
        its methods should be called only from the thread that created it.

        To access the same database from multiple threads,
        create one instance in each thread.
        If you have a strong use case preventing you to do so,
        please +1 / comment in :issue:`206`.


    .. versionadded:: 1.13
        JSON Feed support.


    """

    def __init__(
        self,
        _storage: Storage,
        _search: Search,
        _parser: Parser,
        _reserved_name_scheme: Mapping[str, str],
        _called_directly: bool = True,
    ):
        self._storage = _storage
        self._search = _search
        self._parser = _parser

        try:
            self.reserved_name_scheme = _reserved_name_scheme
        except AttributeError as e:
            raise ValueError(str(e)) from (e.__cause__ or e)

        self._updater = reader._updater
        self._post_feed_update_plugins: Collection[_PostFeedUpdatePluginType] = []

        #: List of functions called for each updated entry
        #: after the feed was updated.
        #:
        #: Each function is called with:
        #:
        #: * `reader` – the :class:`Reader` instance
        #: * `entry` – an :class:`Entry`-like object
        #: * `status` – an :class:`EntryUpdateStatus` value
        #:
        #: Each function should return :const:`None`.
        #:
        #: .. warning::
        #:
        #:  The only `entry` attributes guaranteed to be present are
        #:  :attr:`~Entry.feed_url`, :attr:`~Entry.id`,
        #:  and :attr:`~Entry.object_id`;
        #:  all other attributes may be missing
        #:  (accessing them may raise :exc:`AttributeError`).
        #:
        #: .. versionadded:: 1.20
        #:
        self.after_entry_update_hooks: MutableSequence[AfterEntryUpdateHook] = []

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

    def delete_feed(self, feed: FeedInput) -> None:
        """Delete a feed and all of its entries, metadata, and tags.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`remove_feed`.

        """
        url = _feed_argument(feed)
        self._storage.delete_feed(url)

    remove_feed = deprecated_wrapper('remove_feed', delete_feed, '1.18', '2.0')

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
        limit: Optional[int] = None,
        starting_after: Optional[FeedInput] = None,
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
            limit (int or None): A limit on the number of feeds to be returned;
                by default, all feeds are returned.
            starting_after (str or Feed or None):
                Return feeds after this feed; a cursor for use in pagination.

        Yields:
            :class:`Feed`: Sorted according to ``sort``.

        Raises:
            StorageError
            FeedNotFoundError: If ``starting_after`` does not exist.

        .. versionadded:: 1.7
            The ``tags`` keyword argument.

        .. versionadded:: 1.7
            The ``broken`` keyword argument.

        .. versionadded:: 1.11
            The ``updates_enabled`` keyword argument.

        .. versionadded:: 1.12
            The ``limit`` and ``starting_after`` keyword arguments.

        """
        filter_options = FeedFilterOptions.from_args(
            feed, tags, broken, updates_enabled
        )

        if sort not in ('title', 'added'):
            raise ValueError("sort should be one of ('title', 'added')")

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")

        return self._storage.get_feeds(
            filter_options,
            sort,
            limit,
            _feed_argument(starting_after) if starting_after else None,
        )

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
            FeedCounts:

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

    def update_feeds(
        self,
        new_only: Union[bool, MissingType] = MISSING,
        workers: int = 1,
        *,
        new: Union[Optional[bool], MissingType] = MISSING,
    ) -> None:
        """Update all the feeds that have updates enabled.

        Silently skip feeds that raise :exc:`ParseError`.

        Roughly equivalent to ``for _ in reader.update_feed_iter(...): pass``.

        Args:
            new_only (bool):
                Only update feeds that have never been updated.
                Defaults to False.

                .. deprecated:: 1.19
                    Use ``new`` instead.

            workers (int): Number of threads to use when getting the feeds.
            new (bool or None):
                Only update feeds that have never been updated
                / have been updated before. Defaults to None.

        Raises:
            StorageError

        .. versionchanged:: 1.11
            Only update the feeds that have updates enabled.

        .. versionchanged:: 1.15
            Update entries whenever their content changes,
            regardless of their :attr:`~Entry.updated` date.

            Content-only updates (not due to an :attr:`~Entry.updated` change)
            are limited to 24 consecutive updates,
            to prevent spurious updates for entries whose content changes
            excessively (for example, because it includes the current time).

            Previously, entries would be updated only if the
            entry :attr:`~Entry.updated` was *newer* than the stored one.

        .. deprecated:: 1.19
            The ``new_only`` argument
            (will be removed in *reader* 2.0);
            use ``new`` instead.

        """
        for url, value in self.update_feeds_iter(new_only, workers, new=new):
            if isinstance(value, ParseError):
                log.exception(
                    "update feed %r: error while getting/parsing feed, "
                    "skipping; exception: %r",
                    url,
                    value.__cause__,
                    exc_info=value,
                )
                continue

            assert not isinstance(value, Exception), value

    def update_feeds_iter(
        self,
        new_only: Union[bool, MissingType] = MISSING,
        workers: int = 1,
        *,
        new: Union[Optional[bool], MissingType] = MISSING,
    ) -> Iterable[UpdateResult]:
        """Update all the feeds that have updates enabled.

        Args:
            new_only (bool):
                Only update feeds that have never been updated.
                Defaults to False.

                .. deprecated:: 1.19
                    Use ``new`` instead.

            workers (int): Number of threads to use when getting the feeds.
            new (bool or None):
                Only update feeds that have never been updated
                / have been updated before. Defaults to None.

        Yields:
            :class:`UpdateResult`:
                An (url, value) pair; the value is one of:

                * a summary of the updated feed, if the update was successful
                * None, if the server indicated the feed has not changed
                  since the last update
                * an exception instance

                Currently, the exception is always a :exc:`ParseError`,
                but other :exc:`ReaderError` subclasses may be yielded
                in the future.

        Raises:
            StorageError

        .. versionadded:: 1.14

        .. versionchanged:: 1.15
            Update entries whenever their content changes.
            See :meth:`~Reader.update_feeds` for details.

        .. deprecated:: 1.19
            The ``new_only`` argument
            (will be removed in *reader* 2.0);
            use ``new`` instead.

        """
        if workers < 1:
            raise ValueError("workers must be a positive integer")

        if new is MISSING and new_only is MISSING:
            new_final = None
        elif new is MISSING and new_only is not MISSING:
            new_final = True if new_only else None
            warnings.warn(
                "new_only is deprecated and will be removed in reader 2.0. "
                "Use new instead.",
                DeprecationWarning,
            )
        elif new is not MISSING and new_only is MISSING:
            assert not isinstance(new, MissingType)  # mypy pleasing
            new_final = new
        else:
            raise TypeError("new and new_only are mutually exclusive")

        make_map = nullcontext(builtins.map) if workers == 1 else make_pool_map(workers)

        with make_map as map:
            results = self._update_feeds(new=new_final, map=map)

            for url, value in results:
                if isinstance(value, FeedNotFoundError):
                    log.info("update feed %r: feed removed during update", url)
                    continue

                if isinstance(value, Exception):
                    if not isinstance(value, ParseError):
                        raise value

                yield UpdateResult(url, value)

    def update_feed(self, feed: FeedInput) -> Optional[UpdatedFeed]:
        """Update a single feed.

        The feed will be updated even if updates are disabled for it.

        Args:
            feed (str or Feed): The feed URL.

        Returns:
            UpdatedFeed or None:
            A summary of the updated feed or None,
            if the server indicated the feed has not changed
            since the last update.

        Raises:
            FeedNotFoundError
            ParseError
            StorageError

        .. versionchanged:: 1.14
            The method now returns UpdatedFeed or None instead of None.

        .. versionchanged:: 1.15
            Update entries whenever their content changes.
            See :meth:`~Reader.update_feeds` for details.

        """
        url = _feed_argument(feed)
        _, rv = zero_or_one(
            self._update_feeds(url=url, enabled_only=False),
            lambda: FeedNotFoundError(url),
        )
        if isinstance(rv, Exception):
            raise rv
        return rv

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

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
        new: Optional[bool] = None,
        enabled_only: bool = True,
        map: Callable[[Callable[[Any], Any], Iterable[Any]], Iterator[Any]] = map,
    ) -> Iterator[Tuple[str, Union[UpdatedFeed, None, Exception]]]:

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

        feeds_for_update = self._storage.get_feeds_for_update(url, new, enabled_only)
        feeds_for_update = builtins.map(
            self._updater.process_old_feed, feeds_for_update
        )

        pairs = map(self._parse_feed_for_update, feeds_for_update)

        for feed_for_update, parse_result in pairs:
            rv: Union[UpdatedFeed, None, Exception]

            try:
                # give storage a chance to consume the entries in a streaming fashion;
                parsed_entries = itertools.tee(
                    parse_result.entries
                    if parse_result and not isinstance(parse_result, Exception)
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
                ) = self._updater.make_update_intents(
                    feed_for_update, now, global_now, parse_result, entry_pairs
                )

                counts = self._update_feed(
                    feed_for_update.url, feed_to_update, entries_to_update
                )

                if isinstance(parse_result, Exception):
                    rv = parse_result
                elif parse_result:
                    rv = UpdatedFeed(feed_for_update.url, *counts)
                else:
                    rv = None

            except Exception as e:
                rv = e

            yield feed_for_update.url, rv

    def _parse_feed_for_update(
        self, feed: FeedForUpdate
    ) -> Tuple[FeedForUpdate, Union[ParsedFeed, None, ParseError]]:
        try:
            return feed, self._parser(feed.url, feed.http_etag, feed.http_last_modified)
        except ParseError as e:
            log.debug(
                "_parse_feed_for_update exception, traceback follows", exc_info=True
            )
            return feed, e

    def _update_feed(
        self,
        url: str,
        feed_to_update: Optional[FeedUpdateIntent],
        entries_to_update: Iterable[EntryUpdateIntent],
    ) -> Tuple[int, int]:
        if feed_to_update:
            if entries_to_update:
                self._storage.add_or_update_entries(entries_to_update)
            self._storage.update_feed(feed_to_update)

        # if feed_for_update.url != parsed_feed.feed.url, the feed was redirected.
        # TODO: Maybe handle redirects somehow else (e.g. change URL if permanent).

        for feed_plugin in self._post_feed_update_plugins:
            feed_plugin(self, url)

        new_count = 0
        updated_count = 0
        for entry in entries_to_update:
            if entry.new:
                new_count += 1
                entry_status = EntryUpdateStatus.NEW
            else:
                updated_count += 1
                entry_status = EntryUpdateStatus.MODIFIED
            for entry_hook in self.after_entry_update_hooks:
                entry_hook(self, entry.entry, entry_status)

        return new_count, updated_count

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
        limit: Optional[int] = None,
        starting_after: Optional[EntryInput] = None,
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

            Random order (shuffled). At at most 256 entries will be returned.

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
            limit (int or None): A limit on the number of entries to be returned;
                by default, all entries are returned.
            starting_after (tuple(str, str) or Entry or None):
                Return entries after this entry; a cursor for use in pagination.
                Using ``starting_after`` with ``sort='random'`` is not supported.

        Yields:
            :class:`Entry`: Sorted according to ``sort``.

        Raises:
            StorageError
            EntryNotFoundError: If ``starting_after`` does not exist.

        .. versionadded:: 1.2
            The ``sort`` keyword argument.

        .. versionadded:: 1.7
            The ``feed_tags`` keyword argument.

        .. versionadded:: 1.12
            The ``limit`` and ``starting_after`` keyword arguments.

        """

        # If we ever implement pagination, consider following the guidance in
        # https://specs.openstack.org/openstack/api-wg/guidelines/pagination_filter_sort.html

        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )

        if sort not in ('recent', 'random'):
            raise ValueError("sort should be one of ('recent', 'random')")

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")

        if starting_after and sort == 'random':
            raise ValueError("using starting_after with sort='random' not supported")

        now = self._now()
        return self._storage.get_entries(
            now,
            filter_options,
            sort,
            limit,
            _entry_argument(starting_after) if starting_after else None,
        )

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
            EntryCounts:

        Raises:
            StorageError

        .. versionadded:: 1.11

        """

        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )
        return self._storage.get_entry_counts(filter_options)

    def mark_entry_as_read(self, entry: EntryInput) -> None:
        """Mark an entry as read.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_read`.

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, True)

    def mark_entry_as_unread(self, entry: EntryInput) -> None:
        """Mark an entry as unread.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_unread`.

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, False)

    def mark_entry_as_important(self, entry: EntryInput) -> None:
        """Mark an entry as important.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_important`.

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_important_unimportant(feed_url, entry_id, True)

    def mark_entry_as_unimportant(self, entry: EntryInput) -> None:
        """Mark an entry as unimportant.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_unimportant`.

        """
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_important_unimportant(feed_url, entry_id, False)

    mark_as_read = deprecated_wrapper('mark_as_read', mark_entry_as_read, '1.18', '2.0')
    mark_as_unread = deprecated_wrapper(
        'mark_as_unread', mark_entry_as_unread, '1.18', '2.0'
    )
    mark_as_important = deprecated_wrapper(
        'mark_as_important', mark_entry_as_important, '1.18', '2.0'
    )
    mark_as_unimportant = deprecated_wrapper(
        'mark_as_unimportant', mark_entry_as_unimportant, '1.18', '2.0'
    )

    def get_feed_metadata(
        self,
        feed: FeedInput,
        *args: Any,
        key: Optional[str] = None,
    ) -> Iterable[Tuple[str, JSONType]]:
        """Get all or some of the metadata for a feed as ``(key, value)`` pairs.

        Args:
            feed (str or Feed): The feed URL.
            key (str or None): Only return the metadata for this key.

        Yields:
            tuple(str, JSONType): ``(key, value)`` pairs, in undefined order.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            StorageError

        .. versionchanged:: 1.18

            :meth:`iter_feed_metadata` was renamed to :meth:`get_feed_metadata`,
            and :meth:`get_feed_metadata` was renamed to :meth:`get_feed_metadata_item`.

            To preserve backwards compatibility,
            the ``get_feed_metadata(feed, key[, default]) -> value``
            form (positional arguments only)
            will continue to work as an alias for
            ``get_feed_metadata_item(feed, key[, default])``
            until the last 1.\\* *reader* version,
            after which it will result in a :exc:`TypeError`.

        """

        if args:
            # get_feed_metadata(feed, key[, default]) -> value
            if len(args) > 2:
                raise TypeError(
                    f"get_feed_metadata() takes 1 positional arguments, but {len(args) + 1} were given"
                )
            warnings.warn(
                "The get_feed_metadata(feed, key[, default]) -> value "
                "version of get_feed_metadata() is deprecated "
                "and will be removed in reader 2.0. "
                "Use get_feed_metadata_item() instead.",
                DeprecationWarning,
            )
            return self.get_feed_metadata_item(feed, *args)  # type: ignore

        # get_feed_metadata(feed, *, key=None) -> (key, value), ...
        feed_url = _feed_argument(feed)
        return self._storage.iter_metadata((feed_url,), key)

    @overload
    def get_feed_metadata_item(
        self, feed: FeedInput, key: str
    ) -> JSONType:  # pragma: no cover
        ...

    @overload
    def get_feed_metadata_item(
        self, feed: FeedInput, key: str, default: _T
    ) -> Union[JSONType, _T]:  # pragma: no cover
        ...

    def get_feed_metadata_item(
        self, feed: FeedInput, key: str, default: Union[MissingType, _T] = MISSING
    ) -> Union[JSONType, _T]:
        """Get metadata for a feed.

        Like ``next(iter(reader.get_feed_metadata(feed, key=key)), (None, default))[1]``,
        but raises a custom exception instead of :exc:`StopIteration`.

        Args:
            feed (str or Feed): The feed URL.
            key (str): The key of the metadata to retrieve.
            default: Returned if given and no metadata exists for `key`.

        Returns:
            JSONType: The metadata value.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            FeedMetadataNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`get_feed_metadata`.

        """
        return zero_or_one(
            (v for _, v in self.get_feed_metadata(feed, key=key)),
            lambda: FeedMetadataNotFoundError(_feed_argument(feed), key),
            default,
        )

    def set_feed_metadata_item(
        self, feed: FeedInput, key: str, value: JSONType
    ) -> None:
        """Set metadata for a feed.

        Args:
            feed (str or Feed): The feed URL.
            key (str): The key of the metadata item to set.
            value (JSONType): The value of the metadata item to set.
                JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`set_feed_metadata`.

        """
        feed_url = _feed_argument(feed)
        self._storage.set_metadata((feed_url,), key, value)

    def delete_feed_metadata_item(self, feed: FeedInput, key: str) -> None:
        """Delete metadata for a feed.

        Args:
            feed (str or Feed): The feed URL.
            key (str): The key of the metadata item to delete.

        Raises:
            FeedMetadataNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`delete_feed_metadata`.

        """
        feed_url = _feed_argument(feed)
        self._storage.delete_metadata((feed_url,), key)

    iter_feed_metadata = deprecated_wrapper(
        'iter_feed_metadata', get_feed_metadata, '1.18', '2.0'
    )
    set_feed_metadata = deprecated_wrapper(
        'set_feed_metadata', set_feed_metadata_item, '1.18', '2.0'
    )
    delete_feed_metadata = deprecated_wrapper(
        'delete_feed_metadata', delete_feed_metadata_item, '1.18', '2.0'
    )

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
        limit: Optional[int] = None,
        starting_after: Optional[EntryInput] = None,
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

            Random order (shuffled). At at most 256 entries will be returned.

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
            limit (int or None): A limit on the number of results to be returned;
                by default, all results are returned.
            starting_after (tuple(str, str) or EntrySearchResult or None):
                Return results after this result; a cursor for use in pagination.
                Using ``starting_after`` with ``sort='random'`` is not supported.

        Yields:
            :class:`EntrySearchResult`: Sorted according to ``sort``.

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            SearchError
            StorageError
            EntryNotFoundError: If ``starting_after`` does not exist.

        .. versionadded:: 1.4
            The ``sort`` keyword argument.

        .. versionadded:: 1.7
            The ``feed_tags`` keyword argument.

        .. versionadded:: 1.12
            The ``limit`` and ``starting_after`` keyword arguments.

        """
        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures, feed_tags
        )

        if sort not in ('relevant', 'recent', 'random'):
            raise ValueError("sort should be one of ('relevant', 'recent', 'random')")

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")

        if starting_after and sort == 'random':
            raise ValueError("using starting_after with sort='random' not supported")

        now = self._now()
        return self._search.search_entries(
            query,
            now,
            filter_options,
            sort,
            limit,
            _entry_argument(starting_after) if starting_after else None,
        )

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
            EntrySearchCounts:

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
        self._storage.add_tag((feed_url,), tag)

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
        self._storage.remove_tag((feed_url,), tag)

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
        feed_url = _feed_argument(feed) if feed is not None else None
        return self._storage.get_tags((feed_url,))

    def make_reader_reserved_name(self, key: str) -> str:
        """Create a *reader*-reserved tag or metadata name.
        See :ref:`reserved names` for details.

        Uses :attr:`~Reader.reserved_name_scheme` to build names of the format::

        {reader_prefix}{key}

        Using the default scheme:

        >>> reader.make_reader_reserved_name('key')
        '.reader.key'

        Args:
            key (str): A key.

        Returns:
            str: The name.

        .. versionadded:: 1.17

        """
        return self._reserved_name_scheme.make_reader_name(key)

    def make_plugin_reserved_name(
        self, plugin_name: str, key: Optional[str] = None
    ) -> str:
        """Create a plugin-reserved tag or metadata name.
        See :ref:`reserved names` for details.

        Plugins should use this to generate names
        for plugin-specific tags and metadata.

        Uses :attr:`~Reader.reserved_name_scheme` to build names of the format::

        {plugin_prefix}{plugin_name}
        {plugin_prefix}{plugin_name}{separator}{key}

        Using the default scheme:

        >>> reader.make_plugin_reserved_name('myplugin')
        '.plugin.myplugin'
        >>> reader.make_plugin_reserved_name('myplugin', 'key')
        '.plugin.myplugin.key'

        Args:
            plugin_name (str): The plugin package/module name.
            key (str or None): A key; if more than one reserved name is needed.

        Returns:
            str: The name.

        .. versionadded:: 1.17

        """
        return self._reserved_name_scheme.make_plugin_name(plugin_name, key)

    # Ideally, the getter would return a TypedDict,
    # but the setter would take *any* Mapping[str, str];
    # unfortunately, mypy doesn't like when the types differ:
    # https://github.com/python/mypy/issues/3004

    @property
    def reserved_name_scheme(self) -> Mapping[str, str]:
        """dict(str, str): Mapping used to build reserved names.
        See :meth:`~Reader.make_reader_reserved_name`
        and :meth:`~Reader.make_plugin_reserved_name`
        for details on how this is used.

        The default scheme (these keys are required)::

            {'reader_prefix': '.reader.', 'plugin_prefix': '.plugin.', 'separator': '.'}

        The returned mapping is immutable; assign a new mapping to change the scheme.

        .. versionadded:: 1.17

        """
        return MappingProxyType(self._reserved_name_scheme.__dict__)

    @reserved_name_scheme.setter
    def reserved_name_scheme(self, value: Mapping[str, str]) -> None:
        try:
            self._reserved_name_scheme = NameScheme.from_value(value)
        except Exception as e:
            raise AttributeError(f"invalid scheme: {value}") from e
