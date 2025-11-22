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

    The main downside is that it is relatively slow.
    To reduce the search space, we're using heuristics
    that find potential duplicates based on title / link / timestamps
    (although we could probably use a prefix of the document as well).

    MinHash is not that complicated to implement[1],
    but you still need LSH to avoid O(n) searches.

    Using datasketch (provides both MinHash and LSH)
    would allow us to get rid of heuristics (which add some complexity),
    since checking content similarity directly likely becomes fast enough.
    Alas, it has some heavy dependencies (numpy, scipy).

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

    [1]: https://gist.github.com/lemon24/b9af5ade919713406bda9603847d32e5

"""

import itertools
import logging
import re
import unicodedata
from collections import Counter
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from functools import cache
from functools import cached_property
from functools import lru_cache
from itertools import chain
from itertools import islice
from urllib.parse import urlparse

from reader._storage._html_utils import strip_html
from reader._utils import BetterStrPartial as partial
from reader.exceptions import EntryNotFoundError


log = logging.getLogger(__name__)


TAG_PREFIX = 'dedupe'


def init_reader(reader):
    reader.after_feed_update_hooks.append(after_feed_update)


def after_feed_update(reader, feed):
    Deduplicator(reader, feed).deduplicate()


class Deduplicator:

    def __init__(self, reader, feed_url):
        self.reader = reader
        self.feed_url = feed_url

    def deduplicate(self):
        config = self.get_config()

        # if optimizing for memory, this should get only metadata (no content)
        all = list(self.reader.get_entries(feed=self.feed))
        all_by_id = {e.id: e for e in all}
        # if optimizing for memory, this should wrap the method (with content)
        get_entry = all_by_id.get

        @cache
        def is_duplicate_by_id(one, two):
            return config.is_duplicate(get_entry(one), get_entry(two))

        def is_duplicate(one, two):
            return is_duplicate_by_id(one.id, two.id)

        if not config.tag:
            new = [e for e in all if e.added == self.feed.last_updated]
        else:
            log.info("entry_dedupe: %r for feed %r", config.tag, self.feed.url)
            new = all

        for group in group_entries(all, new, config.groupers, is_duplicate):
            assert len(group) > 1, [e.id for e in group]
            # TODO: if latest_key is the same, preserve the 'recent' order
            group.sort(key=config.latest_key, reverse=True)
            entry, *duplicates = group
            dedupe_entries(self.reader, entry, duplicates)

        if config.tag:
            self.clear_feed_request()

    @cached_property
    def feed(self):
        return self.reader.get_feed(self.feed_url)

    @cached_property
    def feed_tags(self):
        return frozenset(self.reader.get_tag_keys(self.feed))

    def get_config(self):
        for config in CONFIGS:
            if not config.tag:
                continue
            tag = self.reader.make_reader_reserved_name(config.tag)
            if tag in self.feed_tags:
                return config
        return Config

    def clear_feed_request(self):
        for config in reversed(CONFIGS):
            if not config.tag:
                continue
            tag = self.reader.make_reader_reserved_name(config.tag)
            if tag in self.feed_tags:
                self.reader.delete_tag(self.feed, tag, missing_ok=True)


# heuristics for finding duplicates

MAX_GROUP_SIZE = 4


def group_entries(all_entries, new_entries, groupers, is_duplicate):
    all = {e.id: e for e in all_entries}
    new = {e.id: e for e in new_entries}
    duplicates = []

    for grouper in groupers:
        grouper_duplicates = []

        log.debug("grouper %s: all=%d new=%d", grouper.__name__, len(all), len(new))

        groups = list(grouper(all.values(), new.values()))
        counts = Counter(map(len, groups))
        log.debug("grouper %s: group count by size %r", grouper.__name__, dict(counts))

        for group in groups:
            if len(group) == 1:
                continue

            # FIXME: unclear why MAX_GROUP_SIZE shouldn't be exactly 2 (or why not limit matches afterwards)

            # grouper is not a good heuristic for this group, skip it
            if len(group) > MAX_GROUP_SIZE:  # pragma: no cover
                log.debug(
                    "grouper %s: found group of size %d > %d, skipping: %r",
                    grouper.__name__,
                    len(group),
                    MAX_GROUP_SIZE,
                    [e.id for e in group],
                )
                continue

            # TODO: is DisjointSet required? would sorting group be enough?

            ds = DisjointSet()
            for one, two in itertools.combinations(group, 2):
                if is_duplicate(one, two):
                    ds.add(one.id, two.id)

            for subgroup_ids in ds.subsets():
                subgroup = [all[id] for id in subgroup_ids]

                grouper_duplicates.append(subgroup)

                # don't use these entries with other groupers
                for e in subgroup:
                    all.pop(e.id, None)
                    new.pop(e.id, None)

        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "grouper %s: found %r",
                grouper.__name__,
                [[e.id for e in ds] for ds in grouper_duplicates],
            )
        if grouper_duplicates:
            log.info(
                "grouper %s: found %d duplicate groups",
                grouper.__name__,
                len(grouper_duplicates),
            )

        duplicates.extend(grouper_duplicates)

        if not new:
            log.debug("no new entries remaining, not trying other groupers")
            break
    else:
        log.debug("no groupers remaining: all=%d new=%d", len(all), len(new))

    if duplicates:
        log.info("found %d duplicate groups", len(duplicates))

    return duplicates


def title_grouper(entries, new_entries):
    return group_by(lambda e: tokenize_title(e.title), entries, new_entries)


def title_strip_prefix_grouper(entries, new_entries):
    # FIXME: only strip new / only use prefixes in new but not in old!
    strip = StripPrefixTokenizer((e.title for e in entries), tokenize_title)
    return group_by(lambda e: strip(e.title), entries, new_entries)


def link_grouper(entries, new_entries):
    return group_by(lambda e: normalize_url(e.link), entries, new_entries)


def normalize_url(url):
    if not url:
        return None

    try:
        url = urlparse(url)
    except ValueError:  # pragma: no cover
        return None

    scheme = url.scheme.lower()
    if scheme == 'http':
        scheme = 'https'

    netloc = url.netloc.lower()
    path = url.path.rstrip('/')

    return url._replace(scheme=scheme, netloc=netloc, path=path).geturl()


def published_grouper(entries, new_entries):
    def key(e):
        dt = e.published or e.updated
        if not dt:
            return None
        return dt.isoformat(timespec='seconds')

    return group_by(key, entries, new_entries)


def published_day_grouper(entries, new_entries):
    def key(e):
        dt = e.published or e.updated
        if not dt:
            return None
        return dt.date()

    return group_by(key, entries, new_entries)


# behavior variations that depend on what triggered dedupe


# to avoid false positives, entries are considered duplicates
# only if their content is long enough;
# there are many valid cases where similar (or even identical) content
# does not indicate two entries are duplicates of one another;
# this is especially prevalent for short entries
# (32 tokens chosen due to historical reasons, might want to increase it);
# detailed motivation and examples in
# https://github.com/lemon24/reader/issues/371#issuecomment-3549816117
MIN_CONTENT_LENGTH = 32


def is_duplicate_entry(one, two):
    one_fields = _content_fields(one)
    two_fields = _content_fields(two)

    for one_words in one_fields:
        for two_words in two_fields:
            # TODO: we should match fields by length, preferring longer ones;
            # a summary is less likely to match, but the whole article might

            min_length = min(len(one_words), len(two_words))

            if min_length < MIN_CONTENT_LENGTH:
                continue

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


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class Config:
    tag = None

    groupers = [
        link_grouper,
        title_grouper,
        published_grouper,
        title_strip_prefix_grouper,
        published_day_grouper,
    ]

    is_duplicate = staticmethod(is_duplicate_entry)

    @staticmethod
    def latest_key(e):
        # unlike OnceConfig, we cannot rely on e.last_updated,
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
        return e.updated or e.published or _EPOCH, e.last_updated, e.id


class OnceConfig(Config):
    tag = f'{TAG_PREFIX}.once'

    @staticmethod
    def latest_key(e):
        # keep the latest entry, consider the rest duplicates
        return e.last_updated


class OnceTitleConfig(OnceConfig):
    tag = f'{TAG_PREFIX}.once.title'
    groupers = [title_grouper]

    @staticmethod
    def is_duplicate(one, two):
        if not one.title or not two.title:  # pragma: no cover
            return False
        return tokenize_title(one.title) == tokenize_title(two.title)


# ordered by strictness (strictest tag first)
CONFIGS = [Config, OnceConfig, OnceTitleConfig]


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
    # TODO: what if this fails with EntryNotFoundError?
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

    indexes = defaultdict(int)  # noqa: B910
    seen_values = defaultdict(list)

    for key, value in entry.items():
        if match := duplicate_tag_re.match(key):
            key = match.group(1)
        seen_values[key].append(value)

    for tags in duplicates:
        for key, value in tags.items():
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


# [(length, tokens_are_chars, n, threshold), ...]
_IS_DUPLICATE_THRESHOLDS = [
    # for shorter texts, we use character ngrams instead of word ngrams,
    # since they're more forgiving of small changes (e.g. typos);
    # thresholds based on the "reasonable" edits in test_is_duplicate TEXT
    (12, True, 3, 0.6),
    (200, True, 3, 0.7),
    (400, True, 4, 0.7),
    (800, True, 4, 0.8),
    # for longer texts, we switch to words, since character ngrams are slow
    (1600, False, 3, 0.7),
    # thresholds based on the 0.8 value mentioned in [1],
    # but increasing towards 0.9 since 0.8 seems too low, e.g.
    # removing 10 words from the middle of 100 -> similarity 0.84 (n=4)
    # [1]: https://github.com/lemon24/reader/issues/202#issuecomment-904139483
    (2400, False, 3, 0.8),
    (3600, False, 4, 0.8),
    (4800, False, 4, 0.9),
]


def is_duplicate(one, two):
    if one == two:
        return True

    avg_length = (sum(map(len, one)) + sum(map(len, two))) / 2

    for length, *params in _IS_DUPLICATE_THRESHOLDS:  # pragma: no cover
        tokens_are_chars, n, threshold = params
        if avg_length <= length:
            break

    if tokens_are_chars:
        one = ' '.join(one)
        two = ' '.join(two)

    pad = min(len(one), len(two)) < 100

    # using weighted Jaccard (repeat occurrences are counted separately),
    # which decreases similarity if two has a sentence from one twice
    similarity = jaccard_similarity(ngrams(one, n, pad), ngrams(two, n, pad))

    return similarity >= threshold


def jaccard_similarity(one, two):
    """Calculate (weighted) Jaccard similarity."""
    one = Counter(one)
    two = Counter(two)
    try:
        return (one & two).total() / (one | two).total()
    except ZeroDivisionError:  # pragma: no cover
        return 0


def ngrams(iterable, n, pad=False, pad_symbol=None):
    # based on nltk.ngrams
    it = iter(iterable)
    if pad:
        padding = (pad_symbol,) * (n - 1)
        it = chain(padding, it, padding)
    # latest nltk uses deque(maxlen=n) per itertools recipe,
    # but list seems to be consistently faster
    window = list(islice(it, n - 1))
    for item in it:
        window.append(item)
        yield tuple(window)
        del window[0]


class StripPrefixTokenizer:

    def __init__(self, documents, tokenize, **kwargs):
        self.tokenize = tokenize
        tokenized_documents = map(tokenize, documents)
        tokenized_prefixes = common_prefixes(tokenized_documents, **kwargs)
        prefixes = sorted(map(' '.join, tokenized_prefixes), key=len)
        self.pattern = re.compile(f"^({'|'.join(map(re.escape, prefixes))}) ")

    def __call__(self, s):
        s = ' '.join(self.tokenize(s))
        return self.pattern.sub('', s) or s


def common_prefixes(documents, *, min_df=4, min_length=5):
    max_decrease_ratio = 3

    def is_not_frequent_enough(node, _):
        return node.value < min_df

    def is_sharp_decrease(node, parents):
        sharp_decrease = parents[-1].value / node.value >= max_decrease_ratio
        prefix_long_enough = sum(len(p.key) for p in parents) >= min_length
        return sharp_decrease and prefix_long_enough

    def keep_frequent_subprefix(node, _):
        if not node.children:
            return
        remaining = node.value - sum(c.value for c in node.children)
        if remaining >= min_df:
            node.insert(('',), remaining)

    # duplicate documents are not a prefix by themselves
    unique_documents = dict.fromkeys(documents)

    trie = Trie('', 0)
    for d in unique_documents:
        for node in trie.insert(d, 0):
            node.value += 1

    trie.prune(is_not_frequent_enough)
    trie.prune(is_sharp_decrease)
    trie.apply(keep_frequent_subprefix)

    for nodes in trie.flatten():
        prefix = tuple(n.key for n in nodes if n.key)
        if sum(map(len, prefix)) < min_length:
            continue
        yield prefix


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


def group_by(keyfn, items, only_items):
    only_keys = set(map(keyfn, only_items))

    groups = defaultdict(list)
    for item in items:
        key = keyfn(item)
        if not key:
            continue
        if key not in only_keys:
            continue
        groups[key].append(item)

    return groups.values()


class Trie:

    def __init__(self, key, value):
        self._key = key
        self.value = value
        self._children = {}

    @property
    def key(self):
        return self._key

    @property
    def children(self):
        return self._children.values()

    def insert(self, keys, value):
        rv = []
        node = self
        for key in keys:
            try:
                child = node._children[key]
            except KeyError:
                child = node._children[key] = type(self)(key, value)
            rv.append(child)
            node = child
        return rv

    def walk(self, _parents=()):
        _parents += (self,)
        for child in self.children:
            yield *_parents[1:], child
            yield from child.walk(_parents)

    def apply(self, fn):
        for *parents, node in self.walk():
            fn(node, [self] + parents)

    def prune(self, pred, _parents=()):
        _parents += (self,)
        for child in list(self.children):
            if pred(child, _parents):
                del self._children[child.key]
            else:
                child.prune(pred, _parents)

    def flatten(self):
        for nodes in self.walk():
            if not nodes[-1].children:
                yield nodes

    def __str__(self):  # pragma: no cover
        return ''.join(
            f"{len(parents) * '  '}{node.key!r} ({node.value})\n"
            for *parents, node in self.walk()
        )


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
