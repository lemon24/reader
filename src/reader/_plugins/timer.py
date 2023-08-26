import inspect
from dataclasses import dataclass
from dataclasses import field
from functools import wraps
from time import perf_counter


@dataclass(slots=True)
class Call:
    name: str = ''
    time: float = 0
    calls: list = field(default_factory=list)

    @property
    def total(self):
        return sum(c.time for c in self.calls)

    def format_tree(self):
        header = f"{self.total:.6f}\n"
        t_width = len(header.strip())

        def _format_tree(calls=self.calls, level=1):
            indent = '  ' * level
            for call in calls:
                yield f"{call.time:{t_width}.6f}{indent}{call.name}\n"
                yield from _format_tree(call.calls, level + 1)

        lines = [header]
        lines.extend(_format_tree())
        return ''.join(lines).rstrip()

    def format_stats(self, tablefmt='plain'):
        times_by_name = {}

        def walk(calls=self.calls):
            for call in calls:
                times_by_name.setdefault(call.name, []).append(call.time)
                walk(call.calls)

        walk()

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


@dataclass
class Timer:
    stack: list[Call] | None = None
    entered: int = 0

    def push(self, name):
        if self.stack is None:
            return
        call = Call(name)
        self.stack[-1].calls.append(call)
        self.stack.append(call)

    def pop(self, name, time):
        if self.stack is None:
            return
        call = self.stack.pop()
        assert name == call.name
        call.time = time

    def __enter__(self):
        # not thread safe
        if not self.entered:
            self.stack = [Call()]
        self.entered += 1
        return self.stack[0]

    def __exit__(self, *args):
        assert self.entered > 0
        self.entered -= 1
        if not self.entered:
            self.stack = None


def timed(fn, push, pop):
    name = fn.__name__

    @wraps(fn)
    def wrapper(*args, **kwargs):
        push(name)
        start = perf_counter()
        try:
            rv = fn(*args, **kwargs)
        except BaseException:
            pop(name, perf_counter() - start)
            raise
        else:
            time = perf_counter() - start
            if not hasattr(rv, '__iter__'):
                pop(name, time)
                return rv
            else:
                return timed_iter(rv, time, name, pop)

    return wrapper


def timed_iter(it, time, name, pop):
    start = perf_counter()
    it = iter(it)
    time += perf_counter() - start
    while True:
        start = perf_counter()
        try:
            rv = next(it)
        except StopIteration:
            time += perf_counter() - start
            pop(name, time)
            break
        else:
            time += perf_counter() - start
            yield rv


def decorate(obj, push, pop, exclude=()):
    obj_name = type(obj).__name__

    def push_prefixed(name):
        push(f'{obj_name}.{name}')

    def pop_prefixed(name, time):
        pop(f'{obj_name}.{name}', time)

    for name, member in inspect.getmembers(obj, callable):
        if name in exclude:
            continue
        if name.startswith('_'):
            continue
        if not hasattr(member, '__name__'):
            continue
        setattr(obj, name, timed(member, push_prefixed, pop_prefixed))


def init_reader(reader):
    reader.timer = timer = Timer()
    decorate(
        reader,
        timer.push,
        timer.pop,
        exclude={
            'make_reader_reserved_name',
            'make_plugin_reserved_name',
        },
    )
    decorate(reader._storage, timer.push, timer.pop)
    decorate(reader._search, timer.push, timer.pop)


if __name__ == '__main__':
    from reader import make_reader

    reader = make_reader('db.sqlite')
    init_reader(reader)

    with reader.timer as timings:
        start = perf_counter()
        for _ in reader.get_feeds():
            pass
        for _ in reader.get_entries(limit=1000):
            pass
        for _ in reader.search_entries('mars'):
            pass
        end = perf_counter()

    print(f"{end-start:1.6f}")
    print(timings.format_tree())
    print(timings.format_stats())
