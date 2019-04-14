import pytest

from reader.core.updater import Updater
from reader.core.storage import FeedForUpdate


def test_prepare_entries_for_update():
    updater = Updater(FeedForUpdate('feed', None, None, None, False, None), 'now')

    assert list(updater.prepare_entries_for_update([
        (True, 'one', 'updated', 'last_updated'),
        (False, 'two', 'updated', 'last_updated'),
    ])) == [
        ('feed', 'one', 'updated', 'last_updated', updater.now),
        ('feed', 'two', 'updated', 'last_updated', None),
    ]

    assert updater.updated_entries == ['two']
    assert updater.new_entries == ['one']


