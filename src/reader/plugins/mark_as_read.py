"""
reader.mark_as_read
~~~~~~~~~~~~~~~~~~~

.. module:: reader
  :noindex:

Mark added entries of specific feeds as read + unimportant
if their title matches a regex.

To configure, set the ``make_reader_reserved_name('mark-as-read')``
(by default, ``.reader.mark-as-read``)
feed metadata to something like::

    {
        "title": ["first-regex", "second-regex"]
    }


.. versionchanged:: 2.4
    Explicitly mark matching entries as unimportant.

.. versionchanged:: 2.7
    Use the ``.reader.mark-as-read`` metadata for configuration.
    Feeds using the old metadata, ``.reader.mark_as_read``,
    will be migrated automatically on update until `reader` 3.0.


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
from reader.types import EntryUpdateStatus

# avoid circular imports

log = logging.getLogger(__name__)


def _get_config(reader, feed_url, metadata_key, patterns_key):
    try:
        metadata = reader.get_feed_metadata_item(feed_url, metadata_key)
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


_METADATA_KEY = 'mark-as-read'


def _mark_as_read(reader, entry, status):
    if status is EntryUpdateStatus.MODIFIED:
        return

    metadata_key = reader.make_reader_reserved_name(_METADATA_KEY)
    patterns = _get_config(reader, entry.feed_url, metadata_key, 'title')

    for pattern in patterns or ():
        if re.search(pattern, entry.title):
            reader._mark_entry_as_dont_care(entry)
            return


_OLD_METADATA_KEY = 'mark_as_read'


def _migrate_pre_2_7_metadata(reader, feed):
    old_key = reader.make_reader_reserved_name(_OLD_METADATA_KEY)
    old_value = reader.get_feed_metadata_item(feed, old_key, None)
    if not old_value:
        return

    key = reader.make_reader_reserved_name(_METADATA_KEY)
    value = reader.get_feed_metadata_item(feed, key, None)
    if value:  # pragma: no cover
        return

    reader.set_feed_metadata_item(feed, key, old_value)
    reader.delete_feed_metadata_item(feed, old_key)


def init_reader(reader):
    reader.before_feed_update_hooks.append(_migrate_pre_2_7_metadata)
    reader.after_entry_update_hooks.append(_mark_as_read)
