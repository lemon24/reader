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


def _migrate_old_config_format(reader, url):
    # Fall back to the old config format.
    # A bit wasteful, since this runs on every update.
    # TODO: Remove this before 1.18.

    metadata_name = reader.make_reader_reserved_name('mark_as_read')

    old_patterns = _get_config(reader, url, 'regex-mark-as-read', 'patterns')
    if old_patterns is None:
        return

    new_patterns = _get_config(reader, url, metadata_name, 'title')
    if new_patterns is not None:  # pragma: no cover
        log.warning(
            "%s: found both old-style and new-style mark_as_read config metadata, not migrating",
            url,
        )
        return

    reader.set_feed_metadata(url, metadata_name, {'title': old_patterns})
    reader.delete_feed_metadata(url, 'regex-mark-as-read')


def _mark_as_read(reader, entry):
    metadata_name = reader.make_reader_reserved_name('mark_as_read')
    patterns = _get_config(reader, entry.feed_url, metadata_name, 'title')

    for pattern in patterns or ():
        if re.search(pattern, entry.title):
            reader.mark_as_read(entry)
            return


def init_reader(reader):
    reader._post_feed_update_plugins.append(_migrate_old_config_format)
    reader._post_entry_add_plugins.append(_mark_as_read)
