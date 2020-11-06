import cProfile
import inspect
import math
import os.path
import pstats
import random
import sqlite3
import statistics
import sys
import tempfile
import timeit
from collections import OrderedDict
from contextlib import contextmanager
from contextlib import ExitStack
from datetime import datetime
from datetime import timedelta
from fnmatch import fnmatchcase
from functools import partial

import click
from jinja2.utils import generate_lorem_ipsum

root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../src'))
sys.path.insert(0, os.path.join(root_dir, '../tests'))

from fakeparser import Parser

from reader import make_reader
from reader._app import create_app, get_reader
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


NUM_FEEDS = 8


def make_reader_with_entries(path, num_entries, num_feeds=NUM_FEEDS, text=False):
    reader = make_reader(path)
    reader._parser = parser = Parser()

    for i in range(num_feeds):
        feed = parser.feed(i, datetime(2010, 1, 1))
        reader.add_feed(feed.url)

    random.seed(0)
    for i in range(num_entries):
        kwargs = {}
        if text:
            kwargs.update(
                title=generate_lorem_ipsum(html=False, n=1, min=1, max=10),
                summary=generate_lorem_ipsum(html=False),
            )
        parser.entry(i % num_feeds, i, datetime(2010, 1, 1) + timedelta(i), **kwargs)

    return reader


def make_test_client(path):
    app = create_app(make_reader_config({'reader': {'url': path}}))
    client = app.test_client()
    with app.app_context():
        get_reader()
    return client


@contextmanager
def setup_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, 'db.sqlite')


EXISTING_DB_PATH = None


@contextmanager
def setup_db_with_entries(num_entries):
    if EXISTING_DB_PATH:
        yield EXISTING_DB_PATH
        return
    with setup_db() as path:
        make_reader_with_entries(path, num_entries).update_feeds()
        yield path


@contextmanager
def setup_reader_with_entries(num_entries):
    with setup_db_with_entries(num_entries) as path:
        yield make_reader(path)


@contextmanager
def setup_client_with_entries(num_entries):
    with setup_db_with_entries(num_entries) as path:
        yield make_test_client(path)


@inject(reader=setup_reader_with_entries)
def time_get_entries_all(reader):
    for _ in reader.get_entries():
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_read(reader):
    for _ in reader.get_entries(read=True):
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_unread(reader):
    for _ in reader.get_entries(read=False):
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_important(reader):
    for _ in reader.get_entries(important=True):
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_unimportant(reader):
    for _ in reader.get_entries(important=False):
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_enclosures(reader):
    for _ in reader.get_entries(has_enclosures=True):
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_no_enclosures(reader):
    for _ in reader.get_entries(has_enclosures=False):
        pass


@inject(reader=setup_reader_with_entries)
def time_get_entries_feed(reader):
    feed = next(reader.get_feeds())
    for _ in reader.get_entries(feed=feed):
        pass


@inject(client=setup_client_with_entries)
def time_show(client):
    for _ in client.get('/?show=all').response:
        pass


@inject(client=setup_client_with_entries)
def time_show_100k(client):
    length = 0
    for chunk in client.get('/?show=all').response:
        length += len(chunk)
        if length >= 100000:
            break


@contextmanager
def setup_reader_with_fake_parser(num_entries):
    with setup_db() as path:
        yield make_reader_with_entries(path, num_entries)


@inject(reader=setup_reader_with_fake_parser)
def time_update_feeds(reader):
    reader.update_feeds()


@contextmanager
def setup_reader_feed_new(num_entries):
    with setup_db() as path:
        yield make_reader_with_entries(path, num_entries, num_feeds=1)


@contextmanager
def setup_reader_feed_old(num_entries):
    with setup_reader_feed_new(num_entries) as reader:
        reader.update_feeds()
        yield reader


def raise_too_many_variables(reader):
    original = getattr(reader._storage, '_get_entries_for_update_one_query', None)

    def wrapper(*args):
        original(*args)
        raise sqlite3.OperationalError("too many SQL variables")

    reader._storage._get_entries_for_update_one_query = wrapper


@contextmanager
def setup_reader_feed_new_fallback(num_entries):
    with setup_reader_feed_new(num_entries) as reader:
        raise_too_many_variables(reader)
        yield reader


@contextmanager
def setup_reader_feed_old_fallback(num_entries):
    with setup_reader_feed_old(num_entries) as reader:
        raise_too_many_variables(reader)
        yield reader


def _time_update_feed(reader):
    feed_url = list(reader._parser.feeds.values())[0].url
    reader.update_feed(feed_url)


time_update_feed_new = inject(reader=setup_reader_feed_new)(_time_update_feed)
time_update_feed_new_fallback = inject(reader=setup_reader_feed_new_fallback)(
    _time_update_feed
)
time_update_feed_old = inject(reader=setup_reader_feed_old)(_time_update_feed)
time_update_feed_old_fallback = inject(reader=setup_reader_feed_old_fallback)(
    _time_update_feed
)


@contextmanager
def setup_reader_with_text_entries(num_entries):
    if EXISTING_DB_PATH:
        yield make_reader(EXISTING_DB_PATH)
        return
    with setup_db() as path:
        reader = make_reader_with_entries(path, num_entries, text=True)
        reader.update_feeds()
        yield reader


@contextmanager
def setup_reader_with_search_and_some_read_entries(num_entries):
    if EXISTING_DB_PATH:
        yield make_reader(EXISTING_DB_PATH)
        return
    with setup_reader_with_text_entries(num_entries) as reader:
        reader.enable_search()
        reader.update_search()
        for i, entry in enumerate(reader.get_entries()):
            if i % 2 == 5:
                reader.mark_as_read(entry)
        yield reader


SEARCH_ENTRIES_QUERY = 'porta justo scelerisque dignissim convallis primis lacus'


@inject(reader=setup_reader_with_search_and_some_read_entries)
def time_search_entries_relevant_all(reader):
    for _ in reader.search_entries(SEARCH_ENTRIES_QUERY):
        pass


@inject(reader=setup_reader_with_search_and_some_read_entries)
def time_search_entries_relevant_read(reader):
    for _ in reader.search_entries(SEARCH_ENTRIES_QUERY, read=True):
        pass


@inject(reader=setup_reader_with_search_and_some_read_entries)
def time_search_entries_recent_all(reader):
    for _ in reader.search_entries(SEARCH_ENTRIES_QUERY, sort='recent'):
        pass


@inject(reader=setup_reader_with_search_and_some_read_entries)
def time_search_entries_recent_read(reader):
    for _ in reader.search_entries(SEARCH_ENTRIES_QUERY, sort='recent', read=True):
        pass


@inject(reader=setup_reader_with_text_entries)
def time_update_search(reader):
    # Sadly time() doesn't allow running the setup for every repeat,
    # so we enable/disable search inside the benchmark
    # (otherwise the second update_search() call has nothing to do).
    reader.enable_search()
    reader.update_search()
    reader.disable_search()


TIMINGS = OrderedDict(
    (tn.partition('_')[2], t)
    for tn, t in sorted(globals().items())
    if tn.startswith('time_')
)
TIMINGS_PARAMS_LIST = [(2 ** i,) for i in range(5, 12)]
TIMINGS_NUMBER = 4
PROFILE_PARAMS = TIMINGS_PARAMS_LIST[-1]
PARAM_IDS = ('num_entries',)


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
    extra_fmt = ['{{:>{}}}'.format(len(e)) for e in extra]
    names_fmt = ['{{:>{}{}}}'.format(len(n), num_fmt) for n in names]
    return ' '.join(extra_fmt + names_fmt)


@cli.command()
@click.argument('which', nargs=-1)
@click.option('-n', '--number', type=int, default=TIMINGS_NUMBER, show_default=True)
@click.option('-r', '--repeat', type=int, show_default=True)
@click.option(
    '--db',
    type=click.Path(exists=True, dir_okay=False),
    help="Use an existing database instead of generating ones of varying sizes. "
    "WARNING: Benchmarks that mutate the database might not make sense.",
)
@click.option('--query', help="Query for search_entries() timings; useful with --db.")
def time(which, number, repeat, db, query):
    if not which:
        which = ['*']

    if not repeat:
        extra = ['number'] + list(PARAM_IDS)
        timeit_func = timeit.timeit
        stats = {'': lambda x: x}
    else:
        extra = ['stat', 'number', 'repeat'] + list(PARAM_IDS)
        timeit_func = partial(timeit.repeat, repeat=repeat)

        # statistics.quantiles only gets added in Python 3.8
        import numpy as np

        stats = {
            'avg': np.mean,
            'min': lambda xs: min(xs),
            'p50': partial(np.quantile, q=0.5),
            'p90': partial(np.quantile, q=0.9),
        }

    names = [name for name in TIMINGS if any(fnmatchcase(name, w) for w in which)]

    header = make_header(extra, names)
    row_fmt = make_row_fmt(extra, names)

    if db:
        # HACK: use an existing DB
        # (for which num_entries can't vary, since it exists already)
        global EXISTING_DB_PATH
        EXISTING_DB_PATH = db
        global TIMINGS_PARAMS_LIST
        TIMINGS_PARAMS_LIST = [(0,)]
    if query:
        global SEARCH_ENTRIES_QUERY
        SEARCH_ENTRIES_QUERY = query

    def get_results():
        for params in TIMINGS_PARAMS_LIST:
            times = []
            for name in names:
                cm = TIMINGS[name](**dict(zip(PARAM_IDS, params)))
                with cm as fn:
                    time = timeit_func('fn()', globals=dict(fn=fn), number=number)
                times.append(time)
            yield list(params), times

    print(header)
    for params, results in get_results():
        for stat_name, stat in stats.items():
            if not repeat:
                prefix = [number]
            else:
                prefix = [stat_name, number, repeat]
            print(row_fmt.format(*prefix, *params, *map(stat, results)))


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
    first_param_index = parts.index(PARAM_IDS[0])
    first_name_index = first_param_index + len(PARAM_IDS)
    assert parts[first_param_index:first_name_index] == list(PARAM_IDS)

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
def profile(which):
    names = [name for name in TIMINGS if any(fnmatchcase(name, w) for w in which)]
    params = PROFILE_PARAMS

    for name in names:
        print(name, ' '.join('{}={}'.format(i, p) for i, p in zip(PARAM_IDS, params)))
        print()

        cm = TIMINGS[name](**dict(zip(PARAM_IDS, params)))

        pr = cProfile.Profile()
        with cm as fn:
            pr.enable()
            fn()
            pr.disable()
        pstats.Stats(pr).strip_dirs().sort_stats('cumulative').print_stats(40)


if __name__ == '__main__':
    cli()
