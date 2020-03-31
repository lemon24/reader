import datetime
import logging
import warnings
from functools import partial
from typing import Callable
from typing import cast
from typing import Collection
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import overload
from typing import Tuple
from typing import TypeVar
from typing import Union

from .exceptions import EntryNotFoundError
from .exceptions import FeedNotFoundError
from .exceptions import MetadataNotFoundError
from .exceptions import NotModified
from .exceptions import ParseError
from .parser import Parser
from .search import Search
from .storage import Storage
from .types import Entry
from .types import entry_argument
from .types import EntryFilterOptions
from .types import EntryInput
from .types import EntrySearchResult
from .types import Feed
from .types import feed_argument
from .types import FeedForUpdate
from .types import FeedInput
from .types import FeedSortOrder
from .types import JSONType
from .types import ParseResult
from .updater import Updater
from .utils import _Missing
from .utils import _missing
from .utils import join_paginated_iter
from .utils import make_noop_map
from .utils import make_pool_map
from .utils import zero_or_one


log = logging.getLogger('reader')


_T = TypeVar('_T')
_U = TypeVar('_U')


_PostEntryAddPluginType = Callable[['Reader', str, Entry], None]


def make_reader(url: str) -> 'Reader':
    """Return a new :class:`Reader`.

    Args:
        url (str): Path to the reader database.

    Raises:
        StorageError

    """
    return Reader(url, called_directly=False)


class Reader:

    """A feed reader.

    Reader objects should be created using :func:`make_reader`; the Reader
    constructor is not stable yet and may change without any notice.

    """

    _pagination_chunk_size = 2 ** 8

    def __init__(self, path: str, called_directly: bool = True):
        self._storage = Storage(path)

        # For now, we're using a storage-bound search provider.
        # If we ever implement an external search provider,
        # we'll probably need to do the wiring differently.
        # See the Search docstring for details.
        self._search = Search(self._storage)

        self._parser = Parser()
        self._post_entry_add_plugins: Collection[_PostEntryAddPluginType] = []

        if called_directly:
            warnings.warn(
                "Reader objects should be created using make_reader(); the Reader "
                "constructor is not stable yet and may change without any notice.",
                DeprecationWarning,
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

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedExistsError
            StorageError

        """
        url = feed_argument(feed)
        now = self._now()
        self._storage.add_feed(url, now)

    def remove_feed(self, feed: FeedInput) -> None:
        """Remove a feed.

        Also removes all of the feed's entries.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = feed_argument(feed)
        self._storage.remove_feed(url)

    def get_feeds(
        self, *, feed: Optional[FeedInput] = None, sort: FeedSortOrder = 'title'
    ) -> Iterable[Feed]:
        """Get all or some of the feeds.

        Args:
            feed (str or Feed or None): Only return the feed with this URL.
            sort (str): How to order feeds; one of ``'title'`` (by
                :attr:`~Feed.user_title` or :attr:`~Feed.title`, case
                insensitive; default), or ``'added'`` (last added first).

        Yields:
            :class:`Feed`: Sorted according to ``sort``.

        Raises:
            StorageError

        """
        url = feed_argument(feed) if feed else None
        if sort not in ('title', 'added'):
            raise ValueError("sort should be one of ('title', 'added')")
        return self._storage.get_feeds(url=url, sort=sort)

    @overload
    def get_feed(self, feed: FeedInput) -> Feed:  # pragma: no cover
        ...

    @overload
    def get_feed(
        self, feed: FeedInput, default: _T
    ) -> Union[Feed, _T]:  # pragma: no cover
        ...

    def get_feed(
        self, feed: FeedInput, default: Union[_Missing, _T] = _missing
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
            lambda: FeedNotFoundError(feed_argument(feed)),
            default,
        )

    def set_feed_user_title(self, feed: FeedInput, title: Optional[str]) -> None:
        """Set a user-defined title for a feed.

        Args:
            feed (str or Feed): The feed URL.
            title (str or None): The title, or None to remove the current title.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = feed_argument(feed)
        return self._storage.set_feed_user_title(url, title)

    def update_feeds(self, new_only: bool = False, workers: int = 1) -> None:
        """Update all the feeds.

        Args:
            new_only (bool): Only update feeds that have never been updated.
            workers (int): Number of threads to use when getting the feeds.

        Raises:
            StorageError

        """

        if workers < 1:
            raise ValueError("workers must be a positive integer")
        make_map = make_noop_map() if workers == 1 else make_pool_map(workers)

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

        with make_map as map:

            # TODO: Remove cast when mypy supports it.
            #
            # Without the cast, we get:
            #
            #   src/reader/core/reader.py:250: error: No overload variant of "next" matches argument type "Iterable[Tuple[FeedForUpdate, Optional[ParseResult]]]"
            #
            # https://github.com/python/mypy/issues/1317
            # https://github.com/python/mypy/issues/6697
            #
            it = cast(
                Iterator[Tuple[FeedForUpdate, Optional[ParseResult]]],
                map(
                    self._parse_feed_for_update,
                    self._storage.get_feeds_for_update(new_only=new_only),
                ),
            )

            while True:
                try:
                    row, parse_result = next(it)
                    self._update_feed(row, parse_result, global_now)
                except FeedNotFoundError as e:
                    log.info("update feed %r: feed removed during update", e.url)
                except ParseError as e:
                    log.exception(
                        "update feed %r: error while getting/parsing feed, "
                        "skipping; exception: %r",
                        e.url,
                        e.__cause__,
                    )
                except StopIteration:
                    break

    def update_feed(self, feed: FeedInput) -> None:
        """Update a single feed.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            ParseError
            StorageError

        """
        url = feed_argument(feed)

        feed_for_update = zero_or_one(
            self._storage.get_feeds_for_update(url), lambda: FeedNotFoundError(url),
        )

        self._update_feed(*self._parse_feed_for_update(feed_for_update))

    def _parse_feed_for_update(
        self, feed: FeedForUpdate
    ) -> Tuple[FeedForUpdate, Optional[ParseResult]]:
        # FIXME: Updater is poorly made, we shold not have to do this ಠ_ಠ
        feed = Updater.process_old_feed(feed)
        try:
            return feed, self._parser(feed.url, feed.http_etag, feed.http_last_modified)
        except NotModified:
            return feed, None

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.utcnow()

    def _update_feed(
        self,
        feed_for_update: FeedForUpdate,
        parse_result: Optional[ParseResult],
        global_now: Optional[datetime.datetime] = None,
    ) -> None:
        now = self._now()

        if not global_now:
            global_now = now

        updater = Updater(feed_for_update, now, global_now)
        result = updater.update(parse_result, self._storage)

        new_entries = [e.entry for e in result.entries if e.new]

        for entry in new_entries:
            for plugin in self._post_entry_add_plugins:
                plugin(self, feed_for_update.url, entry)

    def get_entries(
        self,
        *,
        feed: Optional[FeedInput] = None,
        entry: Optional[EntryInput] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
    ) -> Iterable[Entry]:
        """Get all or some of the entries.

        Entries are sorted most recent first. Currently "recent" means:

        * by import date for entries published less than 7 days ago
        * by published date otherwise (if an entry does not have
          :attr:`~Entry.published`, :attr:`~Entry.updated` is used)

        Note:
            The algorithm for "recent" is a heuristic and may change over time.

        Args:
            feed (str or Feed or None): Only return the entries for this feed.
            entry (tuple(str, str) or Entry or None):
                Only return the entry with this (feed URL, entry id) tuple.
            read (bool or None): Only return (un)read entries.
            important (bool or None): Only return (un)important entries.
            has_enclosures (bool or None): Only return entries that (don't)
                have enclosures.

        Yields:
            :class:`Entry`: Most recent entries first.

        Raises:
            StorageError

        """

        # If we ever implement pagination, consider following the guidance in
        # https://specs.openstack.org/openstack/api-wg/guidelines/pagination_filter_sort.html

        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures
        )
        yield from join_paginated_iter(
            partial(self._storage.get_entries, self._now(), filter_options),
            self._pagination_chunk_size,
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
        self, entry: EntryInput, default: Union[_Missing, _T] = _missing
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
            lambda: EntryNotFoundError(*entry_argument(entry)),
            default,
        )

    def mark_as_read(self, entry: EntryInput) -> None:
        """Mark an entry as read.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, True)

    def mark_as_unread(self, entry: EntryInput) -> None:
        """Mark an entry as unread.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, False)

    def mark_as_important(self, entry: EntryInput) -> None:
        """Mark an entry as important.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._storage.mark_as_important_unimportant(feed_url, entry_id, True)

    def mark_as_unimportant(self, entry: EntryInput) -> None:
        """Mark an entry as unimportant.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
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
        feed_url = feed_argument(feed)
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
        self, feed: FeedInput, key: str, default: Union[_Missing, _T] = _missing
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
            lambda: MetadataNotFoundError(feed_argument(feed), key),
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
        feed_url = feed_argument(feed)
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
        feed_url = feed_argument(feed)
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
    ) -> Iterable[EntrySearchResult]:
        """Get entries matching a full-text search query, sorted by relevance.

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

        Yields:
            :class:`EntrySearchResult`: Best-match entries first.

        Raises:
            SearchNotEnabledError
            InvalidSearchQueryError
            SearchError
            StorageError

        """
        filter_options = EntryFilterOptions.from_args(
            feed, entry, read, important, has_enclosures
        )
        yield from join_paginated_iter(
            partial(self._search.search_entries, query, filter_options),
            self._pagination_chunk_size,
        )
