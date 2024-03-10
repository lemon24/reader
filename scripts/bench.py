import cProfile
import inspect
import math
import os.path
import pstats
import sys
import tempfile
import timeit
from collections import OrderedDict
from contextlib import contextmanager
from contextlib import ExitStack
from fnmatch import fnmatchcase
from functools import partial

import click


root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../src'))
sys.path.insert(0, os.path.join(root_dir, '../tests'))

from fakeparser import Parser
from reader import make_reader
from reader._app import create_app
from reader._app import get_reader
from reader._config import make_reader_config


def get_params(fn):
    rv = []
    for param in inspect.signature(fn).parameters.values():
        assert (
            param.kind == param.POSITIONAL_OR_KEYWORD
        ), f"parameter {param.name} of {fn.__name__} is variable"
        rv.append(param.name)
    return rv


def inject(**factories):
    params = {p for cm in factories.values() for p in get_params(cm)}

    def decorator(fn):
        fn_params = get_params(fn)

        @contextmanager
        def wrapper(**kwargs):
            for kw in kwargs:
                if kw not in params:
                    raise TypeError(
                        f"{fn.__name__}({', '.join(sorted(params))}) "
                        f"got an unexpected keyword argument {kw!r}"
                    )

            with ExitStack() as stack:
                fn_kwargs = {}
                for cm_name, cm in factories.items():
                    try:
                        cm_kwargs = {p: kwargs[p] for p in get_params(cm)}
                    except KeyError as e:
                        raise TypeError(
                            f"{fn.__name__}({', '.join(sorted(params))}) "
                            f"missing required argument {e} (from {cm.__name__})"
                        ) from None

                    cm_val = stack.enter_context(cm(**cm_kwargs))
                    if cm_name in fn_params:
                        fn_kwargs[cm_name] = cm_val

                yield partial(fn, **fn_kwargs)

        return wrapper

    return decorator


def make_test_client(path):
    app = create_app(make_reader_config({'reader': {'url': path}}))
    client = app.test_client()
    with app.app_context():
        get_reader()
    return client


# these get set by the CLI
DB_PATH = None
QUERY = None
SNIPPET = None

LIMIT = 100
SEARCH_LIMIT = 20


@contextmanager
def setup_db():
    assert DB_PATH
    yield DB_PATH


@contextmanager
def setup_reader():
    with setup_db() as path:
        yield make_reader(path)


@contextmanager
def setup_client():
    with setup_db() as path:
        yield make_test_client(path)


@inject(reader=setup_reader)
def time_get_entries_all(reader):
    for _ in reader.get_entries():
        pass


@inject(reader=setup_reader)
def time_get_entries_all_page(reader):
    for _ in reader.get_entries(limit=LIMIT):
        pass


@inject(reader=setup_reader)
def time_get_entries_read(reader):
    for _ in reader.get_entries(read=True):
        pass


@inject(reader=setup_reader)
def time_get_entries_unread(reader):
    for _ in reader.get_entries(read=False):
        pass


@inject(reader=setup_reader)
def time_get_entries_unread_page(reader):
    for _ in reader.get_entries(read=False, limit=LIMIT):
        pass


@inject(reader=setup_reader)
def time_get_entries_important(reader):
    for _ in reader.get_entries(important=True):
        pass


@inject(reader=setup_reader)
def time_get_entries_important_page(reader):
    for _ in reader.get_entries(important=True, limit=LIMIT):
        pass


@inject(reader=setup_reader)
def time_get_entries_unimportant(reader):
    for _ in reader.get_entries(important=False):
        pass


@inject(reader=setup_reader)
def time_get_entries_enclosures(reader):
    for _ in reader.get_entries(has_enclosures=True):
        pass


@inject(reader=setup_reader)
def time_get_entries_no_enclosures(reader):
    for _ in reader.get_entries(has_enclosures=False):
        pass


@inject(reader=setup_reader)
def time_get_entries_feed(reader):
    feed = next(reader.get_feeds())
    for _ in reader.get_entries(feed=feed):
        pass


@inject(reader=setup_reader)
def time_get_entries_random(reader):
    for _ in reader.get_entries(sort='random'):
        pass


@inject(reader=setup_reader)
def time_get_entries_random_read(reader):
    for _ in reader.get_entries(sort='random', read=True):
        pass


@inject(client=setup_client)
def time_show(client):
    for _ in client.get('/?show=all').response:
        pass


@inject(client=setup_client)
def time_show_100k(client):
    length = 0
    for chunk in client.get('/?show=all').response:
        length += len(chunk)
        if length >= 100000:
            break


@inject(reader=setup_reader)
def time_snippet(reader):
    exec(SNIPPET, {'reader': reader})


# there were some update_feeds() timings here (up to 537348c);
# I removed them because they relied on fake feeds (also removed in #330),
# and I didn't want to spend the time to find another way of doing it


@inject(reader=setup_reader)
def time_search_entries_relevant_all(reader):
    for _ in reader.search_entries(QUERY):
        pass


@inject(reader=setup_reader)
def time_search_entries_relevant_all_page(reader):
    for _ in reader.search_entries(QUERY, limit=SEARCH_LIMIT):
        pass


@inject(reader=setup_reader)
def time_search_entries_relevant_read(reader):
    for _ in reader.search_entries(QUERY, read=True):
        pass


@inject(reader=setup_reader)
def time_search_entries_recent_all(reader):
    for _ in reader.search_entries(QUERY, sort='recent'):
        pass


@inject(reader=setup_reader)
def time_search_entries_recent_all_page(reader):
    for _ in reader.search_entries(QUERY, sort='recent', limit=SEARCH_LIMIT):
        pass


@inject(reader=setup_reader)
def time_search_entries_recent_read(reader):
    for _ in reader.search_entries(QUERY, sort='recent', read=True):
        pass


@inject(reader=setup_reader)
def time_update_search(reader):
    # Sadly time() doesn't allow running the setup for every repeat,
    # so we disable/enable search inside the benchmark.
    reader.disable_search()
    reader.enable_search()
    reader.update_search()


TIMINGS = OrderedDict(
    (tn.partition('_')[2], t)
    for tn, t in sorted(globals().items())
    if tn.startswith('time_')
)


def common_options(fn):
    def set_global(ctx, param, value):
        name = param.name.upper()
        gs = globals()
        assert name in gs, name
        assert gs[name] is None, name
        gs[name] = value

        @ctx.call_on_close
        def reset():
            gs[name] = None

    click.option(
        '--db',
        'db_path',
        default='db.sqlite',
        show_default=True,
        callback=set_global,
        expose_value=False,
        help="Database to use.",
    )(fn)
    click.option(
        '-q',
        '--query',
        default='query',
        show_default=True,
        callback=set_global,
        expose_value=False,
        help="search_entries() query.",
    )(fn)
    click.option(
        '--snippet',
        show_default=True,
        callback=set_global,
        expose_value=False,
        help="Python snippet.",
    )(fn)

    return fn


@click.group()
def cli():
    pass


@cli.command(name='list')
def list_():
    for timing in TIMINGS:
        print(timing)


def make_header(extra, names):
    return ' '.join(extra + names)


def make_row_fmt(extra, names, num_fmt='.3f'):
    extra_fmt = [f'{{:>{len(e)}}}' for e in extra]
    names_fmt = [f'{{:>{len(n)}{num_fmt}}}' for n in names]
    return ' '.join(extra_fmt + names_fmt)


@cli.command()
@click.argument('which', nargs=-1)
@common_options
@click.option('-n', '--number', type=int, default=1, show_default=True)
@click.option('-r', '--repeat', type=int, default=1, show_default=True)
@click.option('-s', '--stat', multiple=True)
def time(which, number, repeat, stat):
    show_stat = stat
    if not which:
        which = ['*']

    extra = ['stat', 'number', 'repeat']
    timeit_func = partial(timeit.repeat, repeat=repeat)

    # we're not installing this on pypy
    import numpy as np

    stats = {
        'avg': np.mean,
        'min': lambda xs: min(xs),
        'p50': partial(np.quantile, q=0.5),
        'p90': partial(np.quantile, q=0.9),
    }
    if not show_stat:
        show_stat = list(stats)

    names = [name for name in TIMINGS if any(fnmatchcase(name, w) for w in which)]
    names_display = [
        n if not n.startswith('search_') else f"{n}({QUERY})" for n in names
    ]
    header = make_header(extra, names_display)
    row_fmt = make_row_fmt(extra, names_display)

    print(header)

    times = []
    for name in names:
        if len(names) > 1:
            print('* timing', name, file=sys.stderr)
        cm = TIMINGS[name]()
        with cm as fn:
            time = timeit_func('fn()', globals=dict(fn=fn), number=number)
        times.append(time)

    for stat_name, stat in stats.items():
        if stat_name not in show_stat:
            continue
        prefix = [stat_name, number, repeat]
        print(row_fmt.format(*prefix, *map(stat, times)))


def fancy_division(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return math.copysign(float('inf'), a)


@cli.command()
@click.argument('before', type=click.File())
@click.argument('after', type=click.File())
@click.option(
    '--format',
    type=click.Choice(['percent-decrease', 'times']),
    default='percent-decrease',
    show_default=True,
    help="percent-decrease == 1 - after / before. times == after / before.",
)
def diff(before, after, format):
    if format == 'percent-decrease':
        row_num_fmt = '.1%'
        func = lambda b, a: 1 - fancy_division(float(a), float(b))
    elif format == 'times':
        # it would be nice if we could add an "x" after the number, but eh...
        row_num_fmt = '.2f'
        func = lambda b, a: fancy_division(float(a), float(b))
    else:
        assert False, "shouldn't happen"

    pairs = zip(before, after)

    b_line, a_line = next(pairs)
    assert b_line == a_line

    parts = b_line.split()
    first_name_index = 3  # ['stat', 'number', 'repeat']
    extra = parts[:first_name_index]
    names = parts[first_name_index:]

    header = make_header(extra, names)
    row_fmt = make_row_fmt(extra, names, row_num_fmt)

    print(header)
    for b_line, a_line in pairs:
        b_parts, a_parts = b_line.split(), a_line.split()
        assert b_parts[:first_name_index] == a_parts[:first_name_index]

        results = [
            func(b, a)
            for a, b in zip(a_parts[first_name_index:], b_parts[first_name_index:])
        ]
        print(row_fmt.format(*b_parts[:first_name_index], *results))


@cli.command()
@click.argument('which', nargs=-1)
@common_options
def profile(which):
    names = [name for name in TIMINGS if any(fnmatchcase(name, w) for w in which)]

    for name in names:
        print(name)
        print()

        cm = TIMINGS[name]()

        pr = cProfile.Profile()
        with cm as fn:
            pr.enable()
            fn()
            pr.disable()
        pstats.Stats(pr).strip_dirs().sort_stats('cumulative').print_stats(40)


if __name__ == '__main__':
    cli(auto_envvar_prefix='BENCH')
