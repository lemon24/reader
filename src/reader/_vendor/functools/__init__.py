"""
Backport of functools.cached_property (added in Python 3.8).

Could not use the backports.cached_property package because
mypy wasn't detecting the .pyi file for it properly
(likely because of the missing py.typed file).

TODO: Remove ._vendor.functools when we drop Python 3.7.

"""
from .functools import cached_property

__all__ = ['cached_property']
