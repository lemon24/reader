
reader
======

A minimal feed reader library.


Features
--------

* Stand-alone library with stable, clearly documented API, and excellent test coverage.
* Minimal web interface that works even with text-only browsers.
* (Some) plugin support.


Usage
-----

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


Table of contents
-----------------

.. toctree::
    :maxdepth: 2

    api
    cli
    app
    deploying
    plugins

Project infromation
-------------------

.. toctree::
    :maxdepth: 2

    dev
    changelog


Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
