"""
Plug-in infrastructure. Not stable.

Also serves as namespace package containing plugins shipped with reader.

"""

import pkg_resources


def import_string(import_name):
    ep = pkg_resources.EntryPoint.parse('none = ' + import_name)
    return ep.resolve()


def load_plugins(reader, import_names):
    for name in import_names:
        plugin = import_string(name)
        plugin(reader)

