
User guide
==========

.. module:: reader
  :noindex:


.. note:: This section of the documentation is a work in progress.

.. todo:: Install reader first.


The Reader
----------

The :class:`Reader` object gives access to most *reader* functionality
and persists the state related to feeds and entries.

To create a new :class:`Reader`, use the :func:`make_reader` function,
and pass it the path to a database file
(if it doesn't exist it will be created automatically)::

    >>> from reader import make_reader
    >>> reader = make_reader("db.sqlite")

After you are done with the reader, call its :meth:`~Reader.close()` method
to release resources associated with it::

    >>> reader.close()

The default (and currently only) storage uses SQLite,
so you can pass ``":memory:"`` as path to use a temporary in-memory database,
or the empty string to use a temporary on-disk one.
In both cases, the data will disappear when the reader is closed.


Working with feeds
------------------

To add a feed, call the :meth:`~Reader.add_feed` method with the feed URL::

    >>> reader.add_feed("http://www.hellointernet.fm/podcast?format=rss")
    >>> reader.add_feed("https://www.relay.fm/cortex/feed")

.. todo:: Talk about feed_root and filesystem access.


The :meth:`~Reader.get_feed` method returns a :class:`Feed` object
with more information about a feed::

    >>> feed = reader.get_feed("http://www.hellointernet.fm/podcast?format=rss")
    >>> feed
    Feed(url='http://www.hellointernet.fm/podcast?format=rss', updated=None, title=None, link=None, author=None, user_title=None, added=datetime.datetime(2020, 10, 10, 0, 0), last_updated=None, last_exception=None)

.. todo:: Talk about how you can also pass a feed object where a feed URL is expected.


At the moment, most of the fields are empty,
because the feed hasn't been updated yet.
You can update all feeds by using the :meth:`~Reader.update_feeds` method::

    >>> reader.update_feeds()

.. todo::

    Talk aobut swallowing exceptions;
    talk about new_only;
    talk about HTTP headers;
    talk about update_feed().


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




.. todo::

    feed operations (remove, get/filtering, user title)
    entry operations (get/filtering, flags)
    full text search (enable/disable, get/filtering, search)
    feed metadata
    feed tags
    errors
