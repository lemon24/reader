
Command-line interface
======================

This part of the documentation covers the reader command-line interface.

.. note::

    The CLI is not stable yet and might change without any notice.

.. note::

    The command-line interface is optional, use the ``cli`` extra to install
    its dependencies:

    .. code-block:: bash

        pip install reader[cli]

Most commands need a database to work. The following are equivalent:

.. code-block:: bash

    python -m reader --db /path/to/db some-command
    READER_DB=/path/to/db python -m reader some-command

If no database path is given, ``~/.config/reader/db.sqlite`` is used
(at least on Linux).

Add a feed:

.. code-block:: bash

    python -m reader add http://www.example.com/atom.xml

Update all feeds:

.. code-block:: bash

    python -m reader update

Start a local reader server at ``http://localhost:8080/``:

.. code-block:: bash

    python -m reader serve


Reference
---------

.. click:: reader.cli:cli
    :prog: reader
    :show-nested:

