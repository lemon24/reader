
Plugins
=======

.. module:: reader
  :noindex:


.. _built-in plugins:

Built-in plugins
----------------

This is a list of built-in plugins that are considered stable.

See the :ref:`Plugins <plugins>` section of the user guide
for details on how built-in plugins are loaded.

.. automodule:: reader.plugins.enclosure_dedupe
.. automodule:: reader.plugins.entry_dedupe
.. automodule:: reader.plugins.mark_as_read
.. automodule:: reader.plugins.ua_fallback


Loading plugins from the CLI and the web application
----------------------------------------------------

There is experimental support of plugins in the CLI and the web application.

.. warning::

    The plugin system/hooks are not stable yet and may change without any notice.


To load plugins, set the ``READER_PLUGIN`` environment variable to the plugin
entry point (e.g. ``package.module:entry_point``); multiple entry points should
be separated by one space::

    READER_PLUGIN='first.plugin:entry_point second_plugin:main' \
    python -m reader some-command

For `built-in plugins`_, it is enough to use the plugin name (``reader.XYZ``).

.. note::

    :func:`make_reader` ignores the plugin environment variables.


To load web application plugins, set the ``READER_APP_PLUGIN`` environment variable.
To load CLI plugins (that customize the CLI),
set the ``READER_CLI_PLUGIN`` environment variable.


Experimental plugins
--------------------

*reader* also ships with a number of experimental plugins.

For these, the full entry point *must* be specified.

To use them from within Python code,
use the entry point as a :ref:`custom plugin <custom plugins>`::

    >>> from reader._plugins import sqlite_releases
    >>> reader = make_reader("db.sqlite", plugins=[sqlite_releases.init])


.. automodule:: reader._plugins.tumblr_gdpr
.. automodule:: reader._plugins.enclosure_tags
.. automodule:: reader._plugins.preview_feed_list
.. automodule:: reader._plugins.sqlite_releases
.. automodule:: reader._plugins.cli_status
