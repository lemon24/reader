import ast
import re

from setuptools import find_packages
from setuptools import setup

_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('src/reader/__init__.py', 'rb') as f:
    version = str(
        ast.literal_eval(_version_re.search(f.read().decode('utf-8')).group(1))
    )

with open('README.rst') as f:
    long_description = f.read()

setup(
    name='reader',
    version=version,
    author='lemon24',
    url='https://github.com/lemon24/reader',
    license='BSD',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    include_package_data=True,
    python_requires='>=3.6',
    install_requires=[
        'dataclasses; python_version<"3.7"',
        'typing-extensions',
        # feedparser 6 already pulls in sgmllib3k
        'feedparser>=6',
        'requests>=2.18',
    ],
    extras_require={
        'search': ['beautifulsoup4>=4.5'],
        # PyYAML is for config;
        # cli, app, and config all need the plugin infra;
        'cli': ['click>=7', 'PyYAML', 'setuptools>=40'],
        'app': ['flask>=0.10', 'humanize', 'PyYAML', 'setuptools>=40'],
        'plugins': ['setuptools>=40'],
        'enclosure-tags': ['requests', 'mutagen'],
        'preview-feed-list': ['requests', 'beautifulsoup4', 'blinker>=1.4'],
        'sqlite-releases': ['beautifulsoup4'],
        'dev': [
            'pytest>=4',
            'pytest-randomly',
            'flaky',
            'hypothesis>=5',
            'coverage',
            'pytest-cov',
            'tox',
            'requests-mock',
            # machanicalsoup hard-depends on lxml,
            # which fails to build on pypy (see below).
            'mechanicalsoup; implementation_name != "pypy"',
            'requests-wsgi-adapter',
            # We want to test all known Beautiful Soup parsers.
            # lxml fails to build on pypy as of October 2020;
            # https://github.com/lemon24/reader/actions/runs/328943935
            'lxml; implementation_name != "pypy"',
            'html5lib',
            # mypy is not working on pypy as of January 2020
            # https://github.com/python/typed_ast/issues/97#issuecomment-484335190
            'mypy; implementation_name!="pypy"',
            # docs
            'sphinx',
            'sphinx_rtd_theme',
            'click>=7',
            'sphinx-click',
            'sphinx-issues',
            # release
            'setuptools',
            'wheel',
            'twine',
            # ...
            'pre-commit',
        ],
        'docs': [
            'sphinx',
            'sphinx_rtd_theme',
            'click>=7',
            'sphinx-click',
            'sphinx-issues',
            'sphinx-hoverxref',
        ],
    },
    description="A minimal feed reader library.",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    project_urls={
        "Documentation": "https://reader.readthedocs.io/",
        "Code": "https://github.com/lemon24/reader",
        "Issue tracker": "https://github.com/lemon24/reader/issues",
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Topic :: Internet',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content :: News/Diary',
        'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Topic :: Software Development :: Libraries',
        'Topic :: Utilities',
    ],
)
