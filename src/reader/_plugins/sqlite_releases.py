"""
sqlite_releases
~~~~~~~~~~~~~~~

Create a feed out of the SQLite release history pages at:

* https://www.sqlite.org/changes.html
* https://www.sqlite.org/chronology.html

Also serves as an example of how to write custom parsers.

This plugin needs additional dependencies, use the ``unstable-plugins`` extra
to install them:

.. code-block:: bash

    pip install reader[unstable-plugins]

To load::

    READER_PLUGIN='reader._plugins.sqlite_releases:init' \\
    python -m reader serve

"""
import warnings
from datetime import datetime
from urllib.parse import urlparse
from urllib.parse import urlunparse

import bs4

from reader._parser import wrap_exceptions
from reader._types import EntryData
from reader._types import FeedData

warnings.filterwarnings(
    'ignore',
    message='No parser was explicitly specified',
    module='reader._plugins.sqlite_releases',
)


FULL_URL = 'https://www.sqlite.org/changes.html'
URLS = [FULL_URL, 'https://www.sqlite.org/chronology.html']


def extract_text(soup):
    for h3 in soup.select('body h3'):
        a_name = None
        for element, _ in zip(h3.previous_siblings, range(3)):
            if element.name == 'h3':
                break
            if element.name == 'a' and 'name' in element.attrs:
                a_name = element
                break

        content = []
        last_a_name_index = None
        for i, element in enumerate(h3.next_siblings):
            if element.name == 'h3':
                break
            if element.name == 'a' and 'name' in element.attrs:
                last_a_name_index = i
            content.append(element)
        if last_a_name_index and len(content) - last_a_name_index <= 3:
            content = content[:last_a_name_index]

        yield h3.text, a_name['name'] if a_name else None, ''.join(map(str, content))


def make_entries(feed_url, url, soup):
    for title, fragment, content in extract_text(soup):
        try:
            updated = datetime.strptime(title.split()[0], '%Y-%m-%d')
        except (ValueError, IndexError):
            continue

        link = urlunparse(urlparse(url)._replace(fragment=fragment))

        yield EntryData(
            feed_url=feed_url,
            id=title,
            updated=updated,
            title=title,
            link=link,
            summary=content,
        )


def make_feed(feed_url, url, soup):
    return FeedData(url=feed_url, title=soup.title and soup.title.text, link=url)


def parse(url, file, headers):
    with wrap_exceptions(url, "while reading feed"):
        soup = bs4.BeautifulSoup(file)
    with wrap_exceptions(url, "while parsing page"):
        feed = make_feed(url, FULL_URL, soup)
        entries = list(make_entries(url, FULL_URL, soup))
        feed = feed._replace(updated=max(e.updated for e in entries))
    return feed, entries


def init(reader):
    for url in URLS:
        reader._parser.mount_parser_by_url(url, parse)
