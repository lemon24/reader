
Installation
============

Python versions
---------------

*reader* supports Python 3.6 and newer, and PyPy.


Dependencies
------------

These packages will be installed automatically when installing *reader*:

* `feedparser`_ parses feeds; *reader* is essentially feedparser + state.
* `requests`_ retrieves feeds from the internet;
  it replaces feedparser's default use of :mod:`urllib`
  to make it easier to write plugins.
* `sgmllib3k`_ is a Python 3 "forward-port" of the `sgmllib`_ Python 2
  standard library module;
  feedparser uses it for ill-formed XML parsing and content sanitizing.

*reader* also depends on the :mod:`sqlite3` standard library module
(at least SQLite 3.15), and on the `JSON1`_ SQLite extension.

.. note::

    The SQLite bundled with Python <= 3.8 on Windows
    does **not** include the JSON1 extension.
    As a consequence, *reader* may not work on Windows.
    See :issue:`163` for details.


.. _optional dependencies:

Optional dependencies
~~~~~~~~~~~~~~~~~~~~~

Despite coming with a CLI and web application, *reader* is primarily a library.
As such, most dependencies are optional, and can be installed as `extras`_.

As of version |version|, *reader* has the following extras:

* ``search`` provides :doc:`full-text search <fts>` functionality;
  search also requires that the SQLite used by :mod:`sqlite3`
  was compiled with the `FTS5`_ extension, and is at least version 3.18.
* ``cli`` installs the dependencies needed for the
  :doc:`command-line interface <cli>`.
* ``app`` installs the dependencies needed for the
  :doc:`web application <app>`.
* ``plugins`` installs the dependencies needed for
  :doc:`plugin <plugins>` loading machinery.
* Specific plugins may require additional dependencies;
  refer to their documentation for details.


.. _feedparser: https://pythonhosted.org/feedparser/
.. _requests: https://requests.readthedocs.io
.. _sgmllib3k: https://pypi.org/project/sgmllib3k/
.. _sgmllib: https://docs.python.org/2/library/sgmllib.html
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


Living on the edge
~~~~~~~~~~~~~~~~~~

If you want to use the latest *reader* code before it’s released,
install or update from the master branch:

.. code-block:: bash

    pip install --upgrade https://github.com/lemon24/reader/archive/master.tar.gz
