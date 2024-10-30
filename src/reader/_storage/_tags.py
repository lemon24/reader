from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from functools import partial
from typing import Any
from typing import NamedTuple
from typing import overload
from typing import TYPE_CHECKING

from .._types import TagFilter
from ..exceptions import EntryNotFoundError
from ..exceptions import FeedNotFoundError
from ..exceptions import ReaderError
from ..exceptions import TagNotFoundError
from ..types import AnyResourceId
from ..types import JSONType
from ..types import MISSING
from ..types import MissingType
from ..types import ResourceId
from ._base import wrap_exceptions
from ._sql_utils import BaseQuery
from ._sql_utils import Query
from ._sqlite_utils import rowcount_exactly_one


if TYPE_CHECKING:  # pragma: no cover
    from ._base import StorageBase
else:
    StorageBase = object


class TagsMixin(StorageBase):
    def get_tags(
        self,
        resource_id: AnyResourceId,
        key: str | None = None,
    ) -> Iterable[tuple[str, JSONType]]:
        def make_query() -> tuple[Query, dict[str, Any]]:
            query = Query().SELECT("key")
            context: dict[str, Any] = dict()

            if resource_id is not None:
                info = SCHEMA_INFO[len(resource_id)]
                query.FROM(f"{info.table_prefix}tags")

                if not any(p is None for p in resource_id):
                    query.SELECT("value")
                    for column in info.id_columns:
                        query.WHERE(f"{column} = :{column}")
                    context.update(zip(info.id_columns, resource_id, strict=True))
                else:
                    query.SELECT_DISTINCT("'null'")

            else:
                union = '\nUNION\n'.join(
                    f"SELECT key, value FROM {i.table_prefix}tags"
                    for i in SCHEMA_INFO.values()
                )
                query.with_('tags', union).FROM('tags')
                query.SELECT_DISTINCT("'null'")

            if key is not None:
                query.WHERE("key = :key")
                context.update(key=key)

            query.scrolling_window_order_by("key")

            return query, context

        def row_factory(row: tuple[Any, ...]) -> tuple[str, JSONType]:
            key, value, *_ = row
            return key, json.loads(value)

        return self.paginated_query(make_query, row_factory=row_factory)

    @overload
    def set_tag(self, resource_id: ResourceId, key: str) -> None:  # pragma: no cover
        ...

    @overload
    def set_tag(
        self, resource_id: ResourceId, key: str, value: JSONType
    ) -> None:  # pragma: no cover
        ...

    @wrap_exceptions()
    def set_tag(
        self,
        resource_id: ResourceId,
        key: str,
        value: MissingType | JSONType = MISSING,
    ) -> None:
        info = SCHEMA_INFO[len(resource_id)]

        params = dict(zip(info.id_columns, resource_id, strict=True), key=key)

        id_columns = info.id_columns + ('key',)
        id_columns_str = ', '.join(id_columns)
        id_values_str = ', '.join(f':{c}' for c in id_columns)

        if value is not MISSING:
            value_str = ':value'
            params.update(value=json.dumps(value))
        else:
            value_str = f"""
                coalesce((
                    SELECT value FROM {info.table_prefix}tags
                    WHERE (
                        {id_columns_str}
                    ) == (
                        {id_values_str}
                    )
                ), 'null')
            """

        query = f"""
            INSERT OR REPLACE INTO {info.table_prefix}tags (
                {id_columns_str}, value
            ) VALUES (
                {id_values_str}, {value_str}
            )
        """

        with self.get_db() as db:
            try:
                db.execute(query, params)
            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                if "foreign key constraint failed" in e_msg:
                    raise info.not_found_exc(*resource_id) from None
                raise  # pragma: no cover

    @wrap_exceptions()
    def delete_tag(self, resource_id: ResourceId, key: str) -> None:
        info = SCHEMA_INFO[len(resource_id)]

        columns = info.id_columns + ('key',)
        query = f"""
            DELETE FROM {info.table_prefix}tags
            WHERE (
                {', '.join(columns)}
            ) = (
                {', '.join('?' for _ in columns)}
            )
        """
        params = resource_id + (key,)

        with self.get_db() as db:
            cursor = db.execute(query, params)
        rowcount_exactly_one(cursor, lambda: TagNotFoundError(resource_id, key))


class SchemaInfo(NamedTuple):
    table_prefix: str
    id_columns: tuple[str, ...]
    not_found_exc: type[ReaderError]


SCHEMA_INFO = {
    0: SchemaInfo('global_', (), ReaderError),
    1: SchemaInfo('feed_', ('feed',), FeedNotFoundError),
    2: SchemaInfo('entry_', ('feed', 'id'), EntryNotFoundError),
}


def feed_tags_filter(
    query: Query, tags: TagFilter, url_column: str, keyword: str = 'WHERE'
) -> dict[str, str]:
    if not tags:
        return {}

    ctes = {
        '__feed_tags': f"SELECT key FROM feed_tags WHERE feed = {url_column}",
        '__feed_tags_count': f"SELECT count(key) FROM feed_tags WHERE feed = {url_column}",
    }
    context, filters = tags_filter(tags, *ctes)

    apply_tags_filter(query, keyword, ctes, filters)

    return context


def entry_tags_filter(
    query: Query, tags: TagFilter, keyword: str = 'WHERE'
) -> dict[str, str]:
    if not tags:
        return {}

    ctes = {
        '__entry_tags': """
            SELECT key FROM entry_tags
            WHERE (id, feed) = (entries.id, entries.feed)
            """,
        '__entry_tags_count': """
            SELECT count(key) FROM entry_tags
            WHERE (id, feed) = (entries.id, entries.feed)
            """,
    }
    context, filters = tags_filter(tags, *ctes)

    apply_tags_filter(query, keyword, ctes, filters)

    return context


def apply_tags_filter(
    query: Query, keyword: str, ctes: dict[str, str], filters: list[str]
) -> None:
    for cte_name, cte in ctes.items():
        query.with_(cte_name, cte)
    add = getattr(query, keyword)
    for filter in filters:
        add(filter)


def tags_filter(
    tags: TagFilter, tags_cte: str, tags_count_cte: str
) -> tuple[dict[str, str], list[str]]:
    context = {}
    filters = []
    next_tag_id = 0

    for or_tags in tags:
        query = BaseQuery({'(': [], ')': ['']}, {'(': 'OR'})
        add = partial(query.add, '(')

        for maybe_tag in or_tags:
            if isinstance(maybe_tag, bool):
                cond = f"(SELECT * FROM {tags_count_cte})"
                if not maybe_tag:
                    cond = f"NOT {cond}"
                add(cond)
                continue

            is_negation, tag = maybe_tag
            tag_name = f'{tags_cte}_{next_tag_id}'
            next_tag_id += 1
            context[tag_name] = tag
            add(f":{tag_name} {'NOT' if is_negation else ''} IN {tags_cte}")

        filters.append(str(query))

    return context, filters
