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
    install_requires=['attrs>=17.3', 'feedparser>=5', 'requests'],
    extras_require={
        'cli': ['click>=5'],
        'web-app': ['flask>=0.10', 'humanize'],
        'enclosure-tags': ['requests', 'mutagen'],
        'plugins': ['setuptools>=40'],
        'dev': [
            # tests
            'pytest>=4',
            'coverage',
            'pytest-cov',
            'tox',
            'requests-mock',
            'mechanicalsoup',
            'requests-wsgi-adapter',
            # docs
            'sphinx',
            'sphinx_rtd_theme',
            'click>=5',
            'sphinx-click',
            # release
            'twine',
            # ...
            'pre-commit',
        ],
        'docs': ['sphinx', 'sphinx_rtd_theme', 'click>=5', 'sphinx-click'],
    },
    description="A minimal feed reader.",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    classifiers=[
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
    ],
)
