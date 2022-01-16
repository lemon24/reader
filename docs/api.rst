
API reference
=============

.. module:: reader

This part of the documentation covers all the interfaces of *reader*.


Reader object
-------------

Most of *reader*'s functionality can be accessed through a :class:`Reader` instance.

.. todo::

    Split this into sub-sections.

.. autofunction:: make_reader(url, *, feed_root='', plugins=..., session_timeout=(3.05, 60), reserved_name_scheme=..., search_enabled='auto')

.. autoclass:: Reader(...)
    :members:


Data objects
------------

.. autoclass:: Feed
    :members:

.. autoclass:: ExceptionInfo
    :members:

.. autoclass:: Entry
    :members:

.. autoclass:: Content
    :members:

.. autoclass:: Enclosure
    :members:

.. autoclass:: EntrySearchResult
    :members:

.. autoclass:: HighlightedString
    :members:

.. autoclass:: FeedCounts
    :members:

.. autoclass:: EntryCounts
    :members:

.. autoclass:: EntrySearchCounts
    :members:

.. autoclass:: UpdateResult
    :members:

.. autoclass:: UpdatedFeed
    :members:

.. autoclass:: EntryUpdateStatus
    :members:


Exceptions
----------

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

    Subclass of :exc:`FeedError` and :exc:`ResourceNotFoundError`.

.. autoexception:: ParseError
    :members:

    Subclass of :exc:`FeedError`.

.. autoexception:: InvalidFeedURLError

    Subclass of :exc:`FeedError` and :exc:`ValueError`.

.. autoexception:: EntryError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: EntryExistsError
    :members:

    Subclass of :exc:`EntryError`.

.. autoexception:: EntryNotFoundError
    :members:

    Subclass of :exc:`EntryError` and :exc:`ResourceNotFoundError`.

.. autoexception:: MetadataError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: MetadataNotFoundError
    :members:

    Subclass of :exc:`MetadataError`.

.. autoexception:: FeedMetadataNotFoundError
    :members:

    Subclass of :exc:`MetadataNotFoundError` and :exc:`FeedError`.

.. autoexception:: StorageError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: SearchError

    Subclass of :exc:`ReaderError`.

.. autoexception:: SearchNotEnabledError

    Subclass of :exc:`SearchError`.

.. autoexception:: InvalidSearchQueryError

    Subclass of :exc:`SearchError` and :exc:`ValueError`.

.. autoexception:: TagError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: TagNotFoundError
    :members:

    Subclass of :exc:`TagError`.

.. autoexception:: ResourceNotFoundError
    :members:

    Subclass of :exc:`ReaderError`.

.. autoexception:: PluginError

    Subclass of :exc:`ReaderError`.

.. autoexception:: InvalidPluginError

    Subclass of :exc:`PluginError` and :exc:`ValueError`.


Constants
---------

.. autodata:: reader.plugins.DEFAULT_PLUGINS
