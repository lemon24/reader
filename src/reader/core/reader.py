import datetime
import logging

from .exceptions import EntryNotFoundError
from .exceptions import FeedNotFoundError
from .exceptions import MetadataNotFoundError
from .exceptions import ParseError
from .parser import RequestsParser
from .storage import Storage
from .updater import Updater

log = logging.getLogger('reader')


def feed_argument(feed):
    try:
        return feed.url
    except AttributeError:
        if isinstance(feed, str):
            return feed
        raise ValueError('feed')


def entry_argument(entry):
    try:
        return entry.feed.url, entry.id
    except AttributeError:
        if isinstance(entry, tuple) and len(entry) == 2:
            feed_url, entry_id = entry
            if isinstance(feed_url, str) and isinstance(entry_id, str):
                return entry
        raise ValueError('entry')


class _Missing:
    def __repr__(self):
        return "no value"


_missing = _Missing()


class Reader:

    """A feed reader.

    Args:
        path (str): Path to the reader database.

    Raises:
        StorageError

    """

    _get_entries_chunk_size = 2 ** 8

    def __init__(self, path=None):
        self._storage = Storage(path)
        self._parser = RequestsParser()
        self._post_entry_add_plugins = []

    def add_feed(self, feed):
        """Add a new feed.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedExistsError
            StorageError

        """
        url = feed_argument(feed)
        now = self._now()
        return self._storage.add_feed(url, now)

    def remove_feed(self, feed):
        """Remove a feed.

        Also removes all of the feed's entries.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = feed_argument(feed)
        return self._storage.remove_feed(url)

    def get_feeds(self, sort='title'):
        """Get all the feeds.

        Args:
            sort (str): How to order feeds; one of ``'title'`` (by
                :attr:`~Feed.user_title` or :attr:`~Feed.title`, case
                insensitive; default), or ``'added'`` (last added first).

        Yields:
            :class:`Feed`: Sorted according to ``sort``.

        Raises:
            StorageError

        """
        if sort not in ('title', 'added'):
            raise ValueError("sort should be one of ('title', 'added')")
        return self._storage.get_feeds(sort=sort)

    def get_feed(self, feed, default=_missing):
        """Get a feed.

        Arguments:
            feed (str or Feed): The feed URL.
            default: Returned if given and the feed does not exist.

        Returns:
            Feed: The feed.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = feed_argument(feed)
        feeds = list(self._storage.get_feeds(url=url))
        if len(feeds) == 0:
            if default is _missing:
                raise FeedNotFoundError(url)
            return default
        elif len(feeds) == 1:
            return feeds[0]
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    def set_feed_user_title(self, feed, title):
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

    def update_feeds(self, new_only=False):
        """Update all the feeds.

        Args:
            new_only (bool): Only update feeds that have never been updated.

        Raises:
            StorageError

        """

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

        for row in self._storage.get_feeds_for_update(new_only=new_only):
            try:
                self._update_feed(row, global_now)
            except FeedNotFoundError as e:
                log.info("update feed %r: feed removed during update", e.url)
            except ParseError as e:
                log.exception(
                    "update feed %r: error while getting/parsing feed, skipping; exception: %r",
                    e.url,
                    e.__cause__,
                )

    def update_feed(self, feed):
        """Update a single feed.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = feed_argument(feed)
        rows = list(self._storage.get_feeds_for_update(url))
        if len(rows) == 0:
            raise FeedNotFoundError(url)
        elif len(rows) == 1:
            self._update_feed(rows[0])
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    @staticmethod
    def _now():
        return datetime.datetime.utcnow()

    def _update_feed(self, feed_for_update, global_now=None):
        now = self._now()

        updater = Updater(feed_for_update, now, global_now)
        result = updater.update(self._parser, self._storage)

        url = result.url or feed_for_update.url
        new_entries = [e.entry for e in result.entries if e.new]

        for entry in new_entries:
            for plugin in self._post_entry_add_plugins:
                plugin(self, url, entry)

    def get_entries(self, which='all', feed=None, has_enclosures=None):
        """Get all or some of the entries.

        Entries are sorted most recent first. Currently "recent" means:

        * by import date for entries published less than 3 days ago
        * by published date otherwise (if an entry does not have
          :attr:`~Entry.published`, :attr:`~Entry.updated` is used)

        Note:
            The algorithm for "recent" is a heuristic and may change over time.

        Args:
            which (str): One of ``'all'``, ``'read'``, or ``'unread'``.
            feed (str or Feed or None): Only return the entries for this feed.
            has_enclosures (bool or None): Only return entries that (don't)
                have enclosures.

        Yields:
            :class:`Entry`: Most recent entries first.

        Raises:
            FeedNotFoundError: Only if `feed` is not None.
            StorageError

        """

        # If we ever implement pagination, consider following the guidance in
        # https://specs.openstack.org/openstack/api-wg/guidelines/pagination_filter_sort.html

        feed_url = feed_argument(feed) if feed is not None else None
        if which not in ('all', 'unread', 'read'):
            raise ValueError("which should be one of ('all', 'read', 'unread')")
        if has_enclosures not in (None, False, True):
            raise ValueError("has_enclosures should be one of (None, False, True)")
        chunk_size = self._get_entries_chunk_size

        now = self._now()

        last = None
        while True:

            entries = self._storage.get_entries(
                which=which,
                feed_url=feed_url,
                has_enclosures=has_enclosures,
                now=now,
                chunk_size=chunk_size,
                last=last,
            )

            # When chunk_size is 0, don't chunk the query.
            #
            # This will ensure there are no missing/duplicated entries, but
            # will block database writes until the whole generator is consumed.
            #
            # Currently not exposed through the public API.
            #
            if not chunk_size:
                entries = (e for e, _ in entries)
                yield from entries
                return

            entries = list(entries)
            if not entries:
                break

            _, last = entries[-1]

            entries = (e for e, _ in entries)
            yield from entries

    def get_entry(self, entry, default=_missing):
        """Get an entry.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Returns:
            Entry: The entry.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        now = self._now()

        entries = list(
            self._storage.get_entries(now=now, feed_url=feed_url, entry_id=entry_id)
        )

        if len(entries) == 0:
            if default is _missing:
                raise EntryNotFoundError(feed_url, entry_id)
            return default
        elif len(entries) == 1:
            return entries[0][0]
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    def mark_as_read(self, entry):
        """Mark an entry as read.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, 1)

    def mark_as_unread(self, entry):
        """Mark an entry as unread.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._storage.mark_as_read_unread(feed_url, entry_id, 0)

    def iter_feed_metadata(self, feed):
        """Get all the metadata values for a feed.

        Args:
            feed (str or Feed): The feed URL.

        Yields:
            tuple(str, JSONType): Key-value pairs, in undefined order.
            JSONType is whatever :py:func:`json.dumps` accepts.

        Raises:
            StorageError

        """
        feed_url = feed_argument(feed)
        return self._storage.iter_feed_metadata(feed_url)

    def get_feed_metadata(self, feed, key, default=_missing):
        """Get metadata for a feed.

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
        feed_url = feed_argument(feed)
        pairs = list(self._storage.iter_feed_metadata(feed_url, key))

        if len(pairs) == 0:
            if default is _missing:
                raise MetadataNotFoundError(feed_url, key)
            return default
        elif len(pairs) == 1:
            assert pairs[0][0] == key
            return pairs[0][1]
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    def set_feed_metadata(self, feed, key, value):
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

    def delete_feed_metadata(self, feed, key):
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
