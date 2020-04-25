
Installation
============

Python versions
---------------

*reader* supports Python 3.6 and newer, and PyPy.


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


Optional dependencies
~~~~~~~~~~~~~~~~~~~~~

Some dependencies are optional; to install them, specify them as `extras`_:

.. code-block:: bash

    pip install 'reader[some-extra,...]'

As of version |version|, *reader* supports the following extras:

* ``search`` installs :doc:`full-text search <fts>` dependencies

.. _extras: https://www.python.org/dev/peps/pep-0508/#extras


Living on the edge
~~~~~~~~~~~~~~~~~~

If you want to use the latest *reader* code before it’s released,
install or update from the master branch:

.. code-block:: bash

    pip install --upgrade https://github.com/lemon24/reader/archive/master.tar.gz
