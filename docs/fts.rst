
Full-text search
================

This part of the documentation covers the *reader* full-text search functionality.

.. note::

    The search functionality is optional, use the ``search`` extra to install
    its :ref:`dependencies <Optional dependencies>`.

.. module:: reader
  :noindex:

*reader* supports full-text searches over the entries' content through the :meth:`~Reader.search_entries()` method.

Since search adds some overhead, it needs to be enabled before being used by calling :meth:`~Reader.enable_search()`. This needs to be done only once (it is persistent across Reader instances using the same database).

Also, once search is enabled, the search index is not updated automatically when feeds/entries change; :meth:`~Reader.update_search()` can be called regularly to keep it in sync.

Enabling, disabling and updating the search index can also be done via the ``reader search`` :doc:`subcommand <cli>`.
