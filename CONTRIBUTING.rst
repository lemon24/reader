Contributing
============

Thank you for considering contributing to *reader*!



.. _issues:

Reporting issues
----------------

Please report issues via `GitHub Issues`_.

When doing so:

* Write a short, descriptive title.
* Describe what you expected to happen.
* Include a `minimal reproducible example`_ if possible.
  This helps identify the root cause
  and confirm the issue is not with your own code.
* Describe what actually happened.
  Include the full traceback if there was an exception,
  and any other relevant output.
* List the Python and *reader* versions you are using.
  If possible, check if the issue is already fixed
  in the latest `PyPI`_ release
  or in the latest :ref:`pre-release code <install-pre-release>`.

.. _GitHub Issues: https://github.com/lemon24/reader/issues
.. _minimal reproducible example: https://stackoverflow.com/help/minimal-reproducible-example
.. _PyPI: https://pypi.org/project/reader/



Asking questions
----------------

Please use `Github Discussions`_ for support or general questions.

.. _GitHub Discussions: https://github.com/lemon24/reader/discussions



.. _prs:

Submitting pull requests
------------------------

Please use `GitHub Issues`_ to discuss non-trivial changes:

* If there is no open issue, open one before working on a pull request.
* You can work on any `help wanted`_ issue
  that does not have an open PR or an assigned maintainer
  (no need to ask).
* For other `open issues`_, please ask first,
  there may be background that didn't end up in the issue yet;
  also see :ref:`roadmap` and :ref:`design notes`.
* For trivial changes (e.g. typos), you can open a PR directly.

.. _help wanted: https://github.com/lemon24/reader/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22
.. _open issues: https://github.com/lemon24/reader/issues


When submitting a pull request (details in the following sections):

* Use `pre-commit`_ to run formatters and linters.
* Add tests for your change.
* Update relevant documentation and docstrings.


.. admonition:: run.sh

    The :gh:`run.sh <run.sh>` script in the repository root
    wraps standard Python development tools in commands
    that serve as executable documentation
    (i.e. a summary of the guide below).

    Where applicable, a matching ``./run.sh`` command for each section is shown;
    you are welcome to use that or invoke the tool directly,
    whichever is more convenient.

    The ``-dev`` version of a command
    reruns it whenever files change,
    usually using `entr`_.

    .. _entr: http://eradman.com/entrproject/


Set up the repository
~~~~~~~~~~~~~~~~~~~~~

* Make sure you have a `GitHub account`_.
* Download and install the `latest version of git`_.
* Configure git with your `username`_ and `email`_.

    .. code-block:: console

        $ git config --global user.name 'your name'
        $ git config --global user.email 'your email'

* Fork *reader* to your GitHub account by clicking the `Fork`_ button.
* `Clone`_ your fork locally, replacing ``your-username``
  in the command below with your actual username.

    .. code-block:: console

        $ git clone https://github.com/your-username/reader
        $ cd reader

* Create a virtualenv. Use the latest version of Python.

  * Linux/macOS

    .. code-block:: console

        $ python3 -m venv .venv
        $ . .venv/bin/activate

  * Windows

    .. code-block:: doscon

        > py -3 -m venv .venv
        > .venv\Scripts\activate


.. _GitHub account: https://github.com/join
.. _latest version of git: https://git-scm.com/downloads
.. _username: https://docs.github.com/en/github/using-git/setting-your-username-in-git
.. _email: https://docs.github.com/en/github/setting-up-and-managing-your-github-user-account/setting-your-commit-email-address
.. _Fork: https://github.com/lemon24/reader/fork
.. _Clone: https://docs.github.com/en/github/getting-started-with-github/fork-a-repo#step-2-create-a-local-clone-of-your-fork


Install development dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. admonition:: run.sh

  ``./run.sh install``
    Install development dependencies.

Install *reader* in editable mode,
with all :ref:`extras <optional dependencies>` and development dependencies:

.. code-block:: console

    $ pip install -e '.[all]' --group dev

Install `pre-commit`_ hooks
(so `Black`_, `Flake8`_ etc. are run automatically before each commit):

.. code-block:: console

    $ pre-commit install --install-hooks


.. _pre-commit: https://pre-commit.com
.. _Black: https://black.readthedocs.io
.. _Flake8: https://flake8.pycqa.org


Start coding
~~~~~~~~~~~~

Create a branch to identify the issue you will work on.
Branch off of the ``master`` branch.

.. code-block:: console

    $ git fetch origin
    $ git checkout -b your-branch-name origin/master

Using your favorite editor, make your changes, `committing as you go`_.

Include tests that cover any code changes you make.
Make sure the test fails without your patch.
Run the tests as described below.

Update any relevant documentation pages and docstrings;
see :ref:`documentation` for details.
Adding a changelog entry is optional,
a maintainer will write one if you're not sure how to.


.. _committing as you go: https://afraid-to-commit.readthedocs.io/en/latest/git/commandlinegit.html#commit-your-changes
.. _inline changelogs: https://www.sphinx-doc.org/en/master/usage/restructuredtext/directives.html#describing-changes-between-versions


Run tests
~~~~~~~~~

.. admonition:: run.sh

  ``./run.sh test``
    Run tests.

  ``./run.sh test-dev``
    Run tests when files change.

Run the tests with `pytest`_ (including slow tests):

.. code-block:: console

    $ pytest --runslow


.. _pytest: https://docs.pytest.org/


Run test coverage
~~~~~~~~~~~~~~~~~

.. admonition:: run.sh

  ``./run.sh coverage``
    Run test coverage and generate reports.

Generating a report of lines that do not have test coverage
can indicate what code needs to be tested.
Use `coverage`_ to run `pytest`_,
generate an HTML report,
and check required coverage:

.. code-block:: console

    $ coverage run -m pytest --runslow
    $ coverage html
    $ ./run.sh coverage-report

Open ``htmlcov/index.html`` in your browser to explore the report.

The core library **must** have 100% test coverage.
Experimental plugins,
the command-line interface,
and the web application
do not have coverage requirements.


.. _coverage: https://coverage.readthedocs.io


Run type checking
~~~~~~~~~~~~~~~~~

.. admonition:: run.sh

  ``./run.sh typing``
    Run type checking.

  ``./run.sh typing-dev``
    Run type checking when files change.

Run type checking with `mypy`_:

.. code-block:: console

    $ mypy

The core library **must** pass strict type checking.
Plugins,
the command-line interface,
and the web application
do not have type checking requirements.


.. _mypy: https://mypy.readthedocs.io/en/stable/


Build the documentation
~~~~~~~~~~~~~~~~~~~~~~~

.. admonition:: run.sh

  ``./run.sh docs``
    Build the docs.

  ``./run.sh docs-dev``
    Build the docs when files change.

Build the documentation using `Sphinx`_:

.. code-block:: console

    $ sphinx-build -E -W docs docs/_build/html

Open ``docs/_build/html/index.html`` in your browser to view the built documentation.


.. _Sphinx: https://www.sphinx-doc.org/en/stable/


Run tests on all Python versions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. admonition:: run.sh

  ``./run.sh test-all``
    Run tests on all supported Python versions.

Run tests on all supported Python versions with `tox`_:

.. code-block:: console

    $ tox run-parallel

This includes coverage, type checking, and documentation,
making it the closest to a full CI run possible locally.


.. _tox: https://tox.wiki/



Create a pull request
~~~~~~~~~~~~~~~~~~~~~

Push your commits to your fork on GitHub and `create a pull request`_.
Link to the issue being addressed with ``Fixes #123.``
in the pull request description.

.. code-block:: console

    $ git push --set-upstream origin your-branch-name


.. _create a pull request: https://docs.github.com/en/github/collaborating-with-issues-and-pull-requests/creating-a-pull-request
