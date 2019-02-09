
reader changelog
================

.. module:: reader


Version 0.5
-----------

Released 2019-02-09

* Make updating new feeds up to 2 orders of magnitude faster;
  fixes a problem introduced by `#94`_. (`#104`_)
* Move the core modules to a separate subpackage and enforce test coverage
  (``make coverage`` now fails if :mod:`reader.core` coverage is less than
  100%). (`#101`_)
* Support Python 3.8 development branch.
* Add ``dev`` and ``docs`` extras (to install development requirements).
* Build HTML documentation when running tox.
* Add ``test-all`` and ``docs`` make targets (to run tox / build HTML docs).

.. _#104: https://github.com/lemon24/reader/issues/104
.. _#101: https://github.com/lemon24/reader/issues/101


Version 0.4
-----------

Released 2019-01-02

* Support Python 3.7.
* Entry :attr:`~Entry.content` and :attr:`~Entry.enclosures` now default to
  an empty tuple instead of ``None``. (`#99`_)
* :meth:`~Reader.get_feeds` now sorts feeds by :attr:`~Feed.user_title` or
  :attr:`~Feed.title` instead of just :attr:`~Feed.title`. (`#102`_)
* :meth:`~Reader.get_feeds` now sorts feeds in a case insensitive way. (`#103`_)
* Add ``sort`` argument to :meth:`~Reader.get_feeds`; allows sorting
  feeds by title or by when they were added. (`#98`_)
* Allow changing the feed sort order in the web application. (`#98`_)

.. _#99: https://github.com/lemon24/reader/issues/99
.. _#102: https://github.com/lemon24/reader/issues/102
.. _#103: https://github.com/lemon24/reader/issues/103
.. _#98: https://github.com/lemon24/reader/issues/98


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
  ``plugins`` extra.
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
