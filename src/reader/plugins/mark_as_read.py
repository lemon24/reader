"""
reader.mark_as_read
~~~~~~~~~~~~~~~~~~~

.. module:: reader
  :noindex:

Mark added entries of specific feeds as read + unimportant
if their title matches a regex.

To configure, set the ``make_reader_reserved_name('mark-as-read')``
(by default, ``.reader.mark-as-read``)
tag to something like::

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

from reader.types import EntryUpdateStatus

# avoid circular imports

log = logging.getLogger(__name__)


def _get_config(reader, feed_url, key, patterns_key):
    value = reader.get_tag(feed_url, key, None)
    if value is None:
        return None

    if isinstance(value, dict):
        patterns = value.get(patterns_key, [])
        if isinstance(patterns, list):
            if all(isinstance(p, str) for p in patterns):
                return patterns

    # TODO: there should be a hook to allow plugins to validate tags
    log.warning("%s: invalid mark_as_read config: %s", feed_url, key)
    return []


_CONFIG_TAG = 'mark-as-read'


def _mark_as_read(reader, entry, status):
    if status is EntryUpdateStatus.MODIFIED:
        return

    key = reader.make_reader_reserved_name(_CONFIG_TAG)
    patterns = _get_config(reader, entry.feed_url, key, 'title')

    for pattern in patterns or ():
        if re.search(pattern, entry.title):
            reader._mark_entry_as_dont_care(entry)
            return


_OLD_CONFIG_TAG = 'mark_as_read'


def _migrate_pre_2_7_metadata(reader, feed):
    old_key = reader.make_reader_reserved_name(_OLD_CONFIG_TAG)
    old_value = reader.get_tag(feed, old_key, None)
    if not old_value:
        return

    key = reader.make_reader_reserved_name(_CONFIG_TAG)
    value = reader.get_tag(feed, key, None)
    if value:  # pragma: no cover
        return

    reader.set_tag(feed, key, old_value)
    reader.delete_tag(feed, old_key)


def init_reader(reader):
    reader.before_feed_update_hooks.append(_migrate_pre_2_7_metadata)
    reader.after_entry_update_hooks.append(_mark_as_read)
