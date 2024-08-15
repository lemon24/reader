"""
reader.readtime
~~~~~~~~~~~~~~~

.. module:: reader
  :no-index:

Calculate the read time for new/updated entries,
and store it as the ``.reader.readtime`` entry tag, with the format::

    {'seconds': 1234}

The content used is that returned by :meth:`~Entry.get_content`.


The read time for existing entries is backfilled as follows:

* On the first :meth:`~Reader.update_feeds` / :meth:`~Reader.update_feeds_iter` call:

  * all feeds with :attr:`~Feed.updates_disabled` false are scheduled to be backfilled

    * the feeds selected to be updated are backfilled then
    * the feeds not selected to be updated will be backfilled
      the next time they are updated

  * all feeds with :attr:`~Feed.updates_disabled` true are backfilled,
    regardless of which feeds are selected to be updated

* To prevent any feeds from being backfilled,
  set the ``.reader.readtime`` global tag to ``{'backfill': 'done'}``.
* To schedule a feed to be backfilled on its next update,
  set the ``.reader.readtime`` feed tag to ``{'backfill': 'pending'}``.


.. versionadded:: 2.12

.. versionchanged:: 3.1

    Do not require additional dependencies.
    Deprecate the ``readtime`` extra.


..
    Implemented for https://github.com/lemon24/reader/issues/275

"""

import logging
import math
import re

from reader._storage._html_utils import get_soup
from reader._storage._html_utils import remove_nontext_elements
from reader.exceptions import EntryNotFoundError
from reader.types import _get_entry_content


log = logging.getLogger('reader.plugins.readtime')


_TAG = 'readtime'


def _readtime_of_entry(entry):
    content = _get_entry_content(entry)
    if not content:
        return {'seconds': 0}

    if content.is_html:
        result = _readtime_of_html(content.value)
    else:
        result = _readtime_of_strings([content.value])

    return {'seconds': result}


# roughly following https://github.com/alanhamlett/readtime 2.0


_WPM = 265
_WORD_DELIMITER = re.compile(r'\W+')


def _readtime_of_html(html):
    soup = get_soup(html)
    remove_nontext_elements(soup)

    seconds = _readtime_of_strings(soup.stripped_strings)

    # add extra seconds for inline images
    images = len(soup.select('img'))
    delta = 12
    for _ in range(images):
        seconds += delta
        if delta > 3:  # pragma: no cover
            delta -= 1

    return seconds


def _readtime_of_strings(strings):
    strings = map(str.strip, strings)
    strings = filter(None, strings)
    num_words = sum(len(re.split(_WORD_DELIMITER, s)) for s in strings)
    return int(math.ceil(num_words / _WPM * 60))


def _after_entry_update(reader, entry, status):
    key = reader.make_reader_reserved_name(_TAG)
    log.info("readtime: setting %s for %s (entry update hook)", key, entry.resource_id)
    _set_entry_readtime(reader, entry, key)


def _before_feeds_update(reader):
    key = reader.make_reader_reserved_name(_TAG)

    if reader.get_tag((), key, None):
        return

    log.info(
        "readtime: global %s not found, setting all feeds to backfill:pending", key
    )
    for feed in reader.get_feeds():
        reader.set_tag(feed, key, {'backfill': 'pending'})


def _after_feed_update(reader, feed):
    key = reader.make_reader_reserved_name(_TAG)
    _backfill_feed(reader, feed, key)


def _after_feeds_update(reader):
    key = reader.make_reader_reserved_name(_TAG)

    if reader.get_tag((), key, None):
        return

    for feed in reader.get_feeds(updates_enabled=False):
        _backfill_feed(reader, feed.url, key)

    log.info("readtime: setting global %s to backfill:done", key)
    reader.set_tag((), key, {'backfill': 'done'})


def _backfill_feed(reader, feed, key):
    if not reader.get_tag(feed, key, None):
        return

    for entry in reader.get_entries(feed=feed):
        if reader.get_tag(entry, key, None):
            continue
        log.info("readtime: setting %s for %s (backfill)", key, entry.resource_id)
        _set_entry_readtime(reader, entry, key)

    log.info("readtime: clearing  %s for %s", key, feed)
    reader.delete_tag(feed, key)


def _set_entry_readtime(reader, entry, key):
    try:
        reader.set_tag(entry, key, _readtime_of_entry(entry))
    except EntryNotFoundError as e:
        if entry.resource_id != e.resource_id:  # pragma: no cover
            raise
        log.info("readtime: entry %r was deleted, skipping", entry.resource_id)


def init_reader(reader):
    reader.after_entry_update_hooks.append(_after_entry_update)
    reader.before_feeds_update_hooks.append(_before_feeds_update)
    reader.after_feed_update_hooks.append(_after_feed_update)
    reader.after_feeds_update_hooks.append(_after_feeds_update)
