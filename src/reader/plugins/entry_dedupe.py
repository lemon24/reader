"""
reader.entry_dedupe
~~~~~~~~~~~~~~~~~~~

Deduplicate the entries of a feed.

Sometimes, the format of the entry id changes for all the entries in a feed,
for example from ``example.com/123`` to ``example.com/entry``.
Because the entry id is used to uniquely identify entries,
normally this results in the entry being added again with the new id.

This plugin addresses this by copying entry user attributes
like *read* or *important* from the old entry to the new one.

.. note::

    There are plans to *delete* the old entry after copying user attributes;
    please +1 / comment in :issue:`140` if you need this.


Duplicates are entries with the same title *and* the same summary/content,
after all HTML tags and whitespace have been stripped.


Entry user attributes are set as follows:

:attr:`~Entry.read`

    If the old entry is read, the new one will be too.
    If the old entry is unread, it will be marked as read in favor of the new one.

    =========== =========== ===========
    before      after
    ----------- -----------------------
    old.read    old.read    new.read
    =========== =========== ===========
    True        True        True
    False       True        False
    =========== =========== ===========

:attr:`~Entry.important`

    If the old entry is important, it will be marked as unimporant,
    and the new one will be marked as important.

    =============== =============== ===============
    before          after
    --------------- -------------------------------
    old.important   old.important   new.important
    =============== =============== ===============
    True            False           True
    False           False           False
    =============== =============== ===============


.. todo::

    Some possible optimizations:

    1.  Do this once per feed (now it's one ``get_entries(feed=...)`` per entry).
    2.  Only get entries with the same title (not possible with the current API).

        **2021 update**: We can use the full-text search if it's enabled.

    3.  Add the entry directly as read instead of marking it afterwards
        (requires a new hook to process the entry before it is added,
        and Storage support).

..
    Implemented for https://github.com/lemon24/reader/issues/79.


"""
import logging
import re

from reader.types import EntryUpdateStatus

log = logging.getLogger('reader._plugins.feed_entry_dedupe')


_XML_TAG_RE = re.compile(r'<[^<]+?>', re.I)
_XML_ENTITY_RE = re.compile(r'&[^\s;]+?;', re.I)
_WHITESPACE_RE = re.compile(r'\s+')


def _normalize(text):
    text = _XML_TAG_RE.sub(' ', text)
    text = _XML_ENTITY_RE.sub(' ', text)
    text = _WHITESPACE_RE.sub(' ', text).strip()
    text = text.lower()
    return text


def _first_content(entry):
    return next((c.value for c in (entry.content or ()) if c.type == 'text/html'), None)


def _is_duplicate(one, two):
    same_title = False
    if one.title and two.title:
        same_title = _normalize(one.title or '') == _normalize(two.title or '')

    same_text = False
    if one.summary and two.summary:
        same_text = _normalize(one.summary) == _normalize(two.summary)
    else:
        one_content = _first_content(one)
        two_content = _first_content(two)
        if one_content and two_content:
            same_text = _normalize(one_content) == _normalize(two_content)

    return same_title and same_text


def _entry_dedupe_plugin(reader, entry, status):
    if status is EntryUpdateStatus.MODIFIED:
        return

    duplicates = [
        e
        for e in reader.get_entries(feed=entry.feed_url)
        if e.id != entry.id and _is_duplicate(entry, e)
    ]

    if not duplicates:
        return

    if all(d.read for d in duplicates):
        log.info(
            "%r (%s): found read duplicates, marking this as read",
            (entry.feed_url, entry.id),
            entry.title,
        )
        reader.mark_entry_as_read(entry)
    else:
        for duplicate in duplicates:
            reader.mark_entry_as_read(duplicate)
        log.info(
            "%r (%s): found unread duplicates, marking duplicates as read",
            (entry.feed_url, entry.id),
            entry.title,
        )

    if any(d.important for d in duplicates):
        log.info(
            "%r (%s): found important duplicates, "
            "marking this as important and duplicates as unimportant",
            (entry.feed_url, entry.id),
            entry.title,
        )
        reader.mark_entry_as_important(entry)
        for duplicate in duplicates:
            reader.mark_entry_as_unimportant(duplicate)


def init_reader(reader):
    reader.after_entry_update_hooks.append(_entry_dedupe_plugin)
