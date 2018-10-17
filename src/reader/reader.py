import json
import logging
import sqlite3
import functools
import contextlib
import datetime

from .db import open_db, DBError
from .types import Feed, Entry, Content, Enclosure
from .parser import RequestsParser
from .exceptions import (
    ParseError, NotModified,
    FeedExistsError, FeedNotFoundError, EntryNotFoundError,
    StorageError,
)

log = logging.getLogger('reader')


@contextlib.contextmanager
def wrap_storage_exceptions(*args):
    """Wrap sqlite3 exceptions in StorageError.

    Only wraps exceptions that are unlikely to be programming errors (bugs),
    can only be fixed by the user (e.g. access permission denied), and aren't
    domain-related (those should have other custom exceptions).

    This is an imprecise science, since the DB-API exceptions are somewhat
    fuzzy in their meaning and we can't access the SQLite result code.

    Full discussion at https://github.com/lemon24/reader/issues/21

    """

    try:
        yield
    except sqlite3.OperationalError as e:
        raise StorageError("sqlite3 error") from e


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


class Reader:

    """A feed reader.

    Args:
        path (str): Path to the reader database.

    Raises:
        StorageError

    """

    _get_entries_chunk_size = 2 ** 8

    _open_db = staticmethod(open_db)

    @wrap_storage_exceptions()
    def __init__(self, path=None):
        try:
            self.db = self._open_db(path)
        except DBError as e:
            raise StorageError(str(e)) from e
        self._parse = RequestsParser()

    @wrap_storage_exceptions()
    def add_feed(self, feed):
        """Add a new feed.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedExistsError
            StorageError

        """
        url = feed_argument(feed)
        with self.db:
            try:
                self.db.execute("""
                    INSERT INTO feeds (url)
                    VALUES (:url);
                """, locals())
            except sqlite3.IntegrityError:
                raise FeedExistsError(url)

    @wrap_storage_exceptions()
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
        with self.db:
            rows = self.db.execute("""
                DELETE FROM feeds
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    def _get_feeds(self, url=None):
        where_url_snippet = '' if not url else "WHERE url = :url"
        cursor = self.db.execute("""
            SELECT url, updated, title, link, author, user_title FROM feeds
            {where_url_snippet}
            ORDER BY feeds.title, feeds.url;
        """.format(**locals()), locals())

        for row in cursor:
            yield Feed._make(row)

    @wrap_storage_exceptions()
    def get_feeds(self):
        """Get all the feeds.

        Yields:
            :class:`Feed`

        Raises:
            StorageError

        """
        return list(self._get_feeds())

    @wrap_storage_exceptions()
    def get_feed(self, feed):
        """Get a feed.

        Arguments:
            feed (str or Feed): The feed URL.

        Returns:
            Feed or None: The feed if it exists, None if it doesn't.

        Raises:
            StorageError

        """
        url = feed_argument(feed)
        feeds = list(self._get_feeds(url))
        if len(feeds) == 0:
            return None
        elif len(feeds) == 1:
            return feeds[0]
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    def _get_feeds_for_update(self, url=None, new_only=False):
        if url or new_only:
            where_snippet = "WHERE 1"
        else:
            where_snippet = ''
        where_url_snippet = '' if not url else " AND url = :url"
        where_new_only_snippet = '' if not new_only else " AND last_updated is NULL"
        cursor = self.db.execute("""
            SELECT url, updated, http_etag, http_last_modified, stale FROM feeds
            {where_snippet}
            {where_url_snippet}
            {where_new_only_snippet}
            ORDER BY feeds.url;
        """.format(**locals()), locals())
        return cursor

    def _mark_as_stale(self, url):
        with self.db:
            rows = self.db.execute("""
                UPDATE feeds
                SET stale = 1
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
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
        with self.db:
            rows = self.db.execute("""
                UPDATE feeds
                SET user_title = :title
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def update_feeds(self, new_only=False):
        """Update all the feeds.

        Args:
            new_only (bool): Only update feeds that have never been updated.

        Raises:
            StorageError

        """
        for row in list(self._get_feeds_for_update(new_only=new_only)):
            try:
                self._update_feed(*row)
            except FeedNotFoundError as e:
                log.info("update feed %r: feed removed during update", e.url)
            except ParseError as e:
                log.exception("update feed %r: error while getting/parsing feed, skipping; exception: %r", e.url, e.__cause__)

    @wrap_storage_exceptions()
    def update_feed(self, feed):
        """Update a single feed.

        Args:
            feed (str or Feed): The feed URL.

        Raises:
            FeedNotFoundError
            StorageError

        """
        url = feed_argument(feed)
        rows = list(self._get_feeds_for_update(url))
        if len(rows) == 0:
            raise FeedNotFoundError(url)
        elif len(rows) == 1:
            self._update_feed(*rows[0])
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    @staticmethod
    def _now():
        return datetime.datetime.utcnow()

    def _update_feed(self, url, db_updated, http_etag, http_last_modified, stale):
        if stale:
            db_updated = None
            http_etag = None
            http_last_modified = None
            log.info("update feed %r: feed marked as stale, ignoring updated, http_etag or http_last_modified", url)

        try:
            t = self._parse(url, http_etag, http_last_modified)
            feed, entries, http_etag, http_last_modified = t
        except NotModified:
            log.info("update feed %r: feed not modified, skipping", url)
            return

        updated = feed.updated
        log.debug("update feed %r: old updated %s, new updated %s", url, db_updated, updated)

        if not updated:
            log.info("update feed %r: feed has no updated, treating as updated", url)
            feed_was_updated = True
        else:
            feed_was_updated = not(updated and db_updated and updated <= db_updated)

        if not stale and not feed_was_updated:
            # Some feeds have entries newer than the feed.
            # https://github.com/lemon24/reader/issues/76
            log.info("update feed %r: feed not updated, updating entries anyway", url)

        title = feed.title
        link = feed.link
        author = feed.author

        with self.db:

            now = self._now()

            if stale or feed_was_updated:
                rows = self.db.execute("""
                    UPDATE feeds
                    SET
                        title = :title,
                        link = :link,
                        updated = :updated,
                        author = :author,
                        http_etag = :http_etag,
                        http_last_modified = :http_last_modified,
                        stale = NULL,
                        last_updated = :now
                    WHERE url = :url;
                """, locals())

                if rows.rowcount == 0:
                    raise FeedNotFoundError(url)
                assert rows.rowcount == 1, "shouldn't have more than 1 row"

            entries_updated, entries_new = 0, 0
            last_updated = now
            for entry in reversed(list(entries)):
                assert entry.feed is None
                entry_updated, entry_new = self._update_entry(url, entry, stale, now, last_updated)
                entries_updated += entry_updated
                entries_new += entry_new
                last_updated += datetime.timedelta(microseconds=1)

            log.info("update feed %r: updated (updated %d, new %d)", url, entries_updated, entries_new)

    def _update_entry(self, feed_url, entry, stale, now, last_updated):
        entry_exists, db_updated = self._get_entry_updated(feed_url, entry.id)
        updated, published = entry.updated, entry.published

        if stale:
            log.debug("update entry %r of feed %r: feed marked as stale, updating anyway", entry.id, feed_url)
        elif not updated:
            log.debug("update entry %r of feed %r: has no updated, updating but not changing updated", entry.id, feed_url)
            updated = db_updated or now
        elif db_updated and updated <= db_updated:
            log.debug("update entry %r of feed %r: entry not updated, skipping (old updated %s, new updated %s)", entry.id, feed_url, db_updated, updated)
            return 0, 0

        id = entry.id
        title = entry.title
        link = entry.link
        author = entry.author
        summary = entry.summary
        content = json.dumps([t._asdict() for t in entry.content]) if entry.content else None
        enclosures = json.dumps([t._asdict() for t in entry.enclosures]) if entry.enclosures else None

        try:

            if not entry_exists:
                self.db.execute("""
                    INSERT INTO entries (
                        id, feed, title, link, updated, author, published, summary, content, enclosures, last_updated
                    ) VALUES (
                        :id, :feed_url, :title, :link, :updated, :author, :published, :summary, :content, :enclosures, :last_updated
                    );
                """, locals())
                log.debug("update entry %r of feed %r: entry added", entry.id, feed_url)
                return 0, 1

            else:
                self.db.execute("""
                    UPDATE entries
                    SET
                        title = :title,
                        link = :link,
                        updated = :updated,
                        author = :author,
                        published = :published,
                        summary = :summary,
                        content = :content,
                        enclosures = :enclosures,
                        last_updated = :last_updated
                    WHERE feed = :feed_url AND id = :id;
                """, locals())
                log.debug("update entry %r of feed %r: entry updated", entry.id, feed_url)
                return 1, 0

        except sqlite3.IntegrityError as e:
            log.debug("update entry %r of feed %r: got IntegrityError", entry.id, feed_url, exc_info=True)
            raise FeedNotFoundError(feed_url)

    def _get_entry_updated(self, feed_url, id):
        rv = self.db.execute("""
            SELECT updated
            FROM entries
            WHERE feed = :feed_url
                AND id = :id;
        """, locals()).fetchone()
        if not rv:
            return False, None
        return True, rv[0]

    def _get_entries(self, which, feed_url, has_enclosures,
                     chunk_size=None, last=None):
        log.debug("_get_entries chunk_size=%s last=%s", chunk_size, last)

        if which == 'all':
            where_read_snippet = ''
        elif which == 'unread':
            where_read_snippet = """
                AND (entries.read IS NULL OR entries.read != 1)
            """
        elif which == 'read':
            where_read_snippet = """
                AND entries.read = 1
            """
        else:
            assert False, "shouldn't get here"  # pragma: no cover

        where_next_snippet = ''
        limit_snippet = ''
        if chunk_size:
            limit_snippet = """
                LIMIT :chunk_size
            """
            if last:
                last_entry_updated, last_feed_url, last_entry_last_updated, last_entry_id = last
                where_next_snippet = """
                    AND (entries.updated, feeds.url, entries.last_updated, entries.id) <
                        (:last_entry_updated, :last_feed_url, :last_entry_last_updated, :last_entry_id)
                """

        where_feed_snippet = ''
        if feed_url:
            where_feed_snippet = """
                AND feeds.url = :feed_url
            """

        where_has_enclosures_snippet = ''
        if has_enclosures is not None:
            where_has_enclosures_snippet = """
                AND {} (json_array_length(entries.enclosures) IS NULL
                        OR json_array_length(entries.enclosures) = 0)
            """.format('NOT' if has_enclosures else '')

        query = """
            SELECT
                feeds.url,
                feeds.updated,
                feeds.title,
                feeds.link,
                feeds.author,
                feeds.user_title,
                entries.id,
                entries.updated,
                entries.title,
                entries.link,
                entries.author,
                entries.published,
                entries.summary,
                entries.content,
                entries.enclosures,
                entries.read,
                entries.last_updated
            FROM entries, feeds
            WHERE
                feeds.url = entries.feed
                {where_read_snippet}
                {where_feed_snippet}
                {where_next_snippet}
                {where_has_enclosures_snippet}
            ORDER BY
                entries.updated DESC,
                feeds.url DESC,
                entries.last_updated DESC,
                entries.id DESC
            {limit_snippet}
            ;
        """.format(**locals())

        log.debug("_get_entries query\n%s\n", query)
        with wrap_storage_exceptions():
            cursor = self.db.execute(query, locals())

        for t in cursor:
            feed = t[0:6]
            feed = Feed._make(feed)
            entry = t[6:13] + (
                tuple(Content(**d) for d in json.loads(t[13])) if t[13] else None,
                tuple(Enclosure(**d) for d in json.loads(t[14])) if t[14] else None,
                t[15] == 1,
                feed,
            )
            last_updated = t[16]
            entry = Entry._make(entry)
            yield entry, last_updated

    @wrap_storage_exceptions()
    def get_entries(self, which='all', feed=None, has_enclosures=None):
        """Get all or some of the entries.

        Args:
            which (str): One of ``'all'``, ``'read'``, or ``'unread'``.
            feed (str or Feed or None): Only return the entries for this feed.
            has_enclosures (bool or None): Only return entries that (don't)
                have enclosures.

        Yields:
            :class:`Entry`: Last updated entries first.

        Raises:
            FeedNotFoundError: Only if `feed` is not None.
            StorageError

        """
        feed_url = feed_argument(feed) if feed is not None else None
        if which not in ('all', 'unread', 'read'):
            raise ValueError("which should be one of ('all', 'read', 'unread')")
        if has_enclosures not in (None, False, True):
            raise ValueError("has_enclosures should be one of (None, False, True)")
        chunk_size = self._get_entries_chunk_size

        last = None
        while True:

            entries = self._get_entries(
                which=which,
                feed_url=feed_url,
                has_enclosures=has_enclosures,
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

            last_entry, last_updated = entries[-1]

            entries = (e for e, _ in entries)
            yield from entries

            last = (
                last_entry.updated,
                last_entry.feed.url,
                last_updated,
                last_entry.id,
            )

    def _mark_as_read_unread(self, feed_url, entry_id, read):
        with self.db:
            rows = self.db.execute("""
                UPDATE entries
                SET read = :read
                WHERE feed = :feed_url AND id = :entry_id;
            """, locals())
            if rows.rowcount == 0:
                raise EntryNotFoundError(feed_url, entry_id)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def mark_as_read(self, entry):
        """Mark an entry as read.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._mark_as_read_unread(feed_url, entry_id, 1)

    @wrap_storage_exceptions()
    def mark_as_unread(self, entry):
        """Mark an entry as unread.

        Args:
            entry (tuple(str, str) or Entry): (feed URL, entry id) tuple.

        Raises:
            EntryNotFoundError
            StorageError

        """
        feed_url, entry_id = entry_argument(entry)
        self._mark_as_read_unread(feed_url, entry_id, 0)

