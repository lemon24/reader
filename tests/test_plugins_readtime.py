import pytest

from reader import Content
from reader import Entry
from utils import rename_argument
from utils import utc_datetime as datetime


def get_readtimes(reader):
    return {
        e.id: reader.get_tag(e, '.reader.readtime', {}).get('seconds')
        for e in reader.get_entries()
    }


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), 0),
        (dict(summary='summary'), 1),
        (dict(content=[Content('content', 'text/plain')]), 1),
        (dict(summary='summary ' * 20, content=[Content('content ' * 5)]), 2),
    ],
)
def test_basic(make_reader, parser, kwargs, expected):
    reader = make_reader(':memory:', plugins=['reader.readtime'])
    feed = parser.feed(1)
    entry = parser.entry(1, 1, **kwargs)
    reader.add_feed(feed)
    reader.update_feeds()
    assert reader.get_tag(entry, '.reader.readtime') == {'seconds': expected}


def test_normal_workflow(make_reader, db_path, parser, monkeypatch):
    def fake_readtime(entry):
        fake_readtime.call_count += 1
        return {'seconds': len(entry.summary.split())}

    fake_readtime.call_count = 0
    monkeypatch.setattr('reader.plugins.readtime._readtime_of_entry', fake_readtime)

    reader = make_reader(db_path)
    feed = parser.feed(1)
    reader.add_feed(feed)

    one = parser.entry(1, 1, datetime(2010, 1, 1), title='title', summary='summary')
    two = parser.entry(
        1, 2, datetime(2010, 1, 1), title='title', summary='summary ' * 2
    )
    reader.update_feeds()

    assert get_readtimes(reader) == {'1, 1': None, '1, 2': None}

    reader = make_reader(db_path, plugins=['reader.readtime'])

    three = parser.entry(
        1, 3, datetime(2010, 1, 1), title='title', summary='summary ' * 3
    )
    reader.update_feeds()

    assert get_readtimes(reader) == {'1, 1': 1, '1, 2': 2, '1, 3': 3}
    assert fake_readtime.call_count == 3
    fake_readtime.call_count = 0

    two = parser.entry(
        1, 2, datetime(2010, 1, 1), title='title', summary='summary ' * 4
    )
    reader.update_feeds()

    assert get_readtimes(reader) == {'1, 1': 1, '1, 2': 4, '1, 3': 3}
    assert fake_readtime.call_count == 1
    fake_readtime.call_count = 0


@pytest.fixture
def backfill_reader(make_reader, db_path, parser, monkeypatch):
    monkeypatch.setattr(
        'reader.plugins.readtime._readtime_of_entry', lambda _: {'seconds': 1}
    )

    reader = make_reader(db_path)

    for i in (1, 2):
        feed = parser.feed(i)
        parser.entry(i, 1, datetime(2010, 1, 1), summary='summary')
        reader.add_feed(feed)

    reader.update_feeds()

    reader = make_reader(db_path, plugins=['reader.readtime'])

    return reader


@rename_argument('reader', 'backfill_reader')
def test_update_feeds_backfills_only_selected(reader):
    two, one = reader.get_feeds(sort='added')
    reader.update_feeds(feed=one)
    assert get_readtimes(reader) == {'1, 1': 1, '2, 1': None}


@rename_argument('reader', 'backfill_reader')
def test_update_feed_does_not_backfill_without_update_feeds(reader):
    two, one = reader.get_feeds(sort='added')
    reader.update_feed(one)
    assert get_readtimes(reader) == {'1, 1': None, '2, 1': None}
    assert reader.get_tag((), '.reader.readtime', None) == None


@rename_argument('reader', 'backfill_reader')
def test_update_feed_backfills_after_any_update_feeds(reader):
    two, one = reader.get_feeds(sort='added')
    reader.update_feeds(tags=['none'])
    reader.update_feed(one)
    assert get_readtimes(reader) == {'1, 1': 1, '2, 1': None}
    assert reader.get_tag(one, '.reader.readtime', None) == None
    assert reader.get_tag(two, '.reader.readtime') == {'backfill': 'pending'}
    assert reader.get_tag((), '.reader.readtime') == {'backfill': 'done'}


@rename_argument('reader', 'backfill_reader')
def test_update_feeds_always_backfills_updates_disabled(reader):
    two, one = reader.get_feeds(sort='added')
    reader.disable_feed_updates(one)
    reader.update_feeds(tags=['none'])
    assert get_readtimes(reader) == {'1, 1': 1, '2, 1': None}


@rename_argument('reader', 'backfill_reader')
def test_existing_backfill_is_not_replaced(reader):
    two, one = reader.get_feeds(sort='added')
    reader.set_tag(('1', '1, 1'), '.reader.readtime', {'seconds': 1234})
    reader.update_feeds()
    assert get_readtimes(reader) == {'1, 1': 1234, '2, 1': 1}


@rename_argument('reader', 'backfill_reader')
def test_prevent_backfill(reader):
    reader.set_tag((), '.reader.readtime', {'backfill': 'done'})
    reader.update_feeds()
    assert get_readtimes(reader) == {'1, 1': None, '2, 1': None}


@rename_argument('reader', 'backfill_reader')
def test_schedule_backfill(reader):
    two, one = reader.get_feeds(sort='added')
    reader.set_tag((), '.reader.readtime', {'backfill': 'done'})
    reader.set_tag(one, '.reader.readtime', {'backfill': 'pending'})
    reader.update_feeds()
    assert get_readtimes(reader) == {'1, 1': 1, '2, 1': None}


@pytest.mark.parametrize(
    'text, is_html, expected_seconds',
    [
        ('', False, 0),
        ('', True, 0),
        ('\n\n', False, 0),
        ('\n\n', True, 0),
        ('content', False, 1),
        ('content', True, 1),
        ('<tag></tag>', True, 0),
        ('<tag>content</tag>', True, 1),
        ('<script>content</script>', True, 0),
        ('content ' * 40, True, 10),
        ('<tag>content</tag>' * 40, True, 10),
        ('<tag>content</tag>' * 40 + '<img src=""/>', True, 22),
        ('<tag>content</tag>' * 40 + '<img src=""/>' * 2, True, 33),
    ],
)
def test_readtime(text, is_html, expected_seconds):
    from reader.plugins.readtime import _readtime_of_entry as readtime

    entry = Entry(
        'id', content=[Content(text, 'text/html' if is_html else 'text/plain')]
    )

    assert readtime(entry) == {'seconds': expected_seconds}


def test_entry_deleted(make_reader, parser):
    def delete_entry_plugin(reader):
        def hook(reader, entry, _):
            if entry.resource_id == ('1', '1, 1'):
                reader._storage.delete_entries([entry.resource_id])

        reader.after_entry_update_hooks.append(hook)

    reader = make_reader(':memory:', plugins=[delete_entry_plugin, 'reader.readtime'])
    reader.add_feed(parser.feed(1))
    parser.entry(1, 1)
    parser.entry(1, 2)

    # shouldn't fail
    reader.update_feeds()

    assert {eval(e.id)[1] for e in reader.get_entries()} == {2}
