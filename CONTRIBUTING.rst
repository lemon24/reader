How to contribute to *reader*
=============================

Thank you for considering contributing to *reader*!



Reporting issues
----------------

Please report issues via `GitHub Issues`_.

Include the following information:

* Describe what you expected to happen.
* If possible, include a `minimal reproducible example`_
  to help identify the issue.
  This also helps check that the issue is not with your own code.
* Describe what actually happened.
  Include the full traceback if there was an exception.
* List your Python and *reader* versions.
  If possible, check if this issue is already fixed
  in the latest release or the latest code in the repository.

.. _GitHub Issues: https://github.com/lemon24/reader/issues
.. _minimal reproducible example: https://stackoverflow.com/help/minimal-reproducible-example



Questions
---------

Please use `Github Discussions`_ for support or general questions.

.. _GitHub Discussions: https://github.com/lemon24/reader/discussions



Submitting patches
------------------

If there is no open issue for what you want to submit,
prefer opening one for discussion before working on a pull request.

You can work on any `help wanted`_ issue
that does not have an open PR or an assigned maintainer
(no need to ask).

For other `open issues`_, please ask first,
there may be background that didn't end up in the issue yet;
also see :ref:`roadmap` and :ref:`design notes`.

.. _help wanted: https://github.com/lemon24/reader/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22
.. _open issues: https://github.com/lemon24/reader/issues


Include the following in your patch:

* Use `Black`_ to format your code.
  This and other tools will run automatically
  if you install `pre-commit`_ using the instructions below.
* Include tests if your patch adds or changes code.
  Make sure the test fails without your patch.
* Update any relevant documentation pages and docstrings.
  Documentation pages and docstrings should be wrapped at 72 characters.
* Add an entry in ``CHANGES.rst``.
  Use the same style as other entries.
  Also include ``.. versionchanged::`` inline changelogs in relevant docstrings.

.. _Black: https://black.readthedocs.io
.. _pre-commit: https://pre-commit.com


First time setup
~~~~~~~~~~~~~~~~

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

    .. code-block:: text

        > py -3 -m venv .venv
        > .venv\Scripts\activate

* Install *reader* in editable mode, with development dependencies.

    .. code-block:: console

        $ pip install -e '.[dev]'

* Install the pre-commit hooks.

    .. code-block:: console

        $ pre-commit install --install-hooks

* Alternatively, use `run.sh`_ to do the last two steps.

    .. code-block:: console

        $ ./run.sh install-dev


.. _GitHub account: https://github.com/join
.. _latest version of git: https://git-scm.com/downloads
.. _username: https://docs.github.com/en/github/using-git/setting-your-username-in-git
.. _email: https://docs.github.com/en/github/setting-up-and-managing-your-github-user-account/setting-your-commit-email-address
.. _Fork: https://github.com/lemon24/reader/fork
.. _Clone: https://docs.github.com/en/github/getting-started-with-github/fork-a-repo#step-2-create-a-local-clone-of-your-fork


Start coding
~~~~~~~~~~~~

* Create a branch to identify the issue you would like to work on.
  Branch off of the "master" branch.

    .. code-block:: console

        $ git fetch origin
        $ git checkout -b your-branch-name origin/master

* Using your favorite editor, make your changes, `committing as you go`_.
* Include tests that cover any code changes you make.
  Make sure the test fails without your patch.
  Run the tests as described below.
* Push your commits to your fork on GitHub and `create a pull request`_.
  Link to the issue being addressed with ``fixes #123``
  in the pull request description.

    .. code-block:: console

        $ git push --set-upstream origin your-branch-name

.. _committing as you go: https://afraid-to-commit.readthedocs.io/en/latest/git/commandlinegit.html#commit-your-changes
.. _create a pull request: https://docs.github.com/en/github/collaborating-with-issues-and-pull-requests/creating-a-pull-request


Running the tests
~~~~~~~~~~~~~~~~~

Run the basic test suite with pytest.

.. code-block:: console

    $ pytest --runslow

This runs the tests for the current environment,
which is usually sufficient.
CI will run the full suite when you submit your pull request.
You can run the full test suite with tox if you don't want to wait.

.. code-block:: console

    $ tox


Running test coverage
~~~~~~~~~~~~~~~~~~~~~

Generating a report of lines that do not have test coverage
can indicate what code needs to be tested.
Use `run.sh`_ to run ``pytest`` using ``coverage``,
generate a report, and check required coverage.

.. code-block:: console

    $ ./run.sh coverage-all

Open ``htmlcov/index.html`` in your browser to explore the report.

The library **must** have 100% test coverage;
the unstable plugins, CLI, and web app do not have coverage requirements.

Read more about `coverage <https://coverage.readthedocs.io>`__.


Type checking
~~~~~~~~~~~~~

Run type checking with ``mypy``.

.. code-block:: console

    $ mypy --strict src

The library **must** pass strict type checking;
the plugins, CLI, and web app do not have type checking requirements.

Read more about `mypy <https://mypy.readthedocs.io/en/stable/>`__.


Building the docs
~~~~~~~~~~~~~~~~~

Build the docs using Sphinx.

.. code-block:: console

    $ make -C docs html

Open ``docs/_build/html/index.html`` in your browser to view the docs.

Read more about `Sphinx <https://www.sphinx-doc.org/en/stable/>`__.


run.sh
~~~~~~

.. code-block:: console

    $ ./run.sh command [argument ...]

The :gh:`run.sh <run.sh>` script wraps the steps above
as "executable documentation".

``./run.sh install-dev``
    `First time setup`_ (install *reader* and pre-commit hooks)

``./run.sh test`` / ``./run.sh test-all``
    `Running the tests`_

``./run.sh coverage-all``
    `Running test coverage`_

``./run.sh typing``
    `Type checking`_

``./run.sh docs``
    `Building the docs`_

Arguments are usually passed along to the underlying tool,
e.g. ``typing`` arguments are passed to ``pytest``;
see the script source for details.


If you have `entr <http://eradman.com/entrproject/>`_ installed,
``test-dev``, ``typing-dev``, and ``docs-dev``
will run the corresponding commands when the files in the repo change.

Likewise, ``serve-dev`` will run the web app with the Flask
`development server <https://flask.palletsprojects.com/en/latest/server/>`_.
