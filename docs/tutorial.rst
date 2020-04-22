Tutorial
========


... in which we download a podcast.

First, you need to install reader by following the instructions :doc:`here <install>`.


TODO: All of the prose.


Adding and updating feeds
-------------------------

Add feed::

    from reader import make_reader, FeedExistsError

    FEED_URL = "http://www.hellointernet.fm/podcast?format=rss"

    reader = make_reader("db.sqlite")

    def add_and_update_feed():
        try:
            reader.add_feed(FEED_URL)
        except FeedExistsError:
            pass

        reader.update_feeds()

        feed = reader.get_feed(FEED_URL)
        print(f"updated {feed.title} (last changed at {feed.updated})\n")

    add_and_update_feed()

Run with ``python3 script.py``.

Expected output:

.. code-block:: text

    updated Hello Internet (last changed at 2020-02-28 09:34:02)


Remove the add_and_update_feed() line for now. It remembers!


Looking at entries
------------------

Go through entries::

    def download_everything():
        entries = reader.get_entries()
        entries = list(entries)[:3]

        for entry in entries:
            print(entry.feed.title, '-', entry.title)

    download_everything()

Expected output:

.. code-block:: text

    Hello Internet - H.I. #136: Dog Bingo
    Hello Internet - H.I. #135: Place Your Bets
    Hello Internet - # H.I. 134: Boxing Day


Only entries with enclosures::

    entries = reader.get_entries(has_enclosures=True)


Mark those we've seen::

    entries = reader.get_entries(has_enclosures=True, read=False)
    ...

    for entry in entries:
        ...
        reader.mark_as_read(entry)

Output one:

.. code-block:: text

    Hello Internet - H.I. #136: Dog Bingo
    Hello Internet - H.I. #135: Place Your Bets
    Hello Internet - # H.I. 134: Boxing Day

Output two:

.. code-block:: text

    Hello Internet - Star Wars: The Rise of Skywalker, Hello Internet Christmas Special
    Hello Internet - H.I. #132: Artisan Water
    Hello Internet - H.I. #131: Panda Park


Look at enclosures::

    for entry in entries:
        print(entry.feed.title, '-', entry.title)

        for enclosure in entry.enclosures:
            if not enclosure.href.endswith('.mp3'):
                continue

            filename = enclosure.href.rpartition('/')[2]
            print("  *", filename)

        reader.mark_as_read(entry)

Output:

.. code-block:: text

    Hello Internet - H.I. #130: Remember Harder
      * 130.mp3
    Hello Internet - H.I. #129: Sunday Spreadsheets
      * 129.mp3
    Hello Internet - H.I. #128: Complaint Tablet Podcast
      * 128.mp3


Downloading enclosures
----------------------

Add download function::

    def download_file(src_url, dst_path):
        with open(dst_path, 'w') as f:
            f.write(src_url + '\n')

and then, in download_everything()::

    for enclosure in entry.enclosures:
        ...
        print("  *", filename)
        download_file(enclosure.href, os.path.join(PODCASTS_DIR, filename))

and imports::

    import os, os.path

and a new constant::

    PODCASTS_DIR = "podcasts"

and create the new directory::

    os.makedirs(PODCASTS_DIR, exist_ok=True)
    download_everything()

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
