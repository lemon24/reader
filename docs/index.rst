
reader
======

A minimal feed reader.


Features
--------

* Stable and clearly documented API.
* Excellent test coverage.
* Minimal web interface.


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


API reference
-------------

If you are looking for information on a specific function, class, or method,
this part of the documentation is for you.

.. toctree::
    api


Command-line interface
----------------------

.. toctree::
    cli


Web application
---------------

.. toctree::
    app


Deployment options
------------------

.. toctree::
    deploying


Plugins
-------

.. toctree::
    plugins


Development
-----------

.. toctree::
    dev


Changelog
---------

.. toctree::
    changelog


Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
