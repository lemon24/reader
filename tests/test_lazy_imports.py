"""
See https://github.com/lemon24/reader/issues/297 for details.

"""

import os
import pkgutil
import subprocess
import sys
import textwrap

import pytest

import reader.plugins
from utils import parametrize_dict


# these tests take ~1s in total
pytestmark = pytest.mark.slow


ALL_PLUGINS = [
    'reader.' + m.name for m in pkgutil.iter_modules(reader.plugins.__path__)
]


CODE_FMT = f"""
from reader import make_reader

# "maximal" reader
reader = make_reader(
    ':memory:',
    feed_root='',
    search_enabled=True,
    plugins={ALL_PLUGINS},
)

{{code}}

import sys
print(*sys.modules)
"""


def get_imported_modules(code):
    # we don't want pytest-cov importing stuff in the subprocess
    # https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html
    # https://github.com/pytest-dev/pytest-cov/blob/v4.0.0/src/pytest-cov.embed
    env = dict(os.environ)
    for k in list(env):
        if k.startswith('COV_CORE_'):
            env.pop(k)

    process = subprocess.run(
        [sys.executable, '-c', CODE_FMT.format(code=textwrap.dedent(code))],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert process.returncode == 0, process.stderr

    return process.stdout.split()


LAZY_MODULES = frozenset(
    """\
    bs4
    requests
    feedparser
    reader._vendor.feedparser
    urllib.request
    multiprocessing
    concurrent.futures
    """.split()
)


# all in a single script to save time

S_NO_IMPORTS = """\
list(reader.get_entries())
list(reader.search_entries('entry'))
reader._parser.session_factory.response_hooks.append('unused')
""", set()  # fmt: skip


# urllib.request being imported by requests/bs4 makes these kinda brittle, but eh...

S_ADD_HTTP = "reader.add_feed('http://example.com')", {
    'requests',
    'reader._vendor.feedparser',
    'urllib.request',
}
S_UPDATE_FEEDS = "reader.update_feeds()", {
    'requests',
    'reader._vendor.feedparser',
    'urllib.request',
}
S_UPDATE_FEEDS_WORKERS = "reader.update_feeds(workers=2)", {
    'requests',
    'reader._vendor.feedparser',
    'urllib.request',
    'concurrent.futures',
}
S_UPDATE_SEARCH = """\
from reader._types import EntryData, EntryUpdateIntent
from datetime import datetime, timezone
reader.add_feed('one', allow_invalid_url=True)
dt = datetime(2010, 1, 1, tzinfo=timezone.utc)
entry = EntryData('one', 'entry', summary='summary')
reader._storage.add_or_update_entry(EntryUpdateIntent(entry, dt, dt, dt, dt))
reader.update_search()
""", {
    'bs4',
    'urllib.request',
}


SNIPPETS = {k: v for k, v in locals().items() if k.startswith('S_')}


@parametrize_dict('code, expected_modules', SNIPPETS)
def test_only_expected_modules_are_imported(code, expected_modules):
    modules = set(get_imported_modules(code))
    actual_modules = LAZY_MODULES & modules

    # sanity check
    assert 'reader' in modules

    # not using == because imports can vary based on library versions,
    # and we care more about slow stuff being imported accidentally
    # than the other way around
    # https://github.com/lemon24/reader/issues/349
    assert actual_modules <= expected_modules, expected_modules
