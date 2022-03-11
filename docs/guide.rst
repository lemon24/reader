
User guide
==========

.. module:: reader
  :noindex:


This page gives a tour of *reader*'s features,
and a few examples of how to use them.

.. note::

    Before starting, make sure that *reader* is :doc:`installed <install>`
    and up-to-date.


The Reader object
-----------------

The :class:`Reader` object persists feed and entry state
and provides operations on them.


To create a new Reader,
call :func:`make_reader` with the path to a database file::

    >>> from reader import make_reader
    >>> reader = make_reader("db.sqlite")


The default (and currently only) storage uses SQLite,
so the path behaves like the ``database`` argument of :func:`sqlite3.connect`:

* If the database does not exist, it will be created automatically.
* You can pass ``":memory:"`` to use a temporary in-memory database;
  the data will disappear when the reader is closed.


After you are done with the reader,
call :meth:`~Reader.close()` to release the resources associated with it::

    >>> reader.close()

While the same thing will eventually happen when the reader is garbage-collected,
it is recommended to call :meth:`~Reader.close()` explicitly,
especially in long-running processes
or when you create multiple readers pointing to the same database.
You can use :func:`contextlib.closing` to do this automatically::

    >>> from contextlib import closing
    >>> with closing(make_reader('db.sqlite')) as reader:
    ...     ... # do stuff with reader
    ...



Adding feeds
------------

To add a feed, call the :meth:`~Reader.add_feed` method with the feed URL::

    >>> reader.add_feed("https://www.relay.fm/cortex/feed")
    >>> reader.add_feed("http://www.hellointernet.fm/podcast?format=rss")

Most of the attributes of a new feed are empty
(to populate them, the feed must be `updated <Updating feeds_>`_)::

    >>> feed = reader.get_feed("http://www.hellointernet.fm/podcast?format=rss")
    >>> print(feed)
    Feed(url='http://www.hellointernet.fm/podcast?format=rss', updated=None, title=None, ...)



File-system access
------------------

*reader* supports *http(s)://* and local (*file:*) feeds.

For security reasons, local feeds are disabled by default.
You can allow full file-system access or restrict it to a single directory
by using the ``feed_root`` :func:`make_reader` argument::

    >>> # all local feed paths allowed
    >>> reader = make_reader("db.sqlite", feed_root='')
    >>> # local feed paths are relative to /feeds
    >>> reader = make_reader("db.sqlite", feed_root='/feeds')
    >>> # ok, resolves to /feeds/feed.xml
    >>> reader.add_feed("feed.xml")
    >>> # ok, resolves to /feeds/also/feed.xml
    >>> reader.add_feed("file:also/feed.xml")
    >>> # error, resolves to /feed.xml, which is above /feeds
    >>> reader.add_feed("file:../feed.xml")
    Traceback (most recent call last):
      ...
    ValueError: path cannot be outside root: '/feed.xml'

Note that it is possible to add invalid feeds;
`updating <Updating feeds_>`_ them will still fail, though::

    >>> reader.add_feed("file:../feed.xml", allow_invalid_url=True)
    >>> reader.update_feed("file:../feed.xml")
    Traceback (most recent call last):
      ...
    reader.exceptions.ParseError: path cannot be outside root: '/feed.xml': 'file:../feed.xml'



Deleting feeds
--------------

To delete a feed and all the data associated with it,
use :meth:`~Reader.delete_feed`::

    >>> reader.delete_feed("https://www.example.com/feed.xml")



Updating feeds
--------------

To retrieve the latest version of a feed, along with any new entries,
it must be updated.
You can update all the feeds by using the :meth:`~Reader.update_feeds` method::

    >>> reader.update_feeds()
    >>> reader.get_feed(feed)
    Feed(url='http://www.hellointernet.fm/podcast?format=rss', updated=datetime.datetime(2020, 2, 28, 9, 34, 2, tzinfo=datetime.timezone.utc), title='Hello Internet', ...)


To retrive feeds in parallel, use the ``workers`` flag::

    >>> reader.update_feeds(workers=10)


You can also update a specific feed using :meth:`~Reader.update_feed`::

    >>> reader.update_feed("http://www.hellointernet.fm/podcast?format=rss")

If supported by the server, *reader* uses the ETag and Last-Modified headers
to only retrieve feeds if they changed
(`details <https://feedparser.readthedocs.io/en/latest/http-etag.html>`_).
Even so, you should not update feeds *too* often,
to avoid wasting the feed publisher's resources,
and potentially getting banned;
every 30 minutes seems reasonable.

To support updating newly-added feeds off the regular update schedule,
you can use the ``new_only`` flag;
you can call this more often (e.g. every minute)::

    >>> reader.update_feeds(new_only=True)


If you need the status of each feed as it gets updated
(for instance, to update a progress bar),
you can use :meth:`~Reader.update_feeds_iter` instead,
and get a (url, updated feed or none or exception) pair for each feed::

    >>> for url, value in reader.update_feeds_iter():
    ...     if value is None:
    ...         print(url, "not modified")
    ...     elif isinstance(value, Exception):
    ...         print(url, "error:", value)
    ...     else:
    ...         print(url, value.new, "new,", value.updated, "updated")
    ...
    http://www.hellointernet.fm/podcast?format=rss 100 new, 0 updated
    https://www.relay.fm/cortex/feed not modified



Disabling feed updates
----------------------

Sometimes, it is useful to skip a feed when using :meth:`~Reader.update_feeds`;
for example, the feed does not exist anymore,
and you want to stop requesting it unnecessarily during regular updates,
but still want to keep its entries (so you cannot remove it).

:meth:`~Reader.disable_feed_updates` allows you to do exactly that::

    >>> reader.disable_feed_updates(feed)

You can check if updates are enabled for a feed by looking at its
:attr:`~Feed.updates_enabled` attribute::

    >>> reader.get_feed(feed).updates_enabled
    False



Getting feeds
-------------

As seen in the previous sections,
:meth:`~Reader.get_feed` returns a :class:`Feed` object
with more information about a feed::

    >>> from prettyprinter import pprint, install_extras;
    >>> install_extras(include=['dataclasses'])
    >>> feed = reader.get_feed(feed)
    >>> pprint(feed)
    reader.types.Feed(
        url='http://www.hellointernet.fm/podcast?format=rss',
        updated=datetime.datetime(
            year=2020,
            month=2,
            day=28,
            hour=9,
            minute=34,
            second=2,
            tzinfo=datetime.timezone.utc
        ),
        title='Hello Internet',
        link='http://www.hellointernet.fm/',
        author='CGP Grey',
        added=datetime.datetime(2020, 10, 12, tzinfo=datetime.timezone.utc),
        last_updated=datetime.datetime(2020, 10, 12, tzinfo=datetime.timezone.utc)
    )

To get all the feeds, use the :meth:`~Reader.get_feeds` method::

    >>> for feed in reader.get_feeds():
    ...     print(
    ...         feed.title or feed.url,
    ...         f"by {feed.author or 'unknown author'},",
    ...         f"updated on {feed.updated or 'never'}",
    ...     )
    ...
    Cortex by Relay FM, updated on 2020-09-14 12:15:00+00:00
    Hello Internet by CGP Grey, updated on 2020-02-28 09:34:02+00:00

:meth:`~Reader.get_feeds` also allows
filtering feeds by their `tags <resource tags_>`_, if the last update succeeded,
or if updates are enabled, and changing the feed sort order.



Changing feed URLs
------------------

Sometimes, feeds move from one URL to another.

This can be handled naively by removing the old feed and adding the new URL;
however, all the data associated with the old feed would get lost,
including any old entries (some feeds only have the last X entries).

To change the URL of a feed in-place, use :meth:`~Reader.change_feed_url`::

    >>> reader.change_feed_url(
    ...     "https://www.example.com/old.xml",
    ...     "https://www.example.com/new.xml"
    ... )


Sometimes, the id of the entries changes as well;
you can handle duplicate entries by using a :doc:`plugin <plugins>`
like ``feed_entry_dedupe``.



Getting entries
---------------

You can get all the entries, most-recent first,
by using :meth:`~Reader.get_entries()`,
which generates :class:`Entry` objects::

    >>> for entry, _ in zip(reader.get_entries(), range(10)):
    ...     print(entry.feed.title, '-', entry.title)
    ...
    Cortex - 106: Clear and Boring
    ...
    Hello Internet - H.I. #136: Dog Bingo


:meth:`~Reader.get_entries` allows filtering entries by their feed,
`flags <Entry flags_>`_, `feed tags <resource tags_>`_, or enclosures,
and changing the entry sort order.
Here is an example of getting entries for a single feed::

    >>> feed.title
    'Hello Internet'
    >>> entries = list(reader.get_entries(feed=feed))
    >>> for entry in entries[:2]:
    ...     print(entry.feed.title, '-', entry.title)
    ...
    Hello Internet - H.I. #136: Dog Bingo
    Hello Internet - H.I. #135: Place Your Bets



Entry flags
-----------

Entries can be marked as :meth:`read <Reader.mark_entry_as_read>`
or as :meth:`important <Reader.mark_entry_as_important>`.

The flags can be used for filtering::

    >>> reader.mark_entry_as_read(entries[0])
    >>> entries = list(reader.get_entries(feed=feed, read=False))
    >>> for entry in entries[:2]:
    ...     printentry.title)
    ...
    H.I. #135: Place Your Bets
    # H.I. 134: Boxing Day


The time when a flag was last modified is recorded, and is available via
:attr:`~Entry.read_modified` and :attr:`~Entry.important_modified`::

    >>> for entry in reader.get_entries(feed=feed, limit=2):
    ...     print(entry.title, '-', entry.read, entry.read_modified)
    ...
    H.I. #136: Dog Bingo - True 2021-10-08 08:00:00+00:00
    H.I. #135: Place Your Bets - False None



.. _fts:

Full-text search
----------------

*reader* supports full-text searches over the entries' content
through the :meth:`~Reader.search_entries()` method.

::

    >>> reader.update_search()
    >>> for result in reader.search_entries('mars'):
    ...     print(result.metadata['.title'].apply('*', '*'))
    ...
    H.I. #106: Water on *Mars*


:meth:`~Reader.search_entries()` generates :class:`EntrySearchResult` objects
containing snippets of relevant entry/feed fields,
with the parts that matched highlighted.

.. todo:: Talk about how you can eval() on an entry to get the corresponding field.

By default, results are filtered by relevance;
you can sort them most-recent first by passing ``sort='recent'``.
Also, you can filter them just as with :meth:`~Reader.get_entries()`.


The search index is not updated automatically;
to keep it in sync, you need to call :meth:`~Reader.update_search()`
when entries change (e.g. after updating/deleting feeds).
:meth:`~Reader.update_search()` only updates
the entries that changed since the last call,
so it is OK to call it relatively often.


Because search adds  minor overhead to other :class:`Reader` methods
and can almost double the size of the database,
it can be turned on/off through the
:meth:`~Reader.enable_search()` / :meth:`~Reader.disable_search()` methods.
This is persistent across instances using the same database,
and only needs to be done once.
You can also use the ``search_enabled`` :func:`make_reader` argument
for the same purpose.
By default, search is disabled,
and enabled automatically on the first :meth:`~Reader.update_search()` call.



.. _feed-tags:
.. _feed-metadata:

Resource tags
-------------

Resources (feeds and entries) can have tags,
key-value pairs where the values are any JSON-serializable data::

    >>> reader.get_tag(feed, 'one', 'default')
    'default'
    >>> reader.set_tag(feed, 'one', 'value')
    >>> reader.get_tag(feed, 'one')
    'value'
    >>> reader.set_tag(feed, 'two', {2: ['ii']})
    >>> dict(reader.get_tags(feed))
    {'one': 'value', 'two': {'2': ['ii']}}

Common uses for tag values are plugin and UI settings.


In addition to feeds and entries,
it is possible to store global (per-database) data.
To work with global tags,
use ``()`` (the empty tuple) as the first argument of the tag methods.


When using :meth:`~Reader.set_tag`, the value can be omitted,
in which case the behavior is to ensure the tag exists
(if it doesn't, :const:`None` is used as value)::

    >>> reader.set_tag(feed, 'two')
    >>> reader.set_tag(feed, 'three')
    >>> set(reader.get_tag_keys(feed))
    {'three', 'one', 'two'}
    >>> dict(reader.get_tags(feed))
    {'one': 'value', 'three': None, 'two': {'2': ['ii']}}


Besides storing resource metadata,
tags can be used for filtering feeds and entries
(as of version |version|, only by feed tags;
see the :meth:`~Reader.get_feeds()` documentation for more complex examples)::

    >>> # feeds that have the tag "one"
    >>> [f.title for f in reader.get_feeds(tags=['one'])]
    ['Hello Internet']
    >>> # entries of feeds that have no tags
    >>> [
    ...     (e.feed.title, e.title)
    ...     for e in reader.get_entries(feed_tags=[False])
    ... ][:2]
    [('Cortex', '106: Clear and Boring'), ('Cortex', '105: Atomic Notes')]



Note that tag keys and the top-level keys of dict tag values
starting with specific (configurable) prefixes are `reserved <Reserved names_>`_.
Other than that, they can be any unicode string,
although UIs might want to restrict this to a smaller set of characters.



.. versionchanged:: 2.8

    Prior to version 2.7, there were two separate APIs,
    with independent namespaces:

    * feed metadata (key/value pairs, could *not* be used for filtering)
    * feed tags (plain strings, could be used for filtering)

    In version 2.7, the two namespaces were merged
    (such that adding a tag to a feed would result in the
    metadata with the same key being set with a value of :const:`None`).

    In version 2.8, these separate APIs were merged into
    a new, unified API for generic resource tags
    (key/value pairs which can be used for filtering).
    The old, feed-only tags/metadata methods were deprecated,
    and **will be removed in version 3.0**.

.. versionchanged:: 2.10
    Support entry and global tags.


Counting things
---------------

You can get aggregated feed and entry counts by using one of the
:meth:`~Reader.get_feed_counts`,
:meth:`~Reader.get_entry_counts`, or
:meth:`~Reader.search_entry_counts` methods::

    >>> reader.get_feed_counts()
    FeedCounts(total=156, broken=5, updates_enabled=154)
    >>> reader.get_entry_counts()
    EntryCounts(total=12494, read=10127, important=115, has_enclosures=2823, averages=...)
    >>> reader.search_entry_counts('feed: death and gravity')
    EntrySearchCounts(total=16, read=16, important=0, has_enclosures=0, averages=...)


The ``_counts`` methods support the same filtering arguments
as their non-``_counts`` counterparts.
The following example shows how to get counts only for feeds/entries
with a specific tag::

    >>> for tag in itertools.chain(reader.get_tag_keys((None,)), [False]):
    ...     feeds = reader.get_feed_counts(tags=[tag])
    ...     entries = reader.get_entry_counts(feed_tags=[tag])
    ...     print(f"{tag or '<no tag>'}: {feeds.total} feeds, {entries.total} entries ")
    ...
    podcast: 27 feeds, 2838 entries
    python: 39 feeds, 1929 entries
    self: 5 feeds, 240 entries
    tech: 90 feeds, 7075 entries
    webcomic: 6 feeds, 1865 entries
    <no tag>: 23 feeds, 1281 entries


.. _entry averages:

For entry counts, the :attr:`~EntryCounts.averages` attribute
is the average number of entries per day during the last 1, 3, 12 months,
as a 3-tuple (e.g. to get an idea of how often a feed gets updated)::

    >>> reader.get_entry_counts().averages
    (8.066666666666666, 8.054945054945055, 8.446575342465753)
    >>> reader.search_entry_counts('feed: death and gravity').averages
    (0.03333333333333333, 0.06593406593406594, 0.043835616438356165)

This example shows how to convert them to monthly statistics::

    >>> periods = [(30, 1, 'month'), (91, 3, '3 months'), (365, 12, 'year')]
    >>> for avg, (days, months, label) in zip(counts.averages, periods):
    ...     entries = round(avg * days / months, 1)
    ...     print(f"{entries} entries/month (past {label})")
    ...
    1.0 entries/month (past month)
    2.0 entries/month (past 3 months)
    1.3 entries/month (past year)



.. _pagination:

Pagination
----------

:meth:`~Reader.get_feeds`, :meth:`~Reader.get_entries`,
and :meth:`~Reader.search_entries`
can be used in a paginated fashion.

The ``limit`` argument allows limiting the number of results returned;
the ``starting_after`` argument allows skipping results until after
a specific one.

To get the first page, use only ``limit``::

    >>> for entry in reader.get_entries(limit=2):
    ...     print(entry.title)
    ...
    H.I. #136: Dog Bingo
    H.I. #135: Place Your Bets

To get the next page, use the last result from a call as
``starting_after`` in the next call::

    >>> for entry in reader.get_entries(limit=2, starting_after=entry):
    ...     print(entry.title)
    ...
    # H.I. 134: Boxing Day
    Star Wars: The Rise of Skywalker, Hello Internet Christmas Special



.. _plugins:

Plugins
-------

*reader* supports plugins as a way to extend its default behavior.

To use a built-in plugin, pass the plugin name to :func:`make_reader`::

    >>> reader = make_reader("db.sqlite", plugins=[
    ...     "reader.enclosure_dedupe",
    ...     "reader.entry_dedupe",
    ... ])


You can find the full list of built-in plugins :ref:`here <built-in plugins>`,
and the list of plugins used by default in :data:`reader.plugins.DEFAULT_PLUGINS`.


.. _custom plugins:

Custom plugins
~~~~~~~~~~~~~~

In addition to built-in plugins, reader also supports *custom plugins*.

A custom plugin is any callable that takes a :class:`Reader` instance
and potentially modifies it in some (useful) way.
To use custom plugins, pass them to :func:`make_reader`::

    >>> def function_plugin(reader):
    ...     print(f"got {reader}")
    ...
    >>> class ClassPlugin:
    ...     def __init__(self, **options):
    ...         self.options = options
    ...     def __call__(self, reader):
    ...         print(f"got options {self.options} and {reader}")
    ...
    >>> reader = make_reader("db.sqlite", plugins=[
    ...     function_plugin,
    ...     ClassPlugin(option=1),
    ... ])
    got <reader.core.Reader object at 0x7f8897824a00>
    got options {'option': 1} and <reader.core.Reader object at 0x7f8897824a00>


For a real-world example, see the implementation of the
:gh:`enclosure_dedupe <src/reader/plugins/enclosure_dedupe.py>`
built-in plugin. Using it as a custom plugin looks like this::

    >>> from reader.plugins import enclosure_dedupe
    >>> reader = make_reader("db.sqlite", plugins=[enclosure_dedupe.init_reader])



Feed and entry arguments
------------------------

As you may have noticed in the examples above,
feed URLs and :class:`Feed` objects can be used interchangeably
as method arguments.
This is by design.
Likewise, wherever an entry argument is expected,
you can either pass a *(feed URL, entry id)* tuple
or an :class:`Entry` (or :class:`EntrySearchResult`) object.

You can get this unique identifier in a uniform way by using the ``object_id``
property.
This is useful when you need to refer to a *reader* object in a generic way
from outside Python (e.g. to make a link to the next :ref:`page <pagination>`
of feeds/entries in a web application).



Streaming methods
-----------------

All methods that return iterators
(:meth:`~Reader.get_feeds()`, :meth:`~Reader.get_entries()` etc.)
generate the results lazily.


Some examples of how this is useful:

* Consuming the first 100 entries
  should take *roughly* the same amount of time,
  whether you have 1000 or 100000 entries.
* Likewise, if you don't keep the entries around (e.g. append them to a list),
  memory usage should remain relatively constant
  regardless of the total number of entries returned.



.. _reserved names:

Reserved names
--------------

In order to expose *reader* and plugin functionality directly to the end user,
*names* starting with ``.reader.`` and ``.plugin.`` are *reserved*.
This applies to the following names:

* tag keys
* the top-level keys of dict tag values

Currently, there are no *reader*-reserved names;
new ones will be documented here.

The prefixes can be changed using
:attr:`~Reader.reserved_name_scheme`.

Note that changing :attr:`~Reader.reserved_name_scheme`
*does not rename* the actual entities,
it just controls how new reserved names are built.
Because of this, I recommend choosing a scheme
before setting up a new *reader* database,
and sticking with that scheme for its lifetime.
To change the scheme of an existing database,
you must rename the entities listed above yourself.

When choosing a :attr:`~Reader.reserved_name_scheme`,
the ``reader_prefix`` and ``plugin_prefix`` should not overlap,
otherwise the *reader* core and various plugins may interfere each other.
(For example, if both prefixes are set to ``.``,
*reader*-reserved key ``user_title``
and a plugin named ``user_title`` that uses just the plugin name (with no key)
will both end up using the ``.user_title`` metadata.)

That said, *reader* will ensure
names reserved by the core
and :ref:`built-in plugin <built-in plugins>` names
*will never collide*,
so this is a concern only if you plan to use third-party plugins.

.. todo::

    ... that don't follow the plugin author guide (doesn't exist yet)
    Mention in the plugin author guide that care should be taken to avoid colliding with known reader names.
    Also, mention that if the plugin name is `reader_whatever`, plugins can use just `whatever` as name.
    Also, mention that if plugin `reader_whatever` exists on PyPI, I won't add a new reader name that's called `whatever`.
    Furthermore, keys starting with `_` are private/unstable.

Reserved names can be built programmatically using
:meth:`~Reader.make_reader_reserved_name`
and :meth:`~Reader.make_plugin_reserved_name`.
Code that wishes to work with any scheme
should always use these methods to construct reserved names
(especially third-party plugins).

.. todo::

    (especially third-party plugins published on PyPI).
    This should be mentoined in the plugin author guide.



Advanced feedparser features
----------------------------

*reader* uses `feedparser`_ ("Universal Feed Parser") to parse feeds.
It comes with a number of advanced features,
most of which *reader* uses transparently.

Two of these features are worth mentioning separately,
since they change the content of the feed,
and, although *always enabled* at the moment,
they may become optional in the future;
note that disabling them is not currently possible.

.. _feedparser: https://feedparser.readthedocs.io/en/latest/


Sanitization
~~~~~~~~~~~~

Quoting:

    Most feeds embed HTML markup within feed elements.
    Some feeds even embed other types of markup, such as SVG or MathML.
    Since many feed aggregators use a web browser (or browser component)
    to display content, Universal Feed Parser sanitizes embedded markup
    to remove things that could pose security risks.


You can find more details about which markup and elements are sanitized in
`the feedparser documentation <https://feedparser.readthedocs.io/en/latest/html-sanitization.html>`__.

The following corresponding *reader* attributes are sanitized:

* :attr:`Entry.content` (:attr:`Content.value`)
* :attr:`Entry.summary`
* :attr:`Entry.title`
* :attr:`Feed.title`


Relative link resolution
~~~~~~~~~~~~~~~~~~~~~~~~

Quoting:

    Many feed elements and attributes are URIs.
    Universal Feed Parser resolves relative URIs
    according to the XML:Base specification. [...]

    In addition [to elements treated as URIs],
    several feed elements may contain HTML or XHTML markup.
    Certain elements and attributes in HTML can be relative URIs,
    and Universal Feed Parser will resolve these URIs
    according to the same rules as the feed elements listed above.


You can find more details about which elements
are treated as URIs and HTML markup in
`the feedparser documentation <https://feedparser.readthedocs.io/en/latest/resolving-relative-links.html>`__.


The following corresponding *reader* attributes are treated as URIs:

* :attr:`Entry.enclosures` (:attr:`Enclosure.href`)
* :attr:`Entry.id`
* :attr:`Entry.link`
* :attr:`Feed.link`

The following corresponding *reader* attributes may be treated as HTML markup,
depending on their type attribute or feedparser defaults:

* :attr:`Entry.content` (:attr:`Content.value`)
* :attr:`Entry.summary`
* :attr:`Entry.title`
* :attr:`Feed.title`



Errors and exceptions
---------------------

All exceptions that :class:`Reader` explicitly raises inherit from
:exc:`ReaderError`.

If there's an issue retrieving or parsing the feed,
:meth:`~Reader.update_feed` will raise a :exc:`ParseError`
with the original exception (if any) as cause.
:meth:`~Reader.update_feeds` will just log the exception and move on.
In both cases, information about the cause will be stored on the feed in
:attr:`~Feed.last_exception`.

Any unexpected exception raised by the underlying storage implementation
will be reraised as a :exc:`StorageError`,
with the original exception as cause.

Search methods will raise a :exc:`SearchError`.
Any unexpected exception raised by the underlying search implementation
will be also be reraised as a :exc:`SearchError`,
with the original exception as cause.

When trying to create a feed, entry, or tag that already exists,
or to operate on one that does not exist,
a corresponding :exc:`*ExistsError` or :exc:`*NotFoundError`
will be raised.

All functions and methods may raise
:exc:`ValueError` or :exc:`TypeError` implicitly or explicitly
if passed invalid arguments.



.. todo::

    feed operations (remove, filtering, user title)
    get_feeds() vs get_feed() (same for entry)
