import builtins
import itertools
import logging
import numbers
import warnings
from contextlib import nullcontext
from datetime import datetime
from datetime import timezone
from types import MappingProxyType
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Mapping
from typing import MutableSequence
from typing import Optional
from typing import overload
from typing import Tuple
from typing import TypeVar
from typing import Union

from typing_extensions import Literal

import reader._updater
from ._parser import default_parser
from ._parser import Parser
from ._parser import SESSION_TIMEOUT
from ._requests_utils import TimeoutType
from ._search import Search
from ._storage import Storage
from ._types import DEFAULT_RESERVED_NAME_SCHEME
from ._types import entry_data_from_obj
from ._types import EntryData
from ._types import EntryFilterOptions
from ._types import EntryUpdateIntent
from ._types import FeedFilterOptions
from ._types import FeedUpdateIntent
from ._types import fix_datetime_tzinfo
from ._types import NameScheme
from ._utils import deprecated
from ._utils import make_pool_map
from ._utils import MapType
from ._utils import zero_or_one
from .exceptions import EntryNotFoundError
from .exceptions import FeedExistsError
from .exceptions import FeedMetadataNotFoundError
from .exceptions import FeedNotFoundError
from .exceptions import InvalidPluginError
from .exceptions import ParseError
from .exceptions import SearchNotEnabledError
from .exceptions import TagNotFoundError
from .plugins import _PLUGINS
from .plugins import DEFAULT_PLUGINS
from .types import _entry_argument
from .types import _feed_argument
from .types import _resource_argument
from .types import AnyResourceId
from .types import AnyResourceInput
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
from .types import ResourceInput
from .types import SearchSortOrder
from .types import TagFilterInput
from .types import UpdatedFeed
from .types import UpdateResult


log = logging.getLogger('reader')


_T = TypeVar('_T')
_U = TypeVar('_U')

ReaderPluginType = Callable[['Reader'], None]
AfterEntryUpdateHook = Callable[['Reader', EntryData, EntryUpdateStatus], None]
FeedUpdateHook = Callable[['Reader', str], None]


def make_reader(
    url: str,
    *,
    feed_root: Optional[str] = None,
    plugins: Iterable[Union[str, ReaderPluginType]] = DEFAULT_PLUGINS,
    session_timeout: TimeoutType = SESSION_TIMEOUT,
    reserved_name_scheme: Mapping[str, str] = DEFAULT_RESERVED_NAME_SCHEME,
    search_enabled: Union[bool, None, Literal['auto']] = 'auto',
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
            One of ``None`` (don't open local feeds; default),
            ``''`` (full filesystem access), or
            ``'/path/to/feed/root'``
            (an absolute path that feed paths are relative to).

        plugins (iterable(str or callable(Reader)) or None):
            An iterable of built-in plugin names or
            `plugin(reader) --> None` callables.
            The callables are called with the reader object
            before it is returned.
            Exceptions from plugin code will propagate to the caller.
            Defaults to :data:`~reader.plugins.DEFAULT_PLUGINS`.

        session_timeout (float or tuple(float, float) or None):
            When retrieving HTTP(S) feeds,
            how many seconds to wait for the server to send data,
            as a float, or a (connect timeout, read timeout) tuple.
            Passed to the underlying `Requests session`_.

        reserved_name_scheme (dict(str, str)):
            Value for :attr:`~Reader.reserved_name_scheme`.
            The prefixes default to ``.reader.``/``.plugin.``,
            and the separator to ``.``

        search_enabled (bool or None or ``'auto'``):
            Whether to enable search. One of
            ``'auto'`` (enable on the first
            :meth:`~Reader.update_search` call; default),
            :const:`True` (enable),
            :const:`False` (disable),
            :const:`None` (do nothing).

    .. _Requests session: https://requests.readthedocs.io/en/master/user/advanced/#timeouts

    Returns:
        Reader: The reader.

    Raises:
        StorageError: An error occurred while connecting to storage.
        SearchError: An error occurred while enabling/disabling search.
        InvalidPluginError: An invalid plugin name was passed to ``plugins``.
        ReaderError: An ambiguous exception occurred while creating the reader.

    .. versionadded:: 1.6
        The ``feed_root`` keyword argument.

    .. versionadded:: 1.14
        The ``session_timeout`` keyword argument,
        with a default of (3.05, 60) seconds;
        the previous behavior was to *never time out*.

    .. versionadded:: 1.16
        The ``plugins`` keyword argument. Using an invalid plugin name
        raises :exc:`InvalidPluginError`, a :exc:`ValueError` subclass.

    .. versionadded:: 1.17
        The ``reserved_name_scheme`` keyword argument.

    .. versionchanged:: 2.0
        ``feed_root`` now defaults to ``None`` (don't open local feeds)
        instead of ``''`` (full filesystem access).

    .. versionadded:: 2.4
        The ``search_enabled`` keyword argument.

    .. versionchanged:: 2.4
        Enable search on the first :meth:`~Reader.update_search` call.
        To get the previous behavior (leave search as-is),
        use ``search_enabled=None``.

    """

    # Do as much work as possible before creating the storage.

    if search_enabled not in ('auto', True, False, None):
        raise ValueError("search_enabled should be one of ('auto', True, False, None)")

    parser = default_parser(feed_root, session_timeout=session_timeout)

    try:
        name_scheme = NameScheme.from_value(reserved_name_scheme)
    except Exception as e:
        raise ValueError(f"invalid reserved name scheme: {reserved_name_scheme}") from e

    plugin_funcs: List[ReaderPluginType] = []
    for plugin in plugins:
        if isinstance(plugin, str):
            if plugin not in _PLUGINS:
                raise InvalidPluginError(f"no such built-in plugin: {plugin!r}")
            plugin_func = _PLUGINS[plugin]
        else:
            plugin_func = plugin
        plugin_funcs.append(plugin_func)

    # If we ever need to change the signature of make_reader(),
    # or support additional storage/search implementations,
    # we'll need to do the wiring differently.
    #
    # See this comment for details on how it should evolve:
    # https://github.com/lemon24/reader/issues/168#issuecomment-642002049

    storage = _storage or Storage(url, factory=_storage_factory)

    try:
        # For now, we're using a storage-bound search provider.
        search = Search(storage)

        if search_enabled is True:
            search.check_dependencies()
            search.enable()
        elif search_enabled is False:
            search.disable()

        reader = Reader(
            storage,
            search,
            parser,
            name_scheme,
            _enable_search=(search_enabled == 'auto'),
            _called_directly=False,
        )

        # TODO: (maybe) wrap exceptions raised here in a custom exception
        for plugin_func in plugin_funcs:
            plugin_func(reader)

    except BaseException:
        storage.close()
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

    .. versionchanged:: 2.10
        Allow passing a `(feed URL,)` 1-tuple anywhere a feed URL can be passed.

    """

    def __init__(
        self,
        _storage: Storage,
        _search: Search,
        _parser: Parser,
        _reserved_name_scheme: NameScheme,
        _enable_search: bool = False,
        _called_directly: bool = True,
    ):
        self._storage = _storage
        self._search = _search
        self._parser = _parser

        self._reserved_name_scheme = _reserved_name_scheme

        self._enable_search = _enable_search

        self._updater = reader._updater

        #: List of functions called for each updated entry
        #: after the feed is updated.
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

        #: List of functions called for each updated feed
        #: before the feed is updated.
        #:
        #: Each function is called with:
        #:
        #: * `reader` – the :class:`Reader` instance
        #: * `feed` – the :class:`str` feed URL
        #:
        #: Each function should return :const:`None`.
        #:
        #: .. versionadded:: 2.7
        #:
        self.before_feed_update_hooks: MutableSequence[FeedUpdateHook] = []

        #: List of functions called for each updated feed
        #: after the feed is updated.
        #:
        #: Each function is called with:
        #:
        #: * `reader` – the :class:`Reader` instance
        #: * `feed` – the :class:`str` feed URL
        #:
        #: Each function should return :const:`None`.
        #:
        #: .. versionadded:: 2.2
        #:
        self.after_feed_update_hooks: MutableSequence[FeedUpdateHook] = []

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

    def add_feed(
        self,
        feed: FeedInput,
        exist_ok: bool = False,
        *,
        allow_invalid_url: bool = False,
    ) -> None:
        """Add a new feed.

        Feed updates are enabled by default.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            allow_invalid_url (bool):
                Add feed even if the current Reader configuration
                does not know how to handle the feed URL
                (and updates for it would fail).
            exist_ok (bool):
                If true, don't raise :exc:`FeedExistsError`
                if the feed already exists.

        Raises:
            FeedExistsError: If the feed already exists, and `exist_ok` is false.
            StorageError
            InvalidFeedURLError: If ``feed`` is invalid and ``allow_invalid_url`` is false.

        .. versionadded:: 2.5
            The ``allow_invalid_url`` keyword argument.

        .. versionchanged:: 2.5
            Validate the new feed URL.
            To get the previous behavior (no validation),
            use ``allow_invalid_url=True``.

        .. versionadded:: 2.8
            The ``exist_ok`` argument.

        """
        url = _feed_argument(feed)
        if not allow_invalid_url:
            self._parser.validate_url(url)
        now = self._now()
        try:
            self._storage.add_feed(url, now)
        except FeedExistsError:
            if not exist_ok:
                raise

    def delete_feed(self, feed: FeedInput, missing_ok: bool = False) -> None:
        """Delete a feed and all of its entries, metadata, and tags.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            missing_ok (bool):
                If true, don't raise :exc:`FeedNotFoundError`
                if the feed does not exist.

        Raises:
            FeedNotFoundError: If the feed does not exist, and `missing_ok` is false.
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`remove_feed`.

        .. versionadded:: 2.8
            The ``missing_ok`` argument.

        """
        url = _feed_argument(feed)
        try:
            self._storage.delete_feed(url)
        except FeedNotFoundError:
            if not missing_ok:
                raise

    def change_feed_url(
        self, old: FeedInput, new: FeedInput, *, allow_invalid_url: bool = False
    ) -> None:
        """Change the URL of a feed.

        User-defined feed attributes are preserved:
        :attr:`~Feed.added`, :attr:`~Feed.user_title`.
        Feed-defined feed attributes are also preserved,
        at least until the next update:
        :attr:`~Feed.title`, :attr:`~Feed.link`, :attr:`~Feed.author`,
        :attr:`~Feed.subtitle`
        (except :attr:`~Feed.updated` and :attr:`~Feed.version`,
        which get set to None).
        All other feed attributes are set to their default values.

        The entries, tags and metadata are preserved.

        Args:
            old (str or tuple(str) or Feed): The old feed; must exist.
            new (str or tuple(str) or Feed): The new feed; must not exist.
            allow_invalid_url (bool):
                Change feed URL even if the current Reader configuration
                does not know how to handle the new feed URL
                (and updates for it would fail).

        Raises:
            FeedNotFoundError: If ``old`` does not exist.
            FeedExistsError: If ``new`` already exists.
            StorageError
            InvalidFeedURLError: If ``new`` is invalid and ``allow_invalid_url`` is false.

        .. versionadded:: 1.8

        .. versionadded:: 2.5
            The ``allow_invalid_url`` keyword argument.

        .. versionchanged:: 2.5
            Validate the new feed URL.
            To get the previous behavior (no validation),
            use ``allow_invalid_url=True``.

        """
        old_str = _feed_argument(old)
        new_str = _feed_argument(new)
        if not allow_invalid_url:
            self._parser.validate_url(new_str)
        self._storage.change_feed_url(old_str, new_str)

    def get_feeds(
        self,
        *,
        feed: Optional[FeedInput] = None,
        tags: TagFilterInput = None,
        broken: Optional[bool] = None,
        updates_enabled: Optional[bool] = None,
        new: Optional[bool] = None,
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
            feed (str or tuple(str) or Feed or None): Only return the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only return feeds matching these tags.
            broken (bool or None): Only return broken / healthy feeds.
            updates_enabled (bool or None):
                Only return feeds that have updates enabled / disabled.
            new (bool or None):
                Only return feeds that have never been updated
                / have been updated before.
            sort (str): How to order feeds; one of ``'title'`` (by
                :attr:`~Feed.user_title` or :attr:`~Feed.title`, case
                insensitive; default), or ``'added'`` (last added first).
            limit (int or None): A limit on the number of feeds to be returned;
                by default, all feeds are returned.
            starting_after (str or tuple(str) or Feed or None):
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

        .. versionadded:: 2.6
            The ``new`` keyword argument.

        """
        filter_options = FeedFilterOptions.from_args(
            feed, tags, broken, updates_enabled, new
        )

        if sort not in ('title', 'added'):
            raise ValueError("sort should be one of ('title', 'added')")

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")

        rv = self._storage.get_feeds(
            filter_options,
            sort,
            limit,
            _feed_argument(starting_after) if starting_after else None,
        )

        for rv_feed in rv:
            yield fix_datetime_tzinfo(rv_feed, 'updated', 'added', 'last_updated')

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

        Like ``next(iter(reader.get_feeds(feed=feed)))``,
        but raises a custom exception instead of :exc:`StopIteration`.

        Arguments:
            feed (str or tuple(str) or Feed): The feed URL.
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
        new: Optional[bool] = None,
    ) -> FeedCounts:
        """Count all or some of the feeds.

        See :meth:`~Reader.get_feeds()` for details on how filtering works.

        Args:
            feed (str or tuple(str) or Feed or None): Only count the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only count feeds matching these tags.
            broken (bool or None): Only count broken / healthy feeds.
            updates_enabled (bool or None):
                Only count feeds that have updates enabled / disabled.
            new (bool or None):
                Only count feeds that have never been updated
                / have been updated before.

        Returns:
            FeedCounts:

        Raises:
            StorageError

        .. versionadded:: 1.11

        .. versionadded:: 2.6
            The ``new`` keyword argument.

        """
        filter_options = FeedFilterOptions.from_args(
            feed, tags, broken, updates_enabled, new
        )
        return self._storage.get_feed_counts(filter_options)

    def set_feed_user_title(self, feed: FeedInput, title: Optional[str]) -> None:
        """Set a user-defined title for a feed.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
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
            feed (str or tuple(str) or Feed): The feed URL.

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
            feed (str or tuple(str) or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.11

        """
        url = _feed_argument(feed)
        self._storage.set_feed_updates_enabled(url, False)

    def update_feeds(
        self,
        *,
        feed: Optional[FeedInput] = None,
        tags: TagFilterInput = None,
        broken: Optional[bool] = None,
        updates_enabled: Optional[bool] = True,
        new: Optional[bool] = None,
        workers: int = 1,
    ) -> None:
        """Update all or some of the feeds.

        Silently skip feeds that raise :exc:`ParseError`.

        By default, update all the feeds that have updates enabled.

        Roughly equivalent to ``for _ in reader.update_feed_iter(...): pass``.

        Args:
            feed (str or tuple(str) or Feed or None): Only update the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only update feeds matching these tags.
            broken (bool or None): Only update broken / healthy feeds.
            updates_enabled (bool or None):
                Only update feeds that have updates enabled / disabled.
                Defaults to true.
            new (bool or None):
                Only update feeds that have never been updated
                / have been updated before. Defaults to None.
            workers (int): Number of threads to use when getting the feeds.

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

        .. versionchanged:: 2.0
            Removed the ``new_only`` parameter.

        .. versionchanged:: 2.0
            All parameters are keyword-only.

        .. versionadded:: 2.6
            The ``feed``, ``tags``, ``broken``, and ``updates_enabled``
            keyword arguments.

        """
        results = self.update_feeds_iter(
            feed=feed,
            tags=tags,
            broken=broken,
            updates_enabled=updates_enabled,
            new=new,
            workers=workers,
        )

        for url, value in results:
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
        *,
        feed: Optional[FeedInput] = None,
        tags: TagFilterInput = None,
        broken: Optional[bool] = None,
        updates_enabled: Optional[bool] = True,
        new: Optional[bool] = None,
        workers: int = 1,
    ) -> Iterable[UpdateResult]:
        """Update all or some of the feeds.

        Yield information about each updated feed.

        By default, update all the feeds that have updates enabled.

        Args:
            feed (str or tuple(str) or Feed or None): Only update the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only update feeds matching these tags.
            broken (bool or None): Only update broken / healthy feeds.
            updates_enabled (bool or None):
                Only update feeds that have updates enabled / disabled.
                Defaults to true.
            new (bool or None):
                Only update feeds that have never been updated
                / have been updated before. Defaults to None.
            workers (int): Number of threads to use when getting the feeds.

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

        .. versionchanged:: 2.0
            Removed the ``new_only`` parameter.

        .. versionchanged:: 2.0
            All parameters are keyword-only.

        .. versionadded:: 2.6
            The ``feed``, ``tags``, ``broken``, and ``updates_enabled``
            keyword arguments.

        """
        filter_options = FeedFilterOptions.from_args(
            feed, tags, broken, updates_enabled, new
        )

        if workers < 1:
            raise ValueError("workers must be a positive integer")

        make_map = nullcontext(builtins.map) if workers == 1 else make_pool_map(workers)

        with make_map as map:
            results = self._update_feeds(filter_options, map)

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

        Like ``next(iter(reader.update_feeds_iter(feed=feed, updates_enabled=None)))[1]``,
        but raises the :exc:`ParseError`, if any.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.

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
        _, rv = zero_or_one(
            self.update_feeds_iter(feed=feed, updates_enabled=None),
            lambda: FeedNotFoundError(_feed_argument(feed)),
        )
        if isinstance(rv, Exception):
            raise rv
        return rv

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    def _update_feeds(
        self,
        filter_options: FeedFilterOptions,
        map: MapType = map,
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
        # Update: However, added == last_updated for the first update.
        #
        global_now = self._now()

        # Excluding the special exception handling,
        # this function is a pipeline that looks somewhat like this:
        #
        #   self._storage.get_feeds_for_update \
        #   | self._updater.process_old_feed \
        #   | xargs -n1 -P $workers self._parser.retrieve \
        #   | self._parser.parse \
        #   | self._get_entries_for_update \
        #   | self._updater.make_update_intents \
        #   | self._update_feed
        #
        # Since we only need retrieve() (and maybe parse()) to run in parallel,
        # everything after that is in a single for loop for readability.

        feeds_for_update = self._storage.get_feeds_for_update(filter_options)
        feeds_for_update = builtins.map(
            self._updater.process_old_feed, feeds_for_update
        )
        parse_results = self._parser.parallel(
            feeds_for_update, map, map is not builtins.map
        )

        for feed_for_update, parse_result in parse_results:
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

    def _update_feed(
        self,
        url: str,
        feed_to_update: Optional[FeedUpdateIntent],
        entries_to_update: Iterable[EntryUpdateIntent],
    ) -> Tuple[int, int]:

        for feed_hook in self.before_feed_update_hooks:
            feed_hook(self, url)

        if feed_to_update:
            if entries_to_update:
                self._storage.add_or_update_entries(entries_to_update)
            self._storage.update_feed(feed_to_update)

        # if feed_for_update.url != parsed_feed.feed.url, the feed was redirected.
        # TODO: Maybe handle redirects somehow else (e.g. change URL if permanent).

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

        for feed_hook in self.after_feed_update_hooks:
            feed_hook(self, url)

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
            feed (str or tuple(str) or Feed or None): Only return the entries for this feed.
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
        rv = self._storage.get_entries(
            now,
            filter_options,
            sort,
            limit,
            _entry_argument(starting_after) if starting_after else None,
        )

        for rv_entry in rv:
            yield fix_datetime_tzinfo(
                rv_entry,
                'updated',
                'published',
                'added',
                'last_updated',
                'read_modified',
                'important_modified',
                feed=fix_datetime_tzinfo(
                    rv_entry.feed, 'updated', 'added', 'last_updated'
                ),
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

        Like ``next(iter(reader.get_entries(entry=entry)))``,
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
            feed (str or tuple(str) or Feed or None): Only count the entries for this feed.
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
        now = self._now()
        return self._storage.get_entry_counts(now, filter_options)

    def set_entry_read(
        self,
        entry: EntryInput,
        read: bool,
        modified: Union[MissingType, None, datetime] = MISSING,
    ) -> None:
        """Mark an entry as read or unread,
        possibly with a custom timestamp.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.
            read (bool): Mark the entry as read if true (default),
                and as unread otherwise.
            modified (datetime or None):
                Set :attr:`~Entry.read_modified` to this.
                Naive datetimes are normalized by passing them to
                :meth:`~datetime.datetime.astimezone`.
                Defaults to the current time.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 2.2

        """
        modified_naive: Optional[datetime]
        if isinstance(modified, MissingType):
            modified_naive = self._now()
        elif modified is None:
            modified_naive = None
        else:
            modified_naive = modified.astimezone(timezone.utc).replace(tzinfo=None)

        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_read(feed_url, entry_id, bool(read), modified_naive)

    def mark_entry_as_read(self, entry: EntryInput) -> None:
        """Mark an entry as read.

        Alias for ``set_entry_read(entry, True)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_read`.

        """
        self.set_entry_read(entry, True)

    def mark_entry_as_unread(self, entry: EntryInput) -> None:
        """Mark an entry as unread.

        Alias for ``set_entry_read(entry, False)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_unread`.

        """
        return self.set_entry_read(entry, False)

    def set_entry_important(
        self,
        entry: EntryInput,
        important: bool,
        modified: Union[MissingType, None, datetime] = MISSING,
    ) -> None:
        """Mark an entry as important or unimportant,
        possibly with a custom timestamp.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.
            important (bool): Mark the entry as important if true (default),
                and as unimportant otherwise.
            modified (datetime or None):
                Set :attr:`~Entry.important_modified` to this.
                Naive datetimes are normalized by passing them to
                :meth:`~datetime.datetime.astimezone`.
                Defaults to the current time.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 2.2

        """
        modified_naive: Optional[datetime]
        if isinstance(modified, MissingType):
            modified_naive = self._now()
        elif modified is None:
            modified_naive = None
        else:
            modified_naive = modified.astimezone(timezone.utc).replace(tzinfo=None)

        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_important(
            feed_url, entry_id, bool(important), modified_naive
        )

    def mark_entry_as_important(self, entry: EntryInput) -> None:
        """Mark an entry as important.

        Alias for ``set_entry_important(entry, True)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_important`.

        """
        self.set_entry_important(entry, True)

    def mark_entry_as_unimportant(self, entry: EntryInput) -> None:
        """Mark an entry as unimportant.

        Alias for ``set_entry_important(entry, False)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_unimportant`.

        """
        return self.set_entry_important(entry, False)

    def _mark_entry_as_dont_care(self, entry: EntryInput) -> None:
        """Mark an entry as read and unimportant at the same time,
        resulting in the same read_modified and important_modified.

        This method becoming public is pending on #254.

        Presumably, we could just use mark_entry_as_{read,important} instead
        and get the slightly different timestamps,
        but it's likely better to collect more accurate data.

        """
        modified_naive = self._now()
        feed_url, entry_id = _entry_argument(entry)
        self._storage.mark_as_read(feed_url, entry_id, True, modified_naive)
        self._storage.mark_as_important(feed_url, entry_id, False, modified_naive)

    def add_entry(self, entry: Any) -> None:
        """Add a new entry to an existing feed.

        ``entry`` can be any :class:`Entry`-like object,
        or a mapping of the same shape::

            >>> from types import SimpleNamespace
            >>> reader.add_entry(SimpleNamespace(
            ...     feed_url='http://example.com',
            ...     id='one',
            ...     title='title',
            ...     enclosures=[SimpleNamespace(href='enclosure')],
            ... ))
            >>> reader.add_entry({
            ...     'feed_url': 'http://example.com',
            ...     'id': 'two',
            ...     'updated': datetime.now(timezone.utc),
            ...     'content': [{'value': 'content'}],
            ... })

        The following attributes are used
        (they must have the same types as on :class:`Entry`):

        * :attr:`~Entry.feed_url` (required)
        * :attr:`~Entry.id` (required)
        * :attr:`~Entry.updated`
        * :attr:`~Entry.title`
        * :attr:`~Entry.link`
        * :attr:`~Entry.author`
        * :attr:`~Entry.published`
        * :attr:`~Entry.summary`
        * :attr:`~Entry.content`
        * :attr:`~Entry.enclosures`

        Naive datetimes are normalized by passing them to
        :meth:`~datetime.datetime.astimezone`.

        The added entry will be :attr:`~Entry.added_by` ``'user'``.

        Args:
            entry (Entry or dict): An entry-like object or equivalent mapping.

        Raises:
            EntryExistsError: If an entry with the same id already exists.
            FeedNotFoundError
            StorageError

        .. versionadded:: 2.5

        """

        # `entry` is of type Union[EntryDataLikeProtocol, EntryDataTypedDict],
        # but modeling that is pretty cumbersome; we can do it later if needed;
        # https://github.com/lemon24/reader/issues/239#issuecomment-951892271
        # https://gist.github.com/lemon24/047f71abe76c47661634459eada7b50a#file-01-typing-py

        now = self._now()

        intent = EntryUpdateIntent(
            entry=entry_data_from_obj(entry),
            last_updated=now,
            first_updated=now,
            first_updated_epoch=now,
            added_by='user',
        )

        self._storage.add_entry(intent)
        for entry_hook in self.after_entry_update_hooks:
            entry_hook(self, intent.entry, EntryUpdateStatus.NEW)

    def delete_entry(self, entry: EntryInput, missing_ok: bool = False) -> None:
        """Delete an entry.

        Currently, only entries added by :meth:`~Reader.add_entry`
        (:attr:`~Entry.added_by` ``'user'``) can be deleted.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.
            missing_ok (bool):
                If true, don't raise :exc:`EntryNotFoundError`
                if the entry does not exist.

        Raises:
            EntryNotFoundError: If the entry does not exist, and `missing_ok` is false.
            EntryError: If the entry was not added by the user.
            StorageError

        .. versionadded:: 2.5

        .. versionadded:: 2.8
            The ``missing_ok`` argument.

        """
        try:
            self._storage.delete_entries([_entry_argument(entry)], added_by='user')
        except EntryNotFoundError:
            if not missing_ok:
                raise

    @deprecated('get_tags', '2.8', '3.0')
    def get_feed_metadata(
        self,
        feed: FeedInput,
        key: Optional[str] = None,
    ) -> Iterable[Tuple[str, JSONType]]:  # pragma: no cover
        """Get all or some of the metadata for a feed as ``(key, value)`` pairs.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            key (str or None): Only return the metadata for this key.

        Yields:
            tuple(str, JSONType): ``(key, value)`` pairs, in undefined order.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            StorageError

        .. versionchanged:: 1.18
            :meth:`get_feed_metadata` was renamed to :meth:`get_feed_metadata_item`,
            :meth:`iter_feed_metadata` was renamed to :meth:`get_feed_metadata`.

        .. versionchanged:: 2.0
            The ``get_feed_metadata(feed, key, default=no value, /)``
            (positional arguments only)
            :meth:`get_feed_metadata_item` alias was removed.

        """
        return self.get_tags(feed, key=key)

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

    @deprecated('get_tag', '2.8', '3.0')
    def get_feed_metadata_item(
        self, feed: FeedInput, key: str, default: Union[MissingType, _T] = MISSING
    ) -> Union[JSONType, _T]:  # pragma: no cover
        """Get metadata for a feed.

        Like ``next(iter(reader.get_feed_metadata(feed, key=key)), (None, default))[1]``,
        but raises a custom exception instead of :exc:`StopIteration`.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
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
        try:
            if isinstance(default, MissingType):
                return self.get_tag(feed, key)
            else:
                return self.get_tag(feed, key, default)
        except TagNotFoundError as e:
            raise FeedMetadataNotFoundError(_feed_argument(feed), e.key) from None

    @deprecated('set_tag', '2.8', '3.0')
    def set_feed_metadata_item(
        self, feed: FeedInput, key: str, value: JSONType
    ) -> None:  # pragma: no cover
        """Set metadata for a feed.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            key (str): The key of the metadata item to set.
            value (JSONType): The value of the metadata item to set.
                JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`set_feed_metadata`.

        """
        self.set_tag(feed, key, value)

    @deprecated('delete_tag', '2.8', '3.0')
    def delete_feed_metadata_item(
        self, feed: FeedInput, key: str
    ) -> None:  # pragma: no cover
        """Delete metadata for a feed.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            key (str): The key of the metadata item to delete.

        Raises:
            FeedMetadataNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`delete_feed_metadata`.

        """
        try:
            self.delete_tag(feed, key)
        except TagNotFoundError as e:
            raise FeedMetadataNotFoundError(_feed_argument(feed), e.key) from None

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

        If :func:`make_reader` was called with ``search_enabled='auto'``
        and search is disabled, it will be enabled automatically.

        Raises:
            SearchNotEnabledError
            SearchError
            StorageError

        """
        try:
            self._search.update()
        except SearchNotEnabledError:
            if not self._enable_search:
                raise
            self._search.enable()
            self._search.update()

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
            feed (str or tuple(str) or Feed or None): Only search the entries for this feed.
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
            feed (str or tuple(str) or Feed or None): Only count the entries for this feed.
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
        now = self._now()
        return self._search.search_entry_counts(query, now, filter_options)

    @deprecated('set_tag', '2.8', '3.0')
    def add_feed_tag(self, feed: FeedInput, tag: str) -> None:  # pragma: no cover
        """Add a tag to a feed.

        Adding a tag that the feed already has is a no-op.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            tag (str): The tag to add.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.7

        """
        self.set_tag(feed, tag)

    @deprecated('delete_tag', '2.8', '3.0')
    def remove_feed_tag(self, feed: FeedInput, tag: str) -> None:  # pragma: no cover
        """Remove a tag from a feed.

        Removing a tag that the feed does not have is a no-op.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            tag (str): The tag to remove.

        Raises:
            StorageError

        .. versionadded:: 1.7

        """
        self.delete_tag(feed, tag, True)

    @deprecated('get_tag_keys', '2.8', '3.0')
    def get_feed_tags(
        self, feed: Optional[FeedInput] = None
    ) -> Iterable[str]:  # pragma: no cover
        """Get all or some of the feed tags.

        Args:
            feed (str or tuple(str) or Feed or None): Only return the tags for this feed.

        Yields:
            str: The tags, in alphabetical order.

        Raises:
            StorageError

        .. versionadded:: 1.7

        """
        return self.get_tag_keys(feed)

    # FIXME: no wildcards allowed in get_tags, update docstring/changelog

    def get_tags(
        self,
        resource: ResourceInput,
        *,
        key: Optional[str] = None,
    ) -> Iterable[Tuple[str, JSONType]]:
        """Get all or some tags of a resource as ``(key, value)`` pairs.

        `resource` can have one of the following types:

        :class:`Feed` or ``str`` or ``(str,)``

            A feed or feed URL (possibly enclosed in a tuple).

        :class:`Entry` or ``(str, str)``

            An entry or a (feed URL, entry id) pair representing an entry.

        ``()`` (empty tuple)

            Special value representing the global tag namespace.

        Args:
            resource: The resource to get tags for.
            key (str or None): Only return the metadata for this key.

        Yields:
            tuple(str, JSONType): ``(key, value)`` pairs, in undefined order.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            StorageError

        .. versionadded:: 2.8

        .. versionchanged:: 2.10
            Support entry and global tags.

        .. versionchanged:: 2.10
            Removed support for the ``(None,)`` (any feed) and
            :const:`None` (any resource) wildcard resource values.

        """
        resource_id = _resource_argument(resource)
        return self._storage.get_tags(resource_id, key)

    def get_tag_keys(
        self,
        resource: AnyResourceInput = None,
    ) -> Iterable[str]:
        """Get the keys of all or some resource tags.

        Equivalent to ``sorted(k for k, _ in reader.get_tags(resource))``.

        See :meth:`get_tags` for possible `resource` values.
        In addition, `resource` can have one of the following wildcard values:

        ``(None,)``

            Any feed.

        ``(None, None)``

            Any entry.

        :const:`None`

            Any resource (feed, entry, or the global namespace).

        Args:
            resource: Only return tag keys for this resource.

        Yields:
            str: The tag keys, in alphabetical order.

        Raises:
            StorageError

        .. versionadded:: 2.8

        .. versionchanged:: 2.10
            Support entry and global tags.

        """
        # TODO: efficient implementation
        resource_id: AnyResourceId
        if resource is None:
            resource_id = None
        elif resource == (None,):
            resource_id = (None,)
        elif resource == (None, None):
            resource_id = (None, None)
        else:
            resource_id = _resource_argument(resource)  # type: ignore[arg-type]
        return (k for k, _ in self._storage.get_tags(resource_id))

    @overload
    def get_tag(
        self, resource: ResourceInput, key: str
    ) -> JSONType:  # pragma: no cover
        ...

    @overload
    def get_tag(
        self, resource: ResourceInput, key: str, default: _T
    ) -> Union[JSONType, _T]:  # pragma: no cover
        ...

    def get_tag(
        self,
        resource: ResourceInput,
        key: str,
        default: Union[MissingType, _T] = MISSING,
    ) -> Union[JSONType, _T]:
        """Get the value of this resource tag.

        Like ``next(iter(reader.get_tags(resource, key=key)))[1]``,
        but raises a custom exception instead of :exc:`StopIteration`.

        See :meth:`get_tags` for possible `resource` values.

        Args:
            resource: The resource.
            key (str): The key of the tag to retrieve.
            default: Returned if given and no tag exists for `key`.

        Returns:
            JSONType: The tag value.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            TagNotFoundError
            StorageError

        .. versionadded:: 2.8

        .. versionchanged:: 2.10
            Support entry and global tags.

        """
        resource_id = _resource_argument(resource)
        object_id: Any = resource_id if len(resource_id) != 1 else resource_id[0]  # type: ignore
        return zero_or_one(
            (v for _, v in self._storage.get_tags(resource_id, key)),
            lambda: TagNotFoundError(key, object_id),
            default,
        )

    @overload
    def set_tag(self, resource: ResourceInput, key: str) -> None:  # pragma: no cover
        ...

    @overload
    def set_tag(
        self, resource: ResourceInput, key: str, value: JSONType
    ) -> None:  # pragma: no cover
        ...

    def set_tag(
        self,
        resource: ResourceInput,
        key: str,
        value: Union[JSONType, MissingType] = MISSING,
    ) -> None:
        """Set the value of this resource tag.

        See :meth:`get_tags` for possible `resource` values.

        Args:
            resource: The resource.
            key (str): The key of the tag to set.
            value (JSONType): The value of the tag to set.
                If not provided, and the tag already exists,
                the value remains unchanged;
                if the tag does not exist, it is set to :const:`None`.
                JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            ResourceNotFoundError
            StorageError

        .. versionadded:: 2.8

        .. versionchanged:: 2.10
            Support entry and global tags.

        """
        resource_id = _resource_argument(resource)
        if not isinstance(value, MissingType):
            self._storage.set_tag(resource_id, key, value)
        else:
            self._storage.set_tag(resource_id, key)

    def delete_tag(
        self, resource: ResourceInput, key: str, missing_ok: bool = False
    ) -> None:
        """Delete this resource tag.

        See :meth:`get_tags` for possible `resource` values.

        Args:
            resource: The resource.
            key (str): The key of the tag to delete.
            missing_ok (bool):
                If true, don't raise :exc:`TagNotFoundError`
                if the tag does not exist.

        Raises:
            TagNotFoundError: If the tag does not exist, and `missing_ok` is false.
            StorageError

        .. versionadded:: 2.8

        .. versionchanged:: 2.10
            Support entry and global tags.

        """
        resource_id = _resource_argument(resource)
        object_id: Any = resource_id if len(resource_id) != 1 else resource_id[0]  # type: ignore
        try:
            self._storage.delete_tag(resource_id, key)
        except TagNotFoundError as e:
            if not missing_ok:
                e.object_id = object_id
                raise

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
            raise AttributeError(f"invalid reserved name scheme: {value}") from e
