"""
global_metadata
~~~~~~~~~~~~~~~

.. module:: reader
  :noindex:

As of reader 2.7, only feeds can have metadata attached.

However, global metadata can be simulated
by using a fake feed with updates disabled.

This plugin adds global metadata methods
analogous to the feed metadata ones::

    >>> from reader._plugins import global_metadata
    >>> reader = make_reader(db_path, plugins=[global_metadata.init_reader])
    >>> reader.get_global_metadata_item('key', 'default')
    'default'
    >>> reader.set_global_metadata_item('key', 'value')
    >>> reader.get_global_metadata_item('key')
    'value'
    >>> reader.set_global_metadata_item('another', {'one': [2]})
    >>> dict(reader.get_global_metadata())
    {'another': {'one': [2]}, 'key': 'value'}

The global metadata is backed by the ``reader:global-metadata`` feed.

For convenience, the fake feed and all feeds with the ``.reader.hidden`` tag
are skipped by :meth:`~Reader.get_feeds()`.
Use the method from the class to get them::

    >>> 'reader:global-metadata' in {f.url for f in reader.get_feeds()}
    False
    >>> 'reader:global-metadata' in {f.url for f in type(reader).get_feeds(reader)}
    True

Implemented for https://github.com/lemon24/reader/issues/267.

"""
from reader import FeedExistsError

METADATA_FEED_URL = 'reader:global-metadata'
HIDDEN_TAG_NAME = 'hidden'


def init_reader(reader):
    url = METADATA_FEED_URL
    tag = reader.make_reader_reserved_name(HIDDEN_TAG_NAME)

    try:
        reader.add_feed(url, allow_invalid_url=True)
    except FeedExistsError:
        pass
    else:
        reader.disable_feed_updates(url)
        reader.set_tag(url, tag)

    def get_global_metadata(*args):
        return reader.get_tags(url, *args)

    def get_global_metadata_item(*args):
        return reader.get_tag(url, *args)

    def set_global_metadata_item(*args):
        reader.set_tag(url, *args)

    def delete_global_metadata_item(*args):
        reader.delete_tag(url, *args)

    reader.get_global_metadata = get_global_metadata
    reader.get_global_metadata_item = get_global_metadata_item
    reader.set_global_metadata_item = set_global_metadata_item
    reader.delete_global_metadata_item = delete_global_metadata_item

    # in order for .reader.hidden to work in all contexts,
    # we should wrap get_entries() and search_entries() too;
    # maybe this is worth breaking into a separate plugin?

    def get_feeds(*, tags=None, **kwargs):
        tags = list(tags) if tags else []
        tags += [f'-{tag}']
        return original_get_feeds(tags=tags, **kwargs)

    original_get_feeds = reader.get_feeds
    get_feeds.__wrapped__ = reader.get_feeds
    reader.get_feeds = get_feeds
