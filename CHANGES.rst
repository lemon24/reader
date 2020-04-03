
reader changelog
================

.. module:: reader
  :noindex:


Version 0.21
------------

Released 2020-04-04

* Minor consistency improvements to the web app search button. (`#122`_)
* Add support for web application plugins. (`#80`_)
* The enclosure tag proxy is now a plugin, and is disabled by default.
  See its documentation for details. (`#52`_)
* In the web app, the "add feed" button shows a preview before adding the feed.
  (`#145`_)
* In the web app, if the feed to be previewed is not actually a feed,
  show a list of feeds linked from that URL. This is a plugin,
  and is disabled by default. (`#150`_)
* reader now uses a User-Agent header like ``python-reader/0.21``
  when retrieving feeds instead of the default `requests`_ one. (`#154`_)

.. _#80: https://github.com/lemon24/reader/issues/80
.. _#52: https://github.com/lemon24/reader/issues/52
.. _#145: https://github.com/lemon24/reader/issues/145
.. _#150: https://github.com/lemon24/reader/issues/150
.. _#154: https://github.com/lemon24/reader/issues/154


Version 0.20
------------

Released 2020-03-31

* Fix bug in :meth:`~Reader.enable_search()` that caused it to fail
  if search was already enabled and the reader had any entries.
* Add an ``entry`` argument to :meth:`~Reader.get_entries`,
  for symmetry with :meth:`~Reader.search_entries`.
* Add a ``feed`` argument to :meth:`~Reader.get_feeds`.
* Add a ``key`` argument to :meth:`~Reader.get_feed_metadata`.
* Require at least `requests`_ 2.18 (before, the version was unspecified).
* Allow updating feeds concurrently; add a ``workers`` argument to
  :meth:`~Reader.update_feeds`. (`#152`_)

.. _requests: https://requests.readthedocs.io
.. _#152: https://github.com/lemon24/reader/issues/152


Version 0.19
------------

Released 2020-03-25

* Support PyPy 3.6.
* Allow :doc:`searching for entries <fts>`. (`#122`_)
* Stricter type checking for the core modules.
* Various changes to the storage internal API.

.. _#122: https://github.com/lemon24/reader/issues/122


Version 0.18
------------

Released 2020-01-26

* Support Python 3.8.
* Increase the :meth:`~Reader.get_entries` recent threshold from 3 to 7 days.
  (`#141`_)
* Enforce type checking for the core modules. (`#132`_)
* Use dataclasses for the data objects instead of attrs. (`#137`_)

.. _#141: https://github.com/lemon24/reader/issues/141
.. _#132: https://github.com/lemon24/reader/issues/132
.. _#137: https://github.com/lemon24/reader/issues/137


Version 0.17
------------

Released 2019-10-12

* Remove the ``which`` argument of :meth:`~Reader.get_entries`. (`#136`_)
* :class:`Reader` objects should now be created using :func:`make_reader`.
  Instantiating Reader directly will raise a deprecation warning.
* The resources associated with a reader can now be released explicitly
  by calling its :meth:`~Reader.close()` method. (`#139`_)
* Make the database schema more strict regarding nulls. (`#138`_)
* Tests are now run in a random order. (`#142`_)

.. _#136: https://github.com/lemon24/reader/issues/136
.. _#138: https://github.com/lemon24/reader/issues/138
.. _#142: https://github.com/lemon24/reader/issues/142
.. _#139: https://github.com/lemon24/reader/issues/139


Version 0.16
------------

Released 2019-09-02

* Allow marking entries as important. (`#127`_)
* :meth:`~Reader.get_entries` and :meth:`~Reader.get_feeds` now take only
  keyword arguments.
* :meth:`~Reader.get_entries` argument ``which`` is now deprecated in favor
  of ``read``. (`#136`_)

.. _#127: https://github.com/lemon24/reader/issues/127
.. _#136: https://github.com/lemon24/reader/issues/136


Version 0.15
------------

Released 2019-08-24

* Improve entry page rendering for text/plain content. (`#117`_)
* Improve entry page rendering for images and code blocks. (`#126`_)
* Show enclosures on the entry page. (`#128`_)
* Show the entry author. (`#129`_)
* Fix bug causing the enclosure tag proxy to use too much memory. (`#133`_)
* Start using mypy on the core modules. (`#132`_)

.. _#117: https://github.com/lemon24/reader/issues/117
.. _#126: https://github.com/lemon24/reader/issues/126
.. _#128: https://github.com/lemon24/reader/issues/128
.. _#129: https://github.com/lemon24/reader/issues/129
.. _#133: https://github.com/lemon24/reader/issues/133
.. _#132: https://github.com/lemon24/reader/issues/132


Version 0.14
------------

Released 2019-08-12

* Drop Python 3.5 support. (`#124`_)
* Improve entry ordering implementation. (`#110`_)

.. _#110: https://github.com/lemon24/reader/issues/110
.. _#124: https://github.com/lemon24/reader/issues/124


Version 0.13
------------

Released 2019-07-12

* Add entry page. (`#117`_)
* :meth:`~Reader.get_feed` now raises :exc:`FeedNotFoundError` if the feed
  does not exist; use ``get_feed(..., default=None)`` for the old behavior.
* Add :meth:`~Reader.get_entry`. (`#120`_)

.. _#117: https://github.com/lemon24/reader/issues/117
.. _#120: https://github.com/lemon24/reader/issues/120


Version 0.12
------------

Released 2019-06-22

* Fix flashed messages never disappearing. (`#81`_)
* Minor metadata page UI improvements.
* Allow limiting the number of entries on the entries page
  via the ``limit`` URL parameter.
* Add link to the feed on the entries and feeds pages. (`#118`_)
* Use Black and pre-commit to enforce style.

.. _#81: https://github.com/lemon24/reader/issues/81
.. _#118: https://github.com/lemon24/reader/issues/118


Version 0.11
------------

Released 2019-05-26

* Support storing per-feed metadata. (`#114`_)
* Add feed metadata page to the web app. (`#114`_)
* The ``regex_mark_as_read`` plugin is now configurable via feed metadata;
  drop support for the ``READER_PLUGIN_REGEX_MARK_AS_READ_CONFIG`` file.
  (`#114`_)

.. _#114: https://github.com/lemon24/reader/issues/114


Version 0.10
------------

Released 2019-05-18

* Unify plugin loading and error handling code. (`#112`_)
* Minor improvements to CLI error reporting.

.. _#112: https://github.com/lemon24/reader/issues/112


Version 0.9
-----------

Released 2019-05-12

* Improve the :meth:`~Reader.get_entries` sorting algorithm.
  Fixes a bug introduced by `#106`_
  (entries of new feeds would always show up at the top). (`#113`_)

.. _#113: https://github.com/lemon24/reader/issues/113


Version 0.8
-----------

Released 2019-04-21

* Make the internal APIs use explicit types instead of tuples. (`#111`_)
* Finish updater internal API. (`#107`_)
* Automate part of the release process (``scripts/release.py``).

.. _#111: https://github.com/lemon24/reader/issues/111


Version 0.7
-----------

Released 2019-04-14

* Increase timeout of the button actions from 2 to 10 seconds.
* :meth:`~Reader.get_entries` now sorts entries by the import date first,
  and then by :attr:`~Entry.published`/:attr:`~Entry.updated`. (`#106`_)
* Add ``enclosure_dedupe`` plugin (deduplicate enclosures of an entry). (`#78`_)
* The ``serve`` command now supports loading plugins. (`#78`_)
* ``reader.app.wsgi`` now supports loading plugins. (`#78`_)

.. _#106: https://github.com/lemon24/reader/issues/106
.. _#78: https://github.com/lemon24/reader/issues/78


Version 0.6
-----------

Released 2019-04-13

* Minor web application style changes to make the layout more condensed.
* Factor out update logic into a separate interface. (`#107`_)
* Fix update failing if the feed does not have a content type header. (`#108`_)

.. _#107: https://github.com/lemon24/reader/issues/107
.. _#108: https://github.com/lemon24/reader/issues/108


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
