# type: ignore
import collections
import functools
import textwrap


# TODO: integrate ScrollingWindow into a Query subclass for usability, with default noop window
# TODO: typing annotations


class Query(collections.OrderedDict):

    default_separators = dict(WHERE='AND', HAVING='AND')

    def add(self, keyword, *things):
        target = self.setdefault(keyword, [])
        for thing in things:
            if isinstance(thing, str):
                thing = (thing,)
            target.append([self._clean_up(t) for t in thing])
        return self

    def __getattr__(self, name):
        # also, we must not shadow dunder methods (e.g. __deepcopy__)
        if not name.isupper():
            return super().__getattr__(name)
        return functools.partial(self.add, name.replace('_', ' '))

    def __str__(self, end=';\n'):
        return ''.join(self._lines()) + end

    def _clean_up(self, thing):
        return textwrap.dedent(thing.rstrip()).strip()

    def _lines(self):
        pairs = sorted(self.items(), key=lambda p: self._keyword_key(p[0]))

        for keyword, things in pairs:
            if not things:
                continue

            yield keyword + '\n'

            for i, thing in enumerate(things, 1):
                fmt = self._keyword_formats[len(thing)][keyword]
                name, thing = (None, *thing) if len(thing) == 1 else thing

                yield self._indent(
                    fmt.format(
                        name=name, thing=thing, indented_thing=self._indent(thing),
                    )
                )

                if i < len(things):
                    yield self._get_separator(keyword)
                yield '\n'

    def _keyword_key(self, keyword):
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

    _keyword_formats = {
        1: collections.defaultdict(lambda: '{thing}'),
        2: dict(SELECT='{thing} AS {name}', WITH='{name} AS (\n{indented_thing}\n)',),
    }

    _indent = functools.partial(textwrap.indent, prefix='    ')

    def _get_separator(self, keyword):
        if 'JOIN' in keyword:
            return '\n' + keyword
        try:
            return ' ' + self.default_separators[keyword]
        except KeyError:
            return ','


class ScrollingWindow:
    def __init__(self, query, *things, desc=False, keyword='WHERE'):
        self._query = query
        self._things = things = [self._query._clean_up(t) for t in things]
        self._desc = desc
        self._keyword = keyword

        order = 'DESC' if desc else 'ASC'
        self._query.ORDER_BY(*(f'{thing} {order}' for thing in things))

    _make_label = 'last_{}'.format

    def LIMIT(self, *things, last):
        self._query.LIMIT(*things)

        if not last:
            return

        op = '<' if self._desc else '>'
        labels = (':' + self._make_label(i) for i in range(len(self._things)))

        getattr(self._query, self._keyword)(
            Query().add('(', *self._things).add(f') {op} (', *labels).__str__(end=')')
        )

    def extract_last(self, result):
        names = [t[0] for t in self._query['SELECT']]
        return tuple(result[names.index(t)] for t in self._things) or None

    def last_params(self, last):
        return [(self._make_label(i), t) for i, t in enumerate(last or ())]
