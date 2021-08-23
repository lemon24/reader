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
import functools
import logging
import re
from itertools import groupby

from reader.types import EntryUpdateStatus

log = logging.getLogger('reader._plugins.feed_entry_dedupe')


_XML_TAG_RE = re.compile(r'<[^<]+?>', re.I)
_XML_ENTITY_RE = re.compile(r'&[^\s;]+?;', re.I)
_NON_WORD_RE = re.compile(r'\W+')
_WHITESPACE_RE = re.compile(r'\s+')


def _normalize(text):
    # TODO: doing them one by one is inefficient
    if text is None:  # pragma: no cover
        return ''
    text = _XML_TAG_RE.sub(' ', text)
    text = _XML_ENTITY_RE.sub(' ', text)
    text = _NON_WORD_RE.sub(' ', text)
    text = _WHITESPACE_RE.sub(' ', text).strip()
    text = text.lower()
    return text


def _first_content(entry):
    return next((c.value for c in (entry.content or ()) if c.type == 'text/html'), None)


def _is_duplicate(one, two):
    same_title = False
    if one.title and two.title:
        same_title = _normalize(one.title) == _normalize(two.title)

    same_text = False
    if one.summary and two.summary:
        same_text = _normalize(one.summary) == _normalize(two.summary)
    else:
        one_content = _first_content(one)
        two_content = _first_content(two)
        if one_content and two_content:
            same_text = _normalize(one_content) == _normalize(two_content)

    return same_title and same_text


def _after_entry_update(reader, entry, status, *, dry_run=False):
    if status is EntryUpdateStatus.MODIFIED:
        return

    others = list(_get_same_group_entries(reader, entry))
    if not others:
        return

    _dedupe_entries(reader, entry, others, dry_run=dry_run)


def _get_same_group_entries(reader, entry):

    # to make this better, we could do something like
    # reader.search_entries(f'title: {fts5_escape(entry.title)}'),
    # assuming the search index is up to date enough;
    # https://github.com/lemon24/reader/issues/202

    for other in reader.get_entries(feed=entry.feed_url, read=None):
        if entry.object_id == other.object_id:
            continue
        if _normalize(entry.title) != _normalize(other.title):
            continue
        yield other


def _after_feed_update(reader, feed, *, dry_run=False):  # pragma: no cover
    tag = reader.make_reader_reserved_name('entry_dedupe.once')
    tags = set(reader.get_feed_tags(feed))

    if tag not in tags:
        return

    for entry, others in _get_entry_groups(reader, feed):
        if not others:
            continue
        _dedupe_entries(reader, entry, others, dry_run=dry_run)

    reader.remove_feed_tag(feed, tag)


def _get_entry_groups(reader, feed):  # pragma: no cover
    def by_title(e):
        return _normalize(e.title)

    # this reads all the feed's entries in memory;
    # better would be to get all the (e.title, e.object_id),
    # sort them, and then get_entry() each entry in order;
    # even better would be to have get_entries(sort='title');
    # https://github.com/lemon24/reader/issues/202

    entries = sorted(reader.get_entries(feed=feed, read=None), key=by_title)

    for _, group in groupby(entries, key=by_title):
        entry, *others = sorted(group, key=lambda e: e.last_updated, reverse=True)
        # print('_', repr(_), len(others))
        yield entry, others


def _name(thing):  # pragma: no cover
    name = getattr(thing, '__name__', None)
    if name:
        return name
    for attr in ('__func__', 'func'):
        new_thing = getattr(thing, attr, None)
        if new_thing:
            return _name(new_thing)
    return '<noname>'


class partial(functools.partial):  # pragma: no cover
    __slots__ = ()

    def __str__(self):
        name = _name(self.func)
        parts = [repr(getattr(v, 'object_id', v)) for v in self.args]
        parts.extend(
            f"{k}={getattr(v, 'object_id', v)!r}" for k, v in self.keywords.items()
        )
        return f"{name}({', '.join(parts)})"


def _make_actions(reader, entry, duplicates):
    # we could check if entry.read/.important before,
    # but entry must Entry, not EntryData

    if all(d.read for d in duplicates):
        yield partial(reader.mark_entry_as_read, entry)
    else:
        for duplicate in duplicates:
            yield partial(reader.mark_entry_as_read, duplicate)

    if any(d.important for d in duplicates):
        yield partial(reader.mark_entry_as_important, entry)
        for duplicate in duplicates:
            yield partial(reader.mark_entry_as_unimportant, duplicate)


def _dedupe_entries(reader, entry, others, *, dry_run):
    duplicates = [e for e in others if _is_duplicate(entry, e)]
    log.info(
        "entry_dedupe: %i candidates and %i duplicates for %r",
        len(others),
        len(duplicates),
        entry.object_id,
    )

    if not duplicates:
        return

    for action in _make_actions(reader, entry, duplicates):
        action()
        log.info("entry_dedupe: %s", action)


def init_reader(reader):
    reader.after_entry_update_hooks.append(_after_entry_update)


if __name__ == '__main__':  # pragma: no cover
    import sys
    import logging
    from reader import make_reader

    db, feed = sys.argv[1:]
    logging.basicConfig(format="%(message)s")
    logging.getLogger('reader').setLevel(logging.INFO)
    reader = make_reader(db)
    reader.add_feed_tag(feed, reader.make_reader_reserved_name('entry_dedupe.once'))
    _after_feed_update(reader, feed)
