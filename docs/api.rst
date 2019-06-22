
API
===

.. module:: reader

This part of the documentation covers all the interfaces of reader.


Reader object
-------------

All of reader's functionality can be accessed through a :class:`Reader` instance.

.. autoclass:: Reader
    :members:


Data objects
------------

.. autoclass:: Feed
    :members:

.. autoclass:: Entry
    :members:

.. autoclass:: Content
    :members:

.. autoclass:: Enclosure
    :members:


Exceptions
----------

All exceptions that :class:`Reader` explicitly raises inherit from :exc:`ReaderError`.

.. autoexception:: ReaderError
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

    Subclass of :exc:`ReaderError`.

.. autoexception:: EntryNotFoundError
    :members:

    Subclass of :exc:`EntryError`.

.. autoexception:: MetadataError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: MetadataNotFoundError
    :members:

    Subclass of :exc:`MetadataError`.

.. autoexception:: StorageError
    :members:

    Subclass of :exc:`ReaderError`.
