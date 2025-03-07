
Development
===========

.. module:: reader
  :no-index:


Development should follow a problem-solution_ approach.

.. seealso:: :ref:`philosophy`

.. _problem-solution: https://hintjens.gitbooks.io/scalable-c/content/chapter1.html#problem-what-do-we-do-next



.. _roadmap:

Roadmap
-------

The plan is to continue evolving the library
to support as many "feed reader application" use cases as possible,
while still following the :ref:`philosophy`.
Even if a specific feature is not a good fit for the library itself,
it should be possible to find a more generic solution
that makes it possible to build the feature on top.

Following is an unsorted, non-exhausive list of known areas for improvement.
I am working on *reader* based on my current interests,
in my spare time,
but I will prioritize supporting :doc:`contributors <contributing>`
(discussions, reviews and so on).

* OPML support, :issue:`165`
* :ref:`deleting entries <deleting entries>`

  * archiving important entries of deleted feeds, :issue:`290`

* :ref:`feed interaction statistics <counts api>`

* security

  * XML safety, :issue:`212`
  * sanitization unification, likely as a plugin, :issue:`125` and :issue:`227`
  * relative link resolution unification, :issue:`125`

* sorting

  * reverse order, :issue:`201`
  * sort by "recently interacted with", :issue:`294`
  * better feed title sort, :issue:`250`
  * sort feeds by entry counts

    * by unread entries, :issue:`245`
    * by :attr:`~EntryCounts.averages` (implemented in the web app, but not in core)
    * :ref:`sorting by tag values <sort by tag>` can help do this in a plugin

* resource tags

  * :ref:`searchable tag values <searchable tags>`, e.g. for comments
  * :ref:`unification with entry.read/important <entry flag unification>`
  * optimistic locking, :issue:`308`
  * filter tags by prefix, :issue:`309`


* HTTP compliance, likely as plugins

  * 301 Moved Permanently, :issue:`246`
  * 410 Gone, :issue:`246`
  * 429 Too Many Requests, :issue:`307`

* add more fields to data objects

  * extra data, as an escape hatch, :issue:`277`

* :ref:`multiple storage implementations <multiple storage implementations>`
* :ref:`batch get methods <batch get methods>`
* :doc:`internal` stabilization
* arbitrary website scraping, :issue:`222`
* :ref:`feed categories <categories>`, likely as a plugin


.. seealso::

    `Open issues`_ and :ref:`Design notes`.

.. _open issues: https://github.com/lemon24/reader/issues


.. _cli roadmap:

Command-line interface
~~~~~~~~~~~~~~~~~~~~~~

The :doc:`cli` is more or less stable,\ [*]_
although both the output and config loading need more polish
and additional tests.

A full-blown terminal feed reader is *not* in scope,
since I don't need one,
but I'm not opposed to the idea.

.. [*] With the exception of ``serve``, which is provided by the web app.


.. _app roadmap:

Web application
~~~~~~~~~~~~~~~

The :doc:`app` is "unsupported",
in that it's not all that polished,
and I don't have time to do major improvments.
But, I am using it daily,
and it will keep working until a better one exists.

Long term, I'd like to:

* re-design it from scratch to improve usability
  (see :issue:`318` for a wishlist)
* switch to `htmx`_ instead of using a home-grown solution
* spin it off into a separate package/project

**2025 update**:
I've started working on a re-design based on `htmx`_ and `Bootstrap`_;
some :ref:`screenshots <app screenshots>`.
The new app will be available in parallel with the old one
until it reaches feature parity.

.. _htmx: https://htmx.org/
.. _Bootstrap: https://getbootstrap.com/


.. _compat:

Backwards compatibility
-----------------------

*reader* uses `semantic versioning`_.

Breaking compatibility is done by incrementing the major version,
announcing it in the :doc:`changelog`,
and raising deprecation warnings for at least one minor version
before the new major version is released (if possible).

There may be minor exceptions to this,
e.g. bug fixes and gross violation of specifications;
they will be announced in the :doc:`changelog`
with a **This is a minor compatibility break** warning.

Schema migrations for the default storage must happen automatically.
Migrations can be removed in new major versions,
with at least 3 months provided since the last migration.

.. _semantic versioning: https://semver.org/


What is the public API
~~~~~~~~~~~~~~~~~~~~~~

*reader* follows the `PEP 8 definition`_ of public interface.

The following are part of the public API:

* Every interface documented in the :doc:`API reference <api>`.
* Any (documented) module, function, object, method, and attribute,
  defined in the *reader* package,
  that is accessible without passing through a name
  that starts with underscore.
* The number and position of positional arguments.
* The names of keyword arguments.
* Argument types (argument types cannot become more strict).
* Attribute types (attribute types cannot become less strict).

Undocumented type aliases (even if not private)
are **not** part of the public API.

Other exceptions are possible; they will be marked aggresively as such.

.. _PEP 8 definition: https://www.python.org/dev/peps/pep-0008/#public-and-internal-interfaces


.. seealso::

  The `Twisted Compatibility Policy <https://github.com/twisted/twisted/blob/twisted-16.2.0/docs/core/development/policy/compatibility-policy.rst>`_,
  which served as inspiration for this.


Internal API
~~~~~~~~~~~~

The :doc:`internal` is not stable,
but the long term goal is for it to become so.

In order to support / encourage potential users
(e.g. plugins, alternate storage implementations),
changes should at least be announced in the :doc:`changelog`.


Supported Python versions
~~~~~~~~~~~~~~~~~~~~~~~~~

The oldest Python version reader should support is:

* the newest CPython available on the latest Ubuntu LTS (3 months after LTS release)
* at least 1 stable PyPy version

This usually ends up being the last 3 stable CPython versions.

Dropping support for a Python version should be announced
at least 1 release prior.



Releases
--------

For convenience, *reader* only releases major and minor versions
(bugfixes go in minor versions).
Changes go only to the next release (no backports).


Making a release
~~~~~~~~~~~~~~~~

.. note::

    :gh:`scripts/release.py <scripts/release.py>` already does most of these.

Making a release (from ``x`` to ``y`` == ``x + 1``):

* (release.py) bump version in ``src/reader/__init__.py`` to ``y``
* (release.py) update changelog with release version and date
* (release.py) make sure tests pass / docs build
* (release.py) clean up dist/: ``rm -rf dist/``
* (release.py) build tarball and wheel: ``python -m build``
* (release.py) push to GitHub
* (release.py prompts) wait for GitHub Actions / Codecov / Read the Docs builds to pass
* upload to test PyPI and check: ``twine upload --repository-url https://test.pypi.org/legacy/ dist/*``
* (release.py) upload to PyPI: ``twine upload dist/*``
* (release.py) tag current commit with `<major>.<minor>` and `<major>.x`
  (e.g. when releasing `1.20`: `1.20` and `1.x`)
* (release.py prompts) create release in GitHub
* build docs from latest and enable ``y`` docs version (should happen automatically after the first time)
* (release.py) bump versions from ``y`` to ``(y + 1).dev0``, add ``(y + 1)`` changelog section
* (release.py prompts) trigger Read the Docs build for `<major>.x` (doesn't happen automatically)



.. _documentation:

Documentation
-------------

Following are notes about what documentation should look like,
especially for the stable high-level :doc:`API <api>`,
since that's what most users will see.


We prefer type information in the method description,
not in the signature,
since the result is more readable.
For the same reason,
we prefer hand-written `Sphinx-style field list types`_.

We still use `autodoc-provided type hints`_
as fallback for parameters that don't have hand-written types,
for type documentation for dataclasses,
and for the unstable :doc:`internal`,
where it's too much effort to maintain hand-written types.


Known issues (October 2023, Sphinx version ~7):

* Overloads are shown with full annotation regardless of autodoc_typehints
  (known, documented behavior).
  May get better with https://github.com/sphinx-doc/sphinx/issues/10359.

* Type aliases that do not come from hand-written types
  but from the autodoc typehints are expanded in-place;
  this also affects the overload type annotations.
  The documented work-around is to add the aliases to autodoc_type_aliases.

* Type alias names that appear in parameter types
  do not link to the documentation in :ref:`type aliases`.
  May get better with https://github.com/sphinx-doc/sphinx/issues/9705

.. _Sphinx-style field list types: https://www.sphinx-doc.org/en/master/usage/domains/python.html#info-field-lists
.. _autodoc-provided type hints: https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#confval-autodoc_typehints



.. _design notes:

Design notes
------------

Folowing are various design notes that aren't captured somewhere else
(either in the code, or in the issue where a feature was initially developed).


Why use SQLite and not SQLAlchemy?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

tl;dr: For "historical reasons".

In `the beginning`_:

* I wanted to keep things as simple as possible, so I don't get demotivated
  and stop working on it.
  I also `wanted`_ to try out a "`problem-solution`_" approach.
* I think by that time I was already a great SQLite fan,
  and knew that because of the relatively single-user nature of the thing
  I won't have to change databases because of concurrency issues.
* The fact that I didn't know exactly where and how I would deploy the web app
  (and that SQLite is in stdlib) kinda cemented that assumption.

Since then, I did come up with some of my own complexity:
there's a SQL query builder, a schema migration system,
and there were *some* concurrency issues.
SQLAlchemy would have likely helped with the first two,
but not with the last one (not without dropping SQLite).

Note that it is possible to use a different storage implementation;
all storage stuff happens through a DAO-style interface,
and SQLAlchemy was the main real alternative `I had in mind`_.
The API is private at the moment (1.10),
but if anyone wants to use it I can make it public.

It is unlikely I'll write a SQLAlchemy storage myself,
since I don't need it (yet),
and I think testing it with multiple databases would take quite some time.

.. _the beginning: https://github.com/lemon24/reader/tree/afbc10335a45ec449205d5757d09cc4a3c6596da/reader
.. _wanted: https://github.com/lemon24/reader/blame/99077c7e56db968cb892353075426bc5b0b141f1/README.md#L9
.. _I had in mind: https://github.com/lemon24/reader/issues/168#issuecomment-642002049


.. _multiple storage implementations:

Multiple storage implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Detailed requirements and API discussion: :issue:`168#issuecomment-642002049`.

Minimal work needed to support alternate storages: :issue:`168#issuecomment-1383127564`.

Storage internal API documented in version 3.10 (November 2023) in :issue:`325`.


Database optimization
~~~~~~~~~~~~~~~~~~~~~

Optimization lessons learned while fixing "database is locked" errors: :issue:`175#issuecomment-657495233`.

Some general guidance on schema/index design: :issue:`327#issuecomment-1859147186`.

Speeding up ``get_entries(sort='recent')``:

* first attempt at adding indexes: :issue:`134`
* using a computed column (``recent_sort``) didn't change things very much: :issue:`279`
* an index on ``recent_sort`` alone is not enough for pagination,
  the index needs to match 1:1 the WHERE clause: :issue:`330`.

Speeding up ``get_entry_counts(feed=...)``:

* having an index on entries(feed) yielded a 4x improvement: :issue:`251`
* even better, we should cache commonly-used counts: :issue:`306#issuecomment-1694655504`

Official guidance: https://www.sqlite.org/queryplanner-ng.html#howtofix


Parser
~~~~~~

file:// handling, feed root, per-URL-prefix parsers (later retrievers, see below):

* requirements: :issue:`155#issuecomment-667970956`
* detailed requirements: :issue:`155#issuecomment-672324186`
* method for URL validation: :issue:`155#issuecomment-673694472`, :issue:`155#issuecomment-946591071`

Requests session plugins:

* requirements: :issue:`155#issuecomment-667970956`
* why the Session wrapper exists: :issue:`155#issuecomment-668716387` and :issue:`155#issuecomment-669164351`

Retriever / parser split:

* :issue:`205#issuecomment-766321855`
* split exception hierarchy (not implemented as of 3.15): :issue:`218#issuecomment-1687094315`
* API overview as of 3.14, meant to show the dataflow: :issue:`307#issuecomment-2266647310`
* ~ideal API (mostly implemented in 3.15): :issue:`307#issuecomment-2281797898`

  * exposes HTTP information (so it can be used by the updater)
  * introduces ~internal RetrieveError and NotModified :exc:`ParseError` subclasses;
    notably, this doesn't really follow the split exception hierarchy mentioned above,
    and is only meant to surface HTTP information in error cases

Alternative feed parsers:

* the logical pipeline of parsing a feed: :issue:`264#issuecomment-973190028`
* comparison between feedparser and Atoma: :issue:`264#issuecomment-981678120`, :issue:`263`


.. _twitter-lessons:

Lessons learned from the :ref:`Twitter` plugin:

* It is useful for a retriever to pass an arbitrary resource to the parser.

  This is already codified in
  :meth:`~reader._parser.RetrieverType` and
  :meth:`~reader._parser.ParserType` being generic.

* It is useful for a Retriever to store arbitrary caching data;
  the plugin (mis)used ``RetrieveResult.http_etag``
  to store the (integer) id of the newest tweet in the thread.

  Update: This was formalized as :attr:`.RetrievedFeed.caching_info` in 3.15.

* It is useful for a Retriever to pass arbitrary data to itself;
  the plugin (mis)used ``FeedForUpdate.http_etag`` to pass from
  :meth:`~reader._parser.FeedForUpdateRetrieverType.process_feed_for_update`
  to :meth:`~reader._parser.RetrieverType.__call__`:

  * the bearer token and the ids of recent entries (used to retrieve tweets)
  * the ids of entries to re-render, triggered by a one-off tag (passed along to the parser)

  This distinction was made so that ``process_feed_for_update()``
  takes all the decisions upfront
  (possibly taking advantage of ``Storage.get_feeds_for_update()``
  future optimisations to e.g. also get tags),
  and calling the retriever (in parallel) doesn't do any reader operations.

  It would be nice to formalize this as well.

* A plugin can coordinate between a custom retriever and custom parser
  with an unregistered RetrieveResult MIME type
  (e.g. ``application/x.twitter``).
* A plugin can keep arbitrary data as a content with an unregistered type
  (e.g. ``application/x.twitter+json``).


Metrics
~~~~~~~

Some thoughts on implementing metrics: :issue:`68#issuecomment-450025175`.

Per-call timings introduced in the :mod:`~reader._plugins.timer` experimental plugin.


Query builder
~~~~~~~~~~~~~

Survey of possible options: :issue:`123#issuecomment-582307504`.

In 2021, I've written an entire series about it:
https://death.andgravity.com/query-builder


Pagination for methods that return iterators
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Why do it for the private implementation: :issue:`167#issuecomment-626753299`;


Detailed requirements and API discussion for public pagination: :issue:`196#issuecomment-706038363`.


Search
~~~~~~

From the initial issue:

* detailed requirements and API discussion: :issue:`122#issuecomment-591302580`
* discussion of possible backend-independent search queries: :issue:`122#issuecomment-508938311`

Enabling search by default, and alternative search APIs: :issue:`252`.

Change tracking API: :issue:`323#issuecomment-1930756417`, model validated in
`this gist <https://gist.github.com/lemon24/558955ad82ba2e4f50c0184c630c668c>`_.

External resources:

* Comprehensive, although a bit old (2017): `What every software engineer should know about search <https://medium.com/startup-grind/what-every-software-engineer-should-know-about-search-27d1df99f80d>`_ (`full version <http://webcache.googleusercontent.com/search?q=cache:https://medium.com/startup-grind/what-every-software-engineer-should-know-about-search-27d1df99f80d&sca_esv=570067020&prmd=ivn&strip=1&vwsrc=0>`_)


reader types to Atom mapping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This whole issue: :issue:`153`.


Sort by random
~~~~~~~~~~~~~~

Some thoughts in the initial issue: :issue:`105`.


.. _sort by tag:

Sort by tag values
~~~~~~~~~~~~~~~~~~

It may be useful to be able to sort by tag values
in order to allow sorting by cached entry counts:
:issue:`306#issuecomment-1694655504`.


Entry/feed "primary key" attribute naming
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This whole issue: :issue:`159#issuecomment-612914956`.


Change feed URL
~~~~~~~~~~~~~~~

From the initial issue:

* use cases: :issue:`149#issuecomment-700066794`
* initial requirements: :issue:`149#issuecomment-700532183`

Splitting a feed into two feeds is discussed in :issue:`221`.
The main takeaway at the time (2021) was that
not all entry data can be retrieved through the storage API,
so it's not fully possible to round-trip an entry.
Based on a quick 2024 survey,
the only affected attributes
are :attr:`~.EntryUpdateIntent.feed_order` (can't get; not critical)
and :attr:`~Entry.original_feed_url` (can't set; will be required for
archiving important entries of deleted feeds, :issue:`290`).


Resource tags / metadata
~~~~~~~~~~~~~~~~~~~~~~~~

Feed tags
^^^^^^^^^

.. _categories:

Detailed requirements and API discussion,
and a case study of how to implement categories on top of tags:
:issue:`184#issuecomment-689587006`.

Merging tags and metadata, and the addition of a new,
generic (global, feed, entry) tag API: :issue:`266#issuecomment-1013739526`.

Entry tags
^^^^^^^^^^

.. _searchable tags:

:issue:`228#issuecomment-810098748` discusses
three different kinds of entry user data,
how they would be implemented,
and why I want more use-cases before implementing them (basically, YAGNI):

* entry searchable text fields (for notes etc.)
* entry tags (similar to feed tags, may be used as additional bool flags)
* entry metadata (similar to feed metadata)

  * also discusses how to build an enclosure cache/preloader
    (doesn't need special *reader* features besides what's available in 1.16)

.. _entry flag unification:

:issue:`253` discusses using entry tags to implement the current entry flags
(read, important); tl;dr: it's not worth adding entry tags just for this.
:issue:`327` discusses using entry tags for ``has_enclosures``; tl;dr:
it wouldn't save a lot of code, it would be only *a bit* slower,
and it reconfirms that read and important are integral to the data model,
so we still want them as regular columns.

After closing :issue:`228` with `wontfix` in late 2021,
in early 2022 (following the :issue:`266` tag/metadata unification)
I implemented entry and global tags in :issue:`272`;
there's a list of known use cases in the issue description.


Resource tags
^^^^^^^^^^^^^

Optimistic locking for tags: :issue:`308`.

Filter tags by prefix: :issue:`309`.


User-added entries
~~~~~~~~~~~~~~~~~~

Discussion about API/typing, and things we didn't do: :issue:`239`.


Feed updates
~~~~~~~~~~~~

Some thoughts about adding a ``map`` argument: :issue:`152#issuecomment-606636200`.

How ``update_feeds()`` is like a pipeline: `comment <https://github.com/lemon24/reader/blob/1.13/src/reader/core.py#L629-L643>`_.

Data flow diagram for the update process, as of v1.13: :issue:`204#issuecomment-779709824`.

``update_feeds_iter()``:

* use case: :issue:`204#issuecomment-779893386` and :issue:`204#issuecomment-780541740`
* return type: :issue:`204#issuecomment-780553373`

Disabling updates:

* :issue:`187#issuecomment-706539658`
* :issue:`187#issuecomment-706593497`

Updating entries based on a hash of their content (regardless of ``updated``):

* stable hasing of Python data objects:
  :issue:`179#issuecomment-796868555`, the :mod:`reader._hash_utils` module,
  `death and gravity article <https://death.andgravity.com/stable-hashing>`_
* ideas for how to deal with spurious hash changes: :issue:`225`

Decision to ignore feed.updated when updating feeds: :issue:`231`.

:ref:`scheduled` (initial design + postponed features): :issue:`322`.


.. _deleting entries:

Deleting entries
~~~~~~~~~~~~~~~~

Requirements, open questions, and how it interacts with :mod:`~reader.plugins.entry_dedupe`: :issue:`96`.

A summary of why it isn't easy to do: :issue:`301#issuecomment-1442423151`.


.. _counts api:

Counts API
~~~~~~~~~~

Detailed requirements and API discussion: :issue:`185#issuecomment-731743327`.

Tracking additional statistics (e.g. :attr:`~Entry.read_modified`): :issue:`254`;
how to expose said statistics: :issue:`254#issuecomment-1807064610`.

Notebook with a successful attempt to determine a feed "usefulness" score
based on how many entries I mark as read / important / don't care;
highlights a number of gaps in the *reader* API:
https://gist.github.com/lemon24/93222ef4bc4a775092b56546a6e6cd0f


Using None as a special argument value
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This comment: :issue:`177#issuecomment-674786498`.


Batch methods
~~~~~~~~~~~~~

.. _batch get methods:

Some initial thoughts on batch get methods (including API/typing)
in :issue:`191` (closed with `wontfix`, for now).

Why I want to postpone batch update/set methods:
:issue:`187#issuecomment-700740251`.

tl:dr: Performance is likely a non-issue with SQLite,
convenience can be added on top as a plugin.

(2025) Why it may be worth adding batch interfaces anyway (even if underneath the storage implementation doesn't actually batch) – it allows for future optimization: https://blog.glyph.im/2022/12/potato-programming.html

See the 2.12 reader._app.ResourceTags class for an idea of how to
represent a bunch of tags in a reserved-name-scheme-agnostic way
(useful e.g. for when get_entries() should return tags x, y, z of each entry).

Some web app measurements that show a few cases where batch methods may help: :issue:`306#issuecomment-1694655504`.


Using a single Reader objects from multiple threads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some thoughts on why it's difficult to do: :issue:`206#issuecomment-751383418`.

Requirements and use cases: :issue:`206#issuecomment-1179739301`.

When/how to run ``pragma optimize``: :issue:`206#issuecomment-1183660880`.

Full support added in version 2.16 (July 2022).


Plugins
~~~~~~~

List of potential hooks (from mid-2018): :issue:`80`.

Minimal plugin API (from 2021) – case study and built-in plugin naming scheme: :issue:`229#issuecomment-803870781`.

We'll add / document new (public) hooks as needed.

"Tag before, clear tag after" pattern for resilient plugins: :issue:`246#issuecomment-1596097300`.

Update hook error handling:

* expected behavior: :issue:`218#issuecomment-1595691410`, :issue:`218#issuecomment-1666823222`
* update hook pseudocode + exception hierarchy: :issue:`218#issuecomment-1666869215`

Considerations on using pluggy: :issue:`329`,
`how adapting reader use cases to the pluggy model may work <https://github.com/pytest-dev/pluggy/issues/151#issuecomment-2421648901>`_.
Conclusions:

    even if using pluggy would require some work-arounds for calling, I think the collection / discovery functionality is still more than worth it

    long-term and/or if reader becomes really popular, pluggy is definitely the way to go


Reserved names
~~~~~~~~~~~~~~

Requirements, thoughts about the naming scheme
and prefixes unlikely to collide with user names:
:issue:`186` (multiple comments).


Wrapping underlying storage exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Which exception to wrap, and which not: :issue:`21#issuecomment-365442439`.


Timezone handling
~~~~~~~~~~~~~~~~~

Aware vs. naive, and what's needed to go fully aware: :issue:`233#issuecomment-881618002`.

In version 3.10 (November 2023), all internal APIs were changed
to use timezone-aware datetimes, with the timezone set to UTC,
in preparation for support for any timezone.


OPML support
~~~~~~~~~~~~

Thoughts on dynamic lists of feeds: :issue:`165#issuecomment-905893420`.


Duplicate entries
~~~~~~~~~~~~~~~~~

Duplicate entries are mainly handled by the :mod:`reader.entry_dedupe` plugin.

* Using MinHash to speed up similarity checks (maybe): https://gist.github.com/lemon24/b9af5ade919713406bda9603847d32e5
* Discussion of unifying "on-line" dedupe (after an entry is added/updated),
  and "on-demand" dedupe (backfill): :issue:`340`.

However, it is also possible for a feed to have two entries with the same id
– yes, even though in most (if not all) formats,
the id is meant to be *universally unique*!
As of 3.13, we do not support multiple entries with the same id
(the first entry wins); see :issue:`335` for thoughts on this.


REST API
~~~~~~~~

Some early thoughts: :issue:`192#issuecomment-700773138`
(closed with `wontfix`, for now).


Web application
~~~~~~~~~~~~~~~

.. toctree::
    dev-app
