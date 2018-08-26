"""
Plug-in infrastructure. Not stable.

"""

import pkg_resources


def import_string(import_name):
    ep = pkg_resources.EntryPoint.parse('none = ' + import_name)
    return ep.load(require=False)


def load_plugins(reader, import_names):
    for name in import_names:
        plugin = import_string(name)
        plugin(reader)

