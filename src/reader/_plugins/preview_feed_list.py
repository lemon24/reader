"""
preview_feed_list
~~~~~~~~~~~~~~~~~

If the feed to be previewed is not actually a feed,
show a list of feeds linked from that URL (if any).

This plugin needs additional dependencies, use the ``preview-feed-list`` extra
to install them:

.. code-block:: bash

    pip install reader[preview-feed-list]

To load::

    READER_APP_PLUGIN='reader._plugins.preview_feed_list:init' \\
    python -m reader serve

Implemented for https://github.com/lemon24/reader/issues/150.

"""
import urllib.parse

import bs4
import requests
from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

import reader
from reader._app import get_reader


blueprint = Blueprint('preview_feed_list', __name__, template_folder='templates')


@blueprint.route('/preview-feed-list')
def feed_list():
    url = request.args['url']

    session = get_reader()._parser.make_session()

    try:
        response = session.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        # TODO: maybe handle this with flash + 404 (and let the handler show the message)
        return render_template('preview_feed_list.html', url=url, errors=[str(e)])

    soup = bs4.BeautifulSoup(response.content)
    alternates = []
    for element in soup.select('link[rel=alternate]'):
        attrs = dict(element.attrs)
        if 'href' not in attrs:
            continue
        if not any(t in attrs.get('type', '').lower() for t in ('rss', 'atom')):
            continue

        # this may not work correctly for relative paths, e.g. should
        # http://example.com/foo + bar.xml result in
        # http://example.com/bar.xml (now) or
        # http://example.com/foo/bar.xml?
        attrs['href'] = urllib.parse.urljoin(url, attrs['href'])
        alternates.append(attrs)

    return render_template('preview_feed_list.html', url=url, alternates=alternates)


@blueprint.app_errorhandler(reader.ParseError)
def handle_parse_error_i_guess(error):
    if request.url_rule.endpoint != 'reader.preview':
        raise error

    # TODO: we should check if we got a requests exception, and not redirect then
    # we can't reuse the text of the original response, because parser is using streaming=True;
    # TODO: maybe we should still expose the response on the exception, we could at least reuse the status code
    # TODO: ParseError should be more specific, it should be clear if retrieving or parsing failed

    return redirect(url_for('preview_feed_list.feed_list', url=error.url))


def init(app):
    app.register_blueprint(blueprint)
