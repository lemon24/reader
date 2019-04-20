import pytest

from reader.core.updater import Updater
from reader.core.types import FeedForUpdate, Entry


@pytest.mark.xfail
def test_prepare_entries_for_update():
    updater = Updater(FeedForUpdate('feed', None, None, None, False, None), 'now', 'global_now')

    assert list(updater.prepare_entries_for_update([
        (True, 'one', 'last_updated'),
        (False, 'two', 'last_updated'),
    ])) == [
        ('feed', 'one', 'last_updated', 'global_now'),
        ('feed', 'two', 'last_updated', None),
    ]

    assert updater.updated_entries == ['two']
    assert updater.new_entries == ['one']


