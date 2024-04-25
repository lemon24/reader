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
_MARK_AS_READ_BY_TAG_SUFFIX = 'once'


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

    all_tags = set(reader.get_tag_keys(feed))

    mark_as_read_tags = []
    suffix = _MARK_AS_READ_BY_TAG_SUFFIX
    tag = reader.make_reader_reserved_name(f'{_CONFIG_TAG}.{suffix}')
    if tag in all_tags:
        mark_as_read_tags.append(tag)
    if not mark_as_read_tags:
        return

    mark_as_read_tag = mark_as_read_tags[
        0
    ]  # use the first one if multiple tags are defined

    log.info("_mark_as_read_backfill: tag: %r for feed %r", mark_as_read_tag, feed)

    entries = sorted(reader.get_entries(feed=feed, read=None), key=by_title)

    for entry in entries:
        _mark_as_read(reader, entry, EntryUpdateStatus.NEW)

    for tag in mark_as_read_tags:
        reader.delete_tag(feed, tag)


def init_reader(reader):
    reader.before_feed_update_hooks.append(_mark_as_read_backfill)
    reader.after_entry_update_hooks.append(_mark_as_read)


if __name__ == '__main__':  # pragma: no cover
    import logging
    import sys

    from reader import make_reader

    db = sys.argv[1]
    logging.basicConfig(format="%(message)s")
    logging.getLogger('reader').setLevel(logging.INFO)
    reader = make_reader(db)

    if len(sys.argv) > 2:
        feeds = [sys.argv[2]]
    else:
        feeds = reader.get_feeds()

    key = '.reader.mark-as-read'
    value = {'title': ['^Two']}

    for feed in feeds:
        # if 'n-gate' not in feed.url: continue
        reader.set_tag(feed, reader.make_reader_reserved_name('mark-as-read.once'))
        reader.set_tag(feed, key, value)
        _mark_as_read_backfill(reader, feed.url)
