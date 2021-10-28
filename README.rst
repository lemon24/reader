.. begin-intro

**reader** is a Python feed reader library.

It aims to allow writing feed reader applications
without any business code,
and without enforcing a dependency on a particular framework.

.. end-intro


|build-status-github| |code-coverage| |documentation-status| |pypi-status| |type-checking| |code-style|


.. |build-status-github| image:: https://github.com/lemon24/reader/workflows/build/badge.svg
  :target: https://github.com/lemon24/reader/actions?query=workflow%3Abuild
  :alt: build status (GitHub Actions)

.. |code-coverage| image:: https://codecov.io/github/lemon24/reader/coverage.svg?branch=master
  :target: https://codecov.io/github/lemon24/reader?branch=master
  :alt: code coverage

.. |documentation-status| image:: https://readthedocs.org/projects/reader/badge/?version=latest&style=flat
  :target: https://reader.readthedocs.io/en/latest/?badge=latest
  :alt: documentation status

.. |pypi-status| image:: https://img.shields.io/pypi/v/reader.svg
  :target: https://pypi.python.org/pypi/reader
  :alt: PyPI status

.. |type-checking| image:: http://www.mypy-lang.org/static/mypy_badge.svg
  :target: http://mypy-lang.org/
  :alt: checked with mypy

.. |code-style| image:: https://img.shields.io/badge/code%20style-black-000000.svg
  :target: https://github.com/psf/black
  :alt: code style: black


.. begin-features

*reader* allows you to:

* retrieve, store, and manage **Atom**, **RSS**, and **JSON** feeds
* mark entries as read or important
* add tags and metadata to feeds
* filter feeds and articles
* full-text search articles
* get statistics on feed and user activity
* write plugins to extend its functionality
* skip all the low level stuff and focus on what makes your feed reader different

...all these with:

* a stable, clearly documented API
* excellent test coverage
* fully typed Python

What *reader* doesn't do:

* provide an UI
* provide a REST API (yet)
* depend on a web framework
* have an opinion of how/where you use it

The following exist, but are optional (and frankly, a bit unpolished):

* a minimal web interface

  * that works even with text-only browsers
  * with automatic tag fixing for podcasts (MP3 enclosures)

* a command-line interface

.. end-features


Documentation: `reader.readthedocs.io`_

.. _reader.readthedocs.io: https://reader.readthedocs.io/


Usage:

.. begin-usage

.. code-block:: bash

    $ pip install reader

.. code-block:: python

    >>> from reader import make_reader
    >>>
    >>> reader = make_reader('db.sqlite')
    >>> reader.add_feed('http://www.hellointernet.fm/podcast?format=rss')
    >>> reader.update_feeds()
    >>>
    >>> entries = list(reader.get_entries())
    >>> [e.title for e in entries]
    ['H.I. #108: Project Cyclops', 'H.I. #107: One Year of Weird', ...]
    >>>
    >>> reader.mark_entry_as_read(entries[0])
    >>>
    >>> [e.title for e in reader.get_entries(read=False)]
    ['H.I. #107: One Year of Weird', 'H.I. #106: Water on Mars', ...]
    >>> [e.title for e in reader.get_entries(read=True)]
    ['H.I. #108: Project Cyclops']
    >>>
    >>> reader.update_search()
    >>>
    >>> for e in list(reader.search_entries('year'))[:3]:
    ...     title = e.metadata.get('.title')
    ...     print(title.value, title.highlights)
    ...
    H.I. #107: One Year of Weird (slice(15, 19, None),)
    H.I. #52: 20,000 Years of Torment (slice(17, 22, None),)
    H.I. #83: The Best Kind of Prison ()

.. end-usage
