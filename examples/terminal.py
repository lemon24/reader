"""
A simple terminal feed reader that shows a screenful of articles
and updates every 10 minutes.

Run with::

    python examples/terminal.py db.sqlite

To add feeds, run::

    python -m reader --db db.sqlite add http://example.com/feed.xml


"""
import logging
import os
import sys
import textwrap
import time

from reader import make_reader


def limit(it, n):
    """list(limit('abcd', 2)) -> ['a', 'b']"""
    return (e for e, _ in zip(it, range(n)))


def get_lines(reader):
    size = os.get_terminal_size()

    # Only take as many entries as we have lines.
    entries = limit(reader.get_entries(), size.lines - 1)

    lines = (
        l
        for e in entries
        for l in textwrap.wrap(
            f"{(e.published or e.updated).date()} - {e.feed.title} - {e.title}",
            width=size.columns,
        )
    )
    return limit(lines, size.lines - 1)


def print_status_line(message, seconds):
    print(message, end="", flush=True)
    time.sleep(seconds)
    length = len(message)
    print("\b" * length, " " * length, "\b" * length, sep="", end="", flush=True)


reader = make_reader(sys.argv[1])

# Prevent update errors from showing.
logging.basicConfig(level=logging.CRITICAL)

update_interval = 60 * 10
last_updated = time.monotonic() - update_interval

while True:
    # Clear screen; should be cross-platform.
    os.system("cls || clear")

    print(*get_lines(reader), sep="\n")

    # Keep sleeping until we need to update.
    while True:
        now = time.monotonic()
        if now - last_updated > update_interval:
            break
        to_sleep = update_interval - (now - last_updated)
        message = f"updating in {int(to_sleep // 60) + 1} minutes ..."
        print_status_line(message, 60)

    print("updating ...", end="", flush=True)
    last_updated = time.monotonic()
    reader.update_feeds(workers=10)
