"""
Use *reader* to download all the episodes of a podcast,
and then each new episode as they come up.

Part of https://reader.readthedocs.io/en/latest/tutorial.html

"""

import os
import os.path
import shutil

import requests

from reader import make_reader, FeedExistsError


feed_url = "http://www.hellointernet.fm/podcast?format=rss"
podcasts_dir = "podcasts"

reader = make_reader("db.sqlite")


def add_and_update_feed():
    try:
        reader.add_feed(feed_url)
    except FeedExistsError:
        pass
    reader.update_feeds()


def download_everything():
    entries = reader.get_entries(feed=feed_url, has_enclosures=True, read=False)

    for entry in entries:
        print(entry.feed.title, '-', entry.title)

        for enclosure in entry.enclosures:
            filename = enclosure.href.rpartition('/')[2]
            print("  *", filename)
            download_file(enclosure.href, os.path.join(podcasts_dir, filename))

        reader.mark_entry_as_read(entry)


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


add_and_update_feed()

feed = reader.get_feed(feed_url)
print(f"updated {feed.title} (last changed at {feed.updated})\n")

os.makedirs(podcasts_dir, exist_ok=True)
download_everything()
