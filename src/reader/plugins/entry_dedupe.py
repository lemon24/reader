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


Duplicates are entries with the same title *and* the same summary/content.

By default, this plugin runs only for newly-added entries.
To run it for the existing entries of a feed,
add the ``.reader.dedupe.once`` tag to the feed;
the plugin will run on the next feed update, and remove the tag afterwards.
To run it for the existing entries in a feed,
and only use the title for comparisons (ignoring the content),
use ``.reader.dedupe.once.title`` instead.


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


To reduce false negatives when detecting duplicates:

* All comparisons are case-insensitive,
  with HTML tags, HTML entities, punctuation, and whitespace removed.
* For entries with content of different lengths,
  only a prefix of common (smaller) length is used in comparison.
  (This is useful when one version of an entry
  has only the first paragraph of the article,
  but the other has the whole article.)
* For entries with longer content (over ~48 words),
  approximate matching is used instead of an exact match
  (currently, Jaccard similarity of 4-grams).

To reduce false positives when detecting duplicates:

* Titles must match exactly (after clean-up).
* Both entries must have title *and* content.
* Similarity thresholds are set relatively high,
  and higher for shorter content.


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
from collections import Counter
from collections import deque
from itertools import groupby
from typing import NamedTuple

from reader.types import EntryUpdateStatus
from reader.types import Feed

log = logging.getLogger('reader._plugins.feed_entry_dedupe')


_XML_TAG_RE = re.compile(r'<[^<]+?>', re.I)
_XML_ENTITY_RE = re.compile(r'&[^\s;]+?;', re.I)
_NON_WORD_RE = re.compile(r'[\W-]+')
_WHITESPACE_RE = re.compile(r'\s+')


def _normalize(text):
    if text is None:  # pragma: no cover
        return ''
    text = _XML_TAG_RE.sub(' ', text)
    text = _XML_ENTITY_RE.sub(' ', text)
    text = _NON_WORD_RE.sub(' ', text)
    text = _WHITESPACE_RE.sub(' ', text).strip()
    text = text.lower()
    # TODO in a better version of this, we'd keep the title/alt of img
    return text


def _content_fields(entry):
    rv = [c.value for c in (entry.content or ())]
    if entry.summary:
        rv.append(entry.summary)
    return [_normalize(s) for s in rv]


class _Threshold(NamedTuple):
    length: int
    similarity: float


# all figures in comments for 4-grams, substitutions only
_THRESHOLDS = [
    # 2 fully-spaced subs in the middle,
    # 4 subs with consecutive on odd or even indexes in the middle,
    # 7 subs with consecutive indexes in the middle,
    # 10 subs at one end
    _Threshold(64, 0.7),
    # 1 substitution in the middle,
    # or ~4 at the ends
    _Threshold(48, 0.8),
    # 1 substitution at the end
    _Threshold(32, 0.9),
]


def _is_duplicate_full(one, two):
    # info on similarity thresholds:
    # https://github.com/lemon24/reader/issues/202#issuecomment-904139483

    if not one.title or not two.title:
        return False
    if _normalize(one.title) != _normalize(two.title):
        return False

    one_fields = _content_fields(one)
    two_fields = _content_fields(two)

    for one_text in one_fields:
        for two_text in two_fields:
            if one_text == two_text:
                return True

            # TODO: we should match content fields by length, preferring longer ones;
            # a summary is less likely to match, but the whole article might

            one_words = one_text.split()
            two_words = two_text.split()
            min_length = min(len(one_words), len(two_words))

            if min_length < min(t.length for t in _THRESHOLDS):
                continue

            one_words = one_words[:min_length]
            two_words = two_words[:min_length]

            similarity = _jaccard_similarity(one_words, two_words, 4)

            for threshold in _THRESHOLDS:
                if (
                    min_length >= threshold.length
                    and similarity >= threshold.similarity
                ):
                    return True

    return False


def _is_duplicate_title(one, two):
    if not one.title or not two.title:  # pragma: no cover
        return False
    return _normalize(one.title) == _normalize(two.title)


def _ngrams(iterable, n):
    it = iter(iterable)
    window = deque(maxlen=n)
    while True:
        if len(window) == n:
            yield tuple(window)
        try:
            window.append(next(it))
        except StopIteration:
            return


def _jaccard_similarity(one, two, n):
    # https://github.com/lemon24/reader/issues/79#issuecomment-447636334
    # https://www.cs.utah.edu/~jeffp/teaching/cs5140-S15/cs5140/L4-Jaccard+nGram.pdf

    # if this ends up being too slow, this may help:
    # https://www.cs.utah.edu/~jeffp/teaching/cs5140-S15/cs5140/L5-Minhash.pdf

    one = Counter(_ngrams(one, n))
    two = Counter(_ngrams(two, n))

    # we count replicas (i.e. weighted Jaccard), hence the sum((...).values());
    # I assume this decreases similarity if two has a sentence from one twice,
    # whereas len(...) would not
    try:
        return sum((one & two).values()) / sum((one | two).values())
    except ZeroDivisionError:  # pragma: no cover
        return 0


def _after_entry_update(reader, entry, status, *, dry_run=False):
    if status is EntryUpdateStatus.MODIFIED:
        return

    duplicates = [
        e
        for e in _get_same_group_entries(reader, entry)
        if _is_duplicate_full(entry, e)
    ]
    if not duplicates:
        return

    _dedupe_entries(reader, entry, duplicates, dry_run=dry_run)


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


_TAG_PREFIX = 'dedupe'

# ordered by strictness (strictest first)
_IS_DUPLICATE_BY_TAG_SUFFIX = {
    'once': _is_duplicate_full,
    'once.title': _is_duplicate_title,
}


def _after_feed_update(reader, feed, *, dry_run=False):
    all_tags = set(reader.get_feed_tags(feed))

    dedupe_tags = []
    for suffix in _IS_DUPLICATE_BY_TAG_SUFFIX:
        tag = reader.make_reader_reserved_name(f'{_TAG_PREFIX}.{suffix}')
        if tag in all_tags:
            dedupe_tags.append((tag, suffix))

    if not dedupe_tags:
        return

    suffix = dedupe_tags[0][1]
    is_duplicate = _IS_DUPLICATE_BY_TAG_SUFFIX[suffix]

    log.info("entry_dedupe: %r for feed %r", suffix, feed)

    for entry, duplicates in _get_entry_groups(reader, feed, is_duplicate):
        if not duplicates:
            continue
        _dedupe_entries(reader, entry, duplicates, dry_run=dry_run)

    for tag, _ in dedupe_tags:
        reader.remove_feed_tag(feed, tag)


_MAX_GROUP_SIZE = 16


def _get_entry_groups(reader, feed, is_duplicate):
    def by_title(e):
        return _normalize(e.title)

    # this reads all the feed's entries in memory;
    # better would be to get all the (e.title, e.object_id),
    # sort them, and then get_entry() each entry in order;
    # even better would be to have get_entries(sort='title');
    # https://github.com/lemon24/reader/issues/202

    entries = sorted(reader.get_entries(feed=feed, read=None), key=by_title)

    for _, group in groupby(entries, key=by_title):
        group = list(group)

        # this gets extremely slow for different entries with the same title,
        # hence the limit

        if (
            len(group) > _MAX_GROUP_SIZE and is_duplicate is _is_duplicate_full
        ):  # pragma: no cover
            log.info(
                "entry_dedupe: feed %r: found group > %r, skipping; first title: %s",
                feed,
                _MAX_GROUP_SIZE,
                group[0].title,
            )
            continue

        while group:
            group.sort(key=lambda e: e.last_updated, reverse=True)
            entry, *rest = group

            duplicates, others = [], []
            for e in rest:
                (duplicates if is_duplicate(entry, e) else others).append(e)

            yield entry, duplicates

            group = others


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


def _get_flag_args(entry, duplicates, name):
    flag = any(getattr(d, name) for d in duplicates)

    modified_name = f'{name}_modified'
    modifieds = (
        getattr(e, modified_name)
        for e in duplicates + [entry]
        if getattr(e, name) == flag and getattr(e, modified_name)
    )
    modified = next(iter(sorted(modifieds)), None)

    if getattr(entry, name) != flag or getattr(entry, modified_name) != modified:
        return flag, modified

    return None


def _make_actions(reader, entry, duplicates):
    args = _get_flag_args(entry, duplicates, 'read')
    if args:
        yield partial(reader.set_entry_read, entry, *args)

    for duplicate in duplicates:
        if not duplicate.read or duplicate.read_modified is not None:
            yield partial(reader.set_entry_read, duplicate, True, None)

    args = _get_flag_args(entry, duplicates, 'important')
    if args:
        yield partial(reader.set_entry_important, entry, *args)

    for duplicate in duplicates:
        if duplicate.important or duplicate.important_modified is not None:
            yield partial(reader.set_entry_important, duplicate, False, None)


def _dedupe_entries(reader, entry, duplicates, *, dry_run):
    log.info(
        "entry_dedupe: %r duplicates: %r", entry.object_id, [e.id for e in duplicates]
    )

    # in case entry is EntryData, not Entry
    if hasattr(entry, 'as_entry'):
        entry = entry.as_entry(feed=Feed(entry.feed_url))

    for action in _make_actions(reader, entry, duplicates):
        action()
        log.info("entry_dedupe: %s", action)


def init_reader(reader):
    reader.after_entry_update_hooks.append(_after_entry_update)
    reader.after_feed_update_hooks.append(_after_feed_update)


if __name__ == '__main__':  # pragma: no cover
    import sys
    import logging
    from reader import make_reader

    db = sys.argv[1]
    logging.basicConfig(format="%(message)s")
    logging.getLogger('reader').setLevel(logging.INFO)
    reader = make_reader(db)

    if len(sys.argv) > 2:
        feeds = [sys.argv[2]]
    else:
        feeds = reader.get_feeds()

    for feed in feeds:
        # if 'n-gate' not in feed.url: continue
        reader.add_feed_tag(feed, reader.make_reader_reserved_name('dedupe.once'))
        _after_feed_update(reader, feed.url)

    import resource

    print(resource.getrusage(resource.RUSAGE_SELF))
