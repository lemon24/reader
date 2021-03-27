"""
Plug-in infrastructure. Not stable.

Also package containing **unstable** plugins shipped with reader.

Note that while the plugin entry points (import names) are relatively stable,
the contents of the actual plugins is not.

"""
import functools
from contextlib import contextmanager

from reader._vendor.pkgutil import resolve_name


class LoaderError(Exception):
    pass


def raise_exception(message, cause):
    raise LoaderError(message) from cause


class Loader:

    """Plugin loader.

    Allows customizing plugin import/initialization failure behavior.

    The load(name, wrap=True) allows any plugin initialization errors
    to raise a single exception type,
    since make_reader(plugins=...) just lets the exception propagate.

    """

    def load(self, name, *, wrap=False):
        try:
            plugin = resolve_name(name)
        except (ImportError, AttributeError, ValueError) as e:
            self.handle_import_error(f"could not import plugin {name}", e)
            return None

        if wrap:
            plugin = self._wrap_init(name)(plugin)

        return plugin

    @contextmanager
    def _wrap_init(self, name):
        try:
            yield
        except Exception as e:
            self.handle_init_error(f"while initializing plugin {name}", e)

    def init(self, target, names):
        for name in names:
            plugin = self.load(name)

            if not plugin:
                continue

            with self._wrap_init(name):
                plugin(target)

    handle_import_error = staticmethod(raise_exception)
    handle_init_error = staticmethod(raise_exception)
