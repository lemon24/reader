
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


Testing
-------

To install the testing dependencies::

    pip install '.[cli,web-app,enclosure-tags,plugins,dev]'

Run tests for all supported Python versions::

    make test-all           # installs the dependencies for you, or
    tox                     # you need to install the dependencies first

Run tests using the current Python interpreter::

    make                    # installs the dependencies for you, or
    pytest -v --runslow     # you need to install the dependencies first

Run tests with coverage and generate an HTML report (in ``./htmlcov``)::

    make coverage           # installs the dependencies for you

Start a local development server for the web-app::

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/app/wsgi.py \
    READER_DB=db.sqlite flask run -h 0.0.0.0 -p 8000


Building the documentation
--------------------------

The documentation is built with Sphinx::

    make docs               # installs the dependencies for you

or, using Sphinx's Makefile directly::

    pip install '.[docs]'   # to install the dependencies
    make -C docs html

The built HTML docs should be in ``./docs/_build/html/``.

Making a release
----------------

Making a release (from ``x`` to ``y`` == ``x + 1``; ``scripts/release.py`` already does some of these):

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

