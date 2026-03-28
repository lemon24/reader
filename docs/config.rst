
Configuration
=============

Both the :doc:`CLI <cli>` and the :doc:`web application <app>` can
be configured from a TOML file.

.. note::

    Configuration file loading dependencies get installed automatically when
    installing the CLI or the web application
    :ref:`extras <Optional dependencies>`.


The configuration file path can be specified either through the ``--config``
CLI option or through the ``READER_CONFIG`` environment variable
(also usable with the web application).

The configuration file matches the shape of the :doc:`CLI <cli>`
(the ``reader`` section has options for the ``reader`` command,
the ``reader.update`` section has options for the ``reader update`` command, etc.).
In general, option names match those in the CLI
(``--feed-root`` -> ``feed_root``);
options that can be passed multiple times in the CLI
are pluralized in the config
(``--cli-plugin`` -> ``cli_plugins``).

Example:

.. literalinclude:: ../examples/config.toml
