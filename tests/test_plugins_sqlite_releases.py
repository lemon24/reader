from datetime import datetime

from reader._plugins.sqlite_releases import FULL_URL
from reader._plugins.sqlite_releases import init


def test_sqlite_releases(reader, requests_mock, data_dir):
    init(reader)

    requests_mock.get(
        FULL_URL,
        content=data_dir.join('sqlite_releases.html').read_binary(),
        headers={
            "Last-Modified": "Thu, 21 Jan 2021 01:23:58 +0000",
            "ETag": "m6008d7aes58501",
            "Content-type": "text/html; charset=utf-8",
        },
    )

    reader.add_feed(FULL_URL)
    reader.update_feeds()

    (feed,) = reader.get_feeds()
    assert feed.updated == datetime(2021, 1, 20, 0, 0)
    assert feed.title == 'Release History Of SQLite'
    assert feed.link == 'https://www.sqlite.org/changes.html'

    (feed_for_update,) = reader._storage.get_feeds_for_update(url=FULL_URL)
    assert feed_for_update.http_etag == 'm6008d7aes58501'
    assert feed_for_update.http_last_modified == 'Thu, 21 Jan 2021 01:23:58 +0000'

    entries = list(reader.get_entries())
    entry_data = [(e.id, e.updated, e.title, e.link, e.summary) for e in entries]
    assert entry_data == [
        (
            '2021-01-20 (3.34.1)',
            datetime(2021, 1, 20, 0, 0),
            '2021-01-20 (3.34.1)',
            'https://www.sqlite.org/changes.html#version_3_34_1',
            '<p></p><ol class="lessindent">\n<li>Fix a potential use-after-free bug.\n</li></ol>\n',
        ),
        (
            '2020-12-01 (3.34.0)',
            datetime(2020, 12, 1, 0, 0),
            '2020-12-01 (3.34.0)',
            'https://www.sqlite.org/changes.html#version_3_34_0',
            '<p>\nAdded the <a href="c3ref/txn_state.html">sqlite3_txn_state()</a> interface.\n</p>\n',
        ),
        (
            '2000-05-30',
            datetime(2000, 5, 30, 0, 0),
            '2000-05-30',
            'https://www.sqlite.org/changes.html',
            '\nAdded the <b>LIKE</b> operator.\n',
        ),
        (
            '2000-05-29',
            datetime(2000, 5, 29, 0, 0),
            '2000-05-29',
            'https://www.sqlite.org/changes.html',
            '\nInitial Public Release of Alpha code\n\n\n',
        ),
    ]
