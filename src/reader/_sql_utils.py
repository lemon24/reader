# type: ignore
import collections
import functools
import textwrap


# TODO: strip out UNION support, and maybe fancy WITH support;
# aside from error handling, coverage should be 100% from the existing code using it
# TODO: integrate ScrollingWindow into a Query subclass for usability, with default noop window
# TODO: add ScrollingWindow method to transform last to params
# TODO: typing annotations
# TODO: add some basic tests


class Query(collections.OrderedDict):  # pragma: no cover

    indent_prefix = '    '
    default_separators = dict(WHERE='AND', HAVING='AND')

    _compound_keywords = ['UNION', 'UNION ALL', 'INTERSECT', 'EXCEPT']

    _keyword_order = [
        '',
        'COMPOUND',
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

    def _keyword_key(self, keyword):
        if 'JOIN' in keyword:
            keyword = 'JOIN'
        elif keyword in self._compound_keywords:
            keyword = 'COMPOUND'
        try:
            return self._keyword_order.index(keyword)
        except ValueError:
            return float('inf')

    _keyword_formats = {
        1: collections.defaultdict(lambda: '{thing}'),
        2: dict(SELECT='{thing} AS {name}', WITH='{name} AS (\n{indented_thing}\n)',),
    }

    def __getattr__(self, name):
        keyword = name.replace('_', ' ').upper()
        if keyword in self._compound_keywords:
            self = type(self)()._add('', self)
        return functools.partial(self._add, keyword)

    def _add(self, keyword, *things):
        target = self.setdefault(keyword, [])
        for thing in things:
            if not isinstance(thing, (tuple, list)):
                thing = (thing,)
            target.append([self._clean_up(t) for t in thing])
        return self

    def _clean_up(self, thing):
        if not isinstance(thing, str):
            return thing
        return textwrap.dedent(thing.rstrip()).strip()

    def __str__(self, complete=True, end=';\n'):
        text = ''.join(self._lines())
        if complete:
            return text + end
        return text.rstrip()

    def _lines(self):
        pairs = sorted(self.items(), key=lambda p: self._keyword_key(p[0]))

        for keyword, things in pairs:
            if keyword:
                yield keyword + '\n'

            for i, thing in enumerate(things, 1):
                fmt = self._keyword_formats[len(thing)][keyword]
                name, thing = (None, *thing) if len(thing) == 1 else thing

                if keyword and keyword not in self._compound_keywords:
                    if isinstance(thing, Query):
                        thing = thing.__str__(complete=False)
                    yield self._indent(
                        fmt.format_map(
                            dict(
                                name=name,
                                thing=thing,
                                indented_thing=self._indent(thing),
                            )
                        )
                    )
                    if i < len(things):
                        yield self._get_separator(keyword)
                    yield '\n'

                else:
                    if isinstance(thing, Query):
                        yield from thing._lines()
                    else:
                        yield fmt.format_map(dict(name=name, thing=thing))
                        yield '\n'
                    if i < len(things):
                        yield keyword
                        yield '\n'

    def _indent(self, text):
        return textwrap.indent(text, self.indent_prefix)

    def _get_separator(self, keyword):
        if 'JOIN' in keyword:
            return '\n' + keyword
        separator = self.default_separators.get(keyword)
        if separator:
            return ' ' + separator
        return ','


class ScrollingWindow:
    def __init__(self, query, *things, desc=False, keyword='WHERE'):
        self._query = query
        self._things = things = self._query._clean_up(things)
        self._desc = desc
        self._keyword = keyword

        order = 'DESC' if desc else 'ASC'
        self._query.ORDER_BY(*(f'{thing} {order}' for thing in things))

    _make_label = 'last_{}'.format

    def LIMIT(self, *things, last):
        self._query.LIMIT(things)

        if not last:
            return

        op = '<' if self._desc else '>'
        labels = (':' + self._make_label(i) for i in range(len(self._things)))

        getattr(self._query, self._keyword)(
            Query()._add('(', *self._things)._add(f') {op} (', *labels).__str__(end=')')
        )

    def extract_last(self, result):
        names = [t[0] for t in self._query['SELECT']]
        return [
            (self._make_label(i), result[names.index(thing)])
            for i, thing in enumerate(self._things)
        ]
