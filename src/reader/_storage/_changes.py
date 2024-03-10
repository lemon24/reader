from __future__ import annotations

import sqlite3
from typing import Any
from typing import TYPE_CHECKING

from .._types import Action
from .._types import Change
from ..exceptions import ChangeTrackingNotEnabledError
from ._base import wrap_exceptions
from ._sql_utils import parse_schema
from ._sql_utils import Query
from ._sqlite_utils import ddl_transaction


if TYPE_CHECKING:  # pragma: no cover
    from ._base import StorageBase


ENABLED_EXC = {'no such table': lambda _: ChangeTrackingNotEnabledError()}


class Changes:
    def __init__(self, storage: StorageBase):
        self.storage = storage

    @wrap_exceptions()
    def enable(self) -> None:
        with ddl_transaction(self.storage.get_db()) as db:
            try:
                self._enable(db)
            except sqlite3.OperationalError as e:
                if "table changes already exists" in str(e).lower():
                    return
                raise  # pragma: no cover

    @classmethod
    def _enable(cls, db: sqlite3.Connection) -> None:
        assert db.in_transaction
        for objects in SCHEMA.values():
            for object in objects.values():
                object.create(db)
        db.execute("UPDATE entries SET sequence = randomblob(16)")
        db.execute(
            """
            INSERT INTO changes
            SELECT sequence, feed, id, '', 1 FROM entries
            """
        )

    @wrap_exceptions()
    def disable(self) -> None:
        with ddl_transaction(self.storage.get_db()) as db:
            self._disable(db)

    @classmethod
    def _disable(cls, db: sqlite3.Connection) -> None:
        assert db.in_transaction
        for objects in SCHEMA.values():
            for object in objects.values():
                db.execute(f"DROP {object.type} IF EXISTS {object.name}")
        db.execute("UPDATE entries SET sequence = NULL")

    @wrap_exceptions(ENABLED_EXC)
    def get(
        self, action: Action | None = None, limit: int | None = None
    ) -> list[Change]:
        if not limit or limit > self.storage.chunk_size:
            limit = self.storage.chunk_size
        context = {'limit': limit}
        # the ORDER_BY is only used for testing; should this return a set instead?
        query = Query().SELECT('*').FROM('changes').ORDER_BY('rowid').LIMIT(':limit')
        if action:
            query.WHERE('action = :action')
            context['action'] = action.value
        rows = self.storage.get_db().execute(str(query), context)
        return list(map(change_factory, rows))

    @wrap_exceptions(ENABLED_EXC)
    def done(self, changes: list[Change]) -> None:
        if len(changes) > self.storage.chunk_size:
            raise ValueError(f"too many changes, expected <= {self.storage.chunk_size}")
        with self.storage.get_db() as db:
            for change in changes:
                db.execute(
                    """
                    DELETE FROM changes
                    WHERE (sequence, feed, id, key, action)
                        = (:sequence, :feed, :id, :key, :action)
                    """,
                    change_to_dict(change),
                )


def change_factory(row: tuple[Any, ...]) -> Change:
    sequence, feed, id, key, action = row
    resource = tuple(filter(bool, (feed, id)))
    return Change(Action(action), sequence, resource, key or None)


def change_to_dict(change: Change) -> dict[str, Any]:
    resource = change.resource_id + ('', '')
    return dict(
        sequence=change.sequence,
        feed=resource[0],
        id=resource[1],
        key=change.tag_key or '',
        action=change.action.value,
    )


SCHEMA = parse_schema("""

CREATE TABLE changes (
    sequence BLOB NOT NULL,
    feed TEXT NOT NULL,
    id TEXT NOT NULL,
    key TEXT NOT NULL,
    action INTEGER NOT NULL,

    PRIMARY KEY (sequence, feed, id, key)
);


CREATE TRIGGER changes_entry_insert
AFTER INSERT
ON entries
BEGIN
    -- SELECT print('  entry_insert', new.feed, new.id);

    UPDATE entries
        SET sequence = randomblob(16)
        WHERE (new.id, new.feed) = (id, feed);

    INSERT OR REPLACE INTO changes
        SELECT sequence, feed, id, '', 1
        FROM entries
        WHERE (feed, id) = (new.feed, new.id);
END;


-- Can't handle feed URL changes in changes_entry_update because
-- those entry updates are a consequence of ON UPDATE CASCADE,
-- which overrides the INSERT OR REPLACE used in the trigger,
-- because "conflict handling policy of the outer statement"
-- takes precedence per https://sqlite.org/lang_createtrigger.html.
-- Instead, we handle feed URL changes in changes_feed_changed.

CREATE TRIGGER changes_entry_update
AFTER UPDATE
OF title, summary, content
ON entries
WHEN
    new.id = old.id AND new.feed = old.feed AND (
        coalesce(new.title, '') != coalesce(old.title, '')
        OR coalesce(new.summary, '') != coalesce(old.summary, '')
        OR coalesce(new.content, '') != coalesce(old.content, '')
    )
BEGIN
    -- SELECT print('  entry_update', old.feed, old.id, '->', new.feed, new.id);

    INSERT OR REPLACE INTO changes
        VALUES (old.sequence, old.feed, old.id, '', 2);

    UPDATE entries
        SET sequence = randomblob(16)
        WHERE (new.id, new.feed) = (id, feed);

    INSERT OR REPLACE INTO changes
        SELECT sequence, feed, id, '', 1
        FROM entries
        WHERE (feed, id) = (new.feed, new.id);
END;


CREATE TRIGGER changes_entry_delete
AFTER DELETE
ON entries
BEGIN
    -- SELECT print('  entry_delete', old.feed, old.id);

    INSERT OR REPLACE INTO changes
        VALUES (old.sequence, old.feed, old.id, '', 2);
END;


CREATE TRIGGER changes_feed_changed
AFTER UPDATE
OF url, title, user_title
ON feeds
WHEN
    new.url != old.url
    OR coalesce(new.title, '') != coalesce(old.title, '')
    OR coalesce(new.user_title, '') != coalesce(old.user_title, '')
BEGIN
    -- SELECT print('  feed_url_change', old.url, '->', new.url);

    INSERT OR REPLACE INTO changes
        SELECT sequence, old.url, id, '', 2
        FROM entries
        WHERE feed = new.url;

    UPDATE entries
        SET sequence = randomblob(16)
        WHERE feed = new.url;

    INSERT OR REPLACE INTO changes
        SELECT sequence, feed, id, '', 1
        FROM entries
        WHERE feed = new.url;
END;


""")  # fmt: skip
