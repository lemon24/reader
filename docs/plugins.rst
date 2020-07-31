
Plugins
=======

.. module:: reader
  :noindex:

.. warning::

    The plugin system/hooks are not stable yet and may change without any notice.

.. note::

    Plugin loading machinery is optional, use the ``plugins`` extra to install
    its :ref:`dependencies <Optional dependencies>`.

There is experimental support of plugins.

To load plugins, set the ``READER_PLUGIN`` environment variable to the plugin
entry point (e.g. ``package.module:entry_point``); multiple entry points should
be separated by one space::

    READER_PLUGIN='first.plugin:entry_point second_plugin:main' \
    python -m reader some-command

To load web application plugins, set the ``READER_APP_PLUGIN`` environment
variable in a similar way.

Currently plugins are loaded through the CLI and web application only
(they won't be loaded when importing :class:`Reader`).


Existing plugins
----------------

.. automodule:: reader._plugins.regex_mark_as_read
.. automodule:: reader._plugins.feed_entry_dedupe
.. automodule:: reader._plugins.enclosure_dedupe
.. automodule:: reader._plugins.tumblr_gdpr
.. automodule:: reader._plugins.enclosure_tags
.. automodule:: reader._plugins.preview_feed_list
.. automodule:: reader._plugins.cloudflare_ua_fix
