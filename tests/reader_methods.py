from reader import EntryCounts
from reader import EntrySearchCounts
from reader import UpdateError
from reader import UpdateResult


def do_nothing(reader):
    pass


def enable_and_update_search(reader):
    reader.enable_search()
    reader.update_search()


def get_entries(reader, **kwargs):
    return reader.get_entries(**kwargs)


def get_entries_recent(reader, **kwargs):
    return reader.get_entries(sort='recent', **kwargs)


def get_entries_recent_paginated(reader, **kwargs):
    starting_after = None
    while True:
        entries = list(
            reader.get_entries(
                sort='recent', limit=1, starting_after=starting_after, **kwargs
            )
        )
        if not entries:
            break
        yield from entries
        starting_after = entries[-1]


def get_entries_random(reader, **kwargs):
    return reader.get_entries(sort='random', **kwargs)


def search_entries(reader, **kwargs):
    return reader.search_entries('entry', **kwargs)


def search_entries_relevant(reader, **kwargs):
    return reader.search_entries('entry', sort='relevant', **kwargs)


def search_entries_recent(reader, **kwargs):
    return reader.search_entries('entry', sort='recent', **kwargs)


def search_entries_recent_paginated(reader, **kwargs):
    starting_after = None
    while True:
        entries = list(
            reader.search_entries(
                'entry', sort='recent', limit=1, starting_after=starting_after, **kwargs
            )
        )
        if not entries:
            break
        yield from entries
        starting_after = entries[-1]


def search_entries_random(reader, **kwargs):
    return reader.search_entries('entry', sort='random', **kwargs)


def get_feeds(reader, **kwargs):
    return reader.get_feeds(**kwargs)


for name, obj in dict(globals()).items():
    if name.startswith('get_'):
        obj.after_update = do_nothing
    if name.startswith('search_entries'):
        obj.after_update = enable_and_update_search


def get_entry_counts(reader, **kwargs) -> EntryCounts:
    return reader.get_entry_counts(**kwargs)


def search_entry_counts(reader, **kwargs) -> EntrySearchCounts:
    return reader.search_entry_counts('entry', **kwargs)


for name, obj in dict(globals()).items():
    if name.startswith('get_entries'):
        obj.counts = get_entry_counts
    if name.startswith('search_entries'):
        obj.counts = search_entry_counts

get_entry_counts.get_entries = get_entries
search_entry_counts.get_entries = search_entries


class _update_feed_methods:
    # TODO: we can remove the update_feeds() variant if we add a test to confirm update_feeds is a thin wrapper over update_feeds_iter

    def update_feeds(reader, _):
        reader.update_feeds()

    def update_feeds_workers(reader, _):
        reader.update_feeds(workers=2)

    def update_feeds_iter(reader, _):
        for _ in reader.update_feeds_iter():
            pass

    def update_feeds_iter_workers(reader, _):
        for _ in reader.update_feeds_iter(workers=2):
            pass

    def update_feed(reader, url):
        reader.update_feed(url)


# update_feed(reader, feed) -> None
update_feed_methods = [
    v for k, v in _update_feed_methods.__dict__.items() if not k.startswith('_')
]


class _update_feeds_iter_methods:
    def update_feeds_iter(reader):
        return reader.update_feeds_iter()

    def update_feeds_iter_workers(reader):
        return reader.update_feeds_iter(workers=2)

    def update_feeds_iter_simulated(reader):
        for feed in reader.get_feeds(updates_enabled=True):
            try:
                yield UpdateResult(feed.url, reader.update_feed(feed))
            except UpdateError as e:
                yield UpdateResult(feed.url, e)


# update_feeds(reader) -> (url, result), ...
update_feeds_iter_methods = [
    v for k, v in _update_feeds_iter_methods.__dict__.items() if not k.startswith('_')
]
