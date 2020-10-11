
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


The default (and currently only) storage uses SQLite,
so you can pass ``":memory:"`` to use a temporary in-memory database,
or the empty string to open a temporary on-disk one.
In both cases, the data will disappear when the connection is closed.

After you are done with the reader, call its :meth:`~Reader.close()` method
to release the associated resources::

    >>> reader.close()


.. todo::

    creating and destroying Readers
    feed operations (add/remove/change, get/filtering, update, user title)
    entry operations (get/filtering, flags)
    full text search (enable/disable, get/filtering, search)
    feed metadata
    feed tags
    errors
