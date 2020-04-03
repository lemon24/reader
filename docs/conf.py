import os
import sys

import packaging.version

sys.path.insert(0, os.path.abspath('../src'))
import reader

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx_click.ext',
]

autodoc_mock_imports = ['bs4', 'mutagen', 'flask', 'werkzeug', 'humanize']

master_doc = 'index'

project = 'reader'
copyright = '2018, lemon24'
author = 'lemon24'

version = packaging.version.parse(reader.__version__).base_version
release = reader.__version__

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

todo_include_todos = False

autodoc_member_order = 'bysource'


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
