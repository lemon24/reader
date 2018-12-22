
reader changelog
================

.. module:: reader


Version 0.3
-----------

Released on 2018-12-22

* :meth:`~Reader.get_entries` now prefers sorting by :attr:`~Entry.published`
  (if present) to sorting by :attr:`~Entry.updated`. (`#97`_)
* Add ``regex_mark_as_read`` plugin (mark new entries as read based on a regex).
  (`#79`_)
* Add ``feed_entry_dedupe`` plugin (deduplicate new entries for a feed).
  (`#79`_)
* Plugin loading machinery dependencies are now installed via the
  ``[plugins]`` extra.
* Add a plugins section to the documentation.

.. _#97: https://github.com/lemon24/reader/issues/97
.. _#79: https://github.com/lemon24/reader/issues/79


Version 0.2
-----------

Released on 2018-11-25

* Factor out storage-related functionality into a separate interface. (`#94`_)
* Fix ``update --new-only`` updating the same feed repeatedly on databases
  that predate ``--new-only``. (`#95`_)
* Add web application screenshots to the documentation.

.. _#94: https://github.com/lemon24/reader/issues/94
.. _#95: https://github.com/lemon24/reader/issues/95


Version 0.1.1
-------------

Released on 2018-10-21

* Fix broken ``reader serve`` command (broken in 0.1).
* Raise :exc:`StorageError` for unsupported SQLite configurations at
  :class:`Reader` instantiation instead of failing at run-time with a generic
  ``StorageError("sqlite3 error")``. (`#92`_)
* Fix wrong submit button being used when pressing enter in non-button fields.
  (`#69`_)
* Raise :exc:`StorageError` for failed migrations instead of an undocumented
  exception. (`#92`_)
* Use ``requests-mock`` in parser tests instead of a web server
  (test suite run time down by ~35%). (`#90`_)

.. _#69: https://github.com/lemon24/reader/issues/69
.. _#90: https://github.com/lemon24/reader/issues/90
.. _#92: https://github.com/lemon24/reader/issues/92


Version 0.1
-----------

Released on 2018-09-15

* Initial release; public API stable.
* Support broken Tumblr feeds via the the ``tumblr_gdpr`` plugin. (`#67`_)

.. _#67: https://github.com/lemon24/reader/issues/67
