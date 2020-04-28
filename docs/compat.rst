
Backwards compatibility
=======================


*reader* uses `semantic versioning`_.

Put simply, you shouldn’t ever be afraid to upgrade *reader*
between minor versions if you’re using its public API.

If breaking compatibility will ever be needed,
it will be done by incrementing the major version,
announcing it in the :doc:`changelog`,
and raising deprecation warnings for at least one minor version
before the new major version is published.

That said, new major versions will be released as conservatively as possible.
Even during the initial development phase (versions 0.*),
over 20+ minor versions spanning 1.5 years,
backwards compatibility was only broken 3 times,
with the approriate deprecation warnings.


.. _semantic versioning: https://semver.org/


.. warning::

    As of version |version|,
    the :doc:`command-line interface <cli>`,
    :doc:`web application <app>`,
    and :doc:`plugin system/hooks <plugins>`
    are **not** part of the public API;
    they are not stable yet and might change without any notice.
