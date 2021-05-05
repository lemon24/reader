"""
reader.mark_as_read
~~~~~~~~~~~~~~~~~~~

Mark added entries of specific feeds as read if their title matches a regex.

To configure, set the ``make_reader_reserved_name('mark_as_read')``
(by default, ``.reader.mark_as_read``)
feed metadata to something like::

    {
        "title": ["first-regex", "second-regex"]
    }


.. todo::

    Possible optimizations:

    1.  Add the entry directly as read instead of marking it afterwards
        (requires a new hook to process the entry before it is added,
        and Storage support).

..
    Implemented for https://github.com/lemon24/reader/issues/79.

"""
import logging
import re

from reader.exceptions import MetadataNotFoundError

# avoid circular imports

log = logging.getLogger(__name__)


def _get_config(reader, feed_url, metadata_key, patterns_key):
    try:
        metadata = reader.get_feed_metadata(feed_url, metadata_key)
    except MetadataNotFoundError:
        return None

    if isinstance(metadata, dict):
        patterns = metadata.get(patterns_key, [])
        if isinstance(patterns, list):
            if all(isinstance(p, str) for p in patterns):
                return patterns

    # TODO: there should be a hook to allow plugins to validate metadata
    log.warning("%s: invalid mark_as_read config metadata: %s", feed_url, metadata_key)
    return []


def _plugin(reader, entry):
    metadata_name = reader.make_reader_reserved_name('mark_as_read')
    patterns = _get_config(reader, entry.feed_url, metadata_name, 'title')

    # Fall back to the old config format.
    # TODO: Remove the fallback before 2.0.
    # NOTE: This won't do anything for feeds that weren't modified. All feeds should be marked as stale at least once before 2.0.
    # TODO: It would be nice to have a hook for running this kind of "migration"...
    if patterns is None:
        old_patterns = _get_config(
            reader, entry.feed_url, 'regex-mark-as-read', 'patterns'
        )
        if old_patterns is not None:
            reader.set_feed_metadata(
                entry.feed_url, metadata_name, {'title': old_patterns}
            )
            reader.delete_feed_metadata(entry.feed_url, 'regex-mark-as-read')
            patterns = old_patterns

    for pattern in patterns or ():
        if re.search(pattern, entry.title):
            reader.mark_as_read(entry)
            return


def init_reader(reader):
    reader._post_entry_add_plugins.append(_plugin)
