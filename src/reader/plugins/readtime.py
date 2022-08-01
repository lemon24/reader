"""
reader.readtime
~~~~~~~~~~~~~~~

.. module:: reader
  :noindex:

Calculate the read time for new/updated entries,
and store it as the ``.reader.readtime`` entry tag, with the format::

    {'seconds': 1234}

The content used is that returned by :meth:`~Entry.get_content`.


The read time for existing entries is backfilled as follows:

* On the first :meth:`~Reader.update_feeds` / :meth:`~Reader.update_feeds_iter` call:

  * all feeds with :attr:`~Feed.updates_disabled` false are scheduled to be backfilled

    * the feeds selected to be updated are backfilled then
    * the feeds not selected to be updated will be backfilled
      the next time they are updated

  * all feeds with :attr:`~Feed.updates_disabled` true are backfilled,
    regardless of which feeds are selected to be updated

* To prevent any feeds from being backfilled,
  set the ``.reader.readtime`` global tag to ``{'backfill': 'done'}``.
* To schedule a feed to be backfilled on its next update,
  set the ``.reader.readtime`` feed tag to ``{'backfill': 'pending'}``.


This plugin needs additional dependencies, use the ``readtime`` extra
to install them:

.. code-block:: bash

    pip install reader[readtime]


.. versionadded:: 2.12


..
    Implemented for https://github.com/lemon24/reader/issues/275

"""
import math
import re
import warnings

import bs4

from reader.types import _get_entry_content


_TAG = 'readtime'


# for details, see similar reader._search filterwarnings call
warnings.filterwarnings(
    'ignore',
    message='No parser was explicitly specified',
    module='reader.plugins.readtime',
)


def _readtime_of_entry(entry):
    content = _get_entry_content(entry)
    if not content:
        return {'seconds': 0}

    if content.is_html:
        result = _readtime_of_html(content.value)
    else:
        result = _readtime_of_strings([content.value])

    return {'seconds': result}


# roughly following https://github.com/alanhamlett/readtime/blob/2.0.0/readtime/utils.py#L63


def _readtime_of_html(html, features=None):
    # TODO: move this line to _html_utils
    soup = bs4.BeautifulSoup(html, features=features)
    _remove_nontext_elements(soup)

    seconds = _readtime_of_strings(soup.stripped_strings)

    # add extra seconds for inline images
    images = len(soup.select('img'))
    delta = 12
    for _ in range(images):
        seconds += delta
        if delta > 3:  # pragma: no cover
            delta -= 1

    return seconds


# TODO: move to _html_utils
def _remove_nontext_elements(soup):
    # <script>, <noscript> and <style> don't contain things relevant to search.
    # <title> probably does, but its content should already be in the entry title.
    #
    # Although <head> is supposed to contain machine-readable content, Firefox
    # shows any free-floating text it contains, so we should keep it around.
    #
    for e in soup.select('script, noscript, style, title'):
        e.replace_with('\n')


_WPM = 265
_WORD_DELIMITER = re.compile(r'\W+')


def _readtime_of_strings(strings):
    strings = map(str.strip, strings)
    strings = filter(None, strings)
    num_words = sum(len(re.split(_WORD_DELIMITER, s)) for s in strings)
    return int(math.ceil(num_words / _WPM * 60))


def _after_entry_update(reader, entry, status):
    key = reader.make_reader_reserved_name(_TAG)
    reader.set_tag(entry, key, _readtime_of_entry(entry))


def _before_feeds_update(reader):
    key = reader.make_reader_reserved_name(_TAG)

    if reader.get_tag((), key, None):
        return

    for feed in reader.get_feeds():
        reader.set_tag(feed, key, {'backfill': 'pending'})


def _after_feed_update(reader, feed):
    key = reader.make_reader_reserved_name(_TAG)
    _backfill_feed(reader, feed, key)


def _after_feeds_update(reader):
    key = reader.make_reader_reserved_name(_TAG)

    if reader.get_tag((), key, None):
        return

    for feed in reader.get_feeds(updates_enabled=False):
        _backfill_feed(reader, feed, key)

    reader.set_tag((), key, {'backfill': 'done'})


def _backfill_feed(reader, feed, key):
    if not reader.get_tag(feed, key, None):
        return
    for entry in reader.get_entries(feed=feed):
        if reader.get_tag(entry, key, None):
            continue
        reader.set_tag(entry, key, _readtime_of_entry(entry))
    reader.delete_tag(feed, key)


def init_reader(reader):
    reader.after_entry_update_hooks.append(_after_entry_update)
    reader.before_feeds_update_hooks.append(_before_feeds_update)
    reader.after_feed_update_hooks.append(_after_feed_update)
    reader.after_feeds_update_hooks.append(_after_feeds_update)
