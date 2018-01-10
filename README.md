**reader** is a minimal feed reader.

Goals:

* clearly documented API
* minimal web interface
* minimal CLI

Development should follow a [problem-solution][] approach.

In scope:

* find a better name
* CLI
    * add/remove feeds
    * update feeds
    * serve the web interface on localhost
* web interface
    * see all entries
    * see entries for a feed
    * mark entries as read
    * (later) mark entries as unread
    * (later) add/remove feeds
    * (much later) basic auth

Usage:

Most commands need a database to work. The following are equivalent:

    python3 -m reader.cli --db /path/to/db some-command
    READER_DB=/path/to/db python3 -m reader.cli some-command

If no database path is given, `~/.config/reader/db.sqlite` is used
(at least on Linux).

Add a feed:

    python3 -m reader.cli add http://www.example.com/atom.xml

Update all feeds:

    python3 -m reader.cli update

Start a local server (http://localhost:8080/):

    python3 -m reader.cli serve

Start a local development server:

    READER_DB=db.sqlite FLASK_DEBUG=1 FLASK_APP=autoapp.py \
        flask run -h localhost -p 8080

Run tests:

    tox

or:

    python3 -m pytest



[problem-solution]: https://hintjens.gitbooks.io/scalable-c/content/chapter1.html#problem-what-do-we-do-next
