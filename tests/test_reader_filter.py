from fakeparser import Parser
from utils import utc_datetime as datetime


def test_entry_tags_basic(reader):
    # roughly modeled after test_filtering_tags

    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))
    one_one = parser.entry(1, 1, datetime(2010, 1, 1))
    one_two = parser.entry(1, 2, datetime(2010, 2, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    two_one = parser.entry(2, 1, datetime(2010, 1, 1))

    for feed in one, two:
        reader.add_feed(feed)

    reader.update_feeds()

    reader.set_tag(one_one, 'tag')
    reader.set_tag(one_one, 'first')
    reader.set_tag(two_one, 'tag')
    reader.set_tag(two_one, 'second')

    def get(tags):
        return {e.id for e in reader.get_entries(tags=tags)}

    assert get(None) == {'1, 1', '1, 2', '2, 1'}
    assert get(['tag']) == {'1, 1', '2, 1'}
    assert get(['first']) == {'1, 1'}
    assert get(['second']) == {'2, 1'}
    assert get(True) == {'1, 1', '2, 1'}
    assert get(False) == {'1, 2'}
    assert get(['unknown']) == set()

    def count(tags):
        return reader.get_entry_counts(tags=tags).total

    assert count(None) == 3
    assert count(['tag']) == 2
    assert count(['first']) == 1
    assert count(['unknown']) == 0
