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

import click

root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../src'))
sys.path.insert(0, os.path.join(root_dir, '../tests'))

from fakeparser import Parser

from reader import Reader
from reader.app import create_app, get_reader


def set_up_db(path, num_entries):
    parser = Parser()
    reader = Reader(path)

    num_feeds = 8
    for i in range(num_feeds):
        feed = parser.feed(i, datetime(2010, 1, 1))
        reader.add_feed(feed.url)

    for i in range(num_entries):
        parser.entry(i % num_feeds, i, datetime(2010, 1, 1) + timedelta(i))

    reader._parse = parser
    reader.update_feeds()


def make_test_client(path):
    app = create_app(path)
    client = app.test_client()
    with app.app_context():
        get_reader()
    return client


class Timings:

    """Scaffolding to manage setup and teardown for a bunch of functions.

    >>> from contextlib import contextmanager
    >>>
    >>> class MyTimings(Timings):
    ...
    ...     @contextmanager
    ...     def setup_thing(self):
    ...         print("setup_thing: before making thing")
    ...         yield 'thing value'
    ...         print("setup_thing: after making thing")
    ...
    ...     def time_one(self, thing):
    ...         print("time_one: doing stuff with thing:", thing)
    ...
    ...     def time_two(self):
    ...         print("time_two: doing stuff")
    ...
    >>> for name, cm in sorted(MyTimings().extract_times()):
    ...     with cm as fn:
    ...         print("setup for", name, "done")
    ...         fn()
    ...     print("teardown for", name, "done")
    ...
    setup_thing: before making thing
    setup for one done
    time_one: doing stuff with thing: thing value
    setup_thing: after making thing
    teardown for one done
    setup for two done
    time_two: doing stuff
    teardown for two done


    """

    def get_methods_with_prefix(self, prefix):
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith(prefix):
                yield name.partition(prefix)[2], method

    def extract_setups(self, method):
        setups = dict(self.get_methods_with_prefix('setup_'))

        for param in inspect.signature(method).parameters.values():
            assert param.kind == param.POSITIONAL_OR_KEYWORD, (
                "parameter {p.name} of {t.__name__}.{m.__name__} "
                "is variable"
                .format(p=param, m=method, t=type(self)))
            assert param.name in setups, (
                "{t.__name__}.setup_{p.name} required by "
                "{t.__name__}.{m.__name__} not found"
                .format(p=param, m=method, t=type(self)))

            yield param.name, setups[param.name]

    @contextmanager
    def bind_setups(self, method):
        with ExitStack() as stack:
            yield partial(method, **{
                name: stack.enter_context(setup())
                for name, setup in self.extract_setups(method)
            })

    def extract_times(self):
        for name, method in self.get_methods_with_prefix('time_'):
            yield name, self.bind_setups(method)

    def extract_time_names(self):
        for name, _ in self.extract_times():
            yield name


class GetEntries(Timings):

    def __init__(self, num_entries=1):
        self.num_entries = num_entries

    @contextmanager
    def setup_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'db.sqlite')
            set_up_db(path, self.num_entries)
            yield path

    @contextmanager
    def setup_reader(self):
        with self.setup_db() as path:
            yield Reader(path)

    @contextmanager
    def setup_client(self):
        with self.setup_db() as path:
            yield make_test_client(path)

    def time_get_entries(self, reader):
        for _ in reader.get_entries(which='all'):
            pass

    def time_show(self, client):
        for _ in client.get('/?show=all').response:
            pass

    def time_show_100k(self, client):
        length = 0
        for chunk in client.get('/?show=all').response:
            length += len(chunk)
            if length >= 100000:
                break


class UpdateFeeds(Timings):

    def __init__(self, num_entries=1):
        self.num_entries = num_entries

    @contextmanager
    def setup_reader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'db.sqlite')

            parser = Parser()
            reader = Reader(path)

            num_feeds = 8
            for i in range(num_feeds):
                feed = parser.feed(i, datetime(2010, 1, 1))
                reader.add_feed(feed.url)

            for i in range(self.num_entries):
                parser.entry(i % num_feeds, i, datetime(2010, 1, 1) + timedelta(i))

            reader._parse = parser

            yield reader

    def time_update_feeds(self, reader):
        reader.update_feeds()


TIMES = [
    (GetEntries, [(2**i,) for i in range(5, 13)], ['entries'], 4),
    (UpdateFeeds, [(2**i,) for i in range(5, 13)], ['entries'], 4),

]

PROFILES = [
    (GetEntries, (2048, ), ['entries']),
    (UpdateFeeds, (2048, ), ['entries']),
]


def make_full_name(timings_cls, name):
    return "{}::{}".format(timings_cls.__name__, name)


@click.group()
def cli():
    pass


@cli.command(name='list')
def list_():
    for timings_cls, params_list, ids, number in TIMES:
        for name in timings_cls().extract_time_names():
            print(make_full_name(timings_cls, name))


@cli.command()
@click.argument('which', nargs=-1)
def time(which):
    if not which:
        which = ['*']

    for timings_cls, params_list, ids, number in TIMES:
        names = sorted(
            name
            for name in timings_cls().extract_time_names()
            if any(
                fnmatchcase(make_full_name(timings_cls, name), w)
                for w in which
            )
        )
        if not names:
            continue

        print(timings_cls.__name__)

        extra = ['runs'] + ids
        header = ' '.join(extra + names)
        print(header)

        extra_fmt = ['{{:>{}}}'.format(len(e)) for e in extra]
        names_fmt = ['{{:>{}.2f}}'.format(len(n)) for n in names]
        row_fmt = ' '.join(extra_fmt + names_fmt)

        for params in params_list:
            times = []
            for name, cm in sorted(timings_cls(*params).extract_times()):
                if name not in names:
                    continue
                with cm as fn:
                    time = timeit.timeit('fn()', globals=dict(fn=fn), number=number)
                times.append(time)
            print(row_fmt.format(number, *(list(params) + times)))

        print()


@cli.command()
@click.argument('which', nargs=-1)
def profile(which):
    for timings_cls, params, ids in PROFILES:
        for name, cm in sorted(timings_cls(*params).extract_times()):
            full_name = make_full_name(timings_cls, name)
            if not any(fnmatchcase(full_name, w) for w in which):
                continue

            print(full_name, ' '.join('{}={}'.format(i, p) for i, p in zip(ids, params)))
            print()

            pr = cProfile.Profile()
            with cm as fn:
                pr.enable()
                fn()
                pr.disable()
            pstats.Stats(pr).strip_dirs().sort_stats('cumulative').print_stats(40)


if __name__ == '__main__':
    cli()
