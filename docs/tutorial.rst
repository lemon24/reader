Tutorial
========

.. module:: reader
    :noindex:


In this tutorial we'll use *reader* to download all the episodes of a podcast,
and then each new episode as they come up.

`Podcasts <podcast_>`_ are episodic series that share information as digital
audio files that a user can download to a personal device for easy listening.

Usually, the user is notified of new episodes by periodically downloading
an `RSS feed <rss_>`_ which contains links to the actual audio files;
in the context of a feed, these files are called *enclosures*.


.. _podcast: https://en.wikipedia.org/wiki/Podcast
.. _rss: https://en.wikipedia.org/wiki/RSS


Before starting, install *reader* by following the instructions :doc:`here <install>`.


Adding and updating feeds
-------------------------

Create a ``script.py`` file::

    from reader import make_reader, FeedExistsError

    reader = make_reader("db.sqlite")

    feed_url = "http://www.hellointernet.fm/podcast?format=rss"

    def add_and_update_feed():
        try:
            reader.add_feed(feed_url)
        except FeedExistsError:
            pass
        reader.update_feeds()

    add_and_update_feed()

    feed = reader.get_feed(feed_url)
    print(f"updated {feed.title} (last changed at {feed.updated})\n")


:func:`make_reader` creates a :class:`Reader` object;
this gives access to most *reader* functionality
and persists the state related to feeds to a file.

:meth:`~Reader.add_feed` adds a new feed to the list of feeds.
Since we will run the script repeatedly to download new episodes,
if the feed already exists, we can just move along.

:meth:`~Reader.update_feeds` retrieves and stores all the added feeds.
*reader* uses the ETag and Last-Modified headers to only retrieve feeds
if they changed (if supported by the server).

:meth:`~Reader.get_feed` returns a :class:`Feed` object that contains
information about the feed.
We could have called :meth:`~Reader.get_feed` before :meth:`~Reader.update_feeds`,
but the returned feed would have most of its attributes set to None,
which is not very useful.


Run the script with the following command:

.. code-block:: bash

    python3 script.py

The output should be similar to this:

.. code-block:: text

    updated Hello Internet (last changed at 2020-02-28 09:34:02)

Comment out the ``add_and_update_feed()`` call for now.
If you re-run the script, the output should be the same,
since :meth:`~Reader.get_feed` returns data already persisted in the database.


Looking at entries
------------------

Let's look at the individual elements in the feed (called *entries*);
add this to the script::

    def download_everything():
        entries = reader.get_entries()
        entries = list(entries)[:3]

        for entry in entries:
            print(entry.feed.title, '-', entry.title)

    download_everything()

By default, :meth:`~Reader.get_entries` returns an iterable of
all the entries of all the feeds, most recent first.

In order to keep the output short, we only look at the first 3 entries for now.
Running the script should output something like this
(skipping that first "updated ..." line):

.. code-block:: text

    Hello Internet - H.I. #136: Dog Bingo
    Hello Internet - H.I. #135: Place Your Bets
    Hello Internet - # H.I. 134: Boxing Day


At the moment we only have a single feed; we can make sure we only get
the entries for this feed by using the `feed` argument; while we're at it,
let's also only get the entries that have enclosures::

    entries = reader.get_entries(feed=feed_url, has_enclosures=True)

Note that we could have also used ``feed=feed``;
wherever Reader needs a feed,
you can pass either the feed URL or a :class:`Feed` object.
This is similar for entries; they are identified by a (feed URL, entry id)
tuple, but you can also use an :class:`Entry` object instead.


Reading entries
---------------

As mentioned in the beginning, the script will keep track of what episodes
it already downloaded and only download the new ones.

We can achieve this by getting the unread entries,
and marking them as read after we process them::

    entries = reader.get_entries(feed=feed_url, has_enclosures=True, read=False)
    ...

    for entry in entries:
        ...
        reader.mark_as_read(entry)

If you run the script once, it should have the same output as before.
If you run it again, it will show the next 3 unread entries:

.. code-block:: text

    Hello Internet - Star Wars: The Rise of Skywalker, Hello Internet Christmas Special
    Hello Internet - H.I. #132: Artisan Water
    Hello Internet - H.I. #131: Panda Park


Downloading enclosures
----------------------

With the machinery to go through entries in place,
let's go through their enclosures::

    for entry in entries:
        print(entry.feed.title, '-', entry.title)

        for enclosure in entry.enclosures:
            filename = enclosure.href.rpartition('/')[2]
            print("  *", filename)
            download_file(enclosure.href, os.path.join(PODCASTS_DIR, filename))

        reader.mark_as_read(entry)

For each :class:`Enclosure`, we extract the filename from the enclosure URL
so we can use it as the name of the local file.

In order to make testing easier, we first write a dummy download_file()
that only writes the enclosure URL to the file instead downloading it::

    def download_file(src_url, dst_path):
        with open(dst_path, 'w') as file:
            file.write(src_url + '\n')

Let's add the needed imports and a new constant for the path of
the download directory::

    import os, os.path
    ...
    PODCASTS_DIR = "podcasts"

and make sure the directory exists (otherwise trying to open the file will fail)::

    os.makedirs(PODCASTS_DIR, exist_ok=True)
    download_everything()


TODO: ...


Output:

.. code-block:: text

    Hello Internet - H.I. #130: Remember Harder
      * 130.mp3
    Hello Internet - H.I. #129: Sunday Spreadsheets
      * 129.mp3
    Hello Internet - H.I. #128: Complaint Tablet Podcast
      * 128.mp3

Running this should create podcasts/ and write 127.mp3, 126.mp3, and 125.mp3,
with http://traffic.libsyn.com/hellointernet/12x.mp3 in each of them.



Final download function::

    import requests, shutil

    def download_file(src_url, dst_path):
        part_path = dst_path + '.part'
        with requests.get(src_url, stream=True) as response:
            response.raise_for_status()
            try:
                with open(part_path, 'wb') as file:
                    shutil.copyfileobj(response.raw, file)
                os.rename(part_path, dst_path)
            except BaseException:
                try:
                    os.remove(part_path)
                except Exception:
                    pass
                raise

Wrapping up
-----------

Add at the end::

    os.makedirs(PODCASTS_DIR, exist_ok=True)
    add_and_update_feed()
    download_everything()

and remove the ``entries = list(entries)[:3]`` line, and db.sqlite and the podcasts/ dir.

And run again; the output should be:

.. code-block:: text

    updated Hello Internet (last changed at 2020-02-28 09:34:02)

    Hello Internet - H.I. #136: Dog Bingo
      * 136FinalFinal.mp3
    Hello Internet - H.I. #135: Place Your Bets
      * 135.mp3
    Hello Internet - # H.I. 134: Boxing Day
      * HI134.mp3
    ...
