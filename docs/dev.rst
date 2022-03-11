
Development
===========


Goals
-----

Goals:

* clearly documented API
* minimal web interface
* minimal CLI

Development should follow a problem-solution_ approach.

.. _problem-solution: https://hintjens.gitbooks.io/scalable-c/content/chapter1.html#problem-what-do-we-do-next


Roadmap
-------

In no particular order:

* update_feeds() filtering. (:issue:`193`)

* Web application re-design.

* Internal API stabilization.
* CLI stabilization.
* Web application stabilization.

* OPML support. (:issue:`165`)


Style guide
-----------

*reader* uses the `Black <https://black.readthedocs.io/en/stable/>`_ style.

You should enforce it by using `pre-commit <https://pre-commit.com/>`_.
To install it into your git hooks, run::

    pip install pre-commit  # ./run.sh install-dev already does both
    pre-commit install

Every time you clone the repo, running ``pre-commit install`` should always be
the first thing you do.


Testing
-------

First, install the testing dependencies::

    ./run.sh install-dev    # or
    pip install '.[cli,app,tests,dev,unstable-plugins]'

Run tests using the current Python interpreter::

    pytest --runslow

Run tests using the current Python interpreter, but skip slow tests::

    pytest

Run tests for all supported Python versions::

    tox

Run tests with coverage and generate an HTML report (in ``./htmlcov``)::

    ./run.sh coverage-all

Run the type checker::

    ./run.sh typing         # or
    mypy --strict src

Start a local development server for the web application::

    ./run.sh serve-dev      # or

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/_app/wsgi.py \
    READER_DB=db.sqlite flask run -h 0.0.0.0 -p 8000


Building the documentation
--------------------------

First, install the dependencie::

    pip install '.[docs]'   # ./run.sh install-dev already does it for you

The documentation is built with Sphinx::

    ./run.sh docs           # or
    make -C docs html       # using Sphinx's Makefile directly

The built HTML docs should be in ``./docs/_build/html/``.


Making a release
----------------

Making a release (from ``x`` to ``y`` == ``x + 1``):

.. note::

    :gh:`scripts/release.py <scripts/release.py>` already does most of these.

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


Multiple storage implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Detailed requirements and API discussion: :issue:`168#issuecomment-642002049`.


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

Alternative feed parsers:

* the logical pipeline of parsing a feed: :issue:`264#issuecomment-973190028`
* comparison between feedparser and Atoma: :issue:`264#issuecomment-981678120`, :issue:`263`


Metrics
~~~~~~~

Some thoughts on implementing metrics: :issue:`68#issuecomment-450025175`.


Query builder
~~~~~~~~~~~~~

Survey of possible options: :issue:`123#issuecomment-582307504`.

In 2021, I've written an entire series about it:
https://death.andgravity.com/query-builder


Pagination for methods that return iterators
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Why do it for the private implementation: :issue:`167#issuecomment-626753299` (also a comment in storage code).

Detailed requirements and API discussion for public pagination: :issue:`196#issuecomment-706038363`.


Search
~~~~~~

From the initial issue:

* detailed requirements and API discussion: :issue:`122#issuecomment-591302580`
* discussion of possible backend-independent search queries: :issue:`122#issuecomment-508938311`

Enabling search by default, and alternative search APIs: :issue:`252`.


reader types to Atom mapping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This whole issue: :issue:`153`.


Sort by random
~~~~~~~~~~~~~~

Some thoughts in the initial issue: :issue:`105`.


Entry/feed "primary key" attribute naming
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This whole issue: :issue:`159#issuecomment-612914956`.


Change feed URL
~~~~~~~~~~~~~~~

From the initial issue:

* use cases: :issue:`149#issuecomment-700066794`
* initial requirements: :issue:`149#issuecomment-700532183`


Feed tags
~~~~~~~~~

Detailed requirements and API discussion: :issue:`184#issuecomment-689587006`.

Merging tags and metadata, and the addition of a new,
generic (global, feed, entry) tag API: :issue:`266#issuecomment-1013739526`.


Entry user data
~~~~~~~~~~~~~~~

:issue:`228#issuecomment-810098748` discusses three different kinds,
how they would be implemented,
and why I want more use-cases before implementing them (basically, YAGNI):

* entry searchable text fields (for notes etc.)
* entry tags (similar to feed tags, may be used as additional bool flags)
* entry metadata (similar to feed metadata)

  * also discusses how to build an enclosure cache/preloader
    (doesn't need special *reader* features besides what's available in 1.16)

:issue:`253` discusses using entry tags to implement the current entry flags
(read, important); tl;dr: it's not worth adding entry tags just for this.

After closing :issue:`228` with `wontfix` in late 2021,
in early 2022 (following the :issue:`266` tag/metadata unification)
I implemented entry and global tags in :issue:`272`;
there's a list of known use cases in the issue description.


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


Counts API
~~~~~~~~~~

Detailed requirements and API discussion: :issue:`185#issuecomment-731743327`.


Using None as a special argument value
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This comment: :issue:`177#issuecomment-674786498`.


Batch methods
~~~~~~~~~~~~~

Some initial thoughts on batch get methods (including API/typing)
in :issue:`191` (closed with `wontfix`, for now).

Why I want to postpone batch update/set methods:
:issue:`187#issuecomment-700740251`.

tl:dr: Performance is likely a non-issue with SQLite,
convenience can be added on top as a plugin.


Using a single Reader objects from multiple threads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some thoughts on why it's difficult to do: :issue:`206#issuecomment-751383418`.


Plugins
~~~~~~~

List of potential hooks (from mid-2018): :issue:`80`.

Minimal plugin API (from 2021) – case study and built-in plugin naming scheme: :issue:`229#issuecomment-803870781`.

We'll add / document new (public) hooks as needed.


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


OPML support
~~~~~~~~~~~~

Thoughts on dynamic lists of feeds: :issue:`165#issuecomment-905893420`.


entry_dedupe
~~~~~~~~~~~~

Using MinHash to speed up similarity checks (maybe): https://gist.github.com/lemon24/b9af5ade919713406bda9603847d32e5


REST API
~~~~~~~~

Some early thoughts: :issue:`192#issuecomment-700773138`
(closed with `wontfix`, for now).


Web application
~~~~~~~~~~~~~~~

.. toctree::
    dev-app
