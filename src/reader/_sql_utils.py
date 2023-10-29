"""
Homegrown SQL query builder.

See tests/test_sql_utils.py for some usage examples.

I've written at length about it elsewhere:

https://death.andgravity.com/query-builder
    Introduction to the series, has more examples.

https://death.andgravity.com/query-builder-why
    "Why use an SQL query builder in the first place?"
    The problem we're trying to solve.

https://death.andgravity.com/own-query-builder
    "Why I wrote my own SQL query builder"
    High-level design decisions, in the context of reader.

https://death.andgravity.com/query-builder-how
    Code walk-through / tutorial.
    Low-level design decisions.
    How to implement: INSERT/UPDATE/DELETE, subqueries, UNION/...

"""
from __future__ import annotations

import functools
import textwrap
from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterable
from typing import Any
from typing import cast
from typing import NamedTuple
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

if TYPE_CHECKING:  # pragma: no cover
    from typing_extensions import Self


_T = TypeVar('_T')
_U = TypeVar('_U')


_QArg = Union[str, tuple[str, ...]]


class _Thing(NamedTuple):
    value: str
    alias: str = ''
    keyword: str = ''
    is_subquery: bool = False

    @classmethod
    def from_arg(cls, arg: _QArg, **kwargs: Any) -> _Thing:
        if isinstance(arg, str):
            alias, value = '', arg
        elif len(arg) == 2:
            alias, value = arg
        else:  # pragma: no cover
            raise ValueError(f"invalid arg: {arg!r}")
        return cls(_clean_up(value), _clean_up(alias), **kwargs)


class _FlagList(list[_T]):
    flag: str = ''


def _clean_up(thing: str) -> str:
    return textwrap.dedent(thing.rstrip()).strip()


class BaseQuery:
    keywords = [
        'WITH',
        'SELECT',
        'FROM',
        'WHERE',
        'GROUP BY',
        'HAVING',
        'ORDER BY',
        'LIMIT',
    ]

    separators: dict[str, str] = dict(WHERE='AND', HAVING='AND')
    default_separator = ','

    formats: tuple[dict[str, str], ...] = (
        defaultdict(lambda: '{value}'),
        defaultdict(lambda: '{value} AS {alias}', WITH='{alias} AS {value}'),
    )

    subquery_keywords = {'WITH'}
    fake_keywords = dict(JOIN='FROM')
    flag_keywords = dict(SELECT={'DISTINCT', 'ALL'})

    def __init__(
        self,
        data: dict[str, Iterable[_QArg]] | None = None,
        separators: dict[str, str] | None = None,
    ) -> None:
        self.data: dict[str, _FlagList[_Thing]] = {}
        if data is None:
            data = dict.fromkeys(self.keywords, ())
        for keyword, args in data.items():
            self.data[keyword] = _FlagList()
            self.add(keyword, *args)

        if separators is not None:
            self.separators = separators

    def add(self, keyword: str, *args: _QArg) -> Self:
        keyword, fake_keyword = self._resolve_fakes(keyword)
        keyword, flag = self._resolve_flags(keyword)
        target = self.data[keyword]

        if flag:
            if target.flag:  # pragma: no cover
                raise ValueError(f"{keyword} already has flag: {flag!r}")
            target.flag = flag

        kwargs: dict[str, Any] = {}
        if fake_keyword:
            kwargs.update(keyword=fake_keyword)
        if keyword in self.subquery_keywords:
            kwargs.update(is_subquery=True)

        for arg in args:
            target.append(_Thing.from_arg(arg, **kwargs))

        return self

    def _resolve_fakes(self, keyword: str) -> tuple[str, str]:
        for part, real in self.fake_keywords.items():
            if part in keyword:
                return real, keyword
        return keyword, ''

    def _resolve_flags(self, keyword: str) -> tuple[str, str]:
        prefix, _, flag = keyword.partition(' ')
        if prefix in self.flag_keywords:
            if flag and flag not in self.flag_keywords[prefix]:
                raise ValueError(f"invalid flag for {prefix}: {flag!r}")
            return prefix, flag
        return keyword, ''

    def __getattr__(self, name: str) -> Callable[..., Self]:
        # conveniently, avoids shadowing dunder methods (e.g. __deepcopy__)
        if not name.isupper():
            return getattr(super(), name)  # type: ignore
        return functools.partial(self.add, name.replace('_', ' '))

    def __str__(self) -> str:
        return ''.join(self._lines())

    def _lines(self) -> Iterable[str]:
        for keyword, things in self.data.items():
            if not things:
                continue

            if things.flag:
                yield f'{keyword} {things.flag}\n'
            else:
                yield f'{keyword}\n'

            grouped: tuple[list[_Thing], ...] = ([], [])
            for thing in things:
                grouped[bool(thing.keyword)].append(thing)
            for group in grouped:
                yield from self._lines_keyword(keyword, group)

    def _lines_keyword(self, keyword: str, things: list[_Thing]) -> Iterable[str]:
        for i, thing in enumerate(things):
            last = i + 1 == len(things)

            if thing.keyword:
                yield thing.keyword + '\n'

            format = self.formats[bool(thing.alias)][keyword]
            value = thing.value
            if thing.is_subquery:
                value = f'(\n{self._indent(value)}\n)'
            yield self._indent(format.format(value=value, alias=thing.alias))

            if not last and not thing.keyword:
                try:
                    yield ' ' + self.separators[keyword]
                except KeyError:
                    yield self.default_separator

            yield '\n'

    _indent = functools.partial(textwrap.indent, prefix='    ')


if TYPE_CHECKING:  # pragma: no cover
    _SWMBase = BaseQuery
else:
    _SWMBase = object

_SWM = TypeVar('_SWM', bound='ScrollingWindowMixin')


class ScrollingWindowMixin(_SWMBase):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.scrolling_window_order_by()

    def scrolling_window_order_by(
        self, *things: str, desc: bool = False, keyword: str = 'WHERE'
    ) -> Self:
        self.__things = [_clean_up(t) for t in things]
        self.__desc = desc
        self.__keyword = keyword

        order = 'DESC' if desc else 'ASC'
        return self.ORDER_BY(*(f'{thing} {order}' for thing in things))

    def extract_last(self, result: tuple[_T, ...]) -> tuple[_T, ...] | None:
        names = [t.alias or t.value for t in self.data['SELECT']]
        return tuple(result[names.index(t)] for t in self.__things) or None

    def add_last(self, last: tuple[_T, ...] | None) -> list[tuple[str, _T]]:
        self.__add_last()
        return self.__last_params(last)

    __make_label = 'last_{}'.format

    def __add_last(self) -> None:
        op = '<' if self.__desc else '>'
        labels = (':' + self.__make_label(i) for i in range(len(self.__things)))
        comparison = BaseQuery({'(': self.__things, f') {op} (': labels, ')': ['']})
        self.add(self.__keyword, str(comparison).rstrip())

    def __last_params(self, last: tuple[_T, ...] | None) -> list[tuple[str, _T]]:
        return [(self.__make_label(i), t) for i, t in enumerate(last or ())]


class Query(ScrollingWindowMixin, BaseQuery):
    pass


if TYPE_CHECKING:  # pragma: no cover
    import sqlite3


def paginated_query(
    db: sqlite3.Connection,
    query: Query,
    params: dict[str, Any] = {},  # noqa: B006
    chunk_size: int | None = 0,
    last: _U | None = None,
    row_factory: Callable[[tuple[Any, ...]], _T] | None = None,
) -> Iterable[tuple[_T, _U]]:
    params = dict(params)

    if chunk_size:
        query.LIMIT(":chunk_size")
        params['chunk_size'] = chunk_size
    if last:
        params.update(query.add_last(last))  # type: ignore

    rv = (
        (row_factory(t) if row_factory else t, cast(_U, query.extract_last(t)))
        for t in db.execute(str(query), params)
    )

    # Consume the result to avoid blocking the database,
    # but only if the query is actually paginated
    # (we may need the pass-through for performance).
    if chunk_size:
        return iter(list(rv))

    return rv
