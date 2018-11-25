
Development
===========


Goals
-----

Goals:

* clearly documented API
* minimal web interface
* minimal CLI

Development should follow a problem-solution_ approach.


Testing
-------

Run tests::

    tox

or::

    make

or::

    python3 -m pytest --runslow

Start a local development server for the web-app::

    READER_DB=db.sqlite FLASK_DEBUG=1 FLASK_APP=autoapp.py \
        flask run -h localhost -p 8080


.. _problem-solution: https://hintjens.gitbooks.io/scalable-c/content/chapter1.html#problem-what-do-we-do-next


Making a release
----------------

Making a release (from ``x`` to ``y`` == ``x + 1``):

* make sure all tests pass etc.
* bump versions in ``docs/conf.py`` and ``src/reader/__init__.py`` to ``y``
* update changelog with release version and date
* clean up dist/: ``rm -rf dist/``
* build tarball and wheel: ``python setup.py build sdist`` and ``python setup.py build bdist_wheel``
* push to GitHub
* wait for Travis / Codecov / Read the Docs builds to pass
* upload to test PyPI and check: ``twine upload --repository-url https://test.pypi.org/legacy/ dist/*``
* upload to PyPI: ``twine upload dist/*``
* tag release in GitHub
* build docs from latest and enable ``y`` docs version (should happen automatically after the first time)
* bump versions from ``y`` to ``(y + 1).dev0``, add ``(y + 1)`` changelog section

