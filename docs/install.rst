
Installation
============

Python versions
---------------

*reader* supports Python |min_python| and newer, and PyPy.


Dependencies
------------

These packages will be installed automatically when installing *reader*:

* `feedparser`_ parses feeds; *reader* is essentially feedparser + state.
* `requests`_ retrieves feeds from the internet;
  it replaces feedparser's default use of :mod:`urllib`
  to make it easier to write plugins.
* `werkzeug`_ provides HTTP utilities.
* `iso8601`_  parses dates in ISO 8601 / RFC 3339; used for JSON Feed parsing.
* `beautifulsoup4`_ is used to strip HTML tags before adding entries
  to the search index.
* `typing-extensions`_ is used for :mod:`typing` backports.

*reader* also depends on the :mod:`sqlite3` standard library module
(at least SQLite 3.18 with the `JSON1`_ and `FTS5`_ extensions).


.. _no-vendored-feedparser:

.. note::

  Because `feedparser`_ makes PyPI releases at a lower cadence,
  *reader* uses a vendored version of feedparser's `develop`_ branch
  by default since :ref:`version 2.9`.
  To opt out of this behavior, and make *reader* use
  the installed ``feedparser`` package,
  set the ``READER_NO_VENDORED_FEEDPARSER`` environment variable to ``1``.

.. _develop: https://github.com/kurtmckee/feedparser


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
.. _werkzeug: https://werkzeug.palletsprojects.com/
.. _iso8601: http://pyiso8601.readthedocs.org/
.. _typing-extensions: https://pypi.org/project/typing-extensions/
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
