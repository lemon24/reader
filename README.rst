.. begin-intro

**reader** is a Python feed reader library.

*reader* can be used to retrieve, store, and manage Atom and RSS feeds.
It is designed to allow writing feed reader applications
without any business code,
and without enforcing a dependency on a particular framework.


.. end-intro


|build-status| |code-coverage| |documentation-status| |pypi-status| |type-checking| |code-style|

.. |build-status| image:: https://travis-ci.org/lemon24/reader.svg?branch=master
  :target: https://travis-ci.org/lemon24/reader
  :alt: build status

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


Features:

.. begin-features

* Stand-alone library with stable, clearly documented API, and excellent test coverage.
* Full-text search.
* Minimal web interface that works even with text-only browsers.

  * ... with automatic tag fixing for podcasts (MP3 enclosures).

* (Some) plugin support.

.. end-features


Documentation: `reader.readthedocs.io`_

.. _reader.readthedocs.io: https://reader.readthedocs.io/


Usage:

.. begin-usage

.. code-block:: bash

    $ pip install reader[search]

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
    >>> reader.mark_as_read(entries[0])
    >>>
    >>> [e.title for e in reader.get_entries(read=False)]
    ['H.I. #107: One Year of Weird', 'H.I. #106: Water on Mars', ...]
    >>> [e.title for e in reader.get_entries(read=True)]
    ['H.I. #108: Project Cyclops']
    >>>
    >>> reader.enable_search()
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
