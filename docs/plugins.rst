
Plugins
=======

.. module:: reader
  :no-index:


.. _built-in plugins:

Built-in plugins
----------------

This is a list of built-in plugins that are considered stable.

See the :ref:`Plugins <plugins>` section of the user guide
for details on how built-in plugins are loaded.

.. automodule:: reader.plugins.enclosure_dedupe
.. automodule:: reader.plugins.entry_dedupe
.. automodule:: reader.plugins.mark_as_read
.. automodule:: reader.plugins.readtime
.. automodule:: reader.plugins.ua_fallback



Experimental plugins
--------------------

*reader* also ships with a number of experimental plugins.

For these, the full entry point *must* be specified.

To use them from within Python code,
use the entry point as a :ref:`custom plugin <custom plugins>`::

    >>> from reader._plugins import sqlite_releases
    >>> reader = make_reader("db.sqlite", plugins=[sqlite_releases.init])


.. automodule:: reader._plugins.cli_status
.. automodule:: reader._plugins.preview_feed_list
.. automodule:: reader._plugins.enclosure_tags
.. automodule:: reader._plugins.sqlite_releases
.. automodule:: reader._plugins.timer
.. automodule:: reader._plugins.share



Discontinued plugins
--------------------

Following are experimental plugins that are not very useful anymore.

.. _twitter:

twitter
~~~~~~~

Prior to version 3.7, *reader* had a Twitter plugin;
it was removed because
it's not possible to get tweets using the free API tier anymore.

However, the plugin used the internal :ref:`parser` API
:ref:`in new and interesting ways <twitter-lessons>`
– it mapped the multiple tweets in a thread to a single entry,
and stored old tweets alongside the rendered HTML content
to avoid retrieving them again when updating the thread/entry.

You can still find the code on GitHub:
`twitter.py <https://github.com/lemon24/reader/blob/3.6/src/reader/_plugins/twitter.py>`_.


.. _tumblr_gdpr:

tumblr_gdpr
~~~~~~~~~~~

Prior to version 3.7, *reader* had a plugin to accept Tumblr GDPR terms
(between 2018 and 2020, Tumblr would redirect all new sessions
to an "accept the terms of service" page,
including machine-readable RSS feeds).

This plugin is a good example of how to set cookies
on the Requests session used to retrieve feeds.

You can still find the code on GitHub:
`tumblr_gdpr.py <https://github.com/lemon24/reader/blob/3.6/src/reader/_plugins/tumblr_gdpr.py>`_.



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



Recipes
-------

I currently don't need this functionality,
but if you'd be interested in maintaining any of these
as an experimental or even built-in plugin,
please :doc:`submit a pull request <contributing>`.

.. include:: ../examples/feed_slugs.py
    :start-after: """
    :end-before: """
.. literalinclude:: ../examples/feed_slugs.py
    :start-at: def init_reader
    :end-before: if __name__
