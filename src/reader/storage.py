import sqlite3
import contextlib
import functools
import logging
import json

from .db import open_db, DBError
from .exceptions import (
    StorageError,
    EntryNotFoundError, FeedNotFoundError, FeedExistsError,
)
from .types import Feed

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


def wrap_storage_exceptions_generator(fn):
    """Like wrap_storage_exceptions, but for generators.

    TODO: Is this worth doing to prevent an indentation level in a few functions?

    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with wrap_storage_exceptions():
            yield from fn(*args, **kwargs)

    return wrapper


class Storage:

    _open_db = staticmethod(open_db)

    @wrap_storage_exceptions()
    def __init__(self, path=None):
        try:
            self.db = self._open_db(path)
        except DBError as e:
            raise StorageError(str(e)) from e
        self.in_transaction = False

    def __enter__(self):
        assert not self.in_transaction
        self.in_transaction = True
        self.db.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.in_transaction = False
        return self.db.__exit__(exc_type, exc_value, traceback)

    @wrap_storage_exceptions()
    def add_feed(self, url):
        assert not self.in_transaction
        with self.db:
            try:
                self.db.execute("""
                    INSERT INTO feeds (url)
                    VALUES (:url);
                """, locals())
            except sqlite3.IntegrityError:
                raise FeedExistsError(url)

    @wrap_storage_exceptions()
    def remove_feed(self, url):
        assert not self.in_transaction
        with self.db:
            rows = self.db.execute("""
                DELETE FROM feeds
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions_generator
    def get_feeds(self, url=None):
        assert not self.in_transaction
        where_url_snippet = '' if not url else "WHERE url = :url"
        cursor = self.db.execute("""
            SELECT url, updated, title, link, author, user_title FROM feeds
            {where_url_snippet}
            ORDER BY feeds.title, feeds.url;
        """.format(**locals()), locals())

        for row in cursor:
            yield Feed._make(row)

    def get_feeds_for_update(self, url=None, new_only=False):
        assert not self.in_transaction
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

    def get_entry_updated(self, feed_url, id):
        assert self.in_transaction
        rv = self.db.execute("""
            SELECT updated
            FROM entries
            WHERE feed = :feed_url
                AND id = :id;
        """, locals()).fetchone()
        if not rv:
            return False, None
        return True, rv[0]

    @wrap_storage_exceptions()
    def set_feed_user_title(self, url, title):
        assert not self.in_transaction
        with self.db:
            rows = self.db.execute("""
                UPDATE feeds
                SET user_title = :title
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    def mark_as_stale(self, url):
        assert not self.in_transaction
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
    def mark_as_read_unread(self, feed_url, entry_id, read):
        assert not self.in_transaction
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
    def update_feed(self, url, feed, http_etag, http_last_modified, now):
        assert self.in_transaction

        updated = feed.updated
        title = feed.title
        link = feed.link
        author = feed.author

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

    @wrap_storage_exceptions()
    def add_entry(self, feed_url, entry, updated, last_updated):
        assert self.in_transaction

        published = entry.published
        id = entry.id
        title = entry.title
        link = entry.link
        author = entry.author
        summary = entry.summary
        content = json.dumps([t._asdict() for t in entry.content]) if entry.content else None
        enclosures = json.dumps([t._asdict() for t in entry.enclosures]) if entry.enclosures else None

        try:
            self.db.execute("""
                INSERT INTO entries (
                    id, feed, title, link, updated, author, published, summary, content, enclosures, last_updated
                ) VALUES (
                    :id, :feed_url, :title, :link, :updated, :author, :published, :summary, :content, :enclosures, :last_updated
                );
            """, locals())
        except sqlite3.IntegrityError as e:
            log.debug("add_entry %r of feed %r: got IntegrityError", entry.id, feed_url, exc_info=True)
            raise FeedNotFoundError(feed_url)

    @wrap_storage_exceptions()
    def update_entry(self, feed_url, entry, updated, last_updated):
        assert self.in_transaction

        published = entry.published
        id = entry.id
        title = entry.title
        link = entry.link
        author = entry.author
        summary = entry.summary
        content = json.dumps([t._asdict() for t in entry.content]) if entry.content else None
        enclosures = json.dumps([t._asdict() for t in entry.enclosures]) if entry.enclosures else None

        try:
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
        except sqlite3.IntegrityError as e:
            log.debug("update_entry %r of feed %r: got IntegrityError", entry.id, feed_url, exc_info=True)
            raise FeedNotFoundError(feed_url)

