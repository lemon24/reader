from datetime import datetime

import pytest
import requests
import wsgiadapter
import mechanicalsoup

from reader import Reader
from reader.app import app

from fakeparser import Parser


@pytest.mark.slow
def test_app(tmpdir):
    db_path = str(tmpdir.join('db.sqlite'))

    parser = Parser()
    feed = parser.feed(1, datetime(2010, 1, 1))
    entry = parser.entry(1, 1, datetime(2010, 1, 1))

    reader = Reader(db_path)
    reader._parse = parser

    reader.add_feed(feed.url)
    reader.update_feeds()

    app.config['READER_DB'] = db_path

    session = requests.Session()
    session.mount('http://app/', wsgiadapter.WSGIAdapter(app))
    browser = mechanicalsoup.StatefulBrowser(session)
    browser.open('http://app/')

    assert len(browser.get_current_page().select('form.entry')) == 1

    form = browser.select_form('form.entry')
    response = browser.submit_selected(form.form.find('button', text='mark as read'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('form.entry')) == 0

    response = browser.follow_link(browser.find_link(text='read'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('form.entry')) == 1

    form = browser.select_form('form.entry')
    response = browser.submit_selected(form.form.find('button', text='mark as unread'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('form.entry')) == 0

    response = browser.follow_link(browser.find_link(text='unread'))
    assert response.status_code == 200
    assert len(browser.get_current_page().select('form.entry')) == 1

