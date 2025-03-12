
API reference
=============

.. module:: reader

This part of the documentation covers all the public interfaces of *reader*.


Reader object
-------------

Most of *reader*'s functionality can be accessed through a :class:`Reader` instance.

.. todo::

    Split this into sub-sections.

.. autofunction:: make_reader

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

.. autoclass:: EntrySource
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
    :show-inheritance:
    :members:

.. autoexception:: FeedExistsError
    :show-inheritance:
    :members:

.. autoexception:: FeedNotFoundError
    :show-inheritance:
    :members:

.. autoexception:: InvalidFeedURLError
    :show-inheritance:

.. autoexception:: EntryError
    :show-inheritance:
    :members:

.. autoexception:: EntryExistsError
    :show-inheritance:
    :members:

.. autoexception:: EntryNotFoundError
    :show-inheritance:
    :members:

.. autoexception:: UpdateError
    :show-inheritance:
    :members:

.. autoexception:: ParseError
    :show-inheritance:
    :members:

.. autoexception:: UpdateHookError
    :show-inheritance:
    :members:

.. autoexception:: SingleUpdateHookError
    :show-inheritance:
    :members:

.. autoexception:: UpdateHookErrorGroup
    :show-inheritance:
    :members:

.. autoexception:: StorageError
    :show-inheritance:
    :members:

.. autoexception:: SearchError
    :show-inheritance:

.. autoexception:: SearchNotEnabledError
    :show-inheritance:

.. autoexception:: InvalidSearchQueryError
    :show-inheritance:

.. autoexception:: TagError
    :show-inheritance:
    :members:

.. autoexception:: TagNotFoundError
    :show-inheritance:
    :members:

.. autoexception:: ResourceNotFoundError
    :show-inheritance:
    :members:

.. autoexception:: PluginError
    :show-inheritance:

.. autoexception:: InvalidPluginError
    :show-inheritance:

.. autoexception:: PluginInitError
    :show-inheritance:


.. autoexception:: ReaderWarning
    :show-inheritance:


.. _exctree:

Exception hierarchy
~~~~~~~~~~~~~~~~~~~

The class hierarchy for :mod:`reader` exceptions is:

.. classtree:: ReaderError



Enumerations
------------

.. autoclass:: reader.FeedSort(value)
    :show-inheritance:
    :members:

.. autoclass:: reader.EntrySort(value)
    :show-inheritance:
    :members:

.. autoclass:: reader.EntrySearchSort(value)
    :show-inheritance:
    :members:



.. _type aliases:

Type aliases
------------

.. autodata:: reader.types.TagFilterInput
.. autodata:: reader.types.TristateFilterInput

.. autoclass:: reader.types.UpdateConfig
    :members:



Constants
---------

.. autodata:: reader.core.DEFAULT_RESERVED_NAME_SCHEME

.. autodata:: reader.plugins.DEFAULT_PLUGINS



Utilities
---------

.. autofunction:: reader.utils.archive_entries
