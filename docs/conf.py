import os
import sys
import unittest.mock

import packaging.version

sys.path.insert(0, os.path.abspath('../src'))

# mock some things "by hand", so we can import reader below without any dependencies
for name in [
    'humanize',
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
    'sphinx_click.ext',
    'sphinx_issues',
    'hoverxref.extension',
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
]

master_doc = 'index'

project = 'reader'
copyright = '2018, lemon24'
author = 'lemon24'

version = packaging.version.parse(reader.__version__).base_version
release = reader.__version__

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

todo_include_todos = False

autodoc_member_order = 'bysource'
autodoc_typehints = 'none'


rst_prolog = ""


GOOGLE_SITE_VERIFICATION = os.environ.get('GOOGLE_SITE_VERIFICATION')
if GOOGLE_SITE_VERIFICATION:
    rst_prolog += f"""

.. meta::
    :google-site-verification: {GOOGLE_SITE_VERIFICATION.strip()}

"""


issues_github_path = 'lemon24/reader'

hoverxref_auto_ref = True
hoverxref_domains = ["py"]

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


# lifted from https://github.com/pallets/flask/blob/0.12.x/docs/conf.py#L64


def github_link(name, rawtext, text, lineno, inliner, options=None, content=None):
    app = inliner.document.settings.env.app
    release = app.config.release
    base_url = "https://github.com/lemon24/reader/tree/"

    if text.endswith(">"):
        words, text = text[:-1].rsplit("<", 1)
        words = words.strip()
    else:
        words = None

    if packaging.version.parse(release).is_devrelease:
        url = f"{base_url}master/{text}"
    else:
        url = f"{base_url}{release}/{text}"

    if words is None:
        words = url

    from docutils.nodes import reference
    from docutils.parsers.rst.roles import set_classes

    options = options or {}
    set_classes(options)
    node = reference(rawtext, words, refuri=url, **options)
    return [node], []


def setup(app):
    app.add_role("gh", github_link)
