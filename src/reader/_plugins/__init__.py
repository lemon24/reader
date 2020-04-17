"""
Plug-in infrastructure. Not stable.

Also namespace package containing plugins shipped with reader.

Note that while the plugin entry points (import names) are relatively stable,
the contents of the actual plugins is not.

"""

import_error = None
try:
    import pkg_resources
except ImportError as e:
    import_error = e


class LoaderError(Exception):
    pass


def import_string(import_name):
    ep = pkg_resources.EntryPoint.parse('none = ' + import_name)
    return ep.resolve()


class Loader:

    """Plugin loader.

    TODO: Cache imported plugins.
    TODO: Cache import errors, so we don't spam the logs / disk.
    TODO: Allow overriding of error handling for import_names.

    """

    def __init__(self, import_names):
        self.import_names = import_names

    @property
    def import_names(self):
        return self._import_names

    @import_names.setter
    def import_names(self, value):
        if import_error and value:
            raise LoaderError(
                "could not import plugin loading dependencies; "
                "use the 'plugins' extra to install them"
            ) from import_error
        self._import_names = value

    def load_plugins(self, target):
        for name in self.import_names:
            try:
                plugin = import_string(name)
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
