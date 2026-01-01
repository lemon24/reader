import random
import re

import pytest

from reader import Content
from reader import Entry
from reader.plugins import entry_dedupe
from reader.plugins.entry_dedupe import common_prefixes
from reader.plugins.entry_dedupe import group_by
from reader.plugins.entry_dedupe import init_reader
from reader.plugins.entry_dedupe import is_duplicate
from reader.plugins.entry_dedupe import is_duplicate_entry
from reader.plugins.entry_dedupe import merge_flags
from reader.plugins.entry_dedupe import merge_tags
from reader.plugins.entry_dedupe import ngrams
from reader.plugins.entry_dedupe import normalize_url
from reader.plugins.entry_dedupe import tokenize_content
from reader.plugins.entry_dedupe import tokenize_title
from utils import parametrize_dict
from utils import utc_datetime as datetime


pytestmark = pytest.mark.noscheduled


@pytest.fixture
def reader(make_reader, request):
    plugins = []
    if 'with_plugin' in request.fixturenames:
        plugins.append('reader.entry_dedupe')
    return make_reader(':memory:', plugins=plugins)


@pytest.fixture
def with_plugin():
    """Tell reader to use the plugin from the beginning."""


@pytest.fixture
def allow_short_content(monkeypatch):
    # to avoid false positives, entry content has to be long enough;
    # this makes tests easier to read;
    # TODO: have an integration-y test that doesn't mess with this
    monkeypatch.setattr(entry_dedupe, 'MIN_CONTENT_LENGTH', 1)


def test_only_duplicates_are_deleted(reader, parser, allow_short_content, monkeypatch):
    # detailed/fuzzy content matching tested in test_is_duplicate*

    reader.add_feed(parser.feed(1))

    published = datetime(2010, 1, 1, 2, 3, 4)
    common_attrs = dict(updated=published, title='title', link='link')

    parser.entry(1, 'different', **common_attrs, summary='another')
    parser.entry(1, 'none')
    parser.entry(1, 'title-old', title='Title', summary='value')
    parser.entry(1, 'link-old', link='link', summary='value')
    parser.entry(1, 'published-old', published=published, summary='value')
    parser.entry(1, 'prefix-old', title='prefix', summary='value')

    reader.update_feeds()

    init_reader(reader)

    parser.entry(1, 'title-new', title='title', summary='value')
    parser.entry(1, 'link-new', link='link', summary='value')
    parser.entry(1, 'published-new', updated=published, summary='value')
    parser.entry(1, 'prefix-new', title='series-prefix', summary='value')
    parser.entry(1, 'prefix-x', title='series-x', summary='value')
    parser.entry(1, 'prefix-xx', title='series-xx')
    parser.entry(1, 'prefix-xxx', title='series-xxx')

    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {
        'different',
        'none',
        'title-new',
        'link-new',
        'published-new',
        'prefix-new',
        'prefix-x',
        'prefix-xx',
        'prefix-xxx',
    }


@pytest.mark.xfail(reason="FIXME (#371) impl still in flux", strict=True)
def test_mass_duplication_doesnt_use_all_groupers(
    reader, parser, allow_short_content, caplog
):
    reader.add_feed(parser.feed(1))

    for i in range(4):
        parser.entry(1, f'{i}-old', datetime(2010, 1, 1), title=str(i), summary=str(i))
    reader.update_feeds()

    init_reader(reader)
    caplog.set_level('DEBUG')

    for i in range(4):
        parser.entry(1, f'{i}-new', datetime(2010, 1, 2), title=str(i), summary=str(i))
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'0-new', '1-new', '2-new', '3-new'}

    assert 'title_grouper' in caplog.text
    assert 'link_grouper' not in caplog.text
    assert 'no new entries remaining' in caplog.text


def test_duplicates_in_another_feed_are_ignored(reader, with_plugin, parser):
    reader.add_feed(parser.feed(1))
    reader.add_feed(parser.feed(2))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(2, 1, today, title='title', summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'1, 1', '2, 1'}


def test_duplicates_change_during_update(
    reader, with_plugin, parser, allow_short_content
):
    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, yesterday, title='title', summary='value')
    parser.entry(1, 2, yesterday, title='title', summary='old')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(1, 1, yesterday, title='title', summary='new')
    parser.entry(1, 2, yesterday, title='title', summary='value')
    parser.entry(1, 3, today, title='title', summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 3'}


@pytest.mark.parametrize('add_third_entry', [False, True])
def test_feed_duplicates_dont_flip_flop(
    reader, with_plugin, parser, allow_short_content, add_third_entry
):
    # https://github.com/lemon24/reader/issues/340
    # TODO: also test the .dedupe.once behavior

    reader.add_feed(parser.feed(1))

    common_attrs = dict(title='title', summary='summary')

    one = parser.entry(1, 1, datetime(2010, 1, 2), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    parser.entry(1, 2, datetime(2010, 1, 3), **common_attrs)
    if add_third_entry:
        parser.entry(1, 3, datetime(2010, 1, 1), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()
    # latest published remains
    assert {e.id for e in reader.get_entries()} == {'1, 2'}

    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()
    # shouldn't flip flop
    assert {e.id for e in reader.get_entries()} == {'1, 2'}

    reader._now = lambda: datetime(2010, 1, 4)
    reader.update_feeds()
    # shouldn't flip flop
    assert {e.id for e in reader.get_entries()} == {'1, 2'}


@parametrize_dict(
    'tags, expected_extra',
    {
        '.once, content matters': (['once'], {'title-only-old', 'link-only-old'}),
        '.once.title, pairs only': (
            ['once.title'],
            {'title-old', 'link-old', 'link-only-old', 'prefix-old'},
        ),
        '.once.link': (
            ['once.link'],
            {'title-old', 'title-only-old', 'link-old', 'prefix-old'},
        ),
        '.once.title.prefix': (
            ['once.title.prefix'],
            {'title-old', 'link-old', 'link-only-old'},
        ),
        '.once has priority': (
            ['once', 'once.title'],
            {'title-only-old', 'link-only-old'},
        ),
    },
)
def test_dedupe_once(reader, parser, allow_short_content, tags, expected_extra):
    feed = parser.feed(1)
    reader.add_feed(feed)
    reader.set_tag(feed, 'unrelated')

    published = datetime(2010, 1, 1, 2, 3, 4)
    common_attrs = dict(updated=published, title='title', link='link')

    parser.entry(1, 'different', **common_attrs, summary='another')
    parser.entry(1, 'title-old', title='title', summary='value')
    parser.entry(1, 'title-only-old', title='only', summary='one')
    parser.entry(1, 'link-old', link='link', summary='value')
    parser.entry(1, 'link-only-old', link='http', summary='abc')
    parser.entry(1, 'prefix-old', title='prefix', summary='value')
    # unlike regular dedupe, all entries are considered new
    parser.entry(1, 'prefix-x', title='series-x', summary='value')
    parser.entry(1, 'prefix-xx', title='series-xx')

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    parser.entry(1, 'title-new', title='title', summary='value')
    parser.entry(1, 'title-only-new', title='only', summary='two')
    parser.entry(1, 'link-new', link='link', summary='value')
    parser.entry(1, 'link-only-new', link='http', summary='xyz')
    parser.entry(1, 'prefix-new', title='series-prefix', summary='value')
    parser.entry(1, 'prefix-xxx', title='series-xxx')

    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    init_reader(reader)

    for tag in tags:
        reader.set_tag(feed, f".reader.dedupe.{tag}")
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == expected_extra | {
        'different',
        'title-new',
        'title-only-new',
        'link-new',
        'link-only-new',
        'prefix-new',
        'prefix-x',
        'prefix-xx',
        'prefix-xxx',
    }
    assert set(reader.get_tag_keys(feed)) == {'unrelated'}


@pytest.mark.parametrize('tag, expected', [(None, 'new-pub'), ('once', 'entry')])
def test_dedupe_once_order(reader, parser, allow_short_content, tag, expected):
    feed = parser.feed(1)
    reader.add_feed(feed)

    common_attrs = dict(title='title', summary='value')

    parser.entry(1, 'old', datetime(2010, 1, 1), **common_attrs)
    parser.entry(1, 'new-pub', datetime(2010, 1, 3), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    parser.entry(1, 'new-last-upd', datetime(2010, 1, 1), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    if not tag:
        init_reader(reader)

    parser.entry(1, 'entry', datetime(2010, 1, 2), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    if tag:
        init_reader(reader)
        reader.set_tag(feed, f".reader.dedupe.{tag}")
        reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {expected}


def test_dedupe_once_title_uses_only_title_grouper(reader, parser, caplog):
    feed = parser.feed(1)
    reader.add_feed(feed)
    parser.entry(1, 1)
    reader.update_feeds()

    init_reader(reader)
    caplog.set_level('DEBUG')

    reader.set_tag(feed, ".reader.dedupe.once.title")
    reader.update_feeds()

    assert 'title_grouper' in caplog.text
    assert 'link_grouper' not in caplog.text


@pytest.mark.parametrize('read', [False, True])
@pytest.mark.parametrize('modified', [None, datetime(2010, 1, 1, 1)])
def test_read(reader, with_plugin, parser, allow_short_content, read, modified):
    # multiple duplicates / modified priority tested in test_merge_flags

    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    one = parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    reader.set_entry_read(one, read, modified)

    today = datetime(2010, 1, 2)
    two = parser.entry(1, 2, today, title='title', summary='value')
    reader.update_feeds()

    two = reader.get_entry(two)
    assert two.read == read
    assert two.read_modified == modified


@pytest.mark.parametrize('important', [False, None, True])
@pytest.mark.parametrize('modified', [None, datetime(2010, 1, 1, 1)])
def test_important(
    reader, with_plugin, parser, allow_short_content, important, modified
):
    # multiple duplicates / modified priority tested in test_merge_flags

    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    one = parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    reader.set_entry_important(one, important, modified)

    today = datetime(2010, 1, 2)
    two = parser.entry(1, 2, today, title='title', summary='value')
    reader.update_feeds()

    two = reader.get_entry(two)
    assert two.important == important
    assert two.important_modified == modified


def test_tags(reader, parser, allow_short_content):
    feed = parser.feed(1)
    reader.add_feed(feed)

    one = parser.entry(1, 1, datetime(2010, 1, 2), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    two = parser.entry(1, 2, datetime(2010, 1, 1), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    reader.set_tag(one, 'just', 'one')
    reader.set_tag(one, 'same', 'value')
    reader.set_tag(two, 'same', 'value')
    reader.set_tag(one, 'different', 'one')
    reader.set_tag(two, 'different', 'two')

    init_reader(reader)

    three = parser.entry(1, 3, datetime(2010, 1, 3), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    assert dict(reader.get_tags(three)) == {
        'just': 'one',
        'same': 'value',
        'different': 'one',
        '.reader.duplicate.1.of.different': 'two',
    }


def test_tags_dedupe_once(reader, parser, allow_short_content):
    feed = parser.feed(1)
    reader.add_feed(feed)

    one = parser.entry(1, 1, datetime(2010, 1, 2), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    two = parser.entry(1, 2, datetime(2010, 1, 1), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    reader.set_tag(one, 'just', 'one')
    reader.set_tag(one, 'same', 'value')
    reader.set_tag(two, 'same', 'value')
    reader.set_tag(one, 'different', 'one')
    reader.set_tag(two, 'different', 'two')

    three = parser.entry(1, 3, datetime(2010, 1, 3), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    reader.set_tag(three, 'same', 'value')
    reader.set_tag(three, 'different', 'three')
    reader.set_tag(three, 'only', 'three')

    init_reader(reader)
    reader.set_tag(feed, '.reader.dedupe.once')
    reader.update_feeds()

    assert dict(reader.get_tags(three)) == {
        'just': 'one',
        'same': 'value',
        'different': 'three',
        # note the order differs from test_tags
        '.reader.duplicate.1.of.different': 'two',
        '.reader.duplicate.2.of.different': 'one',
        'only': 'three',
    }


def entry(summary=None, *, title=None, content=None):
    entry = Entry('id', None, title=title, summary=summary)
    if content:
        if isinstance(content, str):
            content = (content,)
        entry = entry._replace(content=[Content(*content)])
    return entry


MC = entry_dedupe.MIN_CONTENT_LENGTH

IS_DUPLICATE_ENTRY_DATA = {
    "no title, no content": (entry(), entry(), False),
    "title, no content": (entry(title='title'), entry(title='title'), False),
    "too short": (entry('one'), entry('one'), False),
    "too medium": (entry('one ' * (MC - 1)), entry('one ' * (MC - 1)), False),
    "long enough": (entry('one ' * MC), entry('one ' * MC), True),
    "summary is content": (
        entry(summary='one ' * MC),
        entry(content='one ' * MC),
        True,
    ),
    "content type is ignored": (
        entry(content=('one ' * MC, 'text/html')),
        entry(content=('one ' * MC, 'absolute/garbage')),
        True,
    ),
    "fuzzy, match": (entry('one ' * MC), entry('one ' * (MC - 4) + 'two ' * 4), True),
    "fuzzy, no match": (
        entry('one ' * MC),
        entry('one ' * (MC - 5) + 'two ' * 5),
        False,
    ),
    "big length difference, use prefix": (
        entry('one ' * MC),
        entry('one ' * MC + 'two ' * 128),
        True,
    ),
    "small length difference, use as-is": (
        entry('one ' * MC),
        entry('one ' * MC + 'two ' * int(MC / 3)),
        False,
    ),
    "two contents, longest wins, match": (
        entry(summary='one ' * (MC + 8), content='abc ' * MC),
        entry(summary='xyz ' * MC, content='one ' * (MC + 8)),
        True,
    ),
    "two contents, longest wins, no match": (
        entry(summary='one ' * (MC + 8), content='one ' * MC),
        entry(summary='one ' * MC, content='one ' * MC + 'two ' * (MC + 8)),
        False,
    ),
    "content prefix becomes full content + different summary": (
        entry(summary='one ' * MC),
        entry(summary='two ' * MC, content='one ' * MC + 'xyz ' * 128),
        True,
    ),
}


@parametrize_dict('one, two, result', IS_DUPLICATE_ENTRY_DATA)
def test_is_duplicate_entry(one, two, result):
    assert bool(is_duplicate_entry(one, two)) is bool(result)


# ([duplicates, ..., entry], expected), ...
MERGE_FLAGS_DATA = [
    # no change
    ([(True, None)], None),
    ([(False, None), (False, 2)], None),
    ([(None, None), (True, 2)], None),
    # read beats not read
    ([(True, None), (False, None)], (True, None)),
    # important beats not set
    ([(True, None), (None, None)], (True, None)),
    # unimportant beats not set
    ([(False, None), (None, None)], (False, None)),
    # none read, earliest modified wins
    ([(False, None), (False, 2), (False, 3)], (False, 2)),
    # none set, earliest modified wins
    ([(None, None), (None, 2), (None, 3)], (None, 2)),
    # some read, earliest read modified wins
    ([(True, None), (False, 2), (True, 3), (True, 4), (None, 5)], (True, 3)),
    # some not set + unimportant, earliest unimportant modified wins
    ([(None, None), (False, 2), (None, 3), (False, 4)], (False, 2)),
]


@pytest.mark.parametrize('flags, expected', MERGE_FLAGS_DATA)
def test_merge_flags(flags, expected):
    def from_days(flag):
        if not flag:
            return None
        value, days = flag
        return value, datetime(2010, 1, days) if days is not None else None

    *duplicates, entry = map(from_days, flags)

    # duplicate order does not matter
    random.shuffle(duplicates)

    assert merge_flags(entry, duplicates) == from_days(expected)


# TODO: test order remains stable if last_updated is the same


COMPLEX_TAGS = {'tag': {'string': [10, True]}}

# ([duplicates, ..., entry], expected), ...
MERGE_TAGS_DATA = [
    # no duplicate entries
    ([{}], {}),
    ([{'tag': None}], {}),
    # duplicate entry with no tags
    ([{}, {}], {}),
    # tag doesn't exist
    ([{'tag': None}, {}], {'tag': None}),
    ([{'tag': 'one'}, {}], {'tag': 'one'}),
    # different tags are merged
    ([{'one': 1}, {'two': 2}, {'three': 3}], {'one': 1, 'two': 2}),
    # tag exists with the same value
    ([{'tag': None}, {'tag': None}], {}),
    # tag doesn't exist, multiple duplicate entries with the same value
    ([{'tag': None}, {'tag': None}, {}], {'tag': None}),
    ([COMPLEX_TAGS, COMPLEX_TAGS, {}], COMPLEX_TAGS),
    # tag doesn't exist, multiple duplicate entries with different values
    ([{'tag': 1}, {'tag': 2}, {}], {'tag': 1, '.duplicate.1.of.tag': 2}),
    # tag exists, multiple duplicate entries with different values
    (
        [{'tag': 1}, {'tag': 2}, {'tag': 3}],
        {'.duplicate.1.of.tag': 1, '.duplicate.2.of.tag': 2},
    ),
    # existing duplicate tag remains unchanged, no duplicate entries
    ([{'.duplicate.1.of.tag': 1}], {}),
    # existing duplicate tag remains unchanged, duplicate entry
    ([{'tag': 1}, {'.duplicate.1.of.tag': 2}], {'tag': 1}),
    # existing duplicate tag remains unchanged, even if out of order
    ([{'tag': 1}, {'.duplicate.10.of.tag': 2}], {'tag': 1}),
    # existing duplicate tag is skipped
    (
        [
            {'.duplicate.1.of.tag': 1},
            {'.duplicate.1.of.tag': 2},
            {'.duplicate.1.of.tag': 3},
        ],
        {'tag': 1, '.duplicate.2.of.tag': 2},
    ),
    # out of order duplicate tags get renumbered
    (
        [
            {'.duplicate.20.of.tag': 1, '.duplicate.10.of.tag': 2},
            {'.duplicate.10.of.tag': 3},
            {'tag': 4},
        ],
        {
            '.duplicate.1.of.tag': 1,
            '.duplicate.2.of.tag': 2,
            '.duplicate.3.of.tag': 3,
        },
    ),
]


@pytest.mark.parametrize('tags, expected', MERGE_TAGS_DATA)
def test_merge_tags(reader, parser, tags, expected):
    *duplicates, entry = tags

    def make_reserved(n):
        return '.' + n

    assert dict(merge_tags(make_reserved, entry, duplicates)) == expected


# TODO: with_maybe_published_or_updated
def test_recent_sort_copying(reader, parser, allow_short_content):
    reader.add_feed(parser.feed(1))

    parser.entry(1, 1, title='title', summary='summary')
    reader._now = lambda: datetime(2010, 1, 10)
    reader.update_feeds()

    parser.entry(1, 2, title='title', summary='summary')
    parser.entry(1, 3, title='other')
    reader._now = lambda: datetime(2010, 1, 20)
    reader.update_feeds()

    init_reader(reader)

    del parser.entries[1][1]
    del parser.entries[1][2]
    four = parser.entry(1, 4, title='title', summary='summary')
    reader._now = lambda: datetime(2010, 2, 1)
    reader.update_feeds()

    assert [eval(e.id)[1] for e in reader.get_entries(sort='recent')] == [3, 4]

    actual_recent_sort = reader._storage.get_entry_recent_sort(four.resource_id)
    assert actual_recent_sort == datetime(2010, 1, 10)


@pytest.mark.parametrize('tokenize', [tokenize_title, tokenize_content])
@pytest.mark.parametrize(
    'input, expected',
    [
        ('\n\n foo  Bar  ', ('foo', 'bar')),
        ('<b>foo</B> &nbsp; bar</p>', ('foo', 'bar')),
        ('Ará Orún', ('ara', 'orun')),
        ('汉语 漢語', ('汉语', '漢語')),
        ('1.0, 1.0.dev0; 2020-10-10', ('1.0', '1.0.dev0', '2020-10-10')),
        ('1.2.3.4 11.22.33.44', ('1.2.3', '4', '11.22.33', '44')),
    ],
)
def test_tokenize(tokenize, input, expected):
    assert tokenize(input) == expected


def with_edits(text, edits, end_at=None):
    if end_at:
        text = re.search(rf"(?s).*?{end_at}", text)[0]
    edited = text
    for edit in edits:
        edited = edited.replace(*edit)
    return text, edited


TEXT = """\
So, you're doing some I/O bound stuff, in parallel.

Maybe you're scraping some websites – a lot of websites.

Maybe you're updating or deleting millions of DynamoDB items.

You've got your [ThreadPoolExecutor],
you've increased the number of threads and tuned connection limits...
but after some point, **it's just not getting any faster**.
You look at your Python process,
and you see CPU utilization hovers above 100%.

You *could* split the work into batches
and have a [ProcessPoolExecutor]
run your original code in separate processes.
But that requires yet more code, and a bunch of changes, which is no fun.
And maybe your input is not that easy to split into batches.

If only we had an executor that
**worked seamlessly across processes and threads**.

Well, you're in luck, since that's exactly what we're building today!

And even better, in a couple years you won't even need it anymore.

---

**asyncio-thread-runner** allows you to run async code from sync code.

This is useful when you're doing some sync stuff, but:

* you also need to do some async stuff, **without** making **everything async**
* maybe the sync stuff is an existing application
* maybe you still want to use your favorite sync library
* or maybe you need just a little async, without having to pay the full price

Features:

* unlike [asyncio.run()], it provides a **long-lived event loop**
* unlike [asyncio.Runner], it runs in a dedicated thread, and you can use it from **multiple threads**
* it allows you to use **async context managers** and **iterables** from sync code
* check out [this article](https://death.andgravity.com/asyncio-bridge) for why these are useful

"""
EDITS = [
    ("you're", "youre", 1),
    ("parallel", "paralel"),
    ("a lot", "lots"),
    ("PoolExecutor", " Pool Executor"),
    ("work", "input"),
    ("even need it anymore", ""),
]
EXTRA_EDITS = EDITS + [
    ("So", "Soo"),
    ("stuff", "thing"),
    ("millions", "billions"),
    ("across processes and threads", ""),
]


IS_DUPLICATE_DATA = [
    ('one two three four', 'one two three four', True),
    ('one two three four', 'one two thre four', True),
    ('one two three four', 'one two three five', False),
    ('hello', 'helo', True),
    ('hello', 'helio', False),
    (*with_edits(TEXT, EDITS, "you're"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "you're"), False),
    (*with_edits(TEXT, EDITS, "parallel"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "parallel"), False),
    (*with_edits(TEXT, EDITS, "items"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "items"), False),
    (*with_edits(TEXT, EDITS, "anymore"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "anymore"), False),
    (*with_edits(TEXT, EDITS, "$"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "$"), False),
]


def long_ids(s):
    if isinstance(s, str):
        if len(s) > 20:
            return s[:6] + '...' + s[-10:]


@pytest.mark.parametrize('one, two, expected', IS_DUPLICATE_DATA, ids=long_ids)
def test_is_duplicate(one, two, expected):
    actual = is_duplicate(tokenize_content(one), tokenize_content(two))
    assert actual == expected


@pytest.mark.parametrize(
    'seq, n, pad, expected',
    [
        ([1, 2, 3], 2, False, [(1, 2), (2, 3)]),
        ([1, 2], 2, False, [(1, 2)]),
        ([1], 2, False, []),
        ([], 2, False, []),
        ([1, 2], 2, True, [(None, 1), (1, 2), (2, None)]),
        ([1], 2, True, [(None, 1), (1, None)]),
        ([], 2, True, [(None, None)]),
    ],
)
def test_ngrams(seq, n, pad, expected):
    assert list(ngrams(seq, n, pad)) == expected


def test_common_prefixes():
    text = """\
        uncommon

        common one
        common two

        tiny prefix
        tiny is skipped

        subprefix is used
        subprefix is too
        subprefix if
        subprefix significant

        shortest xx wins
        shortest xx if
        shortest yy drop-off
        shortest yy is
        shortest zz too
        shortest zz sharp

        too xx but
        too xx not
        too yy if
        too yy it's
        too zz too
        too zz short

        duplicate counted just once
        duplicate counted just once

        but counted once
        but counted once
        but counted

    """
    documents = [tuple(l.split()) for l in text.splitlines()]
    assert set(common_prefixes(documents, min_df=2)) == {
        ('common',),
        ('subprefix', 'is'),
        ('subprefix',),
        ('shortest',),
        ('too', 'xx'),
        ('too', 'yy'),
        ('too', 'zz'),
        ('but', 'counted'),
    }


@pytest.mark.parametrize(
    'items, only_items, expected',
    [
        ('abc', 'a', [['a']]),
        ('aAb', 'a', [['a', 'A']]),
        ('abc', '', []),
        ('', 'abc', []),
        (['a', ''], 'a', [['a']]),
    ],
)
def test_group_by(items, only_items, expected):
    assert list(group_by(str.upper, items, only_items)) == expected


@pytest.mark.parametrize(
    'input, expected',
    [
        (None, None),
        ('', None),
        ('Https://Host/Path?Query=Str#Frag', 'https://host/Path?Query=Str#Frag'),
        ('http://host', 'https://host'),
        ('trailing/slash/?q=s', 'trailing/slash?q=s'),
        ('https://in[valid', None),
    ],
)
def test_normalize_url(input, expected):
    assert normalize_url(input) == expected
