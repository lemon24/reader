import re
import ast
from setuptools import setup

_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('reader/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(
        f.read().decode('utf-8')).group(1)))

setup(
    name='reader',
    version=version,
    author='lemon24',
    url='https://github.com/lemon24/reader',
    packages=['reader'],
    include_package_data=True,
    install_requires=[
        'attrs>=17',
        'feedparser>=5',
        'click>=5',
        'flask>=0.10',
        'humanize',
    ],
    extras_require={
        'enclosure-tags': ['requests', 'mutagen'],
    },
    description="",
    classifiers=[
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
)

