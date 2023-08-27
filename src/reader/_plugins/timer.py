import inspect
from collections.abc import Collection
from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from functools import wraps
from time import perf_counter


@dataclass(slots=True)
class Call:
    name: str = ''
    time: float = 0
    start: float = 0

    def __enter__(self):
        self.start = perf_counter()
        return self

    def __exit__(self, *_):
        self.time += perf_counter() - self.start


# a previous version of this tried to build a tree of calls
# pushing to a stack at the beginning of the timer() wrapper and
# popping at the end of that or the end of timed_iter();
# this approach sometimes resulted in wrong nesting
# when an iterable was consumed far from where it was created,
# so I removed the tree of calls feature entirely.


@dataclass
class Timer:
    calls: list[Call] | None = None
    entered: int = 0

    nc = nullcontext()

    def call(self, name):
        if self.calls is None:
            return self.nc
        call = Call(name)
        self.calls.append(call)
        return call

    def timed(self, fn, prefix=''):
        name = f'{prefix}{fn.__name__}'

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with self.call(name) as call:
                rv = fn(*args, **kwargs)
            if call is None:
                return rv
            if not isinstance(rv, Iterable) or isinstance(rv, Collection):
                return rv
            return self.timed_iter(rv, call)

        return wrapper

    def timed_iter(self, it, call):
        with call:
            it = iter(it)
        while True:
            with call:
                try:
                    rv = next(it)
                except StopIteration:
                    break
            yield rv

    def decorate(self, obj, exclude=()):
        prefix = f'{type(obj).__name__}.'
        for name, member in inspect.getmembers(obj, callable):
            if name in exclude:
                continue
            if name.startswith('_'):
                continue
            if not hasattr(member, '__name__'):
                continue
            setattr(obj, name, self.timed(member, prefix=prefix))

    def enable(self):
        self.calls = []

    def disable(self, *args):
        self.calls = None

    def format_stats(self, tablefmt='plain'):
        if not self.calls:
            return None

        times_by_name = {}
        for call in self.calls:
            times_by_name.setdefault(call.name, []).append(call.time)

        def avg(times):
            return sum(times) / len(times)

        fns = [len, sum, min, avg, max]

        headers = [''] + [f.__name__ for f in fns]
        rows = []
        for name, times in sorted(times_by_name.items()):
            row = [name]
            row.extend(f(times) for f in fns)
            rows.append(row)

        from tabulate import tabulate

        return tabulate(
            rows, headers, tablefmt=tablefmt, numalign='decimal', floatfmt='.3f'
        )

    def total(self, prefix=''):
        return sum(c.time for c in self.calls or () if c.name.startswith(prefix))


def init_reader(reader):
    reader.timer = timer = Timer()
    timer.decorate(
        reader,
        exclude={
            # delegate to other Reader methods,
            # excluded so total() doesn't count them twice
            'get_feed',
            'update_feeds',
            'update_feed',
            'get_entry',
            'mark_entry_as_read',
            'mark_entry_as_unread',
            'mark_entry_as_important',
            'mark_entry_as_unimportant',
            # just string manipulation, don't need timing
            'make_reader_reserved_name',
            'make_plugin_reserved_name',
        },
    )
    # not bothering with methods that delegate to methods for these
    timer.decorate(reader._storage)
    timer.decorate(reader._search)


if __name__ == '__main__':
    from reader import make_reader

    reader = make_reader('db.sqlite')
    init_reader(reader)

    reader.timer.enable()

    start = perf_counter()
    for _ in reader.get_feeds():
        pass
    for _ in reader.get_entries(limit=1000):
        pass
    for _ in reader.search_entries('mars'):
        pass
    end = perf_counter()

    print(f"{end-start:1.6f}")
    print(f"{reader.timer.total('Reader.'):1.6f}")
    print(reader.timer.format_stats())
    print(reader.make_reader_reserved_name('ok'))
