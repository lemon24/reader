
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

Most *reader* functionality can be accessed through a :class:`Reader` instance,
which persists feed and entry state, and provides operations on them.

To create a new :class:`Reader`,
call  :func:`make_reader` function with the path to a database file
(if it doesn't exist it will be created automatically)::

    >>> from reader import make_reader
    >>> reader = make_reader("db.sqlite")

After you are done with the reader, call its :meth:`~Reader.close()` method
to release resources associated with it::

    >>> reader.close()

The default (and currently only) storage uses SQLite,
so you can pass ``":memory:"``/``""`` as path
to use a temporary in-memory/on-disk database.
In both cases, the data will disappear when the reader is closed.


File-system access
------------------

*reader* supports *http(s)://* and local (*file:*) feeds.

For security reasons, you might want to restrict file-system access
to a single directory or prevent it entirely;
you can do so by using the ``feed_root`` :func:`make_reader` argument::

    >>> # local feed paths are relative to /path/to/feed/root
    >>> reader = make_reader("db.sqlite", feed_root='/path/to/feed/root')
    >>> reader.add_feed("feed.xml")
    >>> reader.add_feed("file:also/feed.xml")
    >>> # local paths will fail to update
    >>> reader = make_reader("db.sqlite", feed_root=None)

Note that it is still possible to `add <Adding feeds_>`_ local feeds
regardless of ``feed_root``;
it is `updating <Updating feeds_>`_ them that will fail.


Adding feeds
------------

To add a feed, call the :meth:`~Reader.add_feed` method with the feed URL::

    >>> reader.add_feed("https://www.relay.fm/cortex/feed")


Updating feeds
--------------

You can update all the feeds by using the :meth:`~Reader.update_feeds` method::

    >>> reader.update_feeds()

You can also update a specific feed using :meth:`~Reader.update_feed`::

    >>> reader.update_feed("https://www.relay.fm/cortex/feed")

If supported by the server, *reader* uses the ETag and Last-Modified headers
to only retrieve feeds if they changed
(`details <https://pythonhosted.org/feedparser/http-etag.html>`_).
Even so, you should not update feeds *too* often,
to avoid wasting the feed publisher's resources,
and potentially getting banned;
every 30 minutes seems reasonable.

To support updating newly-added feeds off the regular update schedule,
you can use the ``new_only`` flag;
you can call this more often (e.g. every minute)::

    >>> reader.update_feeds(new_only=True)


Getting feeds
-------------

The :meth:`~Reader.get_feed` method returns a :class:`Feed` object
with more information about a feed.

If the feed was never updated, most fields are empty;
after update, they'll be set with data from the retrieved feed::

    >>> reader.add_feed("http://www.hellointernet.fm/podcast?format=rss")
    >>> feed = reader.get_feed("http://www.hellointernet.fm/podcast?format=rss")
    >>> print(feed)
    Feed(url='http://www.hellointernet.fm/podcast?format=rss', updated=None, title=None, ...)
    >>> reader.update_feed(feed)
    >>> reader.get_feed(feed)
    Feed(url='http://www.hellointernet.fm/podcast?format=rss', updated=datetime.datetime(2020, 2, 28, 9, 34, 2), title='Hello Internet', ...)


You can get all the feeds by using the :meth:`~Reader.get_feeds` method::

    >>> for feed in reader.get_feeds():
    ...     print(
    ...         feed.title or feed.url,
    ...         f"by {feed.author or 'unknown author'},",
    ...         f"updated on {feed.updated or 'never'}",
    ...     )
    ...
    Cortex by Relay FM, updated on 2020-09-14 12:15:00
    Hello Internet by CGP Grey, updated on 2020-02-28 09:34:02


.. todo:: Talk about filtering and sorting.

.. todo:: Talk about remove_feed() and change_feed_url().


Getting entries
---------------

You can get all the entries, most-recent first,
by using :meth:`~Reader.get_entries()`::

    >>> for entry, _ in zip(reader.get_entries(), range(10)):
    ...     print(entry.feed.title, '-', entry.title)
    ...
    Cortex - 106: Clear and Boring
    ...
    Hello Internet - H.I. #136: Dog Bingo

:meth:`~Reader.get_entries()` generates :class:`Entry` objects lazily,
so the entries will be pulled in memory only on-demand.

.. todo:: Move ^ to a section of its own, maybe.


You can filter entries by feed::

    >>> feed.title
    'Hello Internet'
    >>> entries = list(reader.get_entries(feed=feed))
    >>> for entry in entries[:2]:
    ...     print(entry.feed.title, '-', entry.title)
    ...
    Hello Internet - H.I. #136: Dog Bingo
    Hello Internet - H.I. #135: Place Your Bets


Also, you can mark entries as read or important, and filter by that::

    >>> reader.mark_as_read(entries[0])
    >>> entries = list(reader.get_entries(feed=feed, read=False))
    >>> for entry in entries[:2]:
    ...     print(entry.feed.title, '-', entry.title)
    ...
    Hello Internet - H.I. #135: Place Your Bets
    Hello Internet - # H.I. 134: Boxing Day

.. todo:: Move ^ to an "entry flags" section.


.. _fts:

Full-text search
----------------

.. note::

    The search functionality is optional, use the ``search`` extra to install
    its :ref:`dependencies <Optional dependencies>`.

.. todo:: Maybe make note a sidebar.


*reader* supports full-text searches over the entries' content through the :meth:`~Reader.search_entries()` method.

Since search adds some overhead,
it needs to be enabled first by calling :meth:`~Reader.enable_search()`
(this is persistent across Reader instances using the same database,
and only needs to be done once).
Also, the search index must be kept in sync by calling
:meth:`~Reader.update_search()` regularly
(usually after updating the feeds).

::

    >>> reader.enable_search()
    >>> reader.update_search()
    >>> for result in reader.search_entries('mars'):
    ...     print(result.metadata['.title'].apply('*', '*'))
    ...
    H.I. #106: Water on *Mars*


:meth:`~Reader.search_entries()` generates :class:`EntrySearchResult` objects,
which contain snippets of relevant entry/feed fields,
with the parts that matched highlighted.

.. todo:: Talk about how you can eval() on an entry to get the corresponding field.


By default, the results are filtered by relevance;
you can sort them most-recent first by passing ``sort='recent'``.

:meth:`~Reader.search_entries()` allows filtering the results just as :meth:`~Reader.get_entries()` does.



Feed metadata
-------------

Feeds can have metadata associated,
key-value pairs where the values can be any JSON-serializable data.

Common uses for metadata are plugin and UI settings.

.. todo:: Link to some of the methods.

::

    >>> reader.get_feed_metadata(feed, 'key', 'default')
    'default'
    >>> reader.set_feed_metadata(feed, 'key', 'value')
    >>> reader.get_feed_metadata(feed, 'key', 'default')
    'value'
    >>> reader.set_feed_metadata(feed, 'another', {'one': [2]})
    >>> dict(reader.iter_feed_metadata(feed))
    {'another': {'one': [2]}, 'key': 'value'}


.. todo:: Mention reader doesn't restrict key characters, but the UI should.
.. todo:: Mention reserved key prefixes (:issue:`186`).


Feed tags
---------

Likewise, feeds can have tags, associated arbitrary strings::

    >>> reader.add_feed_tag(feed, 'one')
    >>> reader.add_feed_tag(feed, 'two')
    >>> set(reader.get_feed_tags(feed))
    {'one', 'two'}

Unlike metadata, tags also allow filtering::

    >>> # feeds that have the tag "one"
    >>> [f.title for f in reader.get_feeds(tags=['one'])]
    ['Hello Internet']
    >>> # entries of feeds that have no tags
    >>> [
    ...     (e.feed.title, e.title)
    ...     for e in reader.get_entries(feed_tags=[False])
    ... ][:2]
    [('Cortex', '106: Clear and Boring'), ('Cortex', '105: Atomic Notes')]

See the :meth:`~Reader.get_feeds()` documentation for more complex tag filters.


.. todo:: Mention reader doesn't restrict tag characters, but the UI should.
.. todo:: Mention reserved tag prefixes (:issue:`186`).


Feed and entry arguments
------------------------

As you may have noticed in the examples above,
feed URLs and :class:`Feed` objects can be used interchangeably
as method arguments.
This is by design.
Likewise, wherever an entry argument is expected,
you can either pass a *(feed URL, entry id)* tuple
or an :class:`Entry` (or :class:`EntrySearchResult`) object.


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

When trying to create a feed, entry, metadata that already exists,
or to operate on one that does not exist,
a corresponding :exc:`*ExistsError` or :exc:`*NotFoundError`
will be raised.



.. todo::

    feed operations (remove, filtering, user title)
    get_feeds() vs get_feed() (same for entry)
