
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



File-system access
------------------

*reader* supports *http(s)://* and local (*file:*) feeds.

For security reasons, you might want to restrict file-system access
to a single directory or prevent it entirely;
you can do so by using the ``feed_root`` :func:`make_reader` argument::

    >>> # local feed paths are relative to /feeds
    >>> reader = make_reader("db.sqlite", feed_root='/feeds')
    >>> # ok, resolves to /feeds/feed.xml
    >>> reader.add_feed("feed.xml")
    >>> # ok, resolves to /feeds/also/feed.xml
    >>> reader.add_feed("file:also/feed.xml")
    >>> # error on update, resolves to /feed.xml, which is above /feeds
    >>> reader.add_feed("file:../feed.xml")
    >>> # all local paths will fail to update
    >>> reader = make_reader("db.sqlite", feed_root=None)

Note that it is still possible to `add <Adding feeds_>`_ local feeds
regardless of ``feed_root``;
it is `updating <Updating feeds_>`_ them that will fail.



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



Deleting feeds
--------------

To delete a feed and all the data associated with it,
use :meth:`~Reader.remove_feed`::

    >>> reader.remove_feed("https://www.example.com/feed.xml")



Updating feeds
--------------

To retrieve the latest version of a feed, along with any new entries,
it must be updated.
You can update all the feeds by using the :meth:`~Reader.update_feeds` method::

    >>> reader.update_feeds()
    >>> reader.get_feed(feed)
    Feed(url='http://www.hellointernet.fm/podcast?format=rss', updated=datetime.datetime(2020, 2, 28, 9, 34, 2), title='Hello Internet', ...)


To retrive feeds in parallel, use the ``workers`` flag::

    >>> reader.update_feeds(workers=10)


You can also update a specific feed using :meth:`~Reader.update_feed`::

    >>> reader.update_feed("http://www.hellointernet.fm/podcast?format=rss")

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
            second=2
        ),
        title='Hello Internet',
        link='http://www.hellointernet.fm/',
        author='CGP Grey',
        added=datetime.datetime(2020, 10, 12),
        last_updated=datetime.datetime(2020, 10, 12)
    )

To get all the feeds, use the :meth:`~Reader.get_feeds` method::

    >>> for feed in reader.get_feeds():
    ...     print(
    ...         feed.title or feed.url,
    ...         f"by {feed.author or 'unknown author'},",
    ...         f"updated on {feed.updated or 'never'}",
    ...     )
    ...
    Cortex by Relay FM, updated on 2020-09-14 12:15:00
    Hello Internet by CGP Grey, updated on 2020-02-28 09:34:02

:meth:`~Reader.get_feeds` also allows
filtering feeds by their last update status or `tags <Feed tags_>`_,
and changing the feed sort order.



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
`flags <Entry flags_>`_, `feed tags <Feed tags_>`_, or enclosures,
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

Entries can be marked as :meth:`read <Reader.mark_as_read>`
or as :meth:`important <Reader.mark_as_important>`.

These flags can be used for filtering::

    >>> reader.mark_as_read(entries[0])
    >>> entries = list(reader.get_entries(feed=feed, read=False))
    >>> for entry in entries[:2]:
    ...     print(entry.feed.title, '-', entry.title)
    ...
    Hello Internet - H.I. #135: Place Your Bets
    Hello Internet - # H.I. 134: Boxing Day



.. _fts:

Full-text search
----------------

.. note::

    The search functionality is optional, use the ``search`` extra to install
    its :ref:`dependencies <Optional dependencies>`.


*reader* supports full-text searches over the entries' content through the :meth:`~Reader.search_entries()` method.

Since search adds some overhead,
it needs to be enabled by calling :meth:`~Reader.enable_search()`
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

Feeds can have metadata,
key-value pairs where the values are any JSON-serializable data::

    >>> reader.get_feed_metadata(feed, 'key', 'default')
    'default'
    >>> reader.set_feed_metadata(feed, 'key', 'value')
    >>> reader.get_feed_metadata(feed, 'key', 'default')
    'value'
    >>> reader.set_feed_metadata(feed, 'another', {'one': [2]})
    >>> dict(reader.iter_feed_metadata(feed))
    {'another': {'one': [2]}, 'key': 'value'}


Common uses for metadata are plugin and UI settings.

.. todo:: Mention reader doesn't restrict key characters, but the UI should.
.. todo:: Mention reserved key prefixes (:issue:`186`).



Feed tags
---------

Feeds can also have tags::

    >>> reader.add_feed_tag(feed, 'one')
    >>> reader.add_feed_tag(feed, 'two')
    >>> set(reader.get_feed_tags(feed))
    {'one', 'two'}

Tags can be used for filtering feeds and entries
(see the :meth:`~Reader.get_feeds()` documentation for more complex examples)::

    >>> # feeds that have the tag "one"
    >>> [f.title for f in reader.get_feeds(tags=['one'])]
    ['Hello Internet']
    >>> # entries of feeds that have no tags
    >>> [
    ...     (e.feed.title, e.title)
    ...     for e in reader.get_entries(feed_tags=[False])
    ... ][:2]
    [('Cortex', '106: Clear and Boring'), ('Cortex', '105: Atomic Notes')]

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



Streaming methods
-----------------

Most methods that return iterables
(:meth:`~Reader.get_feeds()`, :meth:`~Reader.get_entries()` etc.)
generate the results lazily.


Some examples of how this is useful:

* Consuming the first 100 entries
  should take *roughly* the same amount of time,
  whether you have 1000 or 100000 entries.
* Likewise, if you don't keep the entries around (e.g. append them to a list),
  memory usage should remain relatively constant
  regardless of the total number of entries returned.



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