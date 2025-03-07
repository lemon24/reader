
Changelog
=========

.. module:: reader
  :no-index:


Version 3.17
------------

Released 2025-03-08

.. attention::

    This is the last release to support Python 3.10;
    see :issue:`354` for details.

* Support PyPy 3.11. (:issue:`354`)

* Start working on a web app :ref:`re-design <app roadmap>`
  based on `htmx`_ and `Bootstrap`_,
  beginning with a new version of the main entries page,
  and dark mode support;
  some :ref:`screenshots <app screenshots>`.
  (:issue:`318`)

* :attr:`Entry.feed_resolved_title`:
  return both the source and feed titles only if they are different.

* The :mod:`~reader._plugins.cli_status` plugin
  now creates only one entry per command,
  with the newest run first.

.. _htmx: https://htmx.org/
.. _Bootstrap: https://getbootstrap.com/


Version 3.16
------------

Released 2024-12-08

* Parse and store :attr:`Entry.source` for Atom and RSS feeds. (:issue:`267`)

  * Add :attr:`Entry.feed_resolved_title` and :attr:`Feed.resolved_title` properties.
  * The ``feed`` search column now indexes :attr:`Entry.feed_resolved_title`,
    instead of feed :attr:`~Feed.user_title` or :attr:`~Feed.title`.
  * Allow filtering entries by the entry source.

* Add :func:`reader.utils.archive_entries` for
  copying entries to an "archived" feed.
  (:issue:`290`)

  * Add :meth:`~Reader.copy_entry`.
  * Allow archiving entries from the web app.

* Fix bug causing :class:`Reader` operations
  from a thread other than the one that created the instance
  to happen with foreign key constraint enforcement disabled
  (e.g. deleting a feed from another thread would not delete its entries).

  This bug exists since using :class:`Reader` instances from other threads
  became allowed in `2.15 <Version 2.15_>`_.

  Serving the web application with ``python -m reader serve``
  is known to be affected.
  Serving it with uWSGI without threads (the default)
  should not be affected.

  .. attention::

    **Your database may be in an inconsistent state because of this bug.**

    It is recommended you run `PRAGMA foreign_key_check`_ on your database.

    If you are upgrading from a version prior to 3.16
    (i.e. were not using a pre-release version of *reader*),
    the migration will do so for you.
    If there are inconsistencies, you will get this error::

      StorageError: integrity error: after migrating to version 43:
        integrity error: FOREIGN KEY constraint failed

* Fix :meth:`~Reader.enable_search` / :meth:`~Reader.update_search`
  not working when the search database is missing but change tracking is enabled
  (e.g. when restoring the main database from backup).
  (:issue:`362`)

.. _PRAGMA foreign_key_check: https://www.sqlite.org/pragma.html#pragma_foreign_key_check


Version 3.15
------------

Released 2024-11-11

* During :ref:`scheduled updates <scheduled>`,
  honor the Retry-After HTTP header sent with
  429 Too Many Requests or 503 Service Unavailable responses.
  (:issue:`307`)
* Optimize OR-only :meth:`~Reader.get_feeds()` and :meth:`~Reader.get_entries()`
  tag filters (e.g. ``[['one', ...]]``). (:issue:`359`)
* Expose :data:`reader.core.DEFAULT_RESERVED_NAME_SCHEME`. (:issue:`287`)

* Update the (unstable) parser API to expose HTTP information to the updater.
  (:issue:`307`)

  * The :class:`.RetrieverType` protocol used by retrievers changed
    (new return type, allow storing arbitrary caching data via
    :attr:`~.RetrievedFeed.caching_info`).
  * The ``HTTPAcceptParserType`` was renamed to :class:`.AcceptParserType`.

* Allow :ref:`using the installed feedparser <no-vendored-feedparser>`
  instead of the one vendored by *reader*.
  This is useful for working around issues in the vendored feedparser,
  like the libxml2 <=2.13.3 incompatibility reported in :issue:`350`;
  thanks to `Maks Verver`_  for reporting,
  root causing, and following up with both dependencies.

* Fix a number of brittle / broken tests.
  Thanks to `Maks Verver`_ for the issues and fixes.
  (:issue:`348`, :issue:`349`, :issue:`355`)

.. _Maks Verver: https://github.com/maksverver


Version 3.14
------------

Released 2024-07-23

* Add :attr:`~EntryCounts.unimportant` attribute to
  :class:`EntryCounts` and :class:`EntrySearchCounts`.
  Thanks to `chenthur`_ for the pull request.
  (:issue:`283`)
* Fix bug in the :mod:`~reader.plugins.entry_dedupe` plugin causing entries
  to flip-flop if there were multiple *new* duplicates of the same issue
  (on the first update, one entry remains, on the second update, the other);
  related to the bug fixed in `version 3.2 <Version 3.2_>`_.
  (:issue:`340`)

* :mod:`~reader._plugins.enclosure_tags` plugin improvements. (:issue:`344`)

  * Set genre to `Podcast` if the feed has any tag containing "podcast".
  * Rewrite tags on the fly,
    instead of downloading the entire file before sending it to the user;
    allows browsers to display accurate download progress.
  * Prefer feed user title to feed title if available.
  * Use feed title as artist, instead of author.

* Support Python 3.13. (:issue:`341`)
* Update vendored `feedparser`_ to the ``develop`` branch as of 2024-06-26.
  Needed because upstream removed dependency on stdlib module ``cgi``
  (removed in Python 3.13), but the `version 2.9 <Version 2.9_>`_
  memory usage reduction was not released upstream yet.
  (:issue:`341`)

.. _chenthur: https://github.com/chenthur
.. _feedparser: https://feedparser.readthedocs.io/en/latest/


Version 3.13
------------

Released 2024-06-19

* Allow different feed update intervals; see :ref:`scheduled` for details.
  (:issue:`332`)

  * Add ``scheduled`` argument to :meth:`~Reader.update_feeds()`,
    :meth:`~Reader.get_feeds()`, etc.

  * Add :attr:`Feed.update_after` and :attr:`~Feed.last_retrieved` attributes.

  * The ``new`` filter of :meth:`~Reader.update_feeds()` etc. considers
    a feed new if it was never retrieved (:attr:`~Feed.last_retrieved`),
    not if it was never updated successfully (:attr:`~Feed.last_updated`).

  * Update an entry whenever its :attr:`~Entry.updated` changes
    (don't require it to be newer).

* Fix bug introduced in `version 3.12 <Version 3.12_>`_ causing an assertion error
  when there are multiple entries with the same id in the same feed,
  or when parallel :meth:`~Reader.update_feeds` calls add the same entry.
  The fix restores the pre-3.12 first-entry-wins / last-write-wins behavior.
  Thanks to `Joakim Hellsén`_ for reporting and helping debug this issue.
  (:issue:`335`)

  * Fix assertion error when an entry is deleted while being updated.

* Allow re-running the :mod:`~reader.plugins.mark_as_read` plugin for existing entries.
  Thanks to `Michael Han`_ for the pull request.
  (:issue:`317`)

* Other changes for scheduled updates. (:issue:`332`)

  * Add ``--scheduled`` flag to the ``update`` command.
  * The :mod:`~reader._plugins.cli_status` plugin now
    records the output of multiple runs instead of just the last one,
    with output from the same hour grouped in a single entry,
    up to 24 entries/hours.
  * Group mutually-exclusive attributes of :class:`~.FeedUpdateIntent`
    into a new :attr:`~.FeedUpdateIntent.value` union attribute.

* New and improved :ref:`update` user guide section.
* Rename ``update --new-only`` CLI flag to ``--new``;
  ``--new-only`` remains available as an alias.
  (:issue:`334`)

.. _Joakim Hellsén: https://github.com/TheLovinator1
.. _Michael Han: https://github.com/Sakunam


Version 3.12
------------

Released 2024-03-05

* Split the :ref:`full-text search <fts>` index into a separate,
  attached database.
  (:issue:`323`)
* Require at least SQLite 3.18.
  Previously, *reader* core required 3.15,
  and only :meth:`~Reader.update_search` required 3.18.
  (:issue:`323`)
* Enable `write-ahead logging`_ only once, when the database is created,
  instead of every time it is opened.
  (:issue:`323`)
* Vacuum the main database after migrations. (:issue:`323`)
* Add an internal :ref:`change tracking API <changes>`
  to formalize how search keeps in sync with storage.
  (:issue:`323`)
* Refactor storage internals. (:issue:`323`)


Version 3.11
------------

Released 2023-12-30

* Allow filtering entries by their (entry) tags. (:issue:`328`)
* Support Python 3.12. (:issue:`326`)


Version 3.10
------------

Released 2023-11-12

* Stop using deprecated :mod:`sqlite3` datetime converters/adapters.
  (:issue:`321`)
* Document the storage :doc:`internal`.
  (:issue:`325`)
* Change all :doc:`internal APIs <internal>` to use timezone-aware datetimes,
  with the timezone set to UTC.
  (:issue:`321`)
* In the API documentation,
  fall back to type hints if hand-written parameter types are not available.
  Add relevant :ref:`documentation` guidelines to the dev documentation.
  (:issue:`287`)
* Add the :mod:`~reader._plugins.share` experimental plugin
  to add social sharing links in the web app.


Version 3.9
-----------

Released 2023-08-28

* Wrap unexpected retriever/parser errors in :exc:`ParseError`,
  instead of letting them bubble up,
  so exceptions raised by custom retrievers/parsers
  for one feed don't prevent updates for the others
  during :meth:`~Reader.update_feeds_iter()` / :meth:`~Reader.update_feeds()`.
  (:issue:`218`)
* Store the details of any :exc:`UpdateError` in :attr:`Feed.last_exception`
  (except hook errors),
  not just the ``__cause__`` of :exc:`ParseError`\s.
  (:issue:`218`)

* Add the :mod:`~reader._plugins.timer` experimental plugin
  to collect per-call method timings.
  Show per-request statistics in the web app.
  (:issue:`306`)


Version 3.8
-----------

Released 2023-08-20

* Drop Python 3.9 support. (:issue:`302`)
* Use :mod:`concurrent.futures` instead of :mod:`multiprocessing.dummy`
  when :ref:`updating feeds <update>` in parallel;
  :mod:`multiprocessing.dummy` does not work on some environments
  (e.g. AWS Lambda).

* Wrap unexpected hook errors in :exc:`UpdateHookError`
  instead of letting them bubble up,
  so plugin-raised exceptions for one feed don't prevent updates for the others
  during :meth:`~Reader.update_feeds_iter()` / :meth:`~Reader.update_feeds()`.
  (:issue:`218`)

  .. warning::

    **This is a minor compatibility break**;
    it is considered acceptable, since it fixes a bug / unexpected behavior.

  * Add new exceptions :exc:`UpdateHookError`,
    :exc:`SingleUpdateHookError`, and :exc:`UpdateHookErrorGroup`.

  * Try to run all
    :attr:`~Reader.after_entry_update_hooks`,
    :attr:`~Reader.after_feed_update_hooks`, and
    :attr:`~Reader.after_feeds_update_hooks`,
    don’t stop after one fails.

* Add :exc:`UpdateError` as parent of all update-related exceptions. (:issue:`218`)

  * Narrow down the error type of :attr:`UpdateResult.value`
    from :exc:`ReaderError` to :exc:`UpdateError`.
  * Make :exc:`ParseError` inherit from :exc:`UpdateError`.
  * Document :meth:`~Reader.update_feeds_iter()`, :meth:`~Reader.update_feeds()`,
    and :meth:`~Reader.update_feed()` can raise :exc:`UpdateError`\s
    (other than :exc:`UpdateHookError` and :exc:`ParseError`).

* Make :exc:`ReaderWarning` inherit from :exc:`ReaderError`.

* Include a diagram of the :ref:`exctree` in the :doc:`api`.

* Add werkzeug dependency,
  instead of vendoring selected :mod:`werkzeug.http` utilities.
* Rework lazy imports introduced in `version 3.3 <Version 3.3_>`_.
  (:issue:`316`)
* Make :mod:`reader._parser` a package, and move parsing-related modules into it.
  (:issue:`316`)


Version 3.7
-----------

Released 2023-07-15

.. attention::

    This is the last release to support Python 3.9;
    see :issue:`302` for details.

* Support PyPy 3.10. (:issue:`302`)

* Remove the :ref:`twitter` experimental plugin
  (deprecated in `3.6 <Version 3.6_>`_).
  (:issue:`310`)
* Remove the :ref:`tumblr_gdpr` experimental plugin
  (not needed since August 2020).
  (:issue:`315`)


Version 3.6
-----------

Released 2023-06-16

* Add documentation on :doc:`contributing`
  and a detailed :ref:`roadmap`.
  Thanks to `Katharine Jarmul <https://kjamistan.com/>`_
  for finally getting me to do this.
  (:issue:`60`)
* Document the low-level
  :meth:`~reader._storage.Storage.delete_entries`
  storage method.
  (:issue:`301`, :issue:`96`)
* Update vendored ``reader._http_utils`` to werkzeug 2.3.5.

* Deprecate the :ref:`twitter` experimental plugin,
  since the Twitter API does not have a (useful) free tier anymore.
  (:issue:`310`)

  .. attention::

    The :ref:`twitter` plugin will be removed in version 3.7.


Version 3.5
-----------

Released 2023-03-19

* Make :attr:`Entry.important` an *optional* boolean
  defaulting to :const:`None`,
  so one can express "explicitly unimportant" (*don't care*)
  by setting it to :const:`False`.
  This replaces the semantics for *don't care* introduced
  in `version 2.2 <Version 2.2_>`_.
  (:issue:`254`)

  .. warning::

    **This is a minor compatibility break**,
    and should mostly affect code that checks identity
    (``if entry.important is True: ...``);
    code that uses :attr:`~Entry.important` in a boolean context
    (``if entry.important: ...``)
    should not be affected.

  * :attr:`Entry.important` values will be migrated as follows::

      if read and not important and important_modified:
          important = False
      elif not important:
          important = None
      else:
          important = important

  * The ``important`` argument of
    :meth:`~Reader.get_entries`, :meth:`~Reader.search_entries`, etc.
    can also take string literals for more precise filtering,
    see :attr:`~reader.types.TristateFilterInput`.

  * The :mod:`~reader.plugins.mark_as_read` plugin
    does not set :attr:`~reader.Entry.read_modified` and
    :attr:`~reader.Entry.important_modified` anymore.

  * The web app uses the new *don't care* semantics.

* :meth:`~Reader.set_entry_read` and :meth:`~Reader.set_entry_important`
  do not coerce the flag value to :class:`bool` anymore,
  and require it to be :const:`True` or :const:`False` (or :const:`None`).


Version 3.4
-----------

Released 2023-01-22

* Drop Python 3.8 support. (:issue:`298`)

* Document the parser :doc:`internal`.
  (:issue:`235`, :issue:`255`)

* Fix ``preview_feed_list`` plugin,
  broken by `3.3 <Version 3.3_>`_ parser refactoring.
  (:issue:`299`)


Version 3.3
-----------

Released 2022-12-19

This release marks *reader*'s `5th anniversary`_ and its 2000th commit.

.. attention::

    This is the last release to support Python 3.8;
    see :issue:`298` for details.

* Support Python 3.11. (:issue:`289`)

* Postpone update-related imports until needed.
  Shortens time from process start to usable Reader instance by 3x
  (imports are 72% faster). (:issue:`297`)

* Refactor parser internals. (:issue:`297`)

  .. note::

    Plugins using the (unstable) session hooks should replace::

        reader._parser.session_hooks.request.append(...)
        reader._parser.session_hooks.response.append(...)

    with::

        reader._parser.session_factory.request_hooks.append(...)
        reader._parser.session_factory.response_hooks.append(...)

* :ref:`twitter` plugin:
  don't fail when deserializing tweets with missing ``edit_history_tweet_ids``
  (fails in tweepy 4.11, warns in tweepy >4.12).

.. _5th anniversary: https://github.com/lemon24/reader/commit/73ac0bd3b8d0e5429e0bd7caf5281e4c9c74f16d


Version 3.2
-----------

Released 2022-09-14

* :class:`UpdatedFeed` changes:
  added field :attr:`~UpdatedFeed.unmodified`
  and property :attr:`~UpdatedFeed.total`;
  fields :attr:`~UpdatedFeed.new` and :attr:`~UpdatedFeed.modified`
  became optional.
  (:issue:`96`)
* Fix bug in :mod:`~reader.plugins.entry_dedupe` causing updates to fail
  if there were multiple *new* duplicates of the same entry.
  (:issue:`292`)
* Fix bug in :mod:`~reader.plugins.readtime`
  and :mod:`~reader.plugins.mark_as_read` causing updates to fail
  if an entry was deleted by another plugin.
  (:issue:`292`)
* Fix bug in :mod:`~reader.plugins.mark_as_read` causing updates to fail
  if an entry had no title.
* In the CLI, don't suppress the traceback of :exc:`ReaderError`,
  since it would also suppress it for bugs.
* In the CLI, stop using deprecated :func:`click.get_terminal_size`.


Version 3.1
-----------

Released 2022-08-29

* Drop :mod:`~reader.plugins.readtime` plugin dependency
  on `readtime <https://github.com/alanhamlett/readtime_>`_
  (which has a transitive dependency on lxml,
  which does not always have PyPy Windows wheels on PyPI).
  The ``readtime`` extra is deprecated,
  but remains available to avoid breaking dependent packages.
  (:issue:`286`)
* Sort entries by added date most of the time,
  with the exception of those imported on the first update.
  Previously, entries would be sorted by added
  only if they were published less than 7 days ago,
  causing entries that appear in the feed months after their published
  to never appear at the top (so the user would never see them).
  (:issue:`279`)


Version 3.0
-----------

Released 2022-07-30

.. attention::

    This release contains backwards incompatible changes.


* Remove old database migrations.

  Remove :mod:`~reader.plugins.mark_as_read` config tag name migration.

  If you are upgrading from *reader* 2.10 or newer, no action is required.

  .. _removed migrations 3.0:

  .. attention::

    If you are upgrading to *reader* 3.0 from a version **older than 2.10**,
    you must open your database with *reader* 2.10 or newer once,
    to run the removed migrations:

    .. code-block:: sh

        pip install 'reader>=2.10,<3' && \
        python - db.sqlite << EOF
        import sys
        from reader import make_reader
        from reader.plugins.mark_as_read import _migrate_pre_2_7_metadata as migrate_mark_as_read

        reader = make_reader(sys.argv[1])

        for feed in reader.get_feeds():
            migrate_mark_as_read(reader, feed)

        print("OK")

        EOF

* Remove code that issued deprecation warnings in versions 2.* (:issue:`268`):

  * :meth:`Reader.get_feed_metadata`
  * :meth:`Reader.get_feed_metadata_item`
  * :meth:`Reader.set_feed_metadata_item`
  * :meth:`Reader.delete_feed_metadata_item`
  * :meth:`Reader.get_feed_tags`
  * :meth:`Reader.add_feed_tag`
  * :meth:`Reader.remove_feed_tag`
  * :exc:`MetadataError`
  * :exc:`MetadataNotFoundError`
  * :exc:`FeedMetadataNotFoundError`
  * :exc:`EntryMetadataNotFoundError`
  * the :attr:`~Entry.object_id` property of data objects and related exceptions

* Make some of the parameters of the following positional-only (:issue:`268`):

  * :meth:`Reader.add_feed`: ``feed``
  * :meth:`Reader.delete_feed`: ``feed``
  * :meth:`Reader.change_feed_url`: ``old``, ``new``
  * :meth:`Reader.get_feed`: ``feed``, ``default``
  * :meth:`Reader.set_feed_user_title`: ``feed``, ``title``
  * :meth:`Reader.enable_feed_updates`: ``feed``
  * :meth:`Reader.disable_feed_updates`: ``feed``
  * :meth:`Reader.update_feed`: ``feed``
  * :meth:`Reader.get_entry`: ``entry``, ``default``
  * :meth:`Reader.set_entry_read`: ``entry``, ``read``
  * :meth:`Reader.mark_entry_as_read`: ``entry``
  * :meth:`Reader.mark_entry_as_unread`: ``entry``
  * :meth:`Reader.set_entry_important`: ``entry``, ``important``
  * :meth:`Reader.mark_entry_as_important`: ``entry``
  * :meth:`Reader.mark_entry_as_unimportant`: ``entry``
  * :meth:`Reader.add_entry`: ``entry``
  * :meth:`Reader.delete_entry`: ``entry``
  * :meth:`Reader.search_entries`: ``query``
  * :meth:`Reader.search_entry_counts`: ``query``
  * :meth:`Reader.get_tags`: ``resource``
  * :meth:`Reader.get_tag_keys`: ``resource``
  * :meth:`Reader.get_tag`: ``resource``, ``key``, ``default``
  * :meth:`Reader.set_tag`: ``resource``, ``key``, ``value``
  * :meth:`Reader.delete_tag`: ``resource``, ``key``
  * :meth:`Reader.make_reader_reserved_name`: ``key``
  * :meth:`Reader.make_plugin_reserved_name`: ``plugin_name``, ``key``
  * :exc:`FeedError` (and subclasses): ``url``
  * :exc:`EntryError` (and subclasses): ``feed_url``, ``entry_id``
  * :exc:`TagError` (and subclasses): ``resource_id``, ``key``

* In :func:`make_reader`,
  wrap exceptions raised during plugin initialization
  in new exception :exc:`PluginInitError`
  instead of letting them bubble up.
  (:issue:`268`)

* Swap the order of the first two arguments of :exc:`TagError` (and subclasses);
  ``TagError(key, resource_id, ...)`` becomes
  ``TagError(resource_id, key, ...)``.
  (:issue:`268`)



Version 2.17
------------

Released 2022-07-23

* Deprecate the :attr:`~Entry.object_id` property of data objects
  in favor of new property :attr:`~Entry.resource_id`.
  :attr:`~Entry.resource_id` is the same as :attr:`~Entry.object_id`,
  except for feeds and feed-related exceptions it is
  of type ``tuple[str]`` instead of ``str``.
  :attr:`~Entry.object_id` **will be removed in version 3.0**.
  (:issue:`266`, :issue:`268`)
* Do not attempt too hard to run ``PRAGMA optimize`` if the database is busy.
  Prevents rare "database is locked" errors when multiple threads
  using the same reader terminate at the same time.
  (:issue:`206`)


Version 2.16
------------

Released 2022-07-17

* Allow using a :class:`Reader` object from multiple threads directly
  (do not require it to be used as a context manager anymore).
  (:issue:`206`)
* Allow :class:`Reader` objects to be reused after closing.
  (:issue:`206`, :issue:`284`)
* Allow calling :meth:`~Reader.close` from any thread. (:issue:`206`)
* Allow using a :class:`Reader` object from multiple asyncio tasks.
  (:issue:`206`)


Version 2.15
------------

Released 2022-07-08

* Allow using :class:`Reader` objects from threads other than the creating thread.
  (:issue:`206`)
* Allow using :class:`Reader` objects as context managers.
  (:issue:`206`)


Version 2.14
------------

Released 2022-06-30

* Mark *reader* as providing type information.
  Previously, code importing from :mod:`reader` would fail type checking with
  ``error: Skipping analyzing "reader": module is installed,
  but missing library stubs or py.typed marker``.
  (:issue:`280`)
* Drop Python 3.7 support. (:issue:`278`)
* Support PyPy 3.9.


Version 2.13
------------

Released 2022-06-28

* Add the :ref:`twitter` experimental plugin,
  which allows using a Twitter account as a feed.
  (:issue:`271`)
* Skip with a warning entries that have no <guid> or <link> in an RSS feed;
  only raise :exc:`ParseError` if *all* entries have a missing id.
  (Note that both Atom and JSON Feed entries are required to have an id
  by their respective specifications.)
  Thanks to `Mirek Długosz`_ for the issue and pull request.
  (:issue:`281`)
* Add :exc:`ReaderWarning`.


Version 2.12
------------

Released 2022-03-31

* Add the :mod:`~reader.plugins.readtime`
  :ref:`built-in <built-in plugins>` plugin,
  which stores the entry read time as a tag during feed update.
  (:issue:`275`)

* Allow running arbitrary actions *once* before/after updating feeds
  via :attr:`~Reader.before_feeds_update_hooks` /
  :attr:`~Reader.after_feeds_update_hooks`.
* Add :meth:`Entry.get_content` and :attr:`Content.is_html`.

* In the web app, use the read time provided by the
  :mod:`~reader.plugins.readtime` plugin,
  instead of calculating it on each page load.
  Speeds up the rendering of the entries page by 20-30%,
  hopefully winning back the time lost
  when the read time feature was first added in `2.6 <Version 2.6_>`_.
  (:issue:`275`)
* In the web app, also show the read time for search results.


Version 2.11
------------

Released 2022-03-17

* Fix issue causing :func:`make_reader` to fail with message
  ``database requirement error: required SQLite compile options missing: ['ENABLE_JSON1']``
  when using SQLite 3.38 or newer.
  (:issue:`273`)


Version 2.10
------------

Released 2022-03-12

* Support entry and global tags. (:issue:`272`, :issue:`228`, :issue:`267`)

* Remove :meth:`~Reader.get_tags()` support for the
  ``(None,)`` (any feed) and :const:`None` (any resource)
  wildcard resource values.

  .. warning::

    **This is a minor compatibility break**, but is unlikely to affect existing users;
    the usefulness of the wildcards was limited, because
    it was impossible to tell to which resource a (key, value) pair belongs.

* Allow passing a `(feed URL,)` 1-tuple anywhere a feed URL can be passed
  to a :class:`Reader` method.

* Remove the ``global_metadata`` experimental plugin
  (superseded by global tags).

* In the web application, support editing entry and global metadata.
  Fix broken delete metadata button.
  Fix broken error flashing.


.. _version 2.9:

Version 2.9
-----------

Released 2022-02-07

* Decrease :meth:`~Reader.update_feeds()` memory usage by ~35%
  (using the maxrss before the call as baseline;
  overall process maxrss decreases by ~20%).
  The improvement is not in *reader* code, but in feedparser;
  *reader* will temporarily vendor feedparser
  until the fix makes it upstream and is released on PyPI.
  (:issue:`265`)

* In the web application, allow sorting feeds by the number of entries:
  important, unread, per day during the last 1, 3, 12 months.
  (:issue:`249`, :issue:`245`).


Version 2.8
-----------

Released 2022-01-22

* Add generic tag methods
  :meth:`~Reader.get_tags`,
  :meth:`~Reader.get_tag_keys`,
  :meth:`~Reader.get_tag`,
  :meth:`~Reader.set_tag`,
  and :meth:`~Reader.delete_tag`,
  providing a unified interface for accessing tags as key-value pairs.
  (:issue:`266`)

  Add the :exc:`TagError`, :exc:`TagNotFoundError`,
  and :exc:`ResourceNotFoundError` exceptions.

* Deprecate feed-specific tag and metadata methods (:issue:`266`):

  * :meth:`~Reader.get_feed_metadata`, use :meth:`~Reader.get_tags` instead
  * :meth:`~Reader.get_feed_metadata_item`, use :meth:`~Reader.get_tag` instead
  * :meth:`~Reader.set_feed_metadata_item`, use :meth:`~Reader.set_tag` instead
  * :meth:`~Reader.delete_feed_metadata_item`, use :meth:`~Reader.delete_tag` instead
  * :meth:`~Reader.get_feed_tags`, use :meth:`~Reader.get_tag_keys` instead
  * :meth:`~Reader.add_feed_tag`, use :meth:`~Reader.set_tag` instead
  * :meth:`~Reader.remove_feed_tag`, use :meth:`~Reader.delete_tag` instead

  Deprecate :exc:`MetadataError`, :exc:`MetadataNotFoundError`, and
  :exc:`FeedMetadataNotFoundError`.

  All deprecated methods/exceptions **will be removed in version 3.0**.

* Add the ``missing_ok`` argument to :meth:`~Reader.delete_feed`
  and :meth:`~Reader.delete_entry`.
* Add the ``exist_ok`` argument to :meth:`~Reader.add_feed`.

* In the web application, show maxrss when debug is enabled. (:issue:`269`)
* In the web application, decrease memory usage of the entries page
  when there are a lot of entries
  (e.g. for 2.5k entries, maxrss decreased from 115 MiB to 75 MiB),
  at the expense of making "entries for feed" slightly slower.
  (:issue:`269`)


Version 2.7
-----------

Released 2022-01-04

* Tags and metadata now share the same namespace.
  See the :ref:`feed-tags` user guide section for details.
  (:issue:`266`)
* The :mod:`~reader.plugins.mark_as_read` plugin now uses the
  ``.reader.mark-as-read`` metadata for configuration.
  Feeds using the old metadata, ``.reader.mark_as_read``,
  will be migrated automatically on update until `reader` 3.0.
* Allow running arbitrary actions before updating feeds
  via :attr:`~Reader.before_feed_update_hooks`.
* Expose :data:`reader.plugins.DEFAULT_PLUGINS`.
* Add the ``global_metadata`` experimental plugin.


Version 2.6
-----------

Released 2021-11-15

* Retrieve feeds in parallel, but parse them serially;
  previously, feeds would be parsed in parallel.
  Decreases Linux memory usage by ~20% when using ``workers``;
  the macOS decrease is less notable.
  (:issue:`261`)

* Allow :meth:`~Reader.update_feeds()` and :meth:`~Reader.update_feeds_iter()`
  to filter feeds by ``feed``, ``tags``, ``broken``, and ``updates_enabled``.
  (:issue:`193`, :issue:`219`, :issue:`220`)
* Allow :meth:`~Reader.get_feeds()` and :meth:`~Reader.get_feed_counts()`
  to filter feeds by ``new``.
  (:issue:`217`)

* Reuse the `requests`_ session when retrieving feeds;
  previously, each feed would get its own session.

* Add support for CLI plugins.
* Add the :mod:`~reader._plugins.cli_status` experimental plugin.

* In the web application, show entry read time.


Version 2.5
-----------

Released 2021-10-28

* In :meth:`~Reader.add_feed` and :meth:`~Reader.change_feed_url`,
  validate if the current Reader configuration can handle the new feed URL;
  if not, raise :exc:`InvalidFeedURLError` (a :exc:`ValueError` subclass).
  (:issue:`155`)

  .. warning::

    **This is a minor compatibility break**; previously,
    :exc:`ValueError` would never be raised for :class:`str` arguments.
    To get the previous behavior (no validation),
    use ``allow_invalid_url=True``.

* Allow users to add entries to an existing feed
  through the new :meth:`~Reader.add_entry` method.
  Allow deleting user-added entries through :meth:`~Reader.delete_entry`.
  (:issue:`239`)
* Add the :attr:`~Entry.added` and :attr:`~Entry.added_by` Entry attributes.
  (:issue:`239`)

* :attr:`Entry.updated` is now :const:`None` if missing in the feed
  (:attr:`~Entry.updated` became optional in `version 2.0`_).
  Use :attr:`~Entry.updated_not_none` for the pre-2.5 behavior.
  Do not swap :attr:`Entry.published` with :attr:`Entry.updated`
  for RSS feeds where :attr:`~Entry.updated` is missing.
  (:issue:`183`)

* Support PyPy 3.8.

* Fix bug causing
  :attr:`~Entry.read_modified` and :attr:`~Entry.important_modified`
  to be reset to :const:`None` when an entry is updated.
* Fix bug where deleting an entry and then adding it again
  (with the same id) would fail
  if search was enabled and :meth:`~Reader.update_search`
  was not run before adding the new entry.


Version 2.4
-----------

Released 2021-10-19

* Enable search by default. (:issue:`252`)

  * Add the ``search_enabled`` :func:`make_reader` argument.
    By default, search is enabled on the first
    :meth:`~Reader.update_search` call;
    the previous behavior was to do nothing.
  * Always install the full-text search dependencies (previously optional).
    The ``search`` extra remains available to avoid breaking dependent packages.

* Add the :attr:`~Feed.subtitle` and :attr:`~Feed.version` Feed attributes.
  (:issue:`223`)

* Change the :mod:`~reader.plugins.mark_as_read` plugin to also
  explicitly mark matching entries as unimportant,
  similar to how the *don't care* web application button works.
  (:issue:`260`)

* In the web application, show the feed subtitle.
  (:issue:`223`)


Version 2.3
-----------

Released 2021-10-11

* Support Python 3.10. (:issue:`248`)

* :mod:`~reader.plugins.entry_dedupe` now
  deletes old duplicates instead of marking them as read/unimportant.
  (:issue:`140`)

  .. note::

    Please comment in :issue:`140` / open an issue
    if you were relying on the old behavior.

* .. _yanked 2.2:

  Fix :mod:`~reader.plugins.entry_dedupe` bug introduced in 2.2,
  causing the newest read entry to be marked as unread
  if none of its duplicates are read (idem for important).
  This was an issue *only when re-running the plugin for existing entries*,
  not for new entries (since new entries are unread/unimportant).


Version 2.2
-----------

Released 2021-10-08

* :mod:`~reader.plugins.entry_dedupe` plugin improvements:
  reduce false negatives by using approximate content matching,
  and make it possible to re-run the plugin for existing entries.
  (:issue:`202`)
* Allow running arbitrary actions for updated feeds
  via :attr:`~Reader.after_feed_update_hooks`.
  (:issue:`202`)

* Add :meth:`~Reader.set_entry_read` and :meth:`~Reader.set_entry_important`
  to allow marking an entry as (un)read/(un)important through a boolean flag.
  (:issue:`256`)

* Record when an entry is marked as read/important,
  and make it available through :attr:`~Entry.read_modified` and
  :attr:`~Entry.important_modified`.
  Allow providing a custom value using the ``modified``
  argument of :meth:`~Reader.set_entry_read`
  and :meth:`~Reader.set_entry_important`.
  (:issue:`254`)
* Make :mod:`~reader.plugins.entry_dedupe` copy
  :attr:`~Entry.read_modified` and :attr:`~Entry.important_modified`
  from the duplicates to the new entry.
  (:issue:`254`)

* In the web application, allow marking an entry as *don't care*
  (read + unimportant explicitly set by the user) with a single button.
  (:issue:`254`)
* In the web application, show the entry read modified / important modified
  timestamps as button tooltips.
  (:issue:`254`)


Version 2.1
-----------

Released 2021-08-18

* Return :ref:`entry averages <entry averages>` for the past 1, 3, 12 months
  from the entry count methods. (:issue:`249`)

* Use an index for ``get_entry_counts(feed=...)`` calls.
  Makes the /feeds?counts=yes page load 2-4x faster. (:issue:`251`)

* Add :class:`UpdateResult` :attr:`~UpdateResult.updated_feed`,
  :attr:`~UpdateResult.error`, and :attr:`~UpdateResult.not_modified`
  convenience properties. (:issue:`204`)

* In the web application, show the feed entry count averages as a bar sparkline.
  (:issue:`249`)

* Make the minimum SQLite version and required SQLite compile options
  ``reader._storage`` module globals, for easier monkeypatching. (:issue:`163`)

  This is allows supplying a user-defined ``json_array_length`` function
  on platforms where SQLite doesn't come with the JSON1 extension
  (e.g. on Windows with stock Python earlier than 3.9;
  `details <https://github.com/lemon24/reader/issues/163#issuecomment-895041943>`_).

  Note these globals are private, and thus *not* covered by the
  :ref:`backwards compatibility policy <compat>`.


Version 2.0
-----------

Released 2021-07-17


.. attention::

    This release contains backwards incompatible changes.


* Remove old database migrations.

  If you are upgrading from *reader* 1.15 or newer, no action is required.

  .. _removed migrations 2.0:

  .. attention::

    If you are upgrading to *reader* 2.0 from a version **older than 1.15**,
    you must open your database with *reader* 1.15 or newer once,
    to run the removed migrations:

    .. code-block:: sh

        pip install 'reader>=1.15,<2' && \
        python - db.sqlite << EOF
        import sys
        from reader import make_reader
        make_reader(sys.argv[1])
        print("OK")
        EOF

* Remove code that issued deprecation warnings in versions 1.* (:issue:`183`):

  * :meth:`Reader.remove_feed`
  * :meth:`Reader.mark_as_read`
  * :meth:`Reader.mark_as_unread`
  * :meth:`Reader.mark_as_important`
  * :meth:`Reader.mark_as_unimportant`
  * :meth:`Reader.iter_feed_metadata`
  * the ``get_feed_metadata(feed, key, default=no value, /)``
    form of :meth:`Reader.get_feed_metadata`
  * :meth:`Reader.set_feed_metadata`
  * :meth:`Reader.delete_feed_metadata`
  * the ``new_only`` parameter of
    :meth:`~Reader.update_feeds()` and :meth:`~Reader.update_feeds_iter()`
  * :attr:`EntryError.url`
  * :attr:`UpdatedFeed.updated`

* The :class:`~datetime.datetime` attributes
  of :class:`Feed` and :class:`Entry` objects are now timezone-aware,
  with the timezone set to :attr:`~datetime.timezone.utc`.
  Previously, they were naive datetimes representing UTC times.
  (:issue:`233`)

* The parameters of
  :meth:`~Reader.update_feeds()` and :meth:`~Reader.update_feeds_iter()`
  are now keyword-only. (:issue:`183`)

* The ``feed_root`` argument of :func:`make_reader`
  now defaults to ``None`` (don't open local feeds)
  instead of ``''`` (full filesystem access).

* :func:`make_reader` may now raise any :exc:`ReaderError`,
  not just :exc:`StorageError`.

* :attr:`Entry.updated` may now be :const:`None`;
  use :attr:`~Entry.updated_not_none` for the pre-2.0 behavior.


Version 1.20
------------

Released 2021-07-12

* Add :attr:`~Reader.after_entry_update_hooks`,
  which allow running arbitrary actions for updated entries.
  Thanks to `Mirek Długosz`_ for the issue and pull request.
  (:issue:`241`)
* Raise :exc:`StorageError` when opening / operating on an invalid database,
  instead of a plain :exc:`sqlite3.DatabaseError`.
  (:issue:`243`)

.. _Mirek Długosz: https://github.com/mirekdlugosz


Version 1.19
------------

Released 2021-06-16

* Drop Python 3.6 support. (:issue:`237`)
* Support PyPy 3.7. (:issue:`234`)
* Skip enclosures with no ``href``/``url``;
  previously, they would result in a parse error.
  (:issue:`240`)
* Stop using Travis CI (only use GitHub Actions). (:issue:`199`)
* Add the ``new`` argument to
  :meth:`~Reader.update_feeds()` and :meth:`~Reader.update_feeds_iter()`;
  ``new_only`` is deprecated and **will be removed in 2.0**.
  (:issue:`217`)

* Rename :attr:`UpdatedFeed.updated` to :attr:`~UpdatedFeed.modified`;
  for backwards compatibility,
  the old attribute will be available as a property **until version 2.0**,
  when it **will be removed.**. (:issue:`241`)

  .. warning::

    The signature of :class:`UpdatedFeed`
    changed from ``UpdatedFeed(url, new, updated)``
    to ``UpdatedFeed(url, new, modified)``.

    **This is a minor compatibility break**,
    but only affects third-party code that instantiates
    UpdatedFeed *directly* with ``updated`` as a *keyword argument*.


Version 1.18
------------

Released 2021-06-03

* Rename :class:`Reader` feed metadata methods:

  * :meth:`~Reader.iter_feed_metadata` to :meth:`~Reader.get_feed_metadata`
  * :meth:`~Reader.get_feed_metadata` to :meth:`~Reader.get_feed_metadata_item`
  * :meth:`~Reader.set_feed_metadata` to :meth:`~Reader.set_feed_metadata_item`
  * :meth:`~Reader.delete_feed_metadata` to :meth:`~Reader.delete_feed_metadata_item`

  For backwards compatibility,
  the old method signatures will continue to work **until version 2.0**,
  when they **will be removed.** (:issue:`183`)

  .. warning::

    The ``get_feed_metadata(feed, key[, default]) -> value`` form
    is backwards-compatible *only when the arguments are positional*.

    **This is a minor compatibility break**;
    the following work in 1.17, but do not in 1.18::

        # raises TypeError
        reader.get_feed_metadata(feed, key, default=None)

        # returns `(key, value), ...` instead of `value`
        reader.get_feed_metadata(feed, key=key)

    The pre-1.18 :meth:`~Reader.get_feed_metadata`
    (1.18 :meth:`~Reader.get_feed_metadata_item`)
    is intended to have positional-only arguments,
    but this cannot be expressed easily until Python 3.8.

* Rename :exc:`MetadataNotFoundError` to :exc:`FeedMetadataNotFoundError`.
  :exc:`MetadataNotFoundError` remains available,
  and is a superclass of :exc:`FeedMetadataNotFoundError`
  for backwards compatibility.
  (:issue:`228`)

  .. warning::

    The signatures of the following exceptions changed:

    :exc:`MetadataError`
        Takes a new required ``key`` argument, instead of no required arguments.

    :exc:`MetadataNotFoundError`
        Takes only one required argument, ``key``;
        the ``url`` argument has been removed.

        Use :exc:`FeedMetadataNotFoundError` instead.

    **This is a minor compatibility break**,
    but only affects third-party code that instantiates
    these exceptions *directly*.

* Rename :attr:`EntryError.url` to :attr:`~EntryError.feed_url`;
  for backwards compatibility,
  the old attribute will be available as a property **until version 2.0**,
  when it **will be removed.** (:issue:`183`).

  .. warning::

    The signature of :exc:`EntryError` (and its subclasses)
    changed from ``EntryError(url, id)`` to ``EntryError(feed_url, id)``.

    **This is a minor compatibility break**,
    but only affects third-party code that instantiates
    these exceptions *directly* with ``url`` as a *keyword argument*.

* Rename :meth:`~Reader.remove_feed` to :meth:`~Reader.delete_feed`.
  For backwards compatibility,
  the old method will continue to work **until version 2.0**,
  when it **will be removed.** (:issue:`183`)

* Rename :class:`Reader` ``mark_as_...`` methods:

  * :meth:`~Reader.mark_as_read` to :meth:`~Reader.mark_entry_as_read`
  * :meth:`~Reader.mark_as_unread` to :meth:`~Reader.mark_entry_as_unread`
  * :meth:`~Reader.mark_as_important` to :meth:`~Reader.mark_entry_as_important`
  * :meth:`~Reader.mark_as_unimportant` to :meth:`~Reader.mark_entry_as_unimportant`

  For backwards compatibility,
  the old methods will continue to work **until version 2.0**,
  when they **will be removed.** (:issue:`183`)

* Fix feeds with no title sometimes missing
  from the :meth:`~Reader.get_feeds()` results
  when there are more than 256 feeds (``Storage.chunk_size``).
  (:issue:`203`)

* When serving the web application with ``python -m reader serve``,
  don't set the ``Referer`` header for cross-origin requests.
  (:issue:`209`)


Version 1.17
------------

Released 2021-05-06

* Reserve tags and metadata keys starting with ``.reader.`` and ``.plugin.``
  for *reader*- and plugin-specific uses.
  See the :ref:`reserved names` user guide section for details.
  (:issue:`186`)

* Ignore :attr:`~Feed.updated` when updating feeds;
  only update the feed if other feed data changed
  or if any entries were added/updated.
  (:issue:`231`)

  Prevents spurious updates for feeds whose :attr:`~Feed.updated`
  changes excessively
  (either because the entries' content changes excessively,
  or because an RSS feed does not have a ``dc:date`` element,
  and feedparser falls back to ``lastBuildDate`` for :attr:`~Feed.updated`).

* The ``regex_mark_as_read`` experimental plugin is now
  :ref:`built-in <built-in plugins>`.
  To use it with the CLI / web application,
  use the plugin name instead of the entry point (``reader.mark_as_read``).

  The config metadata key and format changed;
  the config will be migrated automatically on the next feed update,
  **during reader version 1.17 only**.
  If you used ``regex_mark_as_read`` and are upgrading to a version >1.17,
  install 1.17 (``pip install reader==1.17``)
  and run a full feed update (``python -m reader update``)
  before installing the newer version.

* The ``enclosure-tags``, ``preview-feed-list``, and ``sqlite-releases``
  unstable extras are not available anymore.
  Use the ``unstable-plugins`` extra to install
  dependencies of the unstable plugins instead.

* In the web application, allow updating a feed manually.
  (:issue:`195`)


Version 1.16
------------

Released 2021-03-29

* Allow :func:`make_reader` to load plugins through the ``plugins`` argument.
  (:issue:`229`)

  Enable the :mod:`~reader.plugins.ua_fallback` plugin by default.

  :func:`make_reader` may now raise :exc:`InvalidPluginError`
  (a :exc:`ValueError` subclass, which it already raises implicitly)
  for invalid plugin names.

* The ``enclosure_dedupe``, ``feed_entry_dedupe``, and ``ua_fallback`` plugins
  are now :ref:`built-in <built-in plugins>`.
  (:issue:`229`)

  To use them with the CLI / web application,
  use the plugin name instead of the entry point::

    reader._plugins.enclosure_dedupe:enclosure_dedupe   -> reader.enclosure_dedupe
    reader._plugins.feed_entry_dedupe:feed_entry_dedupe -> reader.entry_dedupe
    reader._plugins.ua_fallback:init                    -> reader.ua_fallback

* Remove the ``plugins`` extra;
  plugin loading machinery does not have additional dependencies anymore.

* Mention in the :doc:`guide` that all *reader* functions/methods can raise
  :exc:`ValueError` or :exc:`TypeError` if passed invalid arguments.
  There is no behavior change, this is just documenting existing,
  previously undocumented behavior.


Version 1.15
------------

Released 2021-03-21

* Update entries whenever their content changes,
  regardless of their :attr:`~Entry.updated` date.
  (:issue:`179`)

  Limit content-only updates (not due to an :attr:`~Entry.updated` change)
  to 24 consecutive updates,
  to prevent spurious updates for entries whose content changes
  excessively (for example, because it includes the current time).
  (:issue:`225`)

  Previously, entries would be updated only if the
  entry :attr:`~Entry.updated` was *newer* than the stored one.

* Fix bug causing entries that don't have :attr:`~Entry.updated`
  set in the feed to not be updated if the feed is marked as stale.
  Feed staleness is an internal feature used during storage migrations;
  this bug could only manifest when migrating from 0.22 to 1.x.
  (found during :issue:`179`)
* Minor web application improvements.
* Minor CLI improvements.


Version 1.14
------------

Released 2021-02-22

* Add the :meth:`~Reader.update_feeds_iter` method,
  which yields the update status of each feed as it gets updated.
  (:issue:`204`)
* Change the return type of :meth:`~Reader.update_feed`
  from ``None`` to ``Optional[UpdatedFeed]``.
  (:issue:`204`)
* Add the ``session_timeout`` argument to :func:`make_reader`
  to set a timeout for retrieving HTTP(S) feeds.
  The default (connect timeout, read timeout) is (3.05, 60) seconds;
  the previous behavior was to *never time out*.
* Use ``PRAGMA user_version`` instead of a version table. (:issue:`210`)
* Use ``PRAGMA application_id`` to identify reader databases;
  the id is ``0x66656564`` – ``read`` in ASCII / UTF-8. (:issue:`211`)
* Change the ``reader update`` command to show a progress bar
  and update summary (with colors), instead of plain log output.
  (:issue:`204`)
* Fix broken Mypy config following 0.800 release. (:issue:`213`)


Version 1.13
------------

Released 2021-01-29

* JSON Feed support. (:issue:`206`)
* Split feed retrieval from parsing;
  should make it easier to add new/custom parsers.
  (:issue:`206`)
* Prevent any logging output from the ``reader`` logger by default.
  (:issue:`207`)
* In the ``preview_feed_list`` plugin, add ``<link rel=alternative ...>``
  tags as a feed detection heuristic.
* In the ``preview_feed_list`` plugin, add ``<a>`` tags as
  a *fallback* feed detection heuristic.
* In the web application, fix bug causing the entries page to crash
  when counts are enabled.


Version 1.12
------------

Released 2020-12-13

* Add the ``limit`` and ``starting_after`` arguments to
  :meth:`~Reader.get_feeds`, :meth:`~Reader.get_entries`,
  and :meth:`~Reader.search_entries`,
  allowing them to be used in a paginated fashion.
  (:issue:`196`)
* Add the :attr:`~Entry.object_id` property that allows
  getting the unique identifier of a data object in a uniform way.
  (:issue:`196`)
* In the web application, add links to toggle feed/entry counts. (:issue:`185`)


Version 1.11
------------

Released 2020-11-28

* Allow disabling feed updates for specific feeds. (:issue:`187`)
* Add methods to get aggregated feed and entry counts. (:issue:`185`)
* In the web application:
  allow disabling feed updates for a feed;
  allow filtering feeds by whether they have updates enabled;
  do not show feed update errors for feeds that have updates disabled.
  (:issue:`187`)
* In the web application,
  show feed and entry counts when ``?counts=yes`` is used.
  (:issue:`185`)
* In the web application,
  use YAML instead of JSON for the tags and metadata fields.


Version 1.10
------------

Released 2020-11-20

* Use indexes for :meth:`~Reader.get_entries()` (recent order);
  should make calls 10-30% faster.
  (:issue:`134`)
* Allow sorting :meth:`~Reader.search_entries` results randomly.
  Allow sorting search results randomly in the web application.
  (:issue:`200`)
* Reraise unexpected errors caused by parser bugs
  instead of replacing them with an :exc:`AssertionError`.
* Add the ``sqlite_releases`` custom parser plugin.
* Refactor the HTTP feed sub-parser to allow reuse by custom parsers.
* Add a user guide, and improve other parts of the documentation.
  (:issue:`194`)


Version 1.9
-----------

Released 2020-10-28

* Support Python 3.9. (:issue:`199`)
* Support Windows (requires Python >= 3.9). (:issue:`163`)
* Use GitHub Actions to do macOS and Windows CI builds. (:issue:`199`)
* Rename the ``cloudflare_ua_fix`` plugin to ``ua_fallback``.
  Retry any feed that gets a 403, not just those served by Cloudflare.
  (:issue:`181`)
* Fix type annotation to avoid mypy 0.790 errors. (:issue:`198`)


Version 1.8
-----------

Released 2020-10-02

* Drop feedparser 5.x support (deprecated in 1.7);
  use feedparser 6.x instead.
  (:issue:`190`)
* Make the string representation of :exc:`ReaderError` and its subclasses
  more consistent; add error messages and improve the existing ones.
  (:issue:`173`)
* Add method :meth:`~Reader.change_feed_url` to change the URL of a feed.
  (:issue:`149`)
* Allow changing the URL of a feed in the web application.
  (:issue:`149`)
* Add more tag navigation links to the web application.
  (:issue:`184`)
* In the ``feed_entry_dedupe`` plugin,
  copy the important flag from the old entry to the new one.
  (:issue:`140`)


Version 1.7
-----------

Released 2020-09-19

* Add new methods to support feed tags: :meth:`~Reader.add_feed_tag`,
  :meth:`~Reader.remove_feed_tag`, and :meth:`~Reader.get_feed_tags`.
  Allow filtering feeds and entries by their feed tags.
  (:issue:`184`)
* Add the ``broken`` argument to :meth:`~Reader.get_feeds`,
  which allows getting only feeds that failed / did not fail
  during the last update.
  (:issue:`189`)
* feedparser 5.x support is deprecated in favor of feedparser 6.x.
  Using feedparser 5.x will raise a deprecation warning in version 1.7,
  and support will be removed the following version.
  (:issue:`190`)
* Tag-related web application features:
  show tags in the feed list;
  allow adding/removing tags;
  allow filtering feeds and entries by their feed tag;
  add a page that lists all tags.
  (:issue:`184`)
* In the web application, allow showing only feeds that failed / did not fail.
  (:issue:`189`)
* In the ``preview_feed_list`` plugin, add ``<meta>`` tags as
  a feed detection heuristic.
* Add a few property-based tests. (:issue:`188`)


Version 1.6
-----------

Released 2020-09-04

* Add the ``feed_root`` argument to :func:`make_reader`,
  which allows limiting local feed parsing to a specific directory
  or disabling it altogether.
  Using it is recommended, since by default *reader* will access
  any local feed path
  (in 2.0, local file parsing will be disabled by default).
  (:issue:`155`)
* Support loading CLI and web application settings from a
  :doc:`configuration file <config>`. (:issue:`177`)
* Fail fast for feeds that return HTTP 4xx or 5xx status codes,
  instead of (likely) failing later with an ambiguous XML parsing error.
  The cause of the raised :exc:`ParseError` is now an instance of
  :exc:`requests.HTTPError`. (:issue:`182`)
* Add ``cloudflare_ua_fix`` plugin (work around Cloudflare sometimes
  blocking requests). (:issue:`181`)
* feedparser 6.0 (beta) compatibility fixes.
* Internal parser API changes to support alternative parsers, pre-request hooks,
  and making arbitrary HTTP requests using the same logic :class:`Reader` uses.
  (:issue:`155`)
* In the /preview page and the ``preview_feed_list`` plugin,
  use the same plugins the main :class:`Reader` does.
  (enabled by :issue:`155`)


Version 1.5
-----------

Released 2020-07-30

* Use rowid when deleting from the search index, instead of the entry id.
  Previously, each :meth:`~Reader.update_search` call would result in a full
  scan, even if there was nothing to update/delete.
  This should reduce the amount of reads significantly
  (deleting 4 entries from a database with 10k entries
  resulted in an 1000x decrease in bytes read).
  (:issue:`178`)
* Require at least SQLite 3.18 (released 2017-03-30) for the current
  :meth:`~Reader.update_search` implementation;
  all other *reader* features continue to work with SQLite >= 3.15.
  (:issue:`178`)
* Run ``PRAGMA optimize`` on :meth:`~Reader.close()`.
  This should increase the performance of all methods.
  As an example, in :issue:`178` it was found that :meth:`~Reader.update_search`
  resulted in a full scan of the entries table,
  even if there was nothing to update;
  this change should prevent this from happening.
  (:issue:`143`)

  .. note::
    ``PRAGMA optimize`` is a no-op in SQLite versions earlier than 3.18.
    In order to avoid the case described above, you should run `ANALYZE`_
    regularly (e.g. every few days).

.. _ANALYZE: https://www.sqlite.org/lang_analyze.html


Version 1.4
-----------

Released 2020-07-13

* Work to reduce the likelihood of "database is locked" errors during updates
  (:issue:`175`):

  * Prepare entries to be added to the search index
    (:meth:`~Reader.update_search`) outside transactions.
  * Fix bug causing duplicate rows in the search index
    when an entry changes while updating the search index.
  * Update the search index only when the indexed values change (details below).
  * Use SQLite WAL (details below).

* Update the search index only when the indexed values change.
  Previously, any change on a feed would result in all its entries being
  re-indexed, even if the feed title or the entry content didn't change.
  This should reduce the :meth:`~Reader.update_search` run time significantly.
* Use SQLite's `write-ahead logging`_ to increase concurrency.
  At the moment there is no way to disable WAL.
  This change may be reverted in the future.
  (:issue:`169`)
* Require at least click 7.0 for the ``cli`` extra.
* Do not fail for feeds with incorrectly-declared media types,
  if feedparser can parse the feed;
  this is similar to the current behavior for incorrectly-declared encodings.
  (:issue:`171`)
* Raise :exc:`ParseError` during update for feeds feedparser can't detect
  the type of, instead of silently returning an empty feed. (:issue:`171`)
* Add ``sort`` argument to :meth:`~Reader.search_entries`.
  Allow sorting search results by recency in addition to relevance
  (the default). (:issue:`176`)
* In the web application, display a nice error message for invalid search
  queries instead of returning an HTTP 500 Internal Server Error.
* Other minor web application improvements.
* Minor CLI logging improvements.

.. _write-ahead logging: https://www.sqlite.org/wal.html


Version 1.3
-----------

Released 2020-06-23

* If a feed failed to update, provide details about the error
  in :attr:`Feed.last_exception`. (:issue:`68`)
* Show details about feed update errors in the web application. (:issue:`68`)
* Expose the :attr:`~Feed.added` and :attr:`~Feed.last_updated` Feed attributes.
* Expose the :attr:`~Entry.last_updated` Entry attribute.
* Raise :exc:`ParseError` / log during update if an entry has no id,
  instead of unconditionally raising :exc:`AttributeError`. (:issue:`170`)
* Fall back to <link> as entry id if an entry in an RSS feed has no <guid>;
  previously, feeds like this would fail on update. (:issue:`170`)
* Minor web application improvements (show feed added/updated date).
* In the web application, handle previewing an invalid feed nicely
  instead of returning an HTTP 500 Internal Server Error. (:issue:`172`)
* Internal API changes to support multiple storage implementations
  in the future. (:issue:`168`)


Version 1.2
-----------

Released 2020-05-18

* Minor web application improvements.
* Remove unneeded additional query in methods that use pagination
  (for n = len(result) / page size, always do n queries instead n+1).
  :meth:`~Reader.get_entries` and :meth:`~Reader.search_entries` are now
  33–7% and 46–36% faster, respectively, for results of size 32–256.
  (:issue:`166`)
* All queries are now chunked/paginated to avoid locking the SQLite storage
  for too long, decreasing the chance of concurrent queries timing out;
  the problem was most visible during :meth:`~Reader.update_search`.
  This should cap memory usage for methods returning an iterable
  that were not paginated before;
  previously the whole result set would be read before returning it.
  (:issue:`167`)


Version 1.1
-----------

Released 2020-05-08

* Add ``sort`` argument to :meth:`~Reader.get_entries`.
  Allow sorting entries randomly in addition to the default
  most-recent-first order. (:issue:`105`)
* Allow changing the entry sort order in the web application. (:issue:`105`)
* Use a query builder instead of appending strings manually
  for the more complicated queries in search and storage. (:issue:`123`)
* Make searching entries faster by filtering them *before* searching;
  e.g. if 1/5 of the entries are read, searching only read entries
  is now ~5x faster. (enabled by :issue:`123`)


Version 1.0.1
-------------

Released 2020-04-30

* Fix bug introduced in `0.20 <Version 0.20_>`_ causing
  :meth:`~Reader.update_feeds()` to silently stop updating
  the remaining feeds after a feed failed. (:issue:`164`)


Version 1.0
-----------

Released 2020-04-28

* Make all private submodules explicitly private. (:issue:`156`)

  .. note::
    All direct imports from :mod:`reader` continue to work.

  * The ``reader.core.*`` modules moved to ``reader.*``
    (most of them prefixed by ``_``).
  * The web application WSGI entry point moved from
    ``reader.app.wsgi:app`` to ``reader._app.wsgi:app``.
  * The entry points for plugins that ship with reader moved from
    ``reader.plugins.*`` to ``reader._plugins.*``.

* Require at least beautifulsoup4 4.5 for the ``search`` extra
  (before, the version was unspecified). (:issue:`161`)
* Rename the web application dependencies extra from ``web-app`` to ``app``.
* Fix relative link resolution and content sanitization;
  sgmllib3k is now a required dependency for this reason.
  (:issue:`125`, :issue:`157`)


Version 0.22
------------

Released 2020-04-14

* Add the :attr:`Entry.feed_url` attribute. (:issue:`159`)
* Rename the :class:`EntrySearchResult` ``feed`` attribute to
  :attr:`~EntrySearchResult.feed_url`.
  Using ``feed`` will raise a deprecation warning in version 0.22,
  and will be removed in the following version. (:issue:`159`)
* Use ``executemany()`` instead of ``execute()`` in the SQLite storage.
  Makes updating feeds (excluding network calls) 5-10% faster. (:issue:`144`)
* In the web app, redirect to the feed's page after adding a feed. (:issue:`119`)
* In the web app, show highlighted search result snippets. (:issue:`122`)


Version 0.21
------------

Released 2020-04-04

* Minor consistency improvements to the web app search button. (:issue:`122`)
* Add support for web application plugins. (:issue:`80`)
* The enclosure tag proxy is now a plugin, and is disabled by default.
  See its documentation for details. (:issue:`52`)
* In the web app, the "add feed" button shows a preview before adding the feed.
  (:issue:`145`)
* In the web app, if the feed to be previewed is not actually a feed,
  show a list of feeds linked from that URL. This is a plugin,
  and is disabled by default. (:issue:`150`)
* reader now uses a User-Agent header like ``python-reader/0.21``
  when retrieving feeds instead of the default `requests`_ one. (:issue:`154`)


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
  :meth:`~Reader.update_feeds`. (:issue:`152`)

.. _requests: https://requests.readthedocs.io


Version 0.19
------------

Released 2020-03-25

* Support PyPy 3.6.
* Allow :ref:`searching for entries <fts>`. (:issue:`122`)
* Stricter type checking for the core modules.
* Various changes to the storage internal API.


Version 0.18
------------

Released 2020-01-26

* Support Python 3.8.
* Increase the :meth:`~Reader.get_entries` recent threshold from 3 to 7 days.
  (:issue:`141`)
* Enforce type checking for the core modules. (:issue:`132`)
* Use dataclasses for the data objects instead of attrs. (:issue:`137`)


Version 0.17
------------

Released 2019-10-12

* Remove the ``which`` argument of :meth:`~Reader.get_entries`. (:issue:`136`)
* :class:`Reader` objects should now be created using :func:`make_reader`.
  Instantiating Reader directly will raise a deprecation warning.
* The resources associated with a reader can now be released explicitly
  by calling its :meth:`~Reader.close()` method. (:issue:`139`)
* Make the database schema more strict regarding nulls. (:issue:`138`)
* Tests are now run in a random order. (:issue:`142`)


Version 0.16
------------

Released 2019-09-02

* Allow marking entries as important. (:issue:`127`)
* :meth:`~Reader.get_entries` and :meth:`~Reader.get_feeds` now take only
  keyword arguments.
* :meth:`~Reader.get_entries` argument ``which`` is now deprecated in favor
  of ``read``. (:issue:`136`)


Version 0.15
------------

Released 2019-08-24

* Improve entry page rendering for text/plain content. (:issue:`117`)
* Improve entry page rendering for images and code blocks. (:issue:`126`)
* Show enclosures on the entry page. (:issue:`128`)
* Show the entry author. (:issue:`129`)
* Fix bug causing the enclosure tag proxy to use too much memory. (:issue:`133`)
* Start using mypy on the core modules. (:issue:`132`)


Version 0.14
------------

Released 2019-08-12

* Drop Python 3.5 support. (:issue:`124`)
* Improve entry ordering implementation. (:issue:`110`)


Version 0.13
------------

Released 2019-07-12

* Add entry page. (:issue:`117`)
* :meth:`~Reader.get_feed` now raises :exc:`FeedNotFoundError` if the feed
  does not exist; use ``get_feed(..., default=None)`` for the old behavior.
* Add :meth:`~Reader.get_entry`. (:issue:`120`)


Version 0.12
------------

Released 2019-06-22

* Fix flashed messages never disappearing. (:issue:`81`)
* Minor metadata page UI improvements.
* Allow limiting the number of entries on the entries page
  via the ``limit`` URL parameter.
* Add link to the feed on the entries and feeds pages. (:issue:`118`)
* Use Black and pre-commit to enforce style.


Version 0.11
------------

Released 2019-05-26

* Support storing per-feed metadata. (:issue:`114`)
* Add feed metadata page to the web app. (:issue:`114`)
* The ``regex_mark_as_read`` plugin is now configurable via feed metadata;
  drop support for the ``READER_PLUGIN_REGEX_MARK_AS_READ_CONFIG`` file.
  (:issue:`114`)


Version 0.10
------------

Released 2019-05-18

* Unify plugin loading and error handling code. (:issue:`112`)
* Minor improvements to CLI error reporting.


Version 0.9
-----------

Released 2019-05-12

* Improve the :meth:`~Reader.get_entries` sorting algorithm.
  Fixes a bug introduced by :issue:`106`
  (entries of new feeds would always show up at the top). (:issue:`113`)


Version 0.8
-----------

Released 2019-04-21

* Make the internal APIs use explicit types instead of tuples. (:issue:`111`)
* Finish updater internal API. (:issue:`107`)
* Automate part of the release process (``scripts/release.py``).


Version 0.7
-----------

Released 2019-04-14

* Increase timeout of the button actions from 2 to 10 seconds.
* :meth:`~Reader.get_entries` now sorts entries by the import date first,
  and then by :attr:`~Entry.published`/:attr:`~Entry.updated`. (:issue:`106`)
* Add ``enclosure_dedupe`` plugin (deduplicate enclosures of an entry). (:issue:`78`)
* The ``serve`` command now supports loading plugins. (:issue:`78`)
* ``reader.app.wsgi`` now supports loading plugins. (:issue:`78`)


Version 0.6
-----------

Released 2019-04-13

* Minor web application style changes to make the layout more condensed.
* Factor out update logic into a separate interface. (:issue:`107`)
* Fix update failing if the feed does not have a content type header. (:issue:`108`)


Version 0.5
-----------

Released 2019-02-09

* Make updating new feeds up to 2 orders of magnitude faster;
  fixes a problem introduced by :issue:`94`. (:issue:`104`)
* Move the core modules to a separate subpackage and enforce test coverage
  (``make coverage`` now fails if the coverage for core modules is less than
  100%). (:issue:`101`)
* Support Python 3.8 development branch.
* Add ``dev`` and ``docs`` extras (to install development requirements).
* Build HTML documentation when running tox.
* Add ``test-all`` and ``docs`` make targets (to run tox / build HTML docs).


Version 0.4
-----------

Released 2019-01-02

* Support Python 3.7.
* Entry :attr:`~Entry.content` and :attr:`~Entry.enclosures` now default to
  an empty tuple instead of ``None``. (:issue:`99`)
* :meth:`~Reader.get_feeds` now sorts feeds by :attr:`~Feed.user_title` or
  :attr:`~Feed.title` instead of just :attr:`~Feed.title`. (:issue:`102`)
* :meth:`~Reader.get_feeds` now sorts feeds in a case insensitive way. (:issue:`103`)
* Add ``sort`` argument to :meth:`~Reader.get_feeds`; allows sorting
  feeds by title or by when they were added. (:issue:`98`)
* Allow changing the feed sort order in the web application. (:issue:`98`)


Version 0.3
-----------

Released on 2018-12-22

* :meth:`~Reader.get_entries` now prefers sorting by :attr:`~Entry.published`
  (if present) to sorting by :attr:`~Entry.updated`. (:issue:`97`)
* Add ``regex_mark_as_read`` plugin (mark new entries as read based on a regex).
  (:issue:`79`)
* Add ``feed_entry_dedupe`` plugin (deduplicate new entries for a feed).
  (:issue:`79`)
* Plugin loading machinery dependencies are now installed via the
  ``plugins`` extra.
* Add a plugins section to the documentation.


Version 0.2
-----------

Released on 2018-11-25

* Factor out storage-related functionality into a separate interface. (:issue:`94`)
* Fix ``update --new-only`` updating the same feed repeatedly on databases
  that predate ``--new-only``. (:issue:`95`)
* Add web application screenshots to the documentation.


Version 0.1.1
-------------

Released on 2018-10-21

* Fix broken ``reader serve`` command (broken in 0.1).
* Raise :exc:`StorageError` for unsupported SQLite configurations at
  :class:`Reader` instantiation instead of failing at run-time with a generic
  ``StorageError("sqlite3 error")``. (:issue:`92`)
* Fix wrong submit button being used when pressing enter in non-button fields.
  (:issue:`69`)
* Raise :exc:`StorageError` for failed migrations instead of an undocumented
  exception. (:issue:`92`)
* Use ``requests-mock`` in parser tests instead of a web server
  (test suite run time down by ~35%). (:issue:`90`)


Version 0.1
-----------

Released on 2018-09-15

* Initial release; public API stable.
* Support broken Tumblr feeds via the the :ref:`tumblr_gdpr` plugin. (:issue:`67`)
