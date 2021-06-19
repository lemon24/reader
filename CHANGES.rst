
Changelog
=========

.. module:: reader
  :noindex:


Version 1.20
------------

Unreleased

* Added public property :attr:`~Reader.after_entry_update_hooks` to
  :class:`Reader`, which contains list of hooks to run for each new/modified
  entry after :meth:`~Reader.update_feeds()` call. Hooks will receive
  :class:`Reader` instance, :class:`~types.Entry`-like object instance and
  :class:`~types.EntryUpdateStatus` value


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
  when it **will be removed.** (:issue:`241`).

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

  Enable the ``ua_fallback`` plugin by default.

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
* Support broken Tumblr feeds via the the ``tumblr_gdpr`` plugin. (:issue:`67`)
