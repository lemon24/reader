"""
Homegrown SQL query builder.

Inspired by sqlitebuilder.mini;
https://sqlbuilder.readthedocs.io/en/latest/#short-manual-for-sqlbuilder-mini

See tests/test_sql_utils.py for some usage examples.

For a version of this that supports UNIONs and nested queries,
see the second prototype in https://github.com/lemon24/reader/issues/123

For a version of this that supports INSERT/UPDATE/DELETE, see
https://github.com/lemon24/reader/commit/7c97fccf61d16946176c2455be3634c5a8343e1b

"""
import collections
import functools
import textwrap
from typing import Any
from typing import Callable
from typing import Iterator
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

_T = TypeVar('_T')


_Q = TypeVar('_Q', bound='BaseQuery')
_QArg = Union[str, Tuple[str, ...]]


if TYPE_CHECKING:  # pragma: no cover
    _BQBase = collections.OrderedDict[str, List[List[str]]]
else:
    _BQBase = collections.OrderedDict


class BaseQuery(_BQBase):

    default_separators = dict(WHERE='AND', HAVING='AND')

    def add(self: _Q, keyword: str, *things: _QArg) -> _Q:
        target = self.setdefault(keyword, [])
        for maybe_thing in things:
            thing = (maybe_thing,) if isinstance(maybe_thing, str) else maybe_thing
            target.append([self._clean_up(t) for t in thing])
        return self

    def __getattr__(self: _Q, name: str) -> Callable[..., _Q]:
        # also, we must not shadow dunder methods (e.g. __deepcopy__)
        if not name.isupper():
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )
        return functools.partial(self.add, name.replace('_', ' '))

    def __str__(self) -> str:
        return ''.join(self._lines())

    def _clean_up(self, thing: str) -> str:
        return textwrap.dedent(thing.rstrip()).strip()

    def _lines(self) -> Iterator[str]:
        pairs = sorted(self.items(), key=lambda p: self._keyword_key(p[0]))

        for keyword, things in pairs:
            if not things:
                continue

            if keyword == 'SELECT' and getattr(self, 'distinct', None):
                yield 'SELECT DISTINCT\n'
            else:
                yield keyword + '\n'

            for i, maybe_thing in enumerate(things, 1):
                fmt = self._keyword_formats[len(maybe_thing)][keyword]
                name, thing = (
                    (None, *maybe_thing) if len(maybe_thing) == 1 else maybe_thing
                )

                yield self._indent(
                    fmt.format(
                        name=name, thing=thing, indented_thing=self._indent(thing),
                    )
                )

                if i < len(things):
                    yield self._get_separator(keyword)
                yield '\n'

    def _keyword_key(self, keyword: str) -> float:
        if 'JOIN' in keyword:
            keyword = 'JOIN'
        try:
            return self._keyword_order.index(keyword)
        except ValueError:
            return float('inf')

    _keyword_order = [
        'WITH',
        'SELECT',
        'FROM',
        'JOIN',
        'WHERE',
        'GROUP BY',
        'HAVING',
        'ORDER BY',
        'LIMIT',
    ]

    _keyword_formats: Mapping[int, Mapping[str, str]] = {
        1: collections.defaultdict(lambda: '{thing}'),
        2: dict(SELECT='{thing} AS {name}', WITH='{name} AS (\n{indented_thing}\n)',),
    }

    _indent = functools.partial(textwrap.indent, prefix='    ')

    def _get_separator(self, keyword: str) -> str:
        if 'JOIN' in keyword:
            return '\n' + keyword
        try:
            return ' ' + self.default_separators[keyword]
        except KeyError:
            return ','

    def SELECT(self: _Q, *things: _QArg, distinct: Optional[bool] = None) -> _Q:
        if distinct is not None:
            # TODO: HACK: this flag should be in the dict somewhere, not an attribute
            self.distinct = distinct
        return self.add('SELECT', *things)

    def SELECT_DISTINCT(self: _Q, *things: _QArg) -> _Q:
        return self.SELECT(*things, distinct=True)


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
        self.__things = [self._clean_up(t) for t in things]
        self.__desc = desc
        self.__keyword = keyword

        order = 'DESC' if desc else 'ASC'
        return self.ORDER_BY(*(f'{thing} {order}' for thing in things))

    __make_label = 'last_{}'.format

    def LIMIT(self: _SWM, *things: str, last: object = False) -> _SWM:
        self.add('LIMIT', *things)

        if not last:
            return self

        op = '<' if self.__desc else '>'
        labels = (':' + self.__make_label(i) for i in range(len(self.__things)))

        return self.add(
            self.__keyword,
            str(Query().add('(', *self.__things).add(f') {op} (', *labels)) + ')',
        )

    def extract_last(self, result: Tuple[_T, ...]) -> Optional[Tuple[_T, ...]]:
        names = [t[0] for t in self['SELECT']]
        return tuple(result[names.index(t)] for t in self.__things) or None

    def last_params(self, last: Optional[Tuple[_T, ...]]) -> Sequence[Tuple[str, _T]]:
        return [(self.__make_label(i), t) for i, t in enumerate(last or ())]


class Query(ScrollingWindowMixin, BaseQuery):
    pass
