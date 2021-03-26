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

    # TODO: break this up between load_plugins (used with reader) and apply_plugins (used with app)
    # TODO: for reader, load_plugins should wrap the plugins to always raise LoaderError (because reader itself just lets the exception propagate); we can't make it do it because of backwards compatibility
    # TODO: OTOH, handle_error should be removed; hell knows in what state target is left after installing a plugin fails; we should not guess

    def load_plugins(self, target):
        for name in self.import_names:
            try:
                plugin = resolve_name(name)
            except (ImportError, AttributeError, ValueError) as e:
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
