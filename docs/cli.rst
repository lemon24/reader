
Command-line interface
======================

This part of the documentation covers the *reader* command-line interface.

.. warning::

    The CLI is not stable yet and might change without any notice.

.. note::

    The command-line interface is optional, use the ``cli`` extra to install
    its :ref:`dependencies <Optional dependencies>`.

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

Serve the web application locally (at http://localhost:8080/):

.. code-block:: bash

    python -m reader serve


Updating feeds
--------------

For *reader* to actually be useful as a feed reader, feeds need to get updated
and, if full-text search is enabled, the search index needs to be updated.

You can run the ``update`` command  regularly to update feeds (e.g. every
hour). Note that *reader* uses the ETag and Last-Modified headers, so, if
supported by the the server, feeds will only be downloaded if they changed.

To avoid waiting too much for a new feed to be updated, you can run
``update --new-only`` more often (e.g. every minute); this will update
only newly-added feeds. This is also a good time to update the search index.

You can achieve this using cron::

    42 * * * *  reader update -v 2>&1 >>"/tmp/$LOGNAME.reader.update.hourly.log"
    * * * * *   reader update -v --new-only 2>&1 >>"/tmp/$LOGNAME.reader.update.new.log"; reader search update 2>&1 >>"/tmp/$LOGNAME.reader.search.update.log"

If you are running *reader* on a personal computer, it might also be convenient
to run ``update`` once immediately after boot::

    @reboot     sleep 60; reader update -v 2>&1 >>"/tmp/$LOGNAME.reader.update.boot.log"


Reference
---------

.. click:: reader._cli:cli
    :prog: reader
    :show-nested:
