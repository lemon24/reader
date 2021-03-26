"""
Backport of pkgutil.resolve_name (added in Python 3.9).

Could have used something like the following::

    pkg_resources.EntryPoint.parse('none = ' + import_name).resolve()

but it requires setuptools to be installed.

TODO: Remove ._vendor.pkgutil when we drop Python 3.8.

"""
from .pkgutil import resolve_name

__all__ = ['resolve_name']
