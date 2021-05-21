"""
Homegrown SQL query builder.

Inspired by sqlitebuilder.mini;
https://sqlbuilder.readthedocs.io/en/latest/#short-manual-for-sqlbuilder-mini

See tests/test_sql_utils.py for some usage examples.

---

For a version of this that supports UNIONs see the second prototype in
https://github.com/lemon24/reader/issues/123#issuecomment-624045621

---

For a version of this that supports INSERT/UPDATE/DELETE, see
https://github.com/lemon24/reader/commit/7c97fccf61d16946176c2455be3634c5a8343e1b

The way things work now has changed slightly;
we'd probably make them flag keywords now.

To make VALUES bake in the parentheses, we just need to set:

    query.formats[0]['VALUES'] = '({value})'

That's to add one values tuple at a time. To add one column, we could do this:

* output keyword even if called with no args
* add(..., flag=...), and allow arbitrary flags;
  INSERT_INTO('x', 'y', flag='table') -> flag is "INTO table"
* parens_keywords = {'INSERT', 'VALUES'};
  different than subquery_keywords because it applies once to the whole set

---

To support marking arbitrary things as subqueries,
add a signalling tuple and a helper function:

    class _Subquery(tuple): pass

    def Subquery(*args) -> _Subquery:
        return _Subquery(args)  # from_arg() has to support 1-tuples

Then, in from_arg(), if arg is a _Subquery, set is_subquery.

Usage looks like this:

    Query().FROM(
        Subquery('alias', 'subquery'),
        ('alias', 'not subquery'),
    )

Alternatively, add an is_subquery kwarg to add():

    query = Query().FROM(('alias', 'subquery'), is_subquery=True)
    query.FROM(('alias', 'not subquery'))

---

To support using Queries as arguments directly,
without having to convert them to strings first,
allow _Thing.value to be a Query (and support it in);
then, in _lines_keyword(), convert queries to str and override is_subquery.

"""
import functools
import textwrap
from collections import defaultdict
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

_T = TypeVar('_T')
_U = TypeVar('_U')


_Q = TypeVar('_Q', bound='BaseQuery')
_QArg = Union[str, Tuple[str, ...]]


class _Thing(NamedTuple):
    value: str
    alias: str = ''
    keyword: str = ''
    is_subquery: bool = False

    @classmethod
    def from_arg(cls, arg: _QArg, **kwargs: Any) -> '_Thing':
        if isinstance(arg, str):
            alias, value = '', arg
        elif len(arg) == 2:
            alias, value = arg
        else:  # pragma: no cover
            raise ValueError(f"invalid arg: {arg!r}")
        return cls(_clean_up(value), _clean_up(alias), **kwargs)


class _FlagList(List[_T]):
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

    separators: Mapping[str, str] = dict(WHERE='AND', HAVING='AND')
    default_separator = ','

    formats: Tuple[Mapping[str, str], ...] = (
        defaultdict(lambda: '{value}'),
        defaultdict(lambda: '{value} AS {alias}', WITH='{alias} AS {value}'),
    )

    subquery_keywords = {'WITH'}
    fake_keywords = dict(JOIN='FROM')
    flag_keywords = dict(SELECT={'DISTINCT', 'ALL'})

    def __init__(
        self,
        data: Optional[Mapping[str, Iterable[_QArg]]] = None,
        separators: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.data: Mapping[str, _FlagList[_Thing]] = {}
        if data is None:
            data = dict.fromkeys(self.keywords, ())
        for keyword, args in data.items():
            self.data[keyword] = _FlagList()
            self.add(keyword, *args)

        if separators is not None:
            self.separators = separators

    def add(self: _Q, keyword: str, *args: _QArg) -> _Q:
        keyword, fake_keyword = self._resolve_fakes(keyword)
        keyword, flag = self._resolve_flags(keyword)
        target = self.data[keyword]

        if flag:
            if target.flag:  # pragma: no cover
                raise ValueError(f"{keyword} already has flag: {flag!r}")
            target.flag = flag

        kwargs: Dict[str, Any] = {}
        if fake_keyword:
            kwargs.update(keyword=fake_keyword)
        if keyword in self.subquery_keywords:
            kwargs.update(is_subquery=True)

        for arg in args:
            target.append(_Thing.from_arg(arg, **kwargs))

        return self

    def _resolve_fakes(self, keyword: str) -> Tuple[str, str]:
        for part, real in self.fake_keywords.items():
            if part in keyword:
                return real, keyword
        return keyword, ''

    def _resolve_flags(self, keyword: str) -> Tuple[str, str]:
        prefix, _, flag = keyword.partition(' ')
        if prefix in self.flag_keywords:
            if flag and flag not in self.flag_keywords[prefix]:
                raise ValueError(f"invalid flag for {prefix}: {flag!r}")
            return prefix, flag
        return keyword, ''

    def __getattr__(self: _Q, name: str) -> Callable[..., _Q]:
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

            grouped: Tuple[List[_Thing], ...] = ([], [])
            for thing in things:
                grouped[bool(thing.keyword)].append(thing)
            for group in grouped:
                yield from self._lines_keyword(keyword, group)

    def _lines_keyword(self, keyword: str, things: Sequence[_Thing]) -> Iterable[str]:
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
        self: _SWM, *things: str, desc: bool = False, keyword: str = 'WHERE'
    ) -> _SWM:
        self.__things = [_clean_up(t) for t in things]
        self.__desc = desc
        self.__keyword = keyword

        order = 'DESC' if desc else 'ASC'
        return self.ORDER_BY(*(f'{thing} {order}' for thing in things))

    def extract_last(self, result: Tuple[_T, ...]) -> Optional[Tuple[_T, ...]]:
        names = [t.alias or t.value for t in self.data['SELECT']]
        return tuple(result[names.index(t)] for t in self.__things) or None

    def add_last(self, last: Optional[Tuple[_T, ...]]) -> Sequence[Tuple[str, _T]]:
        self.__add_last()
        return self.__last_params(last)

    __make_label = 'last_{}'.format

    def __add_last(self: _SWM) -> None:
        op = '<' if self.__desc else '>'
        labels = (':' + self.__make_label(i) for i in range(len(self.__things)))
        comparison = BaseQuery({'(': self.__things, f') {op} (': labels, ')': ['']})
        self.add(self.__keyword, str(comparison).rstrip())

    def __last_params(self, last: Optional[Tuple[_T, ...]]) -> Sequence[Tuple[str, _T]]:
        return [(self.__make_label(i), t) for i, t in enumerate(last or ())]


class Query(ScrollingWindowMixin, BaseQuery):
    pass


if TYPE_CHECKING:  # pragma: no cover
    import sqlite3


def paginated_query(
    db: 'sqlite3.Connection',
    query: Query,
    params: Dict[str, Any] = {},  # noqa: B006
    chunk_size: Optional[int] = 0,
    last: Optional[_U] = None,
    row_factory: Optional[Callable[[Tuple[Any, ...]], _T]] = None,
) -> Iterator[Tuple[_T, _U]]:

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
