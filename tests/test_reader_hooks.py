from datetime import datetime

from fakeparser import Parser

from reader import EntryUpdateStatus


def test_post_entry_update_hooks(reader):
    parser = Parser()
    reader._parser = parser

    plugin_calls = []

    def first_plugin(r, e, s):
        assert r is reader
        plugin_calls.append((first_plugin, e, s))

    def second_plugin(r, e, s):
        assert r is reader
        plugin_calls.append((second_plugin, e, s))

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader.after_entry_update_hooks.append(first_plugin)
    reader.update_feeds()
    assert plugin_calls == [(first_plugin, one, EntryUpdateStatus.NEW)]
    assert set(e.id for e in reader.get_entries()) == {'1, 1'}

    plugin_calls[:] = []

    feed = parser.feed(1, datetime(2010, 1, 2))
    one = parser.entry(1, 1, datetime(2010, 1, 2))
    two = parser.entry(1, 2, datetime(2010, 1, 2))
    reader.after_entry_update_hooks.append(second_plugin)
    reader.update_feeds()
    assert plugin_calls == [
        (first_plugin, two, EntryUpdateStatus.NEW),
        (second_plugin, two, EntryUpdateStatus.NEW),
        (first_plugin, one, EntryUpdateStatus.MODIFIED),
        (second_plugin, one, EntryUpdateStatus.MODIFIED),
    ]
    assert set(e.id for e in reader.get_entries()) == {'1, 1', '1, 2'}

    # TODO: What is the expected behavior if a plugin raises an exception?
