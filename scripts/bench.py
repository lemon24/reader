from datetime import datetime, timedelta
from textwrap import dedent
import tempfile
import sys
import os.path
import timeit
import cProfile, pstats

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


def do_time(num_entries, number):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, 'db.sqlite')
        set_up_db(path, num_entries)
        reader = Reader(path)
        reader_time = timeit.timeit(
            "list(reader.get_entries(which='all'))",
            globals=dict(reader=reader), number=number)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, 'db.sqlite')
        set_up_db(path, num_entries)
        client = make_test_client(path)
        app_time = timeit.timeit(
            "for _ in client.get('/?show=all').response: pass",
            globals=dict(client=client), number=number)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, 'db.sqlite')
        set_up_db(path, num_entries)
        client = make_test_client(path)
        app_time_100kb = timeit.timeit(dedent("""
            length = 0
            for chunk in client.get('/?show=all').response:
                length += len(chunk)
                if length >= 100000:
                    break
            """),
            globals=dict(client=client), number=number)

    print("{:>7} {:>4} {:>11.2f} {:>10.2f} {:>5.1f} {:>16.2f}".format(
        num_entries, number, reader_time, app_time, app_time/reader_time, app_time_100kb))

def do_time_all():
    print("{} {} {} {} {} {}".format(
        'entries', 'runs', 'get_entries', '/?show=all', 'ratio', '/?show=all#100kb'))
    for i in range(5,13):
        do_time(2**i, min(8, 2**(12-i)))


def do_profile(num_entries):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, 'db.sqlite')
        set_up_db(path, num_entries)
        client = make_test_client(path)

        pr = cProfile.Profile()
        pr.enable()
        for _ in client.get('/?show=all').response: pass
        pr.disable()
        pstats.Stats(pr).strip_dirs().sort_stats('cumulative').print_stats(40)


if __name__ == '__main__':

    {
        'profile': lambda: do_profile(2048),
        'time': do_time_all,
    }[sys.argv[1]]()

