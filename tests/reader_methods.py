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

for name, obj in dict(globals()).items():
    if name.startswith('search_entries'):
        obj.after_update = enable_and_update_search
