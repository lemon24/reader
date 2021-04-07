from setuptools import setup

# Metadata goes in setup.cfg. These are here for GitHub's dependency graph.
# TODO: move to setup.cfg once this issue is resolved: https://github.com/dependabot/dependabot-core/issues/2133
setup(
    name='reader',
    install_requires=[
        'dataclasses; python_version<"3.7"',
        'typing-extensions',
        # feedparser 6 already pulls in sgmllib3k
        'feedparser>=6',
        'requests>=2.18',
        # for JSON Feed date parsing
        'iso8601',
    ],
    extras_require={
        'search': ['beautifulsoup4>=4.5'],
        # PyYAML is for config
        'cli': ['click>=7', 'PyYAML'],
        'app': ['flask>=0.10', 'humanize', 'PyYAML'],
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
            # for parser tests
            'werkzeug',
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
)
