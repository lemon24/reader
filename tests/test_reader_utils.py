from unittest.mock import Mock

import pytest

from reader import EntryNotFoundError
from reader.utils import archive_entries


def test_archive_entries(reader, parser):
    reader.copy_entry = Mock(wraps=reader.copy_entry)

    feed = parser.feed(1)
    one = parser.entry(1, 'one', title='one')
    two = parser.entry(1, '&?:/', title='not URL safe')
    reader.add_feed(feed)
    reader.update_feeds()

    # archive an entry, archived does not exist

    reader.copy_entry.reset_mock()
    archive_entries(reader, [one])

    assert len(reader.copy_entry.call_args_list) == 1
    assert {e.resource_id + (e.title,) for e in reader.get_entries()} == {
        ('1', 'one', 'one'),
        ('1', '&?:/', 'not URL safe'),
        ('reader:archived', 'reader:archived?feed=1&entry=one', 'one'),
    }
    archived = reader.get_feed('reader:archived')
    assert archived.updates_enabled is False
    assert archived.user_title == 'Archived'

    # archive two entries (one already archived), archived exists

    one = parser.entry(1, 'one', title='new one')
    reader.update_feeds()

    reader.copy_entry.reset_mock()
    archive_entries(reader, [one, two])

    # 3 because one is copied (exists error), deleted, and then copied again
    assert len(reader.copy_entry.call_args_list) == 3
    assert {e.resource_id + (e.title,) for e in reader.get_entries()} == {
        ('1', 'one', 'new one'),
        ('1', '&?:/', 'not URL safe'),
        ('reader:archived', 'reader:archived?feed=1&entry=one', 'new one'),
        (
            'reader:archived',
            'reader:archived?feed=1&entry=%26%3F%3A%2F',
            'not URL safe',
        ),
    }

    # archive inexistent entry

    with pytest.raises(EntryNotFoundError):
        archive_entries(reader, [('1', 'inexistent')])
