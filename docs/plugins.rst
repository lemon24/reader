
Plugins
=======

.. module:: reader
  :noindex:


Built-in plugins
----------------

This is a list of built-in plugins that are considered stable.

See the :ref:`Plugins <plugins>` section of the :doc:`guide`
for details on how built-in plugins are loaded.

.. automodule:: reader.plugins.enclosure_dedupe
.. automodule:: reader.plugins.entry_dedupe
.. automodule:: reader.plugins.ua_fallback


Loading plugins from the CLI and the web application
----------------------------------------------------

There is experimental support of plugins in the CLI and the web application.

.. warning::

    The plugin system/hooks are not stable yet and may change without any notice.

.. note::

    Plugin loading machinery is optional, use the ``plugins`` extra to install
    its :ref:`dependencies <Optional dependencies>`.

To load plugins, set the ``READER_PLUGIN`` environment variable to the plugin
entry point (e.g. ``package.module:entry_point``); multiple entry points should
be separated by one space::

    READER_PLUGIN='first.plugin:entry_point second_plugin:main' \
    python -m reader some-command

For `built-in plugins`_, it is enough to use the plugin name (``reader.XYZ``).

To load web application plugins, set the ``READER_APP_PLUGIN`` environment
variable in a similar way.

Currently plugins are loaded through the CLI and web application only
(they won't be loaded when importing :class:`Reader`).


Experimental plugins
--------------------

*reader* also ships with a number of experimental plugins.
These *must* be loaded via their entry points.

.. automodule:: reader._plugins.regex_mark_as_read
.. automodule:: reader._plugins.tumblr_gdpr
.. automodule:: reader._plugins.enclosure_tags
.. automodule:: reader._plugins.preview_feed_list
.. automodule:: reader._plugins.sqlite_releases
