import sys

import pytest
import requests
import wsgiadapter

from reader._app import create_app
from reader._config import make_reader_config
from reader._config import make_reader_from_config
from utils import utc_datetime as datetime


# mechanicalsoup depends on lxml, but we don't have that everywhere.
try:
    import mechanicalsoup
except ImportError:
    pass

pytestmark = [pytest.mark.requires_lxml, pytest.mark.apptest]


def make_app(config):
    return create_app(make_reader_config(config))


def make_browser(app):
    session = requests.Session()
    session.mount('http://app/', WSGIAdapter(app))
    browser = mechanicalsoup.StatefulBrowser(session)
    return browser


class WSGIAdapter(wsgiadapter.WSGIAdapter):
    """Workaround for https://github.com/seanbrant/requests-wsgi-adapter/issues/23."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        original_app = self.app

        def new_app(environ, start_response):
            environ['CONTENT_LENGTH'] = str(environ['CONTENT_LENGTH'])
            return original_app(environ, start_response)

        self.app = new_app


@pytest.fixture
def app(db_path):
    return make_app({'reader': {'url': db_path}})


@pytest.fixture
def browser(app):
    return make_browser(app)


@pytest.mark.slow
def test_mark_as_read_unread(db_path, make_reader, parser, browser):
    reader = make_reader(db_path)

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    browser.open('http://app/')
    assert len(browser.get_current_page().select('.entry')) == 1

    form = browser.select_form('.entry form.action-mark-as-read')
    response = browser.submit_selected(form.form.find('button', string='mark as read'))

    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 0

    response = browser.follow_link(browser.find_link(string='read'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 1

    form = browser.select_form('.entry form.action-mark-as-unread')
    response = browser.submit_selected(
        form.form.find('button', string='mark as unread')
    )
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 0

    response = browser.follow_link(browser.find_link(string='unread'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 1


@pytest.mark.slow
def test_mark_all_as_read_unread(db_path, make_reader, parser, browser):
    reader = make_reader(db_path)

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    browser.open('http://app/', params={'feed': feed.url})
    assert len(browser.get_current_page().select('.entry')) == 1

    form = browser.select_form('#update-entries form.action-mark-all-as-read')
    form.set_checkbox({'really-mark-all-as-read': True})
    response = browser.submit_selected(
        form.form.find('button', string='mark all as read')
    )
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 0

    response = browser.follow_link(browser.find_link(string='read'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 1

    form = browser.select_form('#update-entries form.action-mark-all-as-unread')
    form.set_checkbox({'really-mark-all-as-unread': True})
    response = browser.submit_selected(
        form.form.find('button', string='mark all as unread')
    )
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 0

    response = browser.follow_link(browser.find_link(string='unread'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 1


@pytest.mark.slow
def test_add_delete_feed(db_path, browser, parser, app, monkeypatch):
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    app.reader._parser = parser

    def app_make_reader(**kwargs):
        reader = make_reader_from_config(**kwargs)
        reader._parser = parser
        return reader

    # this is brittle, it may break if we change how we use make_reader in app
    monkeypatch.setattr('reader._config.make_reader_from_config', app_make_reader)

    reader = app_make_reader(url=db_path)

    browser.open('http://app/')
    response = browser.follow_link(browser.find_link(string='feeds'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.feed')) == 0

    # go to the preview page
    form = browser.select_form('#top-bar form')
    form.input({'url': feed.url})
    response = browser.submit_selected(form.form.find('button', string='add feed'))
    assert response.status_code == 200
    assert (
        browser.get_current_page().select('title')[0].text
        == 'Preview for ' + feed.title
    )
    assert len(browser.get_current_page().select('.entry')) == 1

    # actually add the feed
    form = browser.select_form('form.action-add-feed')
    response = browser.submit_selected(form.form.find('button', string='add feed'))

    # we should be at the feed page, via a redirect
    assert response.status_code == 200
    assert response.url == 'http://app/?feed=' + feed.url
    assert response.history[-1].status_code == 302

    assert len(browser.get_current_page().select('.entry')) == 0

    reader.update_feeds()

    browser.refresh()
    assert len(browser.get_current_page().select('.entry')) == 1

    response = browser.follow_link(browser.find_link(string='feeds'))
    assert response.status_code == 200

    feed_link = browser.find_link(string=feed.title)

    form = browser.select_form('.feed form.action-delete-feed')
    form.set_checkbox({'really-delete-feed': True})
    response = browser.submit_selected(form.form.find('button', string='delete feed'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.feed')) == 0

    response = browser.follow_link(browser.find_link(string='entries'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('.entry')) == 0

    response = browser.follow_link(feed_link)
    assert response.status_code == 404


@pytest.mark.slow
def test_delete_feed_from_entries_page_redirects(db_path, make_reader, parser, browser):
    reader = make_reader(db_path)

    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader.add_feed(feed.url)
    reader.update_feeds()

    browser.open('http://app/', params={'feed': feed.url})
    form = browser.select_form('#update-entries form.action-delete-feed')
    form.set_checkbox({'really-delete-feed': True})
    response = browser.submit_selected(form.form.find('button', string='delete feed'))
    assert response.status_code == 200
    assert browser.get_url() == 'http://app/'
    assert len(browser.get_current_page().select('.entry')) == 0


@pytest.mark.slow
def test_limit(db_path, make_reader, parser, browser):
    reader = make_reader(db_path)

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    two = parser.entry(1, 2, datetime(2010, 1, 2))

    reader.add_feed(feed.url)
    reader.update_feeds()

    browser.open('http://app/')
    entries = browser.get_current_page().select('.entry')
    assert len(entries) == 2
    assert '#2' in str(entries[0])
    assert '#1' in str(entries[1])

    browser.open('http://app/', params={'limit': 1})
    entries = browser.get_current_page().select('.entry')
    assert len(entries) == 1
    assert '#2' in str(entries[0])


@pytest.mark.slow
def test_search(db_path, make_reader, parser, browser):
    reader = make_reader(db_path)

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='one')
    two = parser.entry(1, 2, datetime(2010, 1, 2), title='two')

    reader.add_feed(feed.url)
    reader.update_feeds()
    reader.update_search()

    browser.open('http://app/', params={'q': 'feed'})
    entries = browser.get_current_page().select('.entry')
    assert len(entries) == 2
    assert 'one' in str(entries[0]) or 'one' in str(entries[1])
    assert 'two' in str(entries[0]) or 'two' in str(entries[1])

    browser.open('http://app/', params={'q': 'one'})
    entries = browser.get_current_page().select('.entry')
    assert len(entries) == 1
    assert 'one' in str(entries[0])
