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

.. versionchanged:: 3.5
    Don't set :attr:`~reader.Entry.read_modified` and
    :attr:`~reader.Entry.important_modified` anymore;
    because :attr:`~reader.Entry.important` is now optional,
    ``important = False`` is enough to mark an entry as unimportant.
    Old unimportant entries will be migrated automatically.


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

from reader.exceptions import EntryNotFoundError
from reader.plugins.entry_dedupe import _normalize
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
_ONCE_TAG_SUFFIX = 'once'


def _mark_as_read(reader, entry, status):
    if status is EntryUpdateStatus.MODIFIED:
        return

    key = reader.make_reader_reserved_name(_CONFIG_TAG)
    patterns = _get_config(reader, entry.feed_url, key, 'title')

    try:
        for pattern in patterns or ():
            if re.search(pattern, entry.title or ''):
                reader.set_entry_read(entry, True, None)
                reader.set_entry_important(entry, False, None)
                return
    except EntryNotFoundError as e:
        if entry.resource_id != e.resource_id:  # pragma: no cover
            raise
        log.info("entry %r was deleted, skipping", entry.resource_id)


def _mark_as_read_backfill(reader, feed, *, dry_run=False):
    def by_title(e):
        return _normalize(e.title)

    suffix = _ONCE_TAG_SUFFIX

    # assume there will only be exactly one "once" tag
    mark_as_read_once_tag = reader.make_reader_reserved_name(f'{_CONFIG_TAG}.{suffix}')
    if reader.get_tag(feed, mark_as_read_once_tag, "no value") == "no value":
        return

    log.info("_mark_as_read_backfill: tag: %r for feed %r", mark_as_read_once_tag, feed)

    for entry in reader.get_entries(feed=feed, read=False, important='notset'):
        _mark_as_read(reader, entry, EntryUpdateStatus.NEW)

    reader.delete_tag(feed, mark_as_read_once_tag, missing_ok=True)


def init_reader(reader):
    reader.before_feed_update_hooks.append(_mark_as_read_backfill)
    reader.after_entry_update_hooks.append(_mark_as_read)
