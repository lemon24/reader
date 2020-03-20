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
        # needed on for pre-3.8 so we can get TypedDict and Protocol
        # TODO: remove this once we drop support for Python 3.7
        'typing_extensions; python_version<"3.8"',
        'feedparser>=5',
        'requests',
    ],
    extras_require={
        'cli': ['click>=5'],
        'web-app': ['flask>=0.10', 'humanize'],
        'enclosure-tags': ['requests', 'mutagen'],
        'plugins': ['setuptools>=40'],
        'search': ['beautifulsoup4'],
        'dev': [
            # !=5.3.4 because of https://github.com/pytest-dev/pytest/issues/6517
            # TODO: remove !=5.3.4 once a newer version is published
            'pytest>=4,!=5.3.4',
            'pytest-randomly',
            'coverage',
            'pytest-cov',
            'tox',
            'requests-mock',
            'mechanicalsoup',
            'requests-wsgi-adapter',
            # We want to test all known Beautiful Soup parsers.
            'lxml',
            'html5lib',
            # mypy is not working on pypy as of January 2020
            # https://github.com/python/typed_ast/issues/97#issuecomment-484335190
            'mypy; implementation_name!="pypy"',
            # docs
            'sphinx',
            'sphinx_rtd_theme',
            'click>=5',
            'sphinx-click',
            # release
            'setuptools',
            'wheel',
            'twine',
            # ...
            'pre-commit',
        ],
        'docs': ['sphinx', 'sphinx_rtd_theme', 'click>=5', 'sphinx-click'],
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
        'Development Status :: 4 - Beta',
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
        'Topic :: Internet',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content :: News/Diary',
        'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
        'Topic :: Software Development :: Libraries',
        'Topic :: Utilities',
    ],
)
