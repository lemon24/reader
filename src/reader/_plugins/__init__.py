"""
Plug-in infrastructure. Not stable.

Also package containing **unstable** plugins shipped with reader.

Note that while the plugin entry points (import names) are relatively stable,
the contents of the actual plugins is not.

"""
from reader._vendor.pkgutil import resolve_name


class LoaderError(Exception):
    pass


class Loader:

    """Plugin loader.

    TODO: Cache imported plugins.
    TODO: Cache import errors, so we don't spam the logs / disk.

    """

    def __init__(self, import_names):
        self.import_names = import_names

    def load_plugins(self, target):
        for name in self.import_names:
            try:
                plugin = resolve_name(name)
            except ImportError as e:
                self.handle_error(
                    LoaderError("could not import plugin {}".format(name)), e
                )
                continue

            try:
                plugin(target)
            except Exception as e:
                self.handle_error(
                    LoaderError("while installing plugin {}".format(name)), e
                )

    def handle_error(self, exception, cause):
        raise exception from cause
