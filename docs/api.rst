
API
===

.. module:: reader


Reader Object
-------------

.. autoclass:: Reader
    :members:
    :inherited-members:


Entry Objects
-------------

.. autoclass:: Feed
    :members:
    :inherited-members:

.. autoclass:: Entry
    :members:
    :inherited-members:

.. autoclass:: Content
    :members:
    :inherited-members:

.. autoclass:: Enclosure
    :members:
    :inherited-members:


Exceptions
----------

All exceptions that :class:`Reader` explicitly raises inherit from :exc:`ReaderError`.


.. autoclass:: ReaderError
    :members:

.. autoexception:: FeedError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: FeedExistsError
    :members:

    Subclass of :exc:`FeedError`.

.. autoexception:: FeedNotFoundError
    :members:

    Subclass of :exc:`FeedError`.

.. autoexception:: ParseError
    :members:

    Subclass of :exc:`FeedError`.

.. autoexception:: EntryError
    :members:

    Subclass of :exc:`FeedError`.

.. autoexception:: EntryNotFoundError
    :members:

    Subclass of :exc:`EntryError`.

.. autoexception:: StorageError
    :members:

    Subclass of :exc:`ReaderError`.

