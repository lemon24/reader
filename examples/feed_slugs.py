"""
Feed slugs
~~~~~~~~~~

This is a recipe of what a "get feed by slug" plugin may look like
(e.g. for user-defined short URLs).

Usage::

    >>> from reader import make_reader
    >>> import feed_slugs
    >>> reader = make_reader('db.sqlite', plugins=[feed_slugs.init_reader])
    >>> reader.set_feed_slug('https://death.andgravity.com/_feed/index.xml', 'andgravity')
    >>> reader.get_feed_by_slug('andgravity')
    Feed(url='https://death.andgravity.com/_feed/index.xml', ...)
    >>> reader.get_feed_slug(_.url)
    'andgravity'

..
    Originally implemented for https://github.com/lemon24/reader/issues/358.

"""

# fmt: off
# flake8: noqa

def init_reader(reader):
    # __get__() allows help(reader.get_feed_by_slug) to work
    reader.get_feed_by_slug = get_feed_by_slug.__get__(reader)
    reader.get_feed_slug = get_feed_slug.__get__(reader)
    reader.set_feed_slug = set_feed_slug.__get__(reader)

def get_feed_by_slug(reader, slug):
    tag = _make_tag(reader, slug)
    return next(reader.get_feeds(tags=[tag], limit=1), None)

def get_feed_slug(reader, feed):
    if tag := next(_get_tags(reader, feed), None):
        return tag.removeprefix(_make_tag(reader, ''))
    return None

def set_feed_slug(reader, feed, slug: str | None):
    feed = reader.get_feed(feed)
    tag = _make_tag(reader, slug)

    if not slug:
        reader.delete_tag(feed, tag, missing_ok=True)
        return

    reader.set_tag(feed, tag)

    # ensure only one feed has the slug; technically a race condition,
    # when it happens no feed will have the tag
    for other_feed in reader.get_feeds(tags=[tag]):
        if feed.url != other_feed.url:
            reader.delete_tag(other_feed, tag, missing_ok=True)

    # ensure feed has only one slug; technically a race condition,
    # when it happens the feed will have no slug
    for other_tag in _get_tags(reader, feed):
        if tag != other_tag:
            reader.delete_tag(feed, other_tag, missing_ok=True)

def _make_tag(reader, slug):
    return reader.make_plugin_reserved_name('slug', slug)

def _get_tags(reader, resource):
    prefix = _make_tag(reader, '')
    # filter tags by prefix would make this faster,
    # https://github.com/lemon24/reader/issues/309
    return (t for t in reader.get_tag_keys(resource) if t.startswith(prefix))

if __name__ == '__main__':
    from reader import make_reader

    reader = make_reader('db.sqlite', plugins=[init_reader])
    url = 'https://death.andgravity.com/_feed/index.xml'

    reader.set_feed_slug(url, 'one')
    print(
        reader.get_feed_slug(url),
        getattr(reader.get_feed_by_slug('one'), 'url', None),
    )

    reader.set_feed_slug(url, 'two')
    print(
        reader.get_feed_slug(url),
        getattr(reader.get_feed_by_slug('two'), 'url', None),
    )

    reader.set_feed_slug('https://xkcd.com/atom.xml', 'two')
    print(
        reader.get_feed_slug(url),
        getattr(reader.get_feed_by_slug('two'), 'url', None),
    )
