**reader** is a minimal feed reader library.


|build-status| |code-coverage| |documentation-status| |pypi-status|

.. |build-status| image:: https://travis-ci.org/lemon24/reader.svg?branch=master
  :target: https://travis-ci.org/lemon24/reader
  :alt: build status

.. |code-coverage| image:: https://codecov.io/github/lemon24/reader/coverage.svg?branch=master
  :target: https://codecov.io/github/lemon24/reader?branch=master
  :alt: code coverage

.. |documentation-status| image:: https://readthedocs.org/projects/pip/badge/?version=latest&style=flat
  :target: https://reader.readthedocs.io/en/latest/?badge=latest
  :alt: documentation status

.. |pypi-status| image:: https://img.shields.io/pypi/v/reader.svg
  :target: https://pypi.python.org/pypi/reader
  :alt: PyPI status


Features:

.. begin-features

* Stand-alone library with stable, clearly documented API, and excellent test coverage.
* Minimal web interface that works even with text-only browsers.

  * ... with automatic tag fixing for MP3 enclosures (e.g. podcasts).

* (Some) plugin support.

.. end-features


Documentation: `reader.readthedocs.io`_

.. _reader.readthedocs.io: https://reader.readthedocs.io/


Usage:

.. begin-usage

.. code-block:: bash

    $ pip install reader

.. code-block:: python

    >>> from reader import Reader
    >>>
    >>> reader = Reader('db.sqlite')
    >>> reader.add_feed('http://www.hellointernet.fm/podcast?format=rss')
    >>> reader.update_feeds()
    >>>
    >>> entries = list(reader.get_entries())
    >>> [e.title for e in entries]
    ['H.I. #108: Project Cyclops', 'H.I. #107: One Year of Weird', ...]
    >>>
    >>> reader.mark_as_read(entries[0])
    >>>
    >>> [e.title for e in reader.get_entries(which='unread')]
    ['H.I. #107: One Year of Weird', 'H.I. #106: Water on Mars', ...]
    >>> [e.title for e in reader.get_entries(which='read')]
    ['H.I. #108: Project Cyclops']

.. end-usage

