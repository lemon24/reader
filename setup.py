from setuptools import setup

# Metadata goes in setup.cfg. These are here for GitHub's dependency graph.
# TODO: Move to setup.cfg once this issue is resolved:
# https://github.com/dependabot/dependabot-core/issues/2133

setup(
    name="reader",
    install_requires=[
        'dataclasses; python_version<"3.7"',
        "typing-extensions",
        # feedparser 6 already pulls in sgmllib3k
        "feedparser>=6",
        "requests>=2.18",
        # for JSON Feed date parsing
        "iso8601",
    ],
    extras_require={
        #
        # --- stable
        #
        "search": ["beautifulsoup4>=4.5"],
        #
        # --- unstable
        #
        # PyYAML is for config
        "cli": ["click>=7", "PyYAML"],
        "app": ["flask>=0.10", "humanize", "PyYAML"],
        #
        # --- development
        #
        # run tests under one interpreter
        "tests": [
            "pytest>=4",
            "pytest-randomly",
            "flaky",
            "hypothesis>=5",
            "coverage",
            "pytest-cov",
            "requests-mock",
            # mechanicalsoup hard-depends on lxml,
            # which fails to build on pypy (see below).
            'mechanicalsoup; implementation_name != "pypy"',
            "requests-wsgi-adapter",
            # We want to test all known Beautiful Soup parsers.
            # lxml fails to build on pypy as of October 2020;
            # https://github.com/lemon24/reader/actions/runs/328943935
            'lxml; implementation_name != "pypy"',
            "html5lib",
            # for parser tests
            "werkzeug",
            # mypy does not on pypy as of January 2020
            # https://github.com/python/typed_ast/issues/97#issuecomment-484335190
            'mypy; implementation_name != "pypy"',
        ],
        # build docs
        "docs": [
            "sphinx",
            "sphinx_rtd_theme",
            "click>=7",
            "sphinx-click",
            "sphinx-issues",
            "sphinx-hoverxref",
        ],
        # other things needed develop / test locally / make releases
        "dev": [
            "tox",
            "pre-commit",
            "build",
            "twine",
        ],
        #
        # --- unstable plugins
        #
        # mushed together for convenience
        "unstable-plugins": [
            # enclosure-tags
            "requests",
            "mutagen",
            # preview-feed-list
            "requests",
            "beautifulsoup4",
            "blinker>=1.4",
            # sqlite-releases
            "beautifulsoup4",
        ],
    },
)
