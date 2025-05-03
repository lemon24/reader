from __future__ import annotations

import builtins
import logging
import numbers
import warnings
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import MutableSequence
from contextlib import nullcontext
from datetime import datetime
from datetime import timezone
from types import MappingProxyType
from typing import Any
from typing import Literal
from typing import overload
from typing import Self
from typing import TYPE_CHECKING
from typing import TypeVar

from ._parser import default_parser
from ._parser.requests import DEFAULT_TIMEOUT
from ._parser.requests import TimeoutType
from ._storage import Storage
from ._types import BoundSearchStorageType
from ._types import entry_data_from_obj
from ._types import entry_update_intent_from_obj
from ._types import EntryData
from ._types import EntryFilter
from ._types import EntryUpdateIntent
from ._types import FeedFilter
from ._types import NameScheme
from ._types import SearchType
from ._types import StorageType
from ._types import UpdateHooks
from ._update import Pipeline
from ._utils import make_pool_map
from ._utils import MapContextManager
from ._utils import zero_or_one
from .exceptions import EntryNotFoundError
from .exceptions import FeedExistsError
from .exceptions import FeedNotFoundError
from .exceptions import ParseError
from .exceptions import PluginInitError
from .exceptions import SearchNotEnabledError
from .exceptions import TagNotFoundError
from .exceptions import UpdateHookError
from .plugins import _load_plugins
from .plugins import DEFAULT_PLUGINS
from .plugins import PluginInput
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
from .types import EntrySearchSort
from .types import EntrySort
from .types import EntryUpdateStatus
from .types import Feed
from .types import FeedCounts
from .types import FeedInput
from .types import FeedSort
from .types import JSONType
from .types import MISSING
from .types import MissingType
from .types import ResourceInput
from .types import TagFilterInput
from .types import TristateFilterInput
from .types import UpdatedFeed
from .types import UpdateResult


if TYPE_CHECKING:  # pragma: no cover
    from ._parser import Parser


log = logging.getLogger('reader')


_T = TypeVar('_T')
_U = TypeVar('_U')

AfterEntryUpdateHook = Callable[['Reader', EntryData, EntryUpdateStatus], None]
FeedUpdateHook = Callable[['Reader', str], None]
FeedsUpdateHook = Callable[['Reader'], None]


#: The :func:`.make_reader` default :ref:`reserved name scheme <reserved names>`.
DEFAULT_RESERVED_NAME_SCHEME = {
    'reader_prefix': '.reader.',
    'plugin_prefix': '.plugin.',
    'separator': '.',
}


def make_reader(
    url: str,
    *,
    feed_root: str | None = None,
    plugins: Iterable[PluginInput] = DEFAULT_PLUGINS,
    session_timeout: TimeoutType = DEFAULT_TIMEOUT,
    reserved_name_scheme: Mapping[str, str] = DEFAULT_RESERVED_NAME_SCHEME,
    search_enabled: bool | None | Literal['auto'] = 'auto',
    _storage: StorageType | None = None,
) -> Reader:
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
            Defaults to :data:`.DEFAULT_RESERVED_NAME_SCHEME`.

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
        PluginInitError: A plugin failed to initialize.
        PluginError: An ambiguous plugin-related error occurred.
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

    .. versionchanged:: 3.0
        Wrap exceptions raised during plugin initialization
        in :exc:`PluginInitError` instead of letting them bubble up.

    """

    # Do as much work as possible before creating the storage.

    if search_enabled not in ('auto', True, False, None):
        raise ValueError("search_enabled should be one of ('auto', True, False, None)")

    parser = default_parser(feed_root, session_timeout=session_timeout)
    # circular import
    from . import USER_AGENT

    parser.session_factory.user_agent = USER_AGENT

    try:
        name_scheme = NameScheme.from_value(reserved_name_scheme)
    except Exception as e:
        raise ValueError(f"invalid reserved name scheme: {reserved_name_scheme}") from e

    plugin_funcs = list(_load_plugins(plugins))

    # If we ever need to change the signature of make_reader(),
    # or support additional storage/search implementations,
    # we'll need to do the wiring differently.
    #
    # See this comment for details on how it should evolve:
    # https://github.com/lemon24/reader/issues/168#issuecomment-642002049

    storage: StorageType = _storage or Storage(url)

    try:
        # For now, we're using a storage-bound search provider.
        if not isinstance(storage, BoundSearchStorageType):  # pragma: no cover
            raise TypeError("storage must have a make_search factory")
        search = storage.make_search()

        if search_enabled is True:
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

        # TODO: move this logic to reader.plugins
        # TODO: show the name the user passed, not that of plugin_func
        for plugin_func in plugin_funcs:
            try:
                plugin_func(reader)
            except Exception as e:
                raise PluginInitError(
                    "plugin failed to initialze: "
                    f"{plugin_func.__module__}:{plugin_func.__qualname__}"
                ) from e

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

    Additional sources can be added through :ref:`plugins <plugins>`.

    .. _feedparser: https://feedparser.readthedocs.io/en/latest/


    In order to perform maintenance tasks and
    release underlying resources in a predictable manner,
    the Reader object should be used as a context manager
    *from each thread* where it is used.
    For convenience, it is possible to use a Reader object directly;
    in this case, maintenance tasks may sometimes be performed
    before arbitrary method calls return.


    .. important::

        Reader objects should be created using :func:`make_reader`; the Reader
        constructor is not stable yet and may change without any notice.


    .. versionadded:: 1.13
        JSON Feed support.

    .. versionchanged:: 2.10
        Allow passing a `(feed URL,)` 1-tuple anywhere a feed URL can be passed.

    .. versionchanged:: 2.15
        Allow using Reader objects as context managers.

    .. versionchanged:: 2.15
        Allow using Reader objects from threads other than the creating thread.

    .. versionchanged:: 2.16
        Allow using a Reader object from multiple threads directly
        (do not require it to be used as a context manager anymore).

    .. versionchanged:: 2.16
        Allow Reader objects to be reused after closing.

    .. versionchanged:: 2.16
        Allow using a Reader object from multiple asyncio tasks.

    """

    def __init__(
        self,
        _storage: StorageType,
        _search: SearchType,
        _parser: Parser,
        _reserved_name_scheme: NameScheme,
        _enable_search: bool = False,
        _called_directly: bool = True,
    ):
        #: The :class:`~reader._types.StorageType` instance used by this reader.
        self._storage = _storage
        #: The :class:`~reader._types.SearchType` instance used by this reader.
        self._search = _search
        #: The :class:`~reader._parser.Parser` instance used by this reader.
        self._parser = _parser

        self._reserved_name_scheme = _reserved_name_scheme
        self._enable_search = _enable_search
        self._update_hooks = UpdateHooks(self)

        if _called_directly:
            warnings.warn(
                "Reader objects should be created using make_reader(); the Reader "
                "constructor is not stable yet and may change without any notice.",
                stacklevel=2,
            )

    def __enter__(self) -> Self:
        self._storage.__enter__()
        return self

    def __exit__(self, *_: Any) -> None:
        self._storage.__exit__()

    def close(self) -> None:
        """Close this :class:`Reader`.

        Releases any underlying resources associated with the reader.

        The reader can be reused after being closed
        (but you have to call close() again after that).

        close() should be called *from each thread* where the reader is used.
        Prefer using the reader as a context manager instead.

        Raises:
            ReaderError

        .. versionchanged:: 2.16
            Allow calling close() from any thread.

        """
        self._storage.close()

    def add_feed(
        self,
        feed: FeedInput,
        /,
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

        .. versionchanged:: 3.0
            The ``feed`` argument is now positional-only.

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

    def delete_feed(self, feed: FeedInput, /, missing_ok: bool = False) -> None:
        """Delete a feed and all of its entries and tags.

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

        .. versionchanged:: 3.0
            The ``feed`` argument is now positional-only.

        """
        url = _feed_argument(feed)
        try:
            self._storage.delete_feed(url)
        except FeedNotFoundError:
            if not missing_ok:
                raise

    def change_feed_url(
        self, old: FeedInput, new: FeedInput, /, *, allow_invalid_url: bool = False
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

        The entries and tags are preserved.

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

        .. versionchanged:: 3.0
            The ``old`` and ``new`` arguments are now positional-only.

        """
        old_str = _feed_argument(old)
        new_str = _feed_argument(new)
        if not allow_invalid_url:
            self._parser.validate_url(new_str)
        self._storage.change_feed_url(old_str, new_str)

    def get_feeds(
        self,
        *,
        feed: FeedInput | None = None,
        tags: TagFilterInput = None,
        broken: bool | None = None,
        updates_enabled: bool | None = None,
        new: bool | None = None,
        scheduled: bool = False,
        sort: FeedSort = FeedSort.TITLE,
        limit: int | None = None,
        starting_after: FeedInput | None = None,
    ) -> Iterable[Feed]:
        """Get all or some of the feeds.

        Args:
            feed (str or tuple(str) or Feed or None): Only return the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only return feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            broken (bool or None): Only return broken / healthy feeds.
            updates_enabled (bool or None):
                Only return feeds that have updates enabled / disabled.
            new (bool or None):
                Only return feeds that have never been updated
                / have been updated before.
            scheduled (bool):
                Only return feeds scheduled to be updated.
            sort (FeedSort):
                How to order feeds; see :class:`FeedSort` for details.
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

        .. versionadded:: 3.13
            The ``scheduled`` keyword argument.

        .. versionchanged:: 3.13
            ``new`` uses :attr:`~Feed.last_retrieved`
            instead of :attr:`~Feed.last_updated`.

        """
        filter = FeedFilter.from_args(
            self._now(), feed, tags, broken, updates_enabled, new, scheduled
        )
        sort = FeedSort(sort)

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")
        starting_after = _feed_argument(starting_after) if starting_after else None

        return self._storage.get_feeds(filter, sort, limit, starting_after)

    @overload
    def get_feed(self, feed: FeedInput, /) -> Feed:  # pragma: no cover
        ...

    @overload
    def get_feed(
        self,
        feed: FeedInput,
        default: _T,
        /,
    ) -> Feed | _T:  # pragma: no cover
        ...

    def get_feed(
        self,
        feed: FeedInput,
        default: MissingType | _T = MISSING,
        /,
    ) -> Feed | _T:
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

        .. versionchanged:: 3.0
            The ``feed`` and ``default`` arguments are now positional-only.

        """
        return zero_or_one(
            self.get_feeds(feed=feed),
            lambda: FeedNotFoundError(_feed_argument(feed)),
            default,
        )

    def get_feed_counts(
        self,
        *,
        feed: FeedInput | None = None,
        tags: TagFilterInput = None,
        broken: bool | None = None,
        updates_enabled: bool | None = None,
        new: bool | None = None,
        scheduled: bool = False,
    ) -> FeedCounts:
        """Count all or some of the feeds.

        Args:
            feed (str or tuple(str) or Feed or None): Only count the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only count feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            broken (bool or None): Only count broken / healthy feeds.
            updates_enabled (bool or None):
                Only count feeds that have updates enabled / disabled.
            new (bool or None):
                Only count feeds that have never been updated
                / have been updated before.
            scheduled (bool):
                Only count feeds scheduled to be updated.

        Returns:
            FeedCounts:

        Raises:
            StorageError

        .. versionadded:: 1.11

        .. versionadded:: 2.6
            The ``new`` keyword argument.

        .. versionadded:: 3.13
            The ``scheduled`` keyword argument.

        .. versionchanged:: 3.13
            ``new`` uses :attr:`~Feed.last_retrieved`
            instead of :attr:`~Feed.last_updated`.

        """
        filter = FeedFilter.from_args(
            self._now(), feed, tags, broken, updates_enabled, new, scheduled
        )
        return self._storage.get_feed_counts(filter)

    def set_feed_user_title(self, feed: FeedInput, title: str | None, /) -> None:
        """Set a user-defined title for a feed.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.
            title (str or None): The title, or None to remove the current title.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionchanged:: 3.0
            The ``feed`` and ``title`` arguments are now positional-only.

        """
        url = _feed_argument(feed)
        return self._storage.set_feed_user_title(url, title)

    def enable_feed_updates(self, feed: FeedInput, /) -> None:
        """Enable updates for a feed.

        See :meth:`~Reader.update_feeds` for details.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.11

        .. versionchanged:: 3.0
            The ``feed`` argument is now positional-only.

        """
        url = _feed_argument(feed)
        self._storage.set_feed_updates_enabled(url, True)

    def disable_feed_updates(self, feed: FeedInput, /) -> None:
        """Disable updates for a feed.

        See :meth:`~Reader.update_feeds` for details.

        Args:
            feed (str or tuple(str) or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        .. versionadded:: 1.11

        .. versionchanged:: 3.0
            The ``feed`` argument is now positional-only.

        """
        url = _feed_argument(feed)
        self._storage.set_feed_updates_enabled(url, False)

    def update_feeds(
        self,
        *,
        feed: FeedInput | None = None,
        tags: TagFilterInput = None,
        broken: bool | None = None,
        updates_enabled: bool | None = True,
        new: bool | None = None,
        scheduled: bool = False,
        workers: int = 1,
    ) -> None:
        r"""Update all or some of the feeds.

        Silently skip feeds that raise :exc:`ParseError`.

        Re-raise :attr:`before_feeds_update_hooks` failures immediately.
        Collect all other update hook failures
        and re-raise them as an :exc:`UpdateHookErrorGroup`;
        currently, only the exceptions for the first 5 feeds
        with hook failures are collected.

        By default, update all the feeds that have updates enabled.

        Roughly equivalent to ``for _ in reader.update_feeds_iter(...): pass``.

        Args:
            feed (str or tuple(str) or Feed or None): Only update the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only update feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            broken (bool or None): Only update broken / healthy feeds.
            updates_enabled (bool or None):
                Only update feeds that have updates enabled / disabled.
                Defaults to true.
            new (bool or None):
                Only update feeds that have never been updated
                / have been updated before. Defaults to None.
            scheduled (bool):
                Only update feeds scheduled to be updated.
            workers (int): Number of threads to use when getting the feeds.

        Raises:
            UpdateHookError: For unexpected hook exceptions.
            UpdateError
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

        .. versionadded:: 1.19
            The ``new`` parameter. ``new_only`` is now deprecated.

        .. versionchanged:: 2.0
            Remove the deprecated ``new_only`` parameter.

        .. versionchanged:: 2.0
            All parameters are keyword-only.

        .. versionadded:: 2.6
            The ``feed``, ``tags``, ``broken``, and ``updates_enabled``
            keyword arguments.

        .. versionchanged:: 3.8
            Wrap unexpected update hook exceptions in :exc:`UpdateHookError`.
            Try to update all the feeds, don’t stop after a feed/entry hook fails.

        .. versionchanged:: 3.8
            Document this method can raise non-feed-related :exc:`UpdateError`\s
            (other than :exc:`UpdateHookError`).

        .. versionadded:: 3.13
            The ``scheduled`` keyword argument.

        .. versionchanged:: 3.13
            ``new`` uses :attr:`~Feed.last_retrieved`
            instead of :attr:`~Feed.last_updated`.

        """
        with self._update_hooks.group("some hooks failed") as hook_errors:
            results = self.update_feeds_iter(
                feed=feed,
                tags=tags,
                broken=broken,
                updates_enabled=updates_enabled,
                new=new,
                scheduled=scheduled,
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

                if isinstance(value, UpdateHookError):
                    hook_errors.add(value, url, limit=5)
                    continue

                assert not isinstance(value, Exception), value

    def update_feeds_iter(
        self,
        *,
        feed: FeedInput | None = None,
        tags: TagFilterInput = None,
        broken: bool | None = None,
        updates_enabled: bool | None = True,
        new: bool | None = None,
        scheduled: bool = False,
        workers: int = 1,
        _call_feeds_update_hooks: bool = True,
    ) -> Iterable[UpdateResult]:
        r"""Update all or some of the feeds.

        Yield information about each updated feed.

        Re-raise :attr:`before_feeds_update_hooks` failures immediately.
        Yield feed/entry update hook failures.
        Collect :attr:`after_feeds_update_hooks` failures
        and re-raise them as an :exc:`UpdateHookErrorGroup`
        after updating all the feeds.

        By default, update all the feeds that have updates enabled.

        Args:
            feed (str or tuple(str) or Feed or None): Only update the feed with this URL.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only update feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            broken (bool or None): Only update broken / healthy feeds.
            updates_enabled (bool or None):
                Only update feeds that have updates enabled / disabled.
                Defaults to true.
            new (bool or None):
                Only update feeds that have never been updated
                / have been updated before. Defaults to None.
            scheduled (bool):
                Only update feeds scheduled to be updated.
            workers (int): Number of threads to use when getting the feeds.

        Yields:
            :class:`UpdateResult`:
                An (url, value) pair; the value is one of:

                * a summary of the updated feed, if the update was successful
                * None, if the server indicated the feed has not changed
                  since the last update
                * an exception instance

                Currently, the exception can be:

                * :exc:`ParseError`, if retrieving/parsing the feed failed
                * :exc:`UpdateHookError`, for unexpected hook exceptions
                  raised in :attr:`before_feed_update_hooks`,
                  :attr:`after_entry_update_hooks`, or
                  :attr:`after_feed_update_hooks`

                ...but other :exc:`UpdateError` subclasses may be yielded
                in the future.

        Raises:
            UpdateHookError: For unexpected hook exceptions raised in
                :attr:`before_feeds_update_hooks` or
                :attr:`after_feeds_update_hooks`.
            UpdateError: For non-feed-related update exceptions.
            StorageError

        .. versionadded:: 1.14

        .. versionchanged:: 1.15
            Update entries whenever their content changes.
            See :meth:`~Reader.update_feeds` for details.

        .. versionadded:: 1.19
            The ``new`` parameter. ``new_only`` is now deprecated.

        .. versionchanged:: 2.0
            Remove the deprecated ``new_only`` parameter.

        .. versionchanged:: 2.0
            All parameters are keyword-only.

        .. versionadded:: 2.6
            The ``feed``, ``tags``, ``broken``, and ``updates_enabled``
            keyword arguments.

        .. versionchanged:: 3.8
            Wrap unexpected update hook exceptions in :exc:`UpdateHookError`.
            Try to update all the feeds, don’t stop after a feed/entry hook fails.

        .. versionchanged:: 3.8
            Document this method can raise non-feed-related :exc:`UpdateError`\s
            (other than :exc:`UpdateHookError`).

        .. versionadded:: 3.13
            The ``scheduled`` keyword argument.

        .. versionchanged:: 3.13
            ``new`` uses :attr:`~Feed.last_retrieved`
            instead of :attr:`~Feed.last_updated`.

        """
        now = self._now()
        filter = FeedFilter.from_args(
            now, feed, tags, broken, updates_enabled, new, scheduled
        )

        if workers < 1:
            raise ValueError("workers must be a positive integer")

        make_map: MapContextManager[Any, Any] = (
            nullcontext(builtins.map) if workers == 1 else make_pool_map(workers)
        )

        if _call_feeds_update_hooks:
            self._update_hooks.run('before_feeds_update', None)

        with make_map as map:
            yield from Pipeline(self, now, map).update(filter)

        if _call_feeds_update_hooks:
            with self._update_hooks.group(
                "got unexpected after-update hook errors"
            ) as hook_errors:
                hook_errors.run('after_feeds_update', None)

    def update_feed(self, feed: FeedInput, /) -> UpdatedFeed | None:
        r"""Update a single feed.

        The feed will be updated even if updates are disabled for it,
        or if it is not scheduled to be updated.

        Like ``next(iter(reader.update_feeds_iter(feed=feed, updates_enabled=None)))[1]``,
        but raises the :exc:`UpdateError`, if any.

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
            UpdateHookError: For unexpected hook exceptions.
            UpdateError
            StorageError

        .. versionchanged:: 1.14
            The method now returns UpdatedFeed or None instead of None.

        .. versionchanged:: 1.15
            Update entries whenever their content changes.
            See :meth:`~Reader.update_feeds` for details.

        .. versionchanged:: 3.0
            The ``feed`` argument is now positional-only.

        .. versionchanged:: 3.8
            Wrap unexpected update hook exceptions in :exc:`UpdateHookError`.

        .. versionchanged:: 3.8
            Document this method can raise :exc:`UpdateError`\s
            (other than :exc:`ParseError` and :exc:`UpdateHookError`).

        """
        _, rv = zero_or_one(
            self.update_feeds_iter(
                feed=feed, updates_enabled=None, _call_feeds_update_hooks=False
            ),
            lambda: FeedNotFoundError(_feed_argument(feed)),
        )
        if isinstance(rv, Exception):
            raise rv
        return rv

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def get_entries(
        self,
        *,
        feed: FeedInput | None = None,
        entry: EntryInput | None = None,
        read: bool | None = None,
        important: TristateFilterInput = None,
        has_enclosures: bool | None = None,
        source: FeedInput | None = None,
        tags: TagFilterInput = None,
        feed_tags: TagFilterInput = None,
        sort: EntrySort = EntrySort.RECENT,
        limit: int | None = None,
        starting_after: EntryInput | None = None,
    ) -> Iterable[Entry]:
        """Get all or some of the entries.

        Args:
            feed (str or tuple(str) or Feed or None):
                Only return the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only return the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only return (un)read entries.
            important (bool or None or str):
                Only return (un)important entries.
                For more precise filtering, use one of the
                :data:`~reader.types.TristateFilterInput` string filters.
            has_enclosures (bool or None): Only return entries that (don't)
                have enclosures.
            source (str or tuple(str) or Feed or None):
                Only return the entries for this source.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only return entries matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only return entries from feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            sort (EntrySort):
                How to order entries; see :class:`EntrySort` for details.
            limit (int or None): A limit on the number of entries to be returned;
                by default, all entries are returned.
            starting_after (tuple(str, str) or Entry or None):
                Return entries after this entry; a cursor for use in pagination.
                Using ``starting_after`` with ``sort=RANDOM`` is not supported.

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

        .. versionchanged:: 3.5
            The ``important`` argument also accepts string values.

        .. versionadded:: 3.11
            The ``tags`` keyword argument.

        .. versionadded:: 3.16
            The ``source`` keyword argument.

        """

        # If we ever implement pagination, consider following the guidance in
        # https://specs.openstack.org/openstack/api-wg/guidelines/pagination_filter_sort.html

        filter = EntryFilter.from_args(
            feed, entry, read, important, has_enclosures, source, tags, feed_tags
        )
        sort = EntrySort(sort)

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")
        starting_after = _entry_argument(starting_after) if starting_after else None

        if starting_after and sort == EntrySort.RANDOM:
            raise ValueError("using starting_after with sort=RANDOM not supported")

        return self._storage.get_entries(filter, sort, limit, starting_after)

    @overload
    def get_entry(self, entry: EntryInput, /) -> Entry:  # pragma: no cover
        ...

    @overload
    def get_entry(
        self,
        entry: EntryInput,
        default: _T,
        /,
    ) -> Entry | _T:  # pragma: no cover
        ...

    def get_entry(
        self,
        entry: EntryInput,
        default: MissingType | _T = MISSING,
        /,
    ) -> Entry | _T:
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

        .. versionchanged:: 3.0
            The ``entry`` and ``default`` arguments are now positional-only.

        """
        return zero_or_one(
            self.get_entries(entry=entry),
            lambda: EntryNotFoundError(*_entry_argument(entry)),
            default,
        )

    def get_entry_counts(
        self,
        *,
        feed: FeedInput | None = None,
        entry: EntryInput | None = None,
        read: bool | None = None,
        important: TristateFilterInput = None,
        has_enclosures: bool | None = None,
        source: FeedInput | None = None,
        tags: TagFilterInput = None,
        feed_tags: TagFilterInput = None,
    ) -> EntryCounts:
        """Count all or some of the entries.

        Args:
            feed (str or tuple(str) or Feed or None):
                Only count the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only count the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only count (un)read entries.
            important (bool or None or str):
                Only count (un)important entries.
                For more precise filtering, use one of the
                :data:`~reader.types.TristateFilterInput` string filters.
            has_enclosures (bool or None): Only count entries that (don't)
                have enclosures.
            source (str or tuple(str) or Feed or None):
                Only count the entries for this source.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only count entries matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only count entries from feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.

        Returns:
            EntryCounts:

        Raises:
            StorageError

        .. versionadded:: 1.11

        .. versionchanged:: 3.5
            The ``important`` argument also accepts string values.

        .. versionadded:: 3.11
            The ``tags`` keyword argument.

        .. versionadded:: 3.16
            The ``source`` keyword argument.

        """

        filter = EntryFilter.from_args(
            feed, entry, read, important, has_enclosures, source, tags, feed_tags
        )
        now = self._now()
        return self._storage.get_entry_counts(now, filter)

    def set_entry_read(
        self,
        entry: EntryInput,
        read: bool,
        /,
        modified: MissingType | None | datetime = MISSING,
    ) -> None:
        """Mark an entry as read or unread,
        possibly with a custom timestamp.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.
            read (bool): Mark the entry as read if true,
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

        .. versionchanged:: 3.0
            The ``entry`` and ``read`` arguments are now positional-only.

        .. versionchanged:: 3.5
            Do not coerce ``read`` to :class:`bool` anymore,
            require it to be :const:`True` or :const:`False`.

        """
        if read not in (True, False):
            raise ValueError("read should be one of (True, False)")

        modified_aware: datetime | None
        if isinstance(modified, MissingType):
            modified_aware = self._now()
        elif modified is None:
            modified_aware = None
        else:
            modified_aware = modified.astimezone(timezone.utc)

        self._storage.set_entry_read(_entry_argument(entry), read, modified_aware)

    def mark_entry_as_read(self, entry: EntryInput, /) -> None:
        """Mark an entry as read.

        Alias for ``set_entry_read(entry, True)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_read`.

        .. versionchanged:: 3.0
            The ``entry`` argument is now positional-only.

        """
        self.set_entry_read(entry, True)

    def mark_entry_as_unread(self, entry: EntryInput, /) -> None:
        """Mark an entry as unread.

        Alias for ``set_entry_read(entry, False)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_unread`.

        .. versionchanged:: 3.0
            The ``entry`` argument is now positional-only.

        """
        return self.set_entry_read(entry, False)

    def set_entry_important(
        self,
        entry: EntryInput,
        important: bool | None,
        /,
        modified: MissingType | None | datetime = MISSING,
    ) -> None:
        """Mark an entry as important or unimportant,
        possibly with a custom timestamp.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.
            important (bool or None): Mark the entry as important if true,
                as unimportant if false, or as not set if none.
            modified (datetime or None):
                Set :attr:`~Entry.important_modified` to this.
                Naive datetimes are normalized by passing them to
                :meth:`~datetime.datetime.astimezone`.
                Defaults to the current time.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 2.2

        .. versionchanged:: 3.0
            The ``entry`` and ``important`` arguments are now positional-only.

        .. versionchanged:: 3.5
            ``important`` can now be :const:`None`.

        .. versionchanged:: 3.5
            Do not coerce ``important`` to :class:`bool` anymore,
            require it to be :const:`True` or :const:`False` or :const:`None`.

        """
        if important not in (True, False, None):
            raise ValueError("important should be one of (True, False, None)")

        modified_aware: datetime | None
        if isinstance(modified, MissingType):
            modified_aware = self._now()
        elif modified is None:
            modified_aware = None
        else:
            modified_aware = modified.astimezone(timezone.utc)

        self._storage.set_entry_important(
            _entry_argument(entry), important, modified_aware
        )

    def mark_entry_as_important(self, entry: EntryInput, /) -> None:
        """Mark an entry as important.

        Alias for ``set_entry_important(entry, True)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_important`.

        .. versionchanged:: 3.0
            The ``entry`` argument is now positional-only.

        """
        self.set_entry_important(entry, True)

    def mark_entry_as_unimportant(self, entry: EntryInput, /) -> None:
        """Mark an entry as unimportant.

        Alias for ``set_entry_important(entry, False)``.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        .. versionadded:: 1.18
            Renamed from :meth:`mark_as_unimportant`.

        .. versionchanged:: 3.0
            The ``entry`` argument is now positional-only.

        """
        return self.set_entry_important(entry, False)

    def add_entry(self, entry: Any, /, *, overwrite: bool = False) -> None:
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
        * :attr:`~Entry.source`

        Naive datetimes are normalized by passing them to
        :meth:`~datetime.datetime.astimezone`.

        The added entry will be :attr:`~Entry.added_by` ``'user'``.

        Args:
            entry (Entry or dict): An entry-like object or equivalent mapping.
            overwrite (bool):
                If true and the entry already exists,
                overwrite it instead of raising :exc:`EntryExistsError`.

        Raises:
            EntryExistsError: If an entry with the same id already exists.
            FeedNotFoundError: If the feed does not exist.
            StorageError

        .. versionadded:: 2.5

        .. versionchanged:: 3.0
            The ``entry`` argument is now positional-only.

        .. versionchanged:: 3.16
            Allow setting :attr:`~Entry.source`.

        .. versionadded:: 3.18
            The ``overwrite`` argument.

        """

        # `entry` is of type Union[EntryDataLikeProtocol, EntryDataTypedDict],
        # but modeling that is pretty cumbersome; we can do it later if needed;
        # https://github.com/lemon24/reader/issues/239#issuecomment-951892271
        # https://gist.github.com/lemon24/047f71abe76c47661634459eada7b50a#file-01-typing-py

        now = self._now()
        entry_data = entry_data_from_obj(entry)
        intent = EntryUpdateIntent(
            entry=entry_data,
            last_updated=now,
            first_updated=now,
            first_updated_epoch=now,
            # WARNING: keep in sync _update and add_entry
            recent_sort=entry_data.published or entry_data.updated or now,
            added_by='user',
        )

        status = EntryUpdateStatus.NEW
        if overwrite:
            (old_entry,) = self._storage.get_entries_for_update(
                [entry_data.resource_id]
            )
            if old_entry:
                status = EntryUpdateStatus.MODIFIED
            self._storage.add_or_update_entries([intent])
        else:
            self._storage.add_entry(intent)

        for entry_hook in self.after_entry_update_hooks:
            entry_hook(self, intent.entry, status)

    def delete_entry(self, entry: EntryInput, /, missing_ok: bool = False) -> None:
        """Delete an entry.

        Currently, only entries added by :meth:`add_entry`
        and :meth:`copy_entry` (:attr:`~Entry.added_by` ``'user'``)
        can be deleted.

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

        .. versionchanged:: 3.0
            The ``entry`` argument is now positional-only.

        """
        try:
            self._storage.delete_entries([_entry_argument(entry)], added_by='user')
        except EntryNotFoundError:
            if not missing_ok:
                raise

    def copy_entry(self, src: EntryInput, dst: EntryInput, /) -> None:
        """Copy an entry from one feed to another.

        All :class:`Entry` attributes that belong to the entry are copied,
        including timestamps like :attr:`~Entry.added`, entry tags,
        and hidden attributes that affect behavior (e.g. sorting).

        If the original does not already have a :attr:`~Entry.source`,
        the copy's source will be set to the original's :attr:`~Entry.feed`,
        with the feed's :attr:`~Feed.user_title` taking precedence
        over :attr:`~Feed.title` as the source title.

        The copy entry will be :attr:`~Entry.added_by` ``'user'``.

        Args:
            src (tuple(str, str) or Entry): Source (feed URL, entry id) tuple.
            dst (tuple(str, str) or Entry): Destination (feed URL, entry id) tuple.

        Raises:
            EntryExistsError: If an entry with the same id as dst already exists.
            FeedNotFoundError: If the dst feed does not exist.
            StorageError

        .. versionadded:: 3.16

        """
        src_entry = self.get_entry(src)
        recent_sort = self._storage.get_entry_recent_sort(src_entry.resource_id)
        dst_resource_id = _entry_argument(dst)

        # FIXME: do not allow copy to the same feed (or at least entry)

        attrs = dict(src_entry.__dict__)
        attrs['feed_url'], attrs['id'] = dst_resource_id

        if src_entry.source:
            attrs['source'] = dict(src_entry.source.__dict__)
        else:
            attrs['source'] = dict(src_entry.feed.__dict__)
        if not src_entry.source or not src_entry.source.title:
            attrs['source']['title'] = src_entry.feed.resolved_title

        attrs['recent_sort'] = recent_sort
        attrs['added_by'] = 'user'

        intent = entry_update_intent_from_obj(attrs)

        self._storage.add_entry(intent)

        # TODO: not atomic, maybe add to intent later on
        self.set_entry_read(dst, src_entry.read, src_entry.read_modified)
        self.set_entry_important(dst, src_entry.important, src_entry.important_modified)
        for key, value in self.get_tags(src_entry):
            self.set_tag(dst, key, value)

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
        /,
        *,
        feed: FeedInput | None = None,
        entry: EntryInput | None = None,
        read: bool | None = None,
        important: TristateFilterInput = None,
        has_enclosures: bool | None = None,
        source: FeedInput | None = None,
        tags: TagFilterInput = None,
        feed_tags: TagFilterInput = None,
        sort: EntrySearchSort = EntrySearchSort.RELEVANT,
        limit: int | None = None,
        starting_after: EntryInput | None = None,
    ) -> Iterable[EntrySearchResult]:
        """Get entries matching a full-text search query.

        Note:
            The query syntax is dependent on the search provider.

            The default (and for now, only) search provider is SQLite FTS5.
            You can find more details on its query syntax here:
            https://www.sqlite.org/fts5.html#full_text_query_syntax

            The columns available in queries are:

            * ``title``: the entry title
            * ``feed``: the feed or source title (:attr:`~Entry.feed_resolved_title`)
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

            .. versionchanged:: 3.16
                The ``feed`` column now indexes :attr:`~Entry.feed_resolved_title`,
                instead of feed :attr:`~Feed.user_title` or :attr:`~Feed.title`.

        Search must be enabled to call this method.

        Args:
            query (str): The search query.
            feed (str or tuple(str) or Feed or None):
                Only search the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only search for the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only search (un)read entries.
            important (bool or None or str):
                Only search (un)important entries.
                For more precise filtering, use one of the
                :data:`~reader.types.TristateFilterInput` string filters.
            has_enclosures (bool or None): Only search entries that (don't)
                have enclosures.
            source (str or tuple(str) or Feed or None):
                Only search the entries for this source.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only search entries matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only search entries from feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            sort (EntrySearchSort):
                How to order results; see :class:`EntrySearchSort` for details.
            limit (int or None): A limit on the number of results to be returned;
                by default, all results are returned.
            starting_after (tuple(str, str) or EntrySearchResult or None):
                Return results after this result; a cursor for use in pagination.
                Using ``starting_after`` with ``sort=RANDOM`` is not supported.

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

        .. versionchanged:: 3.0
            The ``query`` argument is now positional-only.

        .. versionchanged:: 3.5
            The ``important`` argument also accepts string values.

        .. versionadded:: 3.11
            The ``tags`` keyword argument.

        .. versionadded:: 3.16
            The ``source`` keyword argument.

        """
        filter = EntryFilter.from_args(
            feed, entry, read, important, has_enclosures, source, tags, feed_tags
        )
        sort = EntrySearchSort(sort)

        if limit is not None:
            if not isinstance(limit, numbers.Integral) or limit < 1:
                raise ValueError("limit should be a positive integer")
        starting_after = _entry_argument(starting_after) if starting_after else None

        if starting_after and sort == EntrySearchSort.RANDOM:
            raise ValueError("using starting_after with sort=RANDOM not supported")

        return self._search.search_entries(query, filter, sort, limit, starting_after)

    def search_entry_counts(
        self,
        query: str,
        /,
        *,
        feed: FeedInput | None = None,
        entry: EntryInput | None = None,
        read: bool | None = None,
        important: TristateFilterInput = None,
        has_enclosures: bool | None = None,
        source: FeedInput | None = None,
        tags: TagFilterInput = None,
        feed_tags: TagFilterInput = None,
    ) -> EntrySearchCounts:
        """Count entries matching a full-text search query.

        See :meth:`~Reader.search_entries()` for details on the query syntax.

        Search must be enabled to call this method.

        Args:
            query (str): The search query.
            feed (str or tuple(str) or Feed or None):
                Only count the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only count the entry with this (feed URL, entry id) tuple.
            read (bool or None or str):
                Only count (un)read entries.
                For more precise filtering, use one of the
                :data:`~reader.types.TristateFilterInput` string filters.
            important (bool or None): Only count (un)important entries.
            has_enclosures (bool or None): Only count entries that (don't)
                have enclosures.
            source (str or tuple(str) or Feed or None):
                Only count the entries for this source.
            tags (None or bool or list(str or bool or list(str or bool))):
                Only count entries matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.
            feed_tags (None or bool or list(str or bool or list(str or bool))):
                Only count entries from feeds matching these tags;
                see :data:`~reader.types.TagFilterInput` for details.

        Returns:
            EntrySearchCounts:

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            SearchError
            StorageError

        .. versionadded:: 1.11

        .. versionchanged:: 3.0
            The ``query`` argument is now positional-only.

        .. versionchanged:: 3.5
            The ``important`` argument also accepts string values.

        .. versionadded:: 3.11
            The ``tags`` keyword argument.

        .. versionadded:: 3.16
            The ``source`` keyword argument.

        """

        filter = EntryFilter.from_args(
            feed, entry, read, important, has_enclosures, source, tags, feed_tags
        )
        now = self._now()
        return self._search.search_entry_counts(query, now, filter)

    def get_tags(
        self, resource: ResourceInput, /, *, key: str | None = None
    ) -> Iterable[tuple[str, JSONType]]:
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
            key (str or None): Only return the value for this key.

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

        .. versionchanged:: 3.0
            The ``resource`` argument is now positional-only.

        """
        resource_id = _resource_argument(resource)
        return self._storage.get_tags(resource_id, key)

    def get_tag_keys(self, resource: AnyResourceInput = None, /) -> Iterable[str]:
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

        .. versionchanged:: 3.0
            The ``resource`` argument is now positional-only.

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
        self,
        resource: ResourceInput,
        key: str,
        /,
    ) -> JSONType:  # pragma: no cover
        ...

    @overload
    def get_tag(
        self,
        resource: ResourceInput,
        key: str,
        default: _T,
        /,
    ) -> JSONType | _T:  # pragma: no cover
        ...

    def get_tag(
        self,
        resource: ResourceInput,
        key: str,
        default: MissingType | _T = MISSING,
        /,
    ) -> JSONType | _T:
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

        .. versionchanged:: 3.0
            The ``resource``, ``key``, and ``default`` arguments are now positional-only.

        """
        resource_id = _resource_argument(resource)
        return zero_or_one(
            (v for _, v in self._storage.get_tags(resource_id, key)),
            lambda: TagNotFoundError(resource_id, key),
            default,
        )

    @overload
    def set_tag(self, resource: ResourceInput, key: str, /) -> None:  # pragma: no cover
        ...

    @overload
    def set_tag(
        self,
        resource: ResourceInput,
        key: str,
        value: JSONType,
        /,
    ) -> None:  # pragma: no cover
        ...

    def set_tag(
        self,
        resource: ResourceInput,
        key: str,
        value: JSONType | MissingType = MISSING,
        /,
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

        .. versionchanged:: 3.0
            The ``resource``, ``key``, and ``value`` arguments are now positional-only.

        """
        resource_id = _resource_argument(resource)
        if not isinstance(value, MissingType):
            self._storage.set_tag(resource_id, key, value)
        else:
            self._storage.set_tag(resource_id, key)

    def delete_tag(
        self, resource: ResourceInput, key: str, /, missing_ok: bool = False
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

        .. versionchanged:: 3.0
            The ``resource`` and ``key`` arguments are now positional-only.

        """
        resource_id = _resource_argument(resource)
        try:
            self._storage.delete_tag(resource_id, key)
        except TagNotFoundError:
            if not missing_ok:
                raise

    def make_reader_reserved_name(self, key: str, /) -> str:
        """Create a *reader*-reserved tag name.
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

        .. versionchanged:: 3.0
            The ``key`` argument is now positional-only.

        """
        return self._reserved_name_scheme.make_reader_name(key)

    def make_plugin_reserved_name(
        self,
        plugin_name: str,
        key: str | None = None,
        /,
    ) -> str:
        """Create a plugin-reserved tag name.
        See :ref:`reserved names` for details.

        Plugins should use this to generate names for plugin-specific tags.

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

        .. versionchanged:: 3.0
            The ``plugin_name`` and ``key`` arguments are now positional-only.

        """
        return self._reserved_name_scheme.make_plugin_name(plugin_name, key)

    # Ideally, the getter would return a TypedDict,
    # but the setter would take *any* Mapping[str, str];
    # unfortunately, mypy doesn't like when the types differ:
    # https://github.com/python/mypy/issues/3004

    @property
    def reserved_name_scheme(self) -> Mapping[str, str]:
        """dict(str, str): Mapping used to build :ref:`reserved names`.
        See :meth:`~Reader.make_reader_reserved_name`
        and :meth:`~Reader.make_plugin_reserved_name`
        for details on how this is used.

        The default scheme is :data:`.DEFAULT_RESERVED_NAME_SCHEME`.

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

    @property
    def before_feeds_update_hooks(self) -> MutableSequence[FeedsUpdateHook]:
        """List of functions called *once* before updating any feeds,
        at the beginning of :meth:`update_feeds` / :meth:`update_feeds_iter`,
        but not :meth:`update_feed`.

        Each function is called with:

        * `reader` – the :class:`Reader` instance

        Each function should return :const:`None`.

        The hooks are run in order.
        Exceptions raised by hooks are wrapped in a :exc:`SingleUpdateHookError`
        and re-raised (hooks after the one that failed are not run).

        .. versionadded:: 2.12

        .. versionchanged:: 3.8
            Wrap unexpected exceptions in :exc:`UpdateHookError`.

        """
        return self._update_hooks.hooks['before_feeds_update']

    @property
    def before_feed_update_hooks(self) -> MutableSequence[FeedUpdateHook]:
        """List of functions called for each updated feed
        before the feed is updated.

        Each function is called with:

        * `reader` – the :class:`Reader` instance
        * `feed` – the :class:`str` feed URL

        Each function should return :const:`None`.

        The hooks are run in order.
        Exceptions raised by hooks are wrapped in a :exc:`SingleUpdateHookError`
        and re-raised (hooks after the one that failed are not run).

        .. versionadded:: 2.7

        .. versionchanged:: 3.8
            Wrap unexpected exceptions in :exc:`UpdateHookError`.

        """
        return self._update_hooks.hooks['before_feed_update']

    @property
    def after_entry_update_hooks(self) -> MutableSequence[AfterEntryUpdateHook]:
        """List of functions called for each updated entry
        after the feed is updated.

        Each function is called with:

        * `reader` – the :class:`Reader` instance
        * `entry` – an :class:`Entry`-like object
        * `status` – an :class:`EntryUpdateStatus` value

        Each function should return :const:`None`.

        .. warning::

            The only `entry` attributes guaranteed to be present are
            :attr:`~Entry.feed_url`, :attr:`~Entry.id`,
            and :attr:`~Entry.resource_id`;
            all other attributes may be missing
            (accessing them may raise :exc:`AttributeError`).

        The hooks are run in order.
        Exceptions raised by hooks are wrapped in a :exc:`SingleUpdateHookError`,
        collected, and re-raised as an :exc:`UpdateHookErrorGroup`
        after all the hooks are run;
        currently, only the exceptions for the first 5 entries
        with hook failures are collected.

        .. versionadded:: 1.20

        .. versionchanged:: 3.8
            Wrap unexpected exceptions in :exc:`UpdateHookError`.
            Try to run all hooks, don't stop after one fails.

        """
        return self._update_hooks.hooks['after_entry_update']

    @property
    def after_feed_update_hooks(self) -> MutableSequence[FeedUpdateHook]:
        """List of functions called for each updated feed
        after the feed is updated.

        Each function is called with:

        * `reader` – the :class:`Reader` instance
        * `feed` – the :class:`str` feed URL

        Each function should return :const:`None`.

        The hooks are run in order.
        Exceptions raised by hooks are wrapped in a :exc:`SingleUpdateHookError`,
        collected, and re-raised as an :exc:`UpdateHookErrorGroup`
        after all the hooks are run.

        .. versionadded:: 2.2

        .. versionchanged:: 3.8
            Wrap unexpected exceptions in :exc:`UpdateHookError`.
            Try to run all hooks, don't stop after one fails.

        """
        return self._update_hooks.hooks['after_feed_update']

    @property
    def after_feeds_update_hooks(self) -> MutableSequence[FeedsUpdateHook]:
        """List of functions called *once* after updating all feeds,
        at the end of :meth:`update_feeds` / :meth:`update_feeds_iter`,
        but not :meth:`update_feed`.

        Each function is called with:

        * `reader` – the :class:`Reader` instance

        Each function should return :const:`None`.

        The hooks are run in order.
        Exceptions raised by hooks are wrapped in a :exc:`SingleUpdateHookError`,
        collected, and re-raised as an :exc:`UpdateHookErrorGroup`
        after all the hooks are run.

        .. versionadded:: 2.12

        .. versionchanged:: 3.8
            Wrap unexpected exceptions in :exc:`UpdateHookError`.
            Try to run all hooks, don't stop after one fails.

        """
        return self._update_hooks.hooks['after_feeds_update']
