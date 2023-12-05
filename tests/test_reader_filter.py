import pytest
from fakeparser import Parser
from reader_methods import get_entries
from reader_methods import get_entries_random
from reader_methods import get_entries_recent
from reader_methods import get_feeds
from reader_methods import search_entries
from reader_methods import search_entries_random
from reader_methods import search_entries_recent
from reader_methods import search_entries_relevant
from utils import utc_datetime as datetime


with_call_feed_tags_method = pytest.mark.parametrize(
    # tags_arg_name is exposed so we can later test get_entries(tags=...)
    'call_method, tags_arg_name',
    [
        (get_entries_recent, 'feed_tags'),
        pytest.param(get_entries_random, 'feed_tags', marks=pytest.mark.slow),
        (search_entries_relevant, 'feed_tags'),
        pytest.param(search_entries_recent, 'feed_tags', marks=pytest.mark.slow),
        pytest.param(search_entries_random, 'feed_tags', marks=pytest.mark.slow),
        # TODO: maybe test all the get_feeds sort orders
        (get_feeds, 'tags'),
    ],
)


ALL_IDS = {(1, 1), (1, 2), (2, 1), (3, 1)}


@with_call_feed_tags_method
@pytest.mark.parametrize(
    'args, expected',
    [
        ((), ALL_IDS),
        ((None,), ALL_IDS),
        (([],), ALL_IDS),
        (([[]],), ALL_IDS),
        ((True,), ALL_IDS - {(3, 1)}),
        (([True],), ALL_IDS - {(3, 1)}),
        ((False,), {(3, 1)}),
        (([False],), {(3, 1)}),
        (([True, False],), set()),
        (([[True, False]],), ALL_IDS),
        ((['tag'],), ALL_IDS - {(3, 1)}),
        (([['tag']],), ALL_IDS - {(3, 1)}),
        ((['tag', 'tag'],), ALL_IDS - {(3, 1)}),
        (([['tag'], ['tag']],), ALL_IDS - {(3, 1)}),
        (([['tag', 'tag']],), ALL_IDS - {(3, 1)}),
        ((['-tag'],), {(3, 1)}),
        ((['unknown'],), set()),
        ((['-unknown'],), ALL_IDS),
        ((['first'],), {(1, 1), (1, 2)}),
        ((['second'],), {(2, 1)}),
        ((['first', 'second'],), set()),
        (([['first'], ['second']],), set()),
        (([['first', 'second']],), {(1, 1), (1, 2), (2, 1)}),
        ((['first', 'tag'],), {(1, 1), (1, 2)}),
        ((['second', 'tag'],), {(2, 1)}),
        (([['first', 'second'], 'tag'],), {(1, 1), (1, 2), (2, 1)}),
        (([['first'], ['tag']],), {(1, 1), (1, 2)}),
        (([['first', 'tag']],), {(1, 1), (1, 2), (2, 1)}),
        ((['-first', 'tag'],), {(2, 1)}),
        (([['first', '-tag']],), ALL_IDS - {(2, 1)}),
        (([[False, 'first']],), {(1, 1), (1, 2), (3, 1)}),
        (([True, '-first'],), {(2, 1)}),
    ],
)
def test_tags(reader, call_method, tags_arg_name, args, expected):
    reader._parser = parser = Parser()

    one = parser.feed(1, datetime(2010, 1, 1))  # tag, first
    one_one = parser.entry(1, '1', datetime(2010, 1, 1))
    one_two = parser.entry(1, '2', datetime(2010, 2, 1))

    two = parser.feed(2, datetime(2010, 1, 1))  # tag, second
    two_one = parser.entry(2, '1', datetime(2010, 1, 1))

    three = parser.feed(3, datetime(2010, 1, 1))  # <no tags>
    three_one = parser.entry(3, '1', datetime(2010, 1, 1))

    for feed in one, two, three:
        reader.add_feed(feed)

    reader.update_feeds()
    call_method.after_update(reader)

    reader.set_tag(one, 'tag')
    reader.set_tag(one, 'first')
    reader.set_tag(two, 'tag')
    reader.set_tag(two, 'second')

    if '_entries' in call_method.__name__:
        resource_id_length = 2
    elif '_feeds' in call_method.__name__:
        resource_id_length = 1
    else:
        assert False, call_method

    assert len(args) <= 1
    kwargs = {tags_arg_name: a for a in args}

    actual_set = {
        tuple(map(eval, o.resource_id)) for o in call_method(reader, **kwargs)
    }
    expected_set = {t[:resource_id_length] for t in expected}
    assert actual_set == expected_set, kwargs


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
