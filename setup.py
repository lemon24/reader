import re
import ast
from setuptools import setup, find_packages

_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('src/reader/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(
        f.read().decode('utf-8')).group(1)))

setup(
    name='reader',
    version=version,
    author='lemon24',
    url='https://github.com/lemon24/reader',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    include_package_data=True,
    install_requires=[
        'attrs>=17.1',
        'feedparser>=5',
        'requests',
    ],
    extras_require={
        'cli': ['click>=5'],
        'web-app': ['flask>=0.10', 'humanize'],
        'enclosure-tags': ['requests', 'mutagen'],
    },
    description="",
    classifiers=[
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
)

