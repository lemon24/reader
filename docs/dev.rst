
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

* API to delete old entries. (:issue:`96`)
* API to delete duplicate entries. (:issue:`140`)
* Better handling of local feeds. (:issue:`155`)
* Handle changing the feed URL. (:issue:`149`)

* Various web application improvements.
* Various search optimizations. (:issue:`122`)
* Various storage optimizations. (:issue:`143`, :issue:`134`)

* Plugin system / hooks stabilization. (:issue:`80`)
* Internal API stabilization.
* CLI stabilization.
* Configuration file.
* Web application stabilization.

* (Some) Windows support. (:issue:`163`)

* OPML support. (:issue:`165`)


Style guide
-----------

*reader* uses the `Black <https://black.readthedocs.io/en/stable/>`_ style.

You should enforce it by using `pre-commit <https://pre-commit.com/>`_.
To install it into your git hooks, run::

    pip install pre-commit  # pip install '.[dev]' already does it for you
    pre-commit install

Every time you clone the repo, running ``pre-commit install`` should always be
the first thing you do.


Testing
-------

First, install the testing dependencies::

    make install-dev        # or
    pip install '.[search,cli,app,plugins,enclosure-tags,preview-feed-list,dev,docs]'

Run tests using the current Python interpreter::

    make                    # or
    make test               # or
    pytest --runslow

Run tests using the current Python interpreter, but skip slow tests::

    pytest

Run tests for all supported Python versions::

    make test-all          # or
    tox

Run tests with coverage and generate an HTML report (in ``./htmlcov``)::

    make coverage

Run the type checker::

    make typing             # or
    mypy --strict src

Start a local development server for the web application::

    make serve-dev          # or

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/_app/wsgi.py \
    READER_DB=db.sqlite flask run -h 0.0.0.0 -p 8000


Building the documentation
--------------------------

First, install the dependencies (``pip install '.[dev]'`` already does it for you)::

    pip install '.[docs]'

The documentation is built with Sphinx::

    make docs               # or
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
* (release.py) build tarball and wheel: ``python setup.py build sdist`` and ``python setup.py build bdist_wheel``
* (release.py) push to GitHub
* (release.py prompts) wait for Travis / Codecov / Read the Docs builds to pass
* upload to test PyPI and check: ``twine upload --repository-url https://test.pypi.org/legacy/ dist/*``
* (release.py) upload to PyPI: ``twine upload dist/*``
* (release.py prompts) tag release in GitHub
* build docs from latest and enable ``y`` docs version (should happen automatically after the first time)
* (release.py) bump versions from ``y`` to ``(y + 1).dev0``, add ``(y + 1)`` changelog section
* (release.py prompts) deactivate old versions in Read the Docs


.. Web application
.. ---------------

.. include:: dev-app.rst
