from datetime import datetime, timedelta
import tempfile
import sys
import os.path
import timeit
import cProfile, pstats
from contextlib import contextmanager, ExitStack
import inspect
from functools import partial
from fnmatch import fnmatchcase
from collections import OrderedDict
import sqlite3

import click

root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../src'))
sys.path.insert(0, os.path.join(root_dir, '../tests'))

from fakeparser import Parser

from reader import Reader
from reader.app import create_app, get_reader


def get_params(fn):
    rv = []
    for param in inspect.signature(fn).parameters.values():
        assert param.kind == param.POSITIONAL_OR_KEYWORD, (
            f"parameter {param.name} of {fn.__name__} is variable")
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
                        f"got an unexpected keyword argument {kw!r}")

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

def make_reader_with_entries(path, num_entries, num_feeds=NUM_FEEDS):
    reader = Reader(path)
    reader._parser = parser = Parser()

    for i in range(num_feeds):
        feed = parser.feed(i, datetime(2010, 1, 1))
        reader.add_feed(feed.url)

    for i in range(num_entries):
        parser.entry(i % num_feeds, i, datetime(2010, 1, 1) + timedelta(i))

    return reader

def make_test_client(path):
    app = create_app(path)
    client = app.test_client()
    with app.app_context():
        get_reader()
    return client


@contextmanager
def setup_db():
    with tempfile.TemporaryDirectory() as tmpdir:
       yield os.path.join(tmpdir, 'db.sqlite')

@contextmanager
def setup_db_with_entries(num_entries):
    with setup_db() as path:
        make_reader_with_entries(path, num_entries).update_feeds()
        yield path

@contextmanager
def setup_reader_with_entries(num_entries):
    with setup_db_with_entries(num_entries) as path:
        yield Reader(path)

@contextmanager
def setup_client_with_entries(num_entries):
    with setup_db_with_entries(num_entries) as path:
        yield make_test_client(path)


@inject(reader=setup_reader_with_entries)
def time_get_entries(reader):
    for _ in reader.get_entries(which='all'):
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
time_update_feed_new_fallback = inject(reader=setup_reader_feed_new_fallback)(_time_update_feed)
time_update_feed_old = inject(reader=setup_reader_feed_old)(_time_update_feed)
time_update_feed_old_fallback = inject(reader=setup_reader_feed_old_fallback)(_time_update_feed)


TIMINGS = OrderedDict(
    (tn.partition('_')[2], t)
    for tn, t in sorted(globals().items())
    if tn.startswith('time_')
)
TIMINGS_PARAMS_LIST = [(2**i,) for i in range(5, 12)]
TIMINGS_NUMBER = 4
PROFILE_PARAMS = (2**11, )
IDS = ('num_entries', )


@click.group()
def cli():
    pass


@cli.command(name='list')
def list_():
    for timing in TIMINGS:
        print(timing)


@cli.command()
@click.argument('which', nargs=-1)
def time(which):
    if not which:
        which = ['*']

    names = [
        name
        for name in TIMINGS
        if any(fnmatchcase(name, w) for w in which)
    ]

    extra = ['number'] + list(IDS)
    header = ' '.join(extra + names)
    print(header)

    extra_fmt = ['{{:>{}}}'.format(len(e)) for e in extra]
    names_fmt = ['{{:>{}.2f}}'.format(len(n)) for n in names]
    row_fmt = ' '.join(extra_fmt + names_fmt)

    number = TIMINGS_NUMBER

    for params in TIMINGS_PARAMS_LIST:
        times = []
        for name in names:
            cm = TIMINGS[name](**dict(zip(IDS, params)))
            with cm as fn:
                time = timeit.timeit('fn()', globals=dict(fn=fn), number=number)
            times.append(time)

        print(row_fmt.format(number, *(list(params) + times)))


@cli.command()
@click.argument('which', nargs=-1)
def profile(which):
    names = [
        name
        for name in TIMINGS
        if any(fnmatchcase(name, w) for w in which)
    ]
    params = PROFILE_PARAMS

    for name in names:
        print(name, ' '.join('{}={}'.format(i, p) for i, p in zip(IDS, params)))
        print()

        cm = TIMINGS[name](**dict(zip(IDS, params)))

        pr = cProfile.Profile()
        with cm as fn:
            pr.enable()
            fn()
            pr.disable()
        pstats.Stats(pr).strip_dirs().sort_stats('cumulative').print_stats(40)


if __name__ == '__main__':
    cli()
