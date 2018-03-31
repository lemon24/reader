**reader** is a minimal feed reader.

[![Build Status](https://travis-ci.org/lemon24/reader.svg?branch=master)](https://travis-ci.org/lemon24/reader)

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
    * mark entries as unread
    * add/remove feeds
    * (much later) basic auth

Usage:

Most commands need a database to work. The following are equivalent:

    python3 -m reader --db /path/to/db some-command
    READER_DB=/path/to/db python3 -m reader some-command

If no database path is given, `~/.config/reader/db.sqlite` is used
(at least on Linux).

Add a feed:

    python3 -m reader add http://www.example.com/atom.xml

Update all feeds:

    python3 -m reader update

Start a local server (http://localhost:8080/):

    python3 -m reader serve

Start a local development server:

    READER_DB=db.sqlite FLASK_DEBUG=1 FLASK_APP=autoapp.py \
        flask run -h localhost -p 8080

Run tests:

    tox

or:

    python3 -m pytest


Short API overview:

```
Reader(path=None)
Reader.add_feed(url)
Reader.get_entries(which='all', feed_url=None)
Reader.get_feed(url)
Reader.get_feeds()
Reader.mark_as_read(feed_url, entry_id)
Reader.mark_as_unread(feed_url, entry_id)
Reader.remove_feed(url)
Reader.set_feed_user_title(url, title)
Reader.update_feed(url)
Reader.update_feeds()
```



[problem-solution]: https://hintjens.gitbooks.io/scalable-c/content/chapter1.html#problem-what-do-we-do-next
