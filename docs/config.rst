
Configuration
=============

Both the :doc:`CLI <cli>` and the :doc:`web application <app>` can
be configured from a file.

.. warning::

    The configuration file format is not stable yet
    and might change without any notice.

.. note::

    Configuration file loading dependencies get installed automatically when
    installing the CLI or the web application
    :ref:`extras <Optional dependencies>`.


The configuration file path can be specified either through the ``--config``
CLI option or through the ``READER_CONFIG`` environment variable
(also usable with the web application).

The config file is split in contexts;
this allows having a set of global defaults
and overriding them with CLI- or web-app-specific values.
Use the ``config dump --merge`` command
to see the final configuration for each context.

The older ``READER_DB``, ``READER_PLUGIN``, and ``READER_APP_PLUGIN``
environment variables always *replace* the corresponding config values,
so they should be used only for debugging.

The following example shows the config file structure
and the options currently available:

.. literalinclude:: ../examples/config.yaml
