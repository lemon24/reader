import os
import re
import sys
import unittest.mock

import packaging.version
from setuptools.config.pyprojecttoml import read_configuration


sys.path.insert(0, os.path.abspath('../src'))

# mock some things "by hand", so we can import reader below without any dependencies
for name in [
    'humanize',
    'readtime',
    'flask',
    'flask.signals',
    'werkzeug',
    'werkzeug.datastructures',
    'werkzeug.http',
    'yaml',
]:
    sys.modules[name] = unittest.mock.Mock()

import reader


extensions = [
    'sphinx_rtd_theme',
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx.ext.intersphinx',
    'sphinx.ext.extlinks',
    'sphinx_click.ext',
    'hoverxref.extension',
    'sphinxcontrib.log_cabinet',
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "requests": ("https://requests.readthedocs.io/en/stable/", None),
}

autodoc_mock_imports = [
    'bs4',
    'mutagen',
    'flask',
    'werkzeug',
    'humanize',
    'markupsafe',
    'yaml',
    'jinja2',
    'tweepy',
]

master_doc = 'index'

project = 'reader'
copyright = '2018, lemon24'
author = 'lemon24'

version_parsed = packaging.version.parse(reader.__version__)
version = version_parsed.base_version
release = reader.__version__


exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

todo_include_todos = False

autodoc_member_order = 'bysource'
# see dev.rst # Documentation
autodoc_typehints = 'description'
autodoc_typehints_description_target = 'documented'
autodoc_type_aliases = {
    'ResourceInput': 'reader.types.ResourceInput',
    'AnyResourceInput': 'reader.types.AnyResourceInput',
    'JSONType': 'reader.types.JSONType',
    'TagFilter': 'reader._types.TagFilter',
    'TristateFilter': 'reader._types.TristateFilter',
}


pyproject_toml = read_configuration('../pyproject.toml')
python_requires = str(pyproject_toml['project']['requires-python'])
min_python = re.match(r"^>=(\d+\.\d+)$", python_requires).group(1)


rst_prolog = f"""

.. |min_python| replace:: {min_python}


"""


GOOGLE_SITE_VERIFICATION = os.environ.get('GOOGLE_SITE_VERIFICATION')
if GOOGLE_SITE_VERIFICATION:
    rst_prolog += f"""

.. meta::
    :google-site-verification: {GOOGLE_SITE_VERIFICATION.strip()}

"""


branch = 'master' if version_parsed.is_devrelease else release
extlinks = {
    'issue': ('https://github.com/lemon24/reader/issues/%s', '#%s'),
    'gh': (f"https://github.com/lemon24/reader/tree/{branch}/%s", '%s'),
}


hoverxref_auto_ref = True
hoverxref_domains = ["py"]
hoverxref_role_types = {
    'ref': 'tooltip',
    'mod': 'tooltip',
    'class': 'tooltip',
    'meth': 'tooltip',
    'attr': 'tooltip',
    'exc': 'tooltip',
    'func': 'tooltip',
    'data': 'tooltip',
}

pygments_style = 'friendly'

html_theme = 'sphinx_rtd_theme'
html_static_path = []


htmlhelp_basename = 'readerdoc'


latex_elements = {}
latex_documents = [
    (master_doc, 'reader.tex', 'reader Documentation', 'lemon24', 'manual')
]


man_pages = [(master_doc, 'reader', 'reader Documentation', [author], 1)]


texinfo_documents = [
    (
        master_doc,
        'reader',
        'reader Documentation',
        author,
        'reader',
        'One line description of project.',
        'Miscellaneous',
    )
]


import pkgutil

from docutils import nodes
from sphinx.util.docutils import SphinxDirective


class ClassTree(SphinxDirective):
    required_arguments = 1

    def run(self):
        # TODO: this does not run again if only the python files changed
        name = self.arguments[0]
        modname = self.env.ref_context.get('py:module')
        if not name.startswith(modname + '.'):
            name = modname + '.' + name
        obj = pkgutil.resolve_name(name)
        text = class_tree(obj)
        paragraph_node = nodes.literal_block(text=text)
        return [paragraph_node]


def class_tree(cls):
    """Render a class tree diagram likee
    https://docs.python.org/3/library/exceptions.html#exception-hierarchy

    """
    classes = [cls]

    parents = {}
    seen_parents = set()

    def init_parents(classes, parent=None, level=0):
        for cls in classes:
            seen_parents.add(cls)
            bases = [
                e for e in cls.__bases__ if e is not parent or e not in seen_parents
            ]
            parents[cls] = bases if level else []
            init_parents(cls.__subclasses__(), parent=cls, level=1)

    init_parents(classes)

    # technically, what we're trying to achieve with the reversed() below
    # is that classes closer to the root appear as secondary parents
    # (in brackets) of those farther from the root, not the other way around;
    # there probably is a more correct way of doing this

    children = {}
    seen_children = set()

    def init_children(classes):
        for cls in reversed(classes):
            subclasses = cls.__subclasses__()
            children[cls] = [e for e in subclasses if e not in seen_children]
            seen_children.update(subclasses)
            init_children(subclasses)

    init_children(classes)

    def output(classes, level=0):
        for i, cls in enumerate(classes):
            if not level:
                prefix = sub_prefix = ''
            elif i < len(classes) - 1:
                prefix = ' ├── '
                sub_prefix = ' │   '
            else:
                prefix = ' └── '
                sub_prefix = '     '

            suffix = ''
            if level and parents[cls]:
                suffix = f" [{', '.join(e.__name__ for e in parents[cls])}]"

            yield f"{prefix}{cls.__name__}{suffix}"
            for line in output(children[cls], level=1):
                yield f"{sub_prefix}{line}"

    return '\n'.join(output(classes)) + '\n'


def setup(app):
    app.add_directive("classtree", ClassTree)
