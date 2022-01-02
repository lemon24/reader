
Installation
============

Python versions
---------------

*reader* supports Python 3.7 and newer, and PyPy.


Dependencies
------------

These packages will be installed automatically when installing *reader*:

* `feedparser`_ parses feeds; *reader* is essentially feedparser + state.
* `requests`_ retrieves feeds from the internet;
  it replaces feedparser's default use of :mod:`urllib`
  to make it easier to write plugins.
* `iso8601`_  parses dates in ISO 8601 / RFC 3339; used for JSON Feed parsing.
* `beautifulsoup4`_ is used to strip HTML tags before adding entries
  to the search index.

*reader* also depends on the :mod:`sqlite3` standard library module
(at least SQLite 3.15), and on the `JSON1`_ SQLite extension.
To use the :ref:`full-text search <fts>` functionality,
at least SQLite 3.18 with the `FTS5`_ extension is required.

.. note::

    **reader works out of the box on Windows only starting with Python 3.9**,
    because the SQLite bundled with the official Python distribution
    does **not** include the JSON1 extension in earlier versions.
    That said, it should be possible to build ``sqlite3``
    with a newer version of SQLite;
    see :issue:`163` for details.


.. _optional dependencies:

Optional dependencies
~~~~~~~~~~~~~~~~~~~~~

Despite coming with a CLI and web application, *reader* is primarily a library.
As such, most dependencies are optional, and can be installed as `extras`_.

As of version |version|, *reader* has the following extras:

* ``cli`` installs the dependencies needed for the
  :doc:`command-line interface <cli>`.
* ``app`` installs the dependencies needed for the
  :doc:`web application <app>`.
* Specific plugins may require additional dependencies;
  refer to their documentation for details.


.. _beautifulsoup4: https://www.crummy.com/software/BeautifulSoup/
.. _feedparser: https://feedparser.readthedocs.io/en/latest/
.. _requests: https://requests.readthedocs.io/
.. _iso8601: http://pyiso8601.readthedocs.org/
.. _JSON1: https://www.sqlite.org/json1.html
.. _FTS5: https://www.sqlite.org/fts5.html

.. _extras: https://www.python.org/dev/peps/pep-0508/#extras


Virtual environments
--------------------

You should probably install *reader* inside a virtual environment;
see `this <venv_>`_ for how and why to do it.

.. _venv: https://flask.palletsprojects.com/en/1.1.x/installation/#virtual-environments


Install reader
--------------

Use the following command to install *reader*,
along with its required dependencies:

.. code-block:: bash

    pip install reader

Use the following command to install *reader*
with `optional dependencies <Optional dependencies_>`_:

.. code-block:: bash

    pip install 'reader[some-extra,...]'


Update reader
~~~~~~~~~~~~~

Use the following command to update *reader*
(add any extras as needed):

.. code-block:: bash

    pip install --upgrade reader


Living on the edge
~~~~~~~~~~~~~~~~~~

If you want to use the latest *reader* code before it’s released,
install or update from the master branch:

.. code-block:: bash

    pip install --upgrade https://github.com/lemon24/reader/archive/master.tar.gz
