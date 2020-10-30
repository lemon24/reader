
.. module:: reader
  :noindex:


Backwards compatibility
=======================


*reader* uses `semantic versioning`_.

This means you should never be afraid to upgrade *reader*
between minor versions if you’re using its public API.

If breaking compatibility will ever be needed,
it will be done by incrementing the *major version*,
announcing it in the :doc:`changelog`,
and raising deprecation warnings for at least one minor version
before the new major version is published.

That said, new major versions will be released as conservatively as possible.
Even during the initial development phase (versions 0.*),
over 20+ minor versions spanning 1.5 years,
backwards compatibility was only broken 3 times,
with the approriate deprecation warnings.

.. _semantic versioning: https://semver.org/


What is the public API
----------------------

The *reader* follows the `PEP 8 definition`_ of public interface.

The following are part of the public API:

* Every interface documented in the :doc:`API reference <api>`.
* Any module, function, object, method, and attribute,
  defined in the *reader* package,
  that is accessible without passing through a name that starts with underscore.
* The number and position of positional arguments.
* The names of keyword arguments.
* Argument types (argument types cannot become more strict).
* Attribute types (attribute types cannot become less strict).

While argument and attribute types are part of the public API,
type annotations and type aliases (even if not private),
are **not** part of the public API.


.. todo::

    When we start exposing plugins, callback signatures must also not change
    (i.e. the "argument types" above does not apply to them).

    Also, how about type aliased intended to be used with plugins, like
    reader.core._PostEntryAddPluginType and reader._types.ParserType?


Other exceptions are possible; they will be marked aggresively as such.


.. _PEP 8 definition: https://www.python.org/dev/peps/pep-0008/#public-and-internal-interfaces


.. warning::

    As of version |version|,
    the :doc:`command-line interface <cli>`,
    :doc:`web application <app>`,
    and :doc:`plugin system/hooks <plugins>`
    are **not** part of the public API;
    they are not stable yet and might change without any notice.
