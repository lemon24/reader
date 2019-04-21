"""
feed_entry_dedupe
~~~~~~~~~~~~~~~~~

Deduplicate entries for the same feed.

Duplicates are entries with the same title *and* summary/content.

If the old entry is read, the new one will be too.
If the old entry is unread, it will be marked as read in favor of the new one.

To load::

    READER_PLUGIN='reader.plugins.feed_entry_dedupe:feed_entry_dedupe' \\
    python -m reader update -v

Implemented for https://github.com/lemon24/reader/issues/79.

.. todo::
    
    Some possible optimizations:

    1.  Do this once per feed (now it's one ``get_entries(feed=...)`` per entry).
    2.  Only get entries with the same title (not possible with the current API).
    3.  Add the entry directly as read instead of marking it afterwards
        (requires a new hook to process the entry before it is added,
        and Storage support).

"""

import re
import logging

log = logging.getLogger('reader.plugins.feed_entry_dedupe')


XML_TAG_RE = re.compile(r'<[^<]+?>', re.I)
XML_ENTITY_RE = re.compile(r'&[^\s;]+?;', re.I)
WHITESPACE_RE = re.compile(r'\s+')

def normalize(text):
    text = XML_TAG_RE.sub(' ', text)
    text = XML_ENTITY_RE.sub(' ', text)
    text = WHITESPACE_RE.sub(' ', text).strip()
    text = text.lower()
    return text


def first_content(entry):
    return next((
        c.value
        for c in (entry.content or ())
        if c.type == 'text/html'
    ), None)


def is_duplicate(one, two):
    same_title = False
    if one.title and two.title:
        same_title = normalize(one.title or '') == normalize(two.title or '')

    same_text = False
    if one.summary and two.summary:
        same_text = normalize(one.summary) == normalize(two.summary)
    else:
        one_content = first_content(one)
        two_content = first_content(two)
        if one_content and two_content:
            same_text = normalize(one_content) == normalize(two_content)

    return same_title and same_text


def feed_entry_dedupe_plugin(reader, url, entry):
    duplicates = [
        e for e in reader.get_entries(feed=url)
        if e.id != entry.id and is_duplicate(entry, e)
    ]
    if not duplicates:
        return
    if all(d.read for d in duplicates):
        log.info("%r (%s): found read duplicates, marking this as read",
                 (url, entry.id), entry.title)
        reader.mark_as_read((url, entry.id))
    else:
        for duplicate in duplicates:
            reader.mark_as_read(duplicate)
        log.info("%r (%s): found unread duplicates, marking duplicates as read",
                 (url, entry.id), entry.title)


def feed_entry_dedupe(reader):
    reader._post_entry_add_plugins.append(feed_entry_dedupe_plugin)


