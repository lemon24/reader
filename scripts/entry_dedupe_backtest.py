"""
Run entry_dedupe .dedupe.once for an entire database,
and parse the logs into a form that makes backtesting easier.

Run dedupe and pretty-print logs:

    $ python scripts/entry_dedupe_backtest.py dedupe.log run

Pretty-print existing logs:

    $ python scripts/entry_dedupe_backtest.py dedupe.log

"""

import logging
import os
import re
import sys
import time

from reader import make_reader
from reader.plugins import entry_dedupe


DB_ARCHIVE = "_backups/reader.sqlite.2025-10-04.gz"

file = sys.argv[1]
run = len(sys.argv) > 2 and sys.argv[2] == 'run'
only = len(sys.argv) > 3 and sys.argv[3]

if run:
    os.system(f"rm db.*; gzip -dc {DB_ARCHIVE} > db.sqlite")
    reader = make_reader('db.sqlite')
    logging.basicConfig(filename=file, filemode='w', level=logging.DEBUG)
    start = time.monotonic()
    for feed in reader.get_feeds():
        if only and not re.search(only, feed.title or '', re.I):
            continue
        reader.set_tag(feed, '.reader.dedupe.once')
        entry_dedupe.after_feed_update(reader, feed)
    end = time.monotonic()
    print(f"TIME: {end-start:.3f} seconds", file=sys.stderr)
    reader.close()
    os.system(f"rm db.*; gzip -dc {DB_ARCHIVE} > db.sqlite")

reader = make_reader('db.sqlite')


def shorten(s, n=48):
    if not s:
        return s
    s = ' '.join(s.split())
    if len(s) < n:
        return s
    return s[:n] + '...'


feed = None
entries = None
grouper = None
prev = ''

for l in open(file):
    if 'skipping:' in prev and 'skipping:' not in l:
        print()
    if 'skipping:' not in prev and 'skipping:' in l:
        print('    HUGE\n')
    prev = l

    if m := re.search(r"for feed '([^']+)'", l):
        feed = reader.get_feed(m[1])
        entries = {e.id: e for e in reader.get_entries(feed=feed)}
        grouper = None
        print(f"{feed.title}  {feed.url}\n")
        continue

    if m := re.search("grouper ([^:]+): all=.*", l):
        grouper = m[1]
        print(f"  grouper {grouper}\n")
        continue

    # if m := re.search(r"found mass duplication pairs \d+ < \d+, skipping", l):
    # print("    TOO FEW PAIRS\n")
    # continue

    if m := re.search(r"found group of size \d+ > \d+, skipping: (.*)", l):
        ids = eval(m[1])
        e = entries[ids[0]]
        fragment = ''
        if 'link' in grouper:
            fragment = e.link
        elif 'published' in grouper:
            fragment = e.published or e.updated
        print(f"    {len(ids):>3}  {shorten(e.title)}  {fragment}")
        continue

    if m := re.search(r"grouper \S+: found (\[.*)", l):
        ids = eval(m[1])
        if ids:
            print('    DUPLICATES\n')
        for ids in ids:
            for i, id in enumerate(ids):
                e = entries[id]
                print(f"    {shorten(e.title, 64)}  {e.id}")
                if 'link' in grouper:
                    print(f"      link = {e.link}")
                if 'published' in grouper:
                    print(f"      published = {e.published or e.updated}")
            print()
        continue

    if m := re.search(r"grouper \S+: group count by size (.*)", l):
        print(f"    summary  {m[1]}\n")
