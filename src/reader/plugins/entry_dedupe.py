"""
reader.entry_dedupe
~~~~~~~~~~~~~~~~~~~

.. module:: reader
  :no-index:

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

import itertools
import logging
import random
import re
import string
import unicodedata
from collections import Counter
from collections import defaultdict
from collections import deque
from datetime import datetime
from datetime import timezone
from functools import cached_property
from functools import lru_cache
from itertools import groupby
from typing import NamedTuple

from reader._storage._html_utils import strip_html
from reader._utils import BetterStrPartial as partial
from reader.exceptions import EntryNotFoundError
from reader.exceptions import TagNotFoundError
from reader.types import EntryUpdateStatus


log = logging.getLogger(__name__)


ENTRY_TAG = 'dedupe'


def init_reader(reader):
    reader.after_entry_update_hooks.append(after_entry_update)
    reader.after_feed_update_hooks.append(after_feed_update)


def after_entry_update(reader, entry, status, *, dry_run=False):
    if status is EntryUpdateStatus.MODIFIED:
        return
    reader.set_tag(entry, reader.make_reader_reserved_name(ENTRY_TAG))


def after_feed_update(reader, feed):
    Deduplicator(reader, feed).deduplicate()


class Deduplicator:

    def __init__(self, reader, feed):
        self.reader = reader
        self.feed = feed

    def deduplicate(self):
        tag, is_duplicate = self.get_feed_request_tag()

        if tag is not None:
            log.info("entry_dedupe: %r for feed %r", tag, self.feed)
            groups = _get_entry_groups(self.reader, self.feed, is_duplicate)
        else:
            entries = self.reader.get_entries(
                feed=self.feed, tags=[self.entry_request_tag]
            )
            groups = map(partial(_get_entry_group, self.reader), entries)

        for entry, duplicates in groups:
            if not duplicates:
                continue
            _dedupe_entries(self.reader, entry, duplicates)

            if tag is None:
                self.clear_entry_request(entry)

        if tag is not None:
            self.clear_feed_request()

    @cached_property
    def feed_tags(self):
        return frozenset(self.reader.get_tag_keys(self.feed))

    def get_feed_request_tag(self):
        for suffix, is_duplicate in _IS_DUPLICATE_BY_TAG.items():
            tag = self.reader.make_reader_reserved_name(suffix)
            if tag in self.feed_tags:
                return tag, is_duplicate
        return None, _is_duplicate_full

    def clear_feed_request(self):
        for suffix in reversed(_IS_DUPLICATE_BY_TAG):
            tag = self.reader.make_reader_reserved_name(suffix)
            if tag in self.feed_tags:
                self.reader.delete_tag(self.feed, tag, missing_ok=True)

    @cached_property
    def entry_request_tag(self):
        return self.reader.make_reader_reserved_name(ENTRY_TAG)

    def clear_entry_request(self, entry):
        self.reader.delete_tag(entry, self.entry_request_tag, missing_ok=True)


def _content_fields(entry):
    rv = [c.value for c in (entry.content or ())]
    if entry.summary:
        rv.append(entry.summary)
    return [tokenize_content(s) for s in rv]


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
    if tokenize_title(one.title) != tokenize_title(two.title):
        return False

    one_fields = _content_fields(one)
    two_fields = _content_fields(two)

    for one_words in one_fields:
        for two_words in two_fields:
            if one_words == two_words:
                return True

            # TODO: we should match content fields by length, preferring longer ones;
            # a summary is less likely to match, but the whole article might

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
    return tokenize_title(one.title) == tokenize_title(two.title)


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


def _get_entry_group(reader, entry):
    duplicates = [
        e
        for e in _get_same_group_entries(reader, entry)
        if _is_duplicate_full(entry, e)
    ]
    if not duplicates:
        log.debug("entry_dedupe: no duplicates for %s", entry.resource_id)
        return entry, []

    try:
        entry = reader.get_entry(entry)
    except EntryNotFoundError:
        log.info("entry_dedupe: entry %r was deleted, aborting", entry.resource_id)
        return entry, []

    def group_key(e):
        # unlike _get_entry_groups, we cannot rely on e.last_updated,
        # because for duplicates in the feed, we'd end up flip-flopping
        # (on the first update, entry 1 is deleted and entry 2 remains;
        # on the second update, entry 1 remains because it's new,
        # and entry 2 is deleted because it's not modified,
        # has lower last_updated, and no update hook runs for it; repeat).
        #
        # it would be more correct to sort by (is in new feed, last_retrieved),
        # but as of 3.14, we don't know about existing but not modified entries
        # (the hook isn't called), and entries don't have last_retrieved.
        #
        # also see test_duplicates_in_feed / #340.
        #
        return e.updated or e.published or DEFAULT_UPDATED, e.id

    group = [entry] + duplicates
    group.sort(key=group_key, reverse=True)
    entry, *duplicates = group

    return entry, duplicates


DEFAULT_UPDATED = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _get_same_group_entries(reader, entry):
    # to make this better, we could do something like
    # reader.search_entries(f'title: {fts5_escape(entry.title)}'),
    # assuming the search index is up to date enough;
    # https://github.com/lemon24/reader/issues/202

    for other in reader.get_entries(feed=entry.feed_url, read=None):
        if entry.resource_id == other.resource_id:
            continue
        if tokenize_title(entry.title) != tokenize_title(other.title):
            continue
        yield other


# ordered by strictness (strictest first)
_IS_DUPLICATE_BY_TAG = {
    'dedupe.once': _is_duplicate_full,
    'dedupe.once.title': _is_duplicate_title,
}


_MAX_GROUP_SIZE = 16


def _get_entry_groups(reader, feed, is_duplicate):
    def by_title(e):
        return tokenize_title(e.title)

    # this reads all the feed's entries in memory;
    # better would be to get all the (e.title, e.resource_id),
    # sort them, and then get_entry() each entry in order;
    # even better would be to have get_entries(sort='title');
    # https://github.com/lemon24/reader/issues/202

    entries = sorted(reader.get_entries(feed=feed, read=None), key=by_title)

    for _, group_it in groupby(entries, key=by_title):
        group = list(group_it)

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
            # keep the latest entry, consider the rest duplicates
            group.sort(key=lambda e: e.last_updated, reverse=True)
            entry, *rest = group

            duplicates, others = [], []
            for e in rest:
                (duplicates if is_duplicate(entry, e) else others).append(e)

            yield entry, duplicates

            group = others


def _get_flag_args(entry, duplicates, name):
    entries = duplicates + [entry]

    flags = {getattr(d, name) for d in entries}
    for flag in (True, False, None):  # pragma: no cover
        if flag in flags:
            break

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
                    f"could not find key for entry {entry.resource_id} and tag {key}"
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

    duplicate_ids = [d.resource_id for d in duplicates]

    yield partial(
        reader._storage.set_entry_recent_sort,
        entry.resource_id,
        min(
            map(
                reader._storage.get_entry_recent_sort,
                [entry.resource_id] + duplicate_ids,
            )
        ),
    )

    # WARNING: any changes to the duplicates must happen at the end
    yield partial(reader._storage.delete_entries, duplicate_ids)


def _dedupe_entries(reader, entry, duplicates):
    log.info(
        "entry_dedupe: %r (title: %r) duplicates: %r",
        entry.resource_id,
        entry.title,
        [e.id for e in duplicates],
    )

    # don't do anything until we know all actions were generated successfully
    actions = list(_make_actions(reader, entry, duplicates))
    # FIXME: what if this fails with EntryNotFoundError?
    # either the entry was deleted (abort),
    # or a duplicate was deleted (start over with the other duplicates, if any)

    try:
        for action in actions:
            action()
            log.info("entry_dedupe: %s", action)
    except EntryNotFoundError as e:  # pragma: no cover
        if entry.resource_id != e.resource_id:
            raise
        log.info("entry_dedupe: entry %r was deleted, aborting", entry.resource_id)


# tokenization


_TOKEN_RE = re.compile(
    r"""(?x)
    \b  # word boundary
    (?:
        \d{1,4} (?: [/-] \d{1,4} ){1,2}  # dates
        |
        \d{1,4} (?: \. \d{1,3} ){1,2} (?: [\._-]? [a-z]{1,5} \d{1,2} )?  # versions
        |
        \w+  # other words
    )
    \b   # word boundary
    """
)


def tokenize(s, preprocessor=lambda x: x):
    if s is None:  # pragma: no cover
        return ()
    s = preprocessor(s)
    s = strip_accents(s)
    s = s.lower()
    return tuple(_TOKEN_RE.findall(s))


_HTML_TAG_OR_ENTITY_RE = re.compile(r"<[^<]+?>|&[^\s;]+?;", re.I)
fast_strip_html = partial(_HTML_TAG_OR_ENTITY_RE.sub, '')

tokenize_title = lru_cache(1024)(partial(tokenize, preprocessor=fast_strip_html))
tokenize_content = lru_cache(64)(partial(tokenize, preprocessor=strip_html))


def strip_accents(s):
    # based on sklearn.feature_extraction.text.strip_accents_unicode
    try:
        s.encode('ascii', errors='strict')
        return s
    except UnicodeEncodeError:
        normalized = unicodedata.normalize('NFKD', s)
        noncombining = itertools.filterfalse(unicodedata.combining, normalized)
        return ''.join(noncombining)


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

    for feed in feeds:
        # if 'n-gate' not in feed.url: continue
        reader.set_tag(feed, reader.make_reader_reserved_name('dedupe.once'))
        after_feed_update(reader, feed.url)

    import resource

    print(resource.getrusage(resource.RUSAGE_SELF))
