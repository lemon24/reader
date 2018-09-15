
Development
===========

Goals:

* clearly documented API
* minimal web interface
* minimal CLI

Development should follow a problem-solution_ approach.

Run tests::

    tox

or::

    make

or::

    python3 -m pytest --runslow

Start a local development server for the web-app::

    READER_DB=db.sqlite FLASK_DEBUG=1 FLASK_APP=autoapp.py \
        flask run -h localhost -p 8080


.. _problem-solution: https://hintjens.gitbooks.io/scalable-c/content/chapter1.html#problem-what-do-we-do-next

