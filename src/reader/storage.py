import sqlite3
import contextlib
import functools

from .db import open_db, DBError
from .exceptions import (
    StorageError,
    EntryNotFoundError, FeedNotFoundError, FeedExistsError,
)
from .types import Feed


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

    @wrap_storage_exceptions()
    def add_feed(self, url):
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
        where_url_snippet = '' if not url else "WHERE url = :url"
        cursor = self.db.execute("""
            SELECT url, updated, title, link, author, user_title FROM feeds
            {where_url_snippet}
            ORDER BY feeds.title, feeds.url;
        """.format(**locals()), locals())

        for row in cursor:
            yield Feed._make(row)

    @wrap_storage_exceptions()
    def set_feed_user_title(self, url, title):
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
        with self.db:
            rows = self.db.execute("""
                UPDATE entries
                SET read = :read
                WHERE feed = :feed_url AND id = :entry_id;
            """, locals())
            if rows.rowcount == 0:
                raise EntryNotFoundError(feed_url, entry_id)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

