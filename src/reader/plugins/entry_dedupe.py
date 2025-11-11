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

..
    Implemented for https://github.com/lemon24/reader/issues/79.
    Deleting entries in https://github.com/lemon24/reader/issues/140.
    On-demand dedupe in https://github.com/lemon24/reader/issues/202.
    More selection heuristics in https://github.com/lemon24/reader/issues/371.

..
    Some notes on how we are finding similar entries.

    There are three methods that build conceptually on one another
    (and get progressively more complicated):

    1. Jaccard similarity + n-grams. Jaccard similarity uses sets;
       the set of words in a document works, but this ignores word order;
       using n-grams instead of words retains word order information.
       This method is pair-wise (searching all the documents is O(n)),
       and requires the documents to be stored forever.

    2. MinHash allows estimating Jaccard similarity
       by "compressing" documents into fixed-size arrays.
       This method is pair-wise; only the arrays need to be stored.

    3. Locality Sensitive Hashing allows using MinHash to find duplicates
       without having to check similarity for all the documents,
       by putting similar items into buckets.

    I chose to go with #1, Jaccard similarity + n-grams,
    since it is simple to understand and implement,
    so we don't necessarily need an external dependency.
    The main downside is that it is relatively slow;
    to reduce the search space, we're using heuristics
    that find potential duplicates based on title / link / timestamps
    (although we could probably use a prefix of the document as well).

    MinHash is not that complicated to implement[1],
    but you still need LSH to avoid O(n) searches.
    [1]: https://gist.github.com/lemon24/b9af5ade919713406bda9603847d32e5

    (LLMs+embeddings are not an option due to the huge extra dependency,
    are are overkill anyway, since we don't care about semantic similarity.)

    Further reading:

    * good summary of Jaccard similarity and MinHash:
      https://blog.nelhage.com/post/fuzzy-dedup/
    * "Mining of Massive Datasets" chapter:
      http://infolab.stanford.edu/~ullman/mmds/ch3.pdf
    * "Data Mining" course notes (shorter than MMDS):
      https://users.cs.utah.edu/~jeffp/teaching/cs5140-S15/cs5140.html

    Libraries (if we choose to have dependencies):

    * https://www.nltk.org/ (tokenization, similarity)
    * https://scikit-learn.org/stable/modules/feature_extraction.html (tokenization)
    * https://ekzhu.com/datasketch/ (MinHash, LSH)

"""

import itertools
import logging
import re
import unicodedata
from collections import Counter
from collections import defaultdict
from collections import deque
from datetime import datetime
from datetime import timezone
from functools import cache
from functools import cached_property
from functools import lru_cache
from typing import NamedTuple

from reader._storage._html_utils import strip_html
from reader._utils import BetterStrPartial as partial
from reader.exceptions import EntryNotFoundError
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

        # content is only required by is_duplicate,
        # if get_entries() could skip content,
        # we could get it on demand in is_duplicate_by_id
        all_entries = list(self.reader.get_entries(feed=self.feed))

        all_by_id = {e.id: e for e in all_entries}

        @cache
        def is_duplicate_by_id(one, two):
            return is_duplicate(all_by_id[one], all_by_id[two])

        def is_duplicate_cached(one, two):
            return is_duplicate_by_id(one.id, two.id)

        if tag is None:
            # content is only required by is_duplicate
            new_entries = self.reader.get_entries(
                feed=self.feed, tags=[self.entry_request_tag]
            )
        else:
            log.info("entry_dedupe: %r for feed %r", tag, self.feed)
            new_entries = all_entries

        # which entry in a group is "latest" depends on what triggered dedupe;
        # ideally, we should unify this, see regular_update_key for details
        latest_key = regular_update_key if tag is None else feed_request_key

        for group_ids in group_entries(all_entries, new_entries, is_duplicate_cached):
            assert len(group_ids) > 1, group_ids

            group = [all_by_id[i] for i in group_ids]

            # FIXME: if latest_key is the same, the all_entries order should be preserved
            entry, *duplicates = sorted(group, key=latest_key, reverse=True)
            dedupe_entries(self.reader, entry, duplicates)

            if tag is None:
                self.clear_entry_request(entry)

        if tag is not None:
            self.clear_feed_request()

    @cached_property
    def feed_tags(self):
        return frozenset(self.reader.get_tag_keys(self.feed))

    def get_feed_request_tag(self):
        for suffix, is_duplicate in IS_DUPLICATE_BY_TAG.items():
            tag = self.reader.make_reader_reserved_name(suffix)
            if tag in self.feed_tags:
                return tag, is_duplicate
        return None, is_duplicate_entry

    def clear_feed_request(self):
        for suffix in reversed(IS_DUPLICATE_BY_TAG):
            tag = self.reader.make_reader_reserved_name(suffix)
            if tag in self.feed_tags:
                self.reader.delete_tag(self.feed, tag, missing_ok=True)

    @cached_property
    def entry_request_tag(self):
        return self.reader.make_reader_reserved_name(ENTRY_TAG)

    def clear_entry_request(self, entry):
        self.reader.delete_tag(entry, self.entry_request_tag, missing_ok=True)


# heuristics for finding duplicates


HUGE_GROUP_SIZE = 16  # 8
MAX_GROUP_SIZE = 16  # 4
MASS_DUPLICATION_MIN_PAIRS = 4


def group_entries(all_entries, new_entries, is_duplicate):
    all = {e.id: e for e in all_entries}
    new = {e.id: e for e in new_entries}
    duplicates = DisjointSet()

    for grouper in GROUPERS:
        grouper_duplicates = DisjointSet()

        for group in grouper(all.values(), new.values()):
            if len(group) == 1:
                continue

            # grouper is not a good heuristic for this group, skip it
            if len(group) > HUGE_GROUP_SIZE:  # pragma: no cover
                log.info(
                    "entry_dedupe: feed %r: found group > %r, skipping; first title: %s",
                    group[0].feed_url,
                    HUGE_GROUP_SIZE,
                    group[0].title,
                )
                continue

            # further constrain big groups to a fixed size,
            # so the combinations() below don't blow up
            group.sort(key=lambda e: e.added, reverse=True)
            group = group[:MAX_GROUP_SIZE]

            for one, two in itertools.combinations(group, 2):
                if is_duplicate(one, two):
                    grouper_duplicates.add(one.id, two.id)

        groups = grouper_duplicates.subsets()
        pair_count = sum(1 for g in groups if len(g) == 2)

        for group in groups:
            duplicates.add(*group)

            for eid in group:
                # if this is a new entry, we found duplicates for it,
                # so trying other heuristics for it is overkill
                new.pop(eid, None)

                # lots of old entries were duplicated in this specific way,
                # don't check remaining new entries against them
                if pair_count >= MASS_DUPLICATION_MIN_PAIRS:  # pragma: no cover
                    all.pop(eid, None)

        # we found duplicates for all the new entries,
        # no need to try additional heuristics
        # if not new:
        #     break

    return duplicates.subsets()


def title_grouper(entries, new_entries):
    def key(e):
        return tokenize_title(e.title)

    return group_by(key, entries, new_entries)


GROUPERS = [title_grouper]


# entry (content) similarity


def is_duplicate_entry(one, two):
    # TODO: remove title checks once thresholds are increased for #371
    if not one.title or not two.title:
        return False
    if tokenize_title(one.title) != tokenize_title(two.title):
        return False

    one_fields = _content_fields(one)
    two_fields = _content_fields(two)

    for one_words in one_fields:
        for two_words in two_fields:
            # TODO: we should match content fields by length, preferring longer ones;
            # a summary is less likely to match, but the whole article might

            min_length = min(len(one_words), len(two_words))

            one_words = one_words[:min_length]
            two_words = two_words[:min_length]

            if is_duplicate(one_words, two_words):
                return True

    return False


def _content_fields(entry):
    rv = [c.value for c in (entry.content or ())]
    if entry.summary:
        rv.append(entry.summary)
    return [tokenize_content(s) for s in rv]


def is_duplicate_entry_title(one, two):
    if not one.title or not two.title:  # pragma: no cover
        return False
    return tokenize_title(one.title) == tokenize_title(two.title)


# ordered by strictness (strictest first)
IS_DUPLICATE_BY_TAG = {
    'dedupe.once': is_duplicate_entry,
    'dedupe.once.title': is_duplicate_entry_title,
}


# finding the "latest" entry

DEFAULT_UPDATED = datetime(1970, 1, 1, tzinfo=timezone.utc)


def regular_update_key(e):
    # unlike feed_request_key, we cannot rely on e.last_updated,
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


def feed_request_key(e):
    # keep the latest entry, consider the rest duplicates
    return e.last_updated


# merging user data and deleting duplicates


def dedupe_entries(reader, entry, duplicates):
    log.info(
        "entry_dedupe: %r (title: %r) duplicates: %r",
        entry.resource_id,
        entry.title,
        [e.id for e in duplicates],
    )

    # don't do anything until we know all actions were generated successfully
    actions = list(make_dedupe_actions(reader, entry, duplicates))
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


def make_dedupe_actions(reader, entry, duplicates):

    def make_flag_args(name):
        def flag(e):
            return getattr(e, name), getattr(e, f'{name}_modified')

        return merge_flags(flag(entry), list(map(flag, duplicates)))

    if args := make_flag_args('read'):
        yield partial(reader.set_entry_read, entry, *args)

    if args := make_flag_args('important'):
        yield partial(reader.set_entry_important, entry, *args)

    tags = merge_tags(
        reader.make_reader_reserved_name,
        dict(reader.get_tags(entry)),
        map(dict, map(reader.get_tags, duplicates)),
    )
    for key, value in tags:
        yield partial(reader.set_tag, entry, key, value)

    duplicate_ids = [d.resource_id for d in duplicates]
    all_ids = [entry.resource_id] + duplicate_ids

    yield partial(
        reader._storage.set_entry_recent_sort,
        entry.resource_id,
        min(map(reader._storage.get_entry_recent_sort, all_ids)),
    )

    # any changes to the duplicates must happen at the end
    yield partial(reader._storage.delete_entries, duplicate_ids)


def merge_flags(entry, duplicates):
    def key(flag):
        value, modified = flag
        return (
            value if value is not None else -1,
            (-modified.timestamp() if modified else float('-inf')),
        )

    new = sorted([entry] + duplicates, key=key)[-1]

    if entry != new:
        return new
    return None


def merge_tags(make_reserved, entry, duplicates):
    prefix = re.escape(make_reserved(''))
    duplicate_tag_re = re.compile(rf"^{prefix}duplicate\.\d+\.of\.(.*)$")
    entry_request_tag = make_reserved(ENTRY_TAG)

    indexes = defaultdict(int)  # noqa: B910
    seen_values = defaultdict(list)

    for key, value in entry.items():
        if match := duplicate_tag_re.match(key):
            key = match.group(1)
        seen_values[key].append(value)

    for tags in duplicates:
        for key, value in tags.items():
            if key == entry_request_tag:
                continue

            if match := duplicate_tag_re.match(key):
                key = match.group(1)

            if value in seen_values[key]:
                continue
            seen_values[key].append(value)

            while True:
                index = indexes[key]
                indexes[key] += 1

                if index == 0:
                    candidate = key
                else:
                    candidate = make_reserved(f"duplicate.{index}.of.{key}")

                if candidate not in entry:
                    key = candidate
                    break

            yield key, value


# text tokenization


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


# text similarity


class _Threshold(NamedTuple):
    length: int
    similarity: float


# thredsholds originally chosen in
# https://github.com/lemon24/reader/issues/202#issuecomment-904139483
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


def is_duplicate(one, two):
    # original logic doesn't handle short text well,
    # so it just returns false if the inputs are not identical

    if one == two:
        return True

    min_length = min(len(one), len(two))

    if min_length < min(t.length for t in _THRESHOLDS):
        return False

    similarity = jaccard_similarity(ngrams(one, 4), ngrams(two, 4))

    for threshold in _THRESHOLDS:
        if min_length >= threshold.length and similarity >= threshold.similarity:
            return True

    return False


def jaccard_similarity(one, two):
    one = Counter(one)
    two = Counter(two)

    # we count replicas (i.e. weighted Jaccard), hence the sum((...).values());
    # I assume this decreases similarity if two has a sentence from one twice,
    # whereas len(...) would not
    try:
        return sum((one & two).values()) / sum((one | two).values())
    except ZeroDivisionError:  # pragma: no cover
        return 0


def ngrams(iterable, n):
    it = iter(iterable)
    window = deque(maxlen=n)
    while True:
        if len(window) == n:
            yield tuple(window)
        try:
            window.append(next(it))
        except StopIteration:
            return


# utilities


class DisjointSet:

    # naive version of scipy.cluster.hierarchy.DisjointSet

    def __init__(self):
        self._subsets = {}

    def add(self, *xs):
        prev = None
        for x in xs:
            if x not in self._subsets:
                self._subsets[x] = {x}
            if prev is not None:
                self.merge(prev, x)
            prev = x

    def merge(self, x, y):
        x_subset = self._subsets[x]
        y_subset = self._subsets[y]

        if x_subset is y_subset:
            return

        if len(x_subset) < len(y_subset):  # pragma: no cover
            x_subset, y_subset = y_subset, x_subset

        x_subset.update(y_subset)
        for n in y_subset:
            self._subsets[n] = x_subset

    def subsets(self):
        unique_subsets = {id(s): s for s in self._subsets.values()}
        return [set(s) for s in unique_subsets.values()]


def group_by(keyfn, items, only_items=None):
    if only_items:
        only_keys = list(map(keyfn, only_items))

    groups = defaultdict(list)
    for item in items:
        key = keyfn(item)
        if not key:
            continue
        if only_items and key not in only_keys:
            continue
        groups[key].append(item)

    return groups.values()


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
