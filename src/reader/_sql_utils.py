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
from typing import Iterable
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


class Thing(str):
    alias: str = ''
    keyword: str = ''

    @classmethod
    def from_arg(cls, arg: _QArg, keyword: str = '') -> 'Thing':
        if isinstance(arg, str):
            rv = cls(_clean_up(arg))
        else:
            if len(arg) != 2:  # pragma: no cover
                raise ValueError(f"invalid arg: {arg!r}")
            alias, value = arg
            rv = cls(_clean_up(value))
            rv.alias = _clean_up(alias)
        if keyword is not None:
            rv.keyword = keyword
        return rv


class FlagList(List[_T]):
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

    fake_keywords = dict(JOIN='FROM')
    flag_keywords = dict(SELECT={'DISTINCT', 'ALL'})

    formats: Tuple[Mapping[str, str], ...] = (
        collections.defaultdict(lambda: '{value}'),
        dict(
            SELECT='{value} AS {alias}',
            WITH='{alias} AS (\n{indented}\n)',
        ),
    )

    separators = dict(WHERE='AND', HAVING='AND')
    default_separator = ','

    def __init__(self, data: Optional[Mapping[str, Iterable[_QArg]]] = None) -> None:
        if data is None:
            data = dict.fromkeys(self.keywords, ())
        self.data: Mapping[str, FlagList[Thing]] = {
            keyword: FlagList(Thing.from_arg(t) for t in things)
            for keyword, things in data.items()
        }

    def add(self: _Q, keyword: str, *args: _QArg) -> _Q:
        keyword, fake_keyword = self._resolve_fakes(keyword)
        keyword, flag = self._resolve_flags(keyword)
        target = self.data[keyword]

        if flag:
            if target.flag:  # pragma: no cover
                raise ValueError(f"keyword {keyword} already has flag: {flag!r}")
            target.flag = flag

        for arg in args:
            target.append(Thing.from_arg(arg, keyword=fake_keyword))

        return self

    def _resolve_fakes(self, keyword: str) -> Tuple[str, str]:
        for fake_part, real in self.fake_keywords.items():
            if fake_part in keyword:
                return real, keyword
        return keyword, ''

    def _resolve_flags(self, keyword: str) -> Tuple[str, str]:
        prefix, _, flag = keyword.partition(' ')
        if prefix in self.flag_keywords:
            if flag and flag not in self.flag_keywords[prefix]:
                raise ValueError(f"invalid flag for keyword {prefix}: {flag!r}")
            return prefix, flag
        return keyword, ''

    def __getattr__(self: _Q, name: str) -> Callable[..., _Q]:
        # also, we must not shadow dunder methods (e.g. __deepcopy__)
        if not name.isupper():
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )
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

            grouped: Tuple[List[Thing], ...] = ([], [])
            for thing in things:
                grouped[bool(thing.keyword)].append(thing)
            for group in grouped:
                yield from self._lines_keyword(keyword, group)

    def _lines_keyword(self, keyword: str, things: Sequence[Thing]) -> Iterable[str]:
        for i, thing in enumerate(things):
            last = i + 1 == len(things)

            if thing.keyword:
                yield thing.keyword + '\n'

            fmt = self.formats[bool(thing.alias)][keyword]
            yield self._indent(
                fmt.format(value=thing, alias=thing.alias, indented=self._indent(thing))
            )

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

    __make_label = 'last_{}'.format

    def add_last(self: _SWM) -> _SWM:
        op = '<' if self.__desc else '>'
        labels = (':' + self.__make_label(i) for i in range(len(self.__things)))
        comparison = BaseQuery({'(': self.__things, f') {op} (': labels, ')': ['']})
        return self.add(self.__keyword, str(comparison).rstrip())

    def extract_last(self, result: Tuple[_T, ...]) -> Optional[Tuple[_T, ...]]:
        names = [t.alias or t for t in self.data['SELECT']]
        return tuple(result[names.index(t)] for t in self.__things) or None

    def last_params(self, last: Optional[Tuple[_T, ...]]) -> Sequence[Tuple[str, _T]]:
        return [(self.__make_label(i), t) for i, t in enumerate(last or ())]


class Query(ScrollingWindowMixin, BaseQuery):
    pass
