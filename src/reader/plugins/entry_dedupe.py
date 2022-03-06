"""
reader.entry_dedupe
~~~~~~~~~~~~~~~~~~~

.. module:: reader
  :noindex:

Deduplicate the entries of a feed.

Sometimes, the format of the entry id changes for all the entries in a feed,
for example from ``example.com/123`` to ``example.com/entry-title``.
Because :attr:`~Entry.id` uniquely identifies the entries of a feed,
this results in them being added again with the new ids.

:mod:`~reader.plugins.entry_dedupe` addresses this
by copying entry user attributes
like *read* or *important* from the old entries to the new one,
and **deleting** the old entries.


Duplicates are entries with the same title *and* the same summary/content.

By default, this plugin runs only for newly-added entries.
To run it for the existing entries of a feed,
add the ``.reader.dedupe.once`` tag to the feed;
the plugin will run on the next feed update, and remove the tag afterwards.
To run it for the existing entries in a feed,
and only use the title for comparisons (ignoring the content),
use ``.reader.dedupe.once.title`` instead.


Entry user attributes are set as follows:

:attr:`~Entry.read` / :attr:`~Entry.important`

    If any of the entries is read/important, the new entry will be read/important.

:attr:`~Entry.read_modified` / :attr:`~Entry.important_modified`

    Set to the oldest *modified* of the entries
    with the same status as the new read/important.

entry tags

    For each tag key:

    * collect all the values from the duplicate entries
    * if the new entry does not have the tag, set it to the first value
    * copy the remaining values to the new entry,
      using a key of the form ``.reader.duplicate.N.of.TAG``,
      where N is an integer and TAG is the tag key

    Only unique values are considered, such that
    ``TAG``, ``.reader.duplicate.1.of.TAG``, ``.reader.duplicate.2.of.TAG``...
    always have different values.


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


.. versionchanged:: 2.2
    Reduce false negatives by using approximate content matching.

.. versionchanged:: 2.2
    Make it possible to re-run the plugin for existing entries.

.. versionchanged:: 2.3
    Delete old duplicates instead of marking them as read / unimportant.


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
    Deleting entries added in https://github.com/lemon24/reader/issues/140.


"""
import logging
import random
import re
import string
from collections import Counter
from collections import defaultdict
from collections import deque
from itertools import groupby
from typing import NamedTuple

from reader._utils import BetterStrPartial as partial
from reader.exceptions import TagNotFoundError
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
    all_tags = set(reader.get_tag_keys(feed))

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
        reader.delete_tag(feed, tag)


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


def _get_flag_args(entry, duplicates, name):
    entries = duplicates + [entry]
    flag = any(getattr(d, name) for d in entries)

    modified_name = f'{name}_modified'
    modifieds = (
        getattr(e, modified_name)
        for e in entries
        if getattr(e, name) == flag and getattr(e, modified_name)
    )
    modified = next(iter(sorted(modifieds)), None)

    if getattr(entry, name) != flag or getattr(entry, modified_name) != modified:
        return flag, modified

    return None


_CANDIDATE_KEYS_LIMIT = 200
_CANDIDATE_KEYS_RANDOM_THRESHOLD = 100


def _generate_candidate_keys(fmt, key):
    yield key
    for i in range(1, _CANDIDATE_KEYS_RANDOM_THRESHOLD + 1):
        yield fmt.format(key=key, i=i)
    while True:  # pragma: no cover
        yield fmt.format(key=key, i=int(''.join(random.choices(string.digits, k=9))))


def _make_duplicate_key_re(reader, key=None):
    prefix = re.escape(reader.make_reader_reserved_name("duplicate."))
    key_re = re.escape(key) if key is not None else '.*'
    return re.compile(rf"^{prefix}\d+{re.escape('.of.')}({key_re})$")


def _collect_tags_to_copy(reader, duplicates):
    duplicate_key_re = _make_duplicate_key_re(reader)

    rv = defaultdict(list)
    for duplicate in duplicates:
        for key, value in reader.get_tags(duplicate):

            # handle existing .reader.duplicate.N.of.KEY tags
            match = duplicate_key_re.search(key)
            if match:
                key = match.group(1)

            rv[key].append(value)

    return rv


def _get_tags(reader, entry, duplicates):
    # the logic mostly assumes it's ok to hold everything in memory

    values_by_key = _collect_tags_to_copy(reader, duplicates)

    initial_keys = set(reader.get_tag_keys(entry))
    seen_keys = set(initial_keys)

    for key, values in values_by_key.items():
        seen_values = []
        try:
            seen_values.append(reader.get_tag(entry, key))
        except TagNotFoundError:
            pass

        duplicate_key_re = _make_duplicate_key_re(reader, key)
        for initial_key in initial_keys:
            if not duplicate_key_re.search(initial_key):
                continue
            try:
                seen_values.append(reader.get_tag(entry, initial_key))
            except TagNotFoundError:  # pragma: no cover
                pass

        duplicate_key_fmt = reader.make_reader_reserved_name("duplicate.{i}.of.{key}")
        candidate_keys = _generate_candidate_keys(duplicate_key_fmt, key)

        for value in values:
            if value in seen_values:
                continue

            for _ in range(_CANDIDATE_KEYS_LIMIT):
                key = next(candidate_keys)

                if key in seen_keys:
                    continue

                yield key, value
                seen_keys.add(key)
                seen_values.append(value)
                break

            else:  # pragma: no cover
                # TODO: custom exception
                raise RuntimeError(
                    f"could not find key for entry {entry.object_id} and tag {key}"
                )


def _make_actions(reader, entry, duplicates):
    args = _get_flag_args(entry, duplicates, 'read')
    if args:
        yield partial(reader.set_entry_read, entry, *args)

    args = _get_flag_args(entry, duplicates, 'important')
    if args:
        yield partial(reader.set_entry_important, entry, *args)

    for key, value in _get_tags(reader, entry, duplicates):
        yield partial(reader.set_tag, entry, key, value)

    duplicate_ids = [d.object_id for d in duplicates]
    yield partial(reader._storage.delete_entries, duplicate_ids)


def _dedupe_entries(reader, entry, duplicates, *, dry_run):
    log.info(
        "entry_dedupe: %r (title: %r) duplicates: %r",
        entry.object_id,
        entry.title,
        [e.id for e in duplicates],
    )

    # in case entry is EntryData, not Entry
    if hasattr(entry, 'as_entry'):
        entry = entry.as_entry(feed=Feed(entry.feed_url))

    # don't do anything until we know all actions were generated successfully
    actions = list(_make_actions(reader, entry, duplicates))

    for action in actions:
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
        reader.set_tag(feed, reader.make_reader_reserved_name('dedupe.once'))
        _after_feed_update(reader, feed.url)

    import resource

    print(resource.getrusage(resource.RUSAGE_SELF))
