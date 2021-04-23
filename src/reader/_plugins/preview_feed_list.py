"""
preview_feed_list
~~~~~~~~~~~~~~~~~

If the feed to be previewed is not actually a feed,
show a list of feeds linked from that URL (if any).

This plugin needs additional dependencies, use the ``unstable-plugins`` extra
to install them:

.. code-block:: bash

    pip install reader[unstable-plugins]

To load::

    READER_APP_PLUGIN='reader._plugins.preview_feed_list:init' \\
    python -m reader serve

Implemented for https://github.com/lemon24/reader/issues/150.

"""
import urllib.parse
import warnings

import bs4
import requests
from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from reader._app import get_reader
from reader._app import got_preview_parse_error


blueprint = Blueprint('preview_feed_list', __name__, template_folder='templates')


ATTRS = ['type', 'href', 'title', 'text']
MARKERS = ['rss', 'atom', 'feed']

SELECTORS = [
    'link[href][rel=alternate], meta[href][name=alternate], link[href][rel=alternative]',
    # fallback
    'a[href]',
]


warnings.filterwarnings(
    'ignore',
    message='No parser was explicitly specified',
    module='reader._plugins.preview_feed_list',
)


def get_alternates(content, url):
    soup = bs4.BeautifulSoup(content)
    for selector in SELECTORS:
        alternates = list(_get_alternates(soup, url, selector))
        if alternates:
            return alternates
    return []


def _get_alternates(soup, url, selector):
    for element in soup.select(selector):
        attrs = dict(element.attrs)

        href = attrs.get('href')
        if not href:
            continue

        text = ' '.join(element.stripped_strings)
        if text:
            attrs['text'] = text

        for attr in ATTRS:
            value = attrs.get(attr, '').lower()
            if any(marker in value for marker in MARKERS):
                break
        else:
            continue

        # this may not work correctly for relative paths, e.g. should
        # http://example.com/foo + bar.xml result in
        # http://example.com/bar.xml (now) or
        # http://example.com/foo/bar.xml?
        rv = {'href': urllib.parse.urljoin(url, attrs['href'])}

        if 'type' in attrs:
            rv['type'] = attrs['type']
        if 'text' in attrs:
            rv['title'] = attrs['text']
        elif 'title' in attrs:
            rv['title'] = attrs['title']

        yield rv


@blueprint.route('/preview-feed-list')
def feed_list():
    url = request.args['url']

    session = get_reader()._parser.make_session()

    # TODO: url may not actually be an http URL; now we get "error: Invalid URL 'file.xml': No schema supplied. ..."
    # if https://github.com/lemon24/reader/issues/155#issuecomment-647048623 gets implemented,
    # we should delegate to the parser "give me the content of this URL"

    try:
        response = session.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        # TODO: maybe handle this with flash + 404 (and let the handler show the message)
        return render_template('preview_feed_list.html', url=url, errors=[str(e)])

    alternates = list(get_alternates(response.content, url))

    return render_template('preview_feed_list.html', url=url, alternates=alternates)


class GotPreviewParseError(Exception):
    """Signaling exception used to intercept /preview ParseError"""


@got_preview_parse_error.connect
def raise_got_preview_parse_error(error):
    # TODO: it would be nice if we could distinguish http-related parse errors from other parse errors
    if error.url.startswith('http:') or error.url.startswith('https:'):
        raise GotPreviewParseError() from error


@blueprint.app_errorhandler(GotPreviewParseError)
def handle_parse_error_i_guess(error):
    parse_error = error.__cause__

    if request.url_rule.endpoint != 'reader.preview':
        raise error

    # TODO: we should check if we got a requests exception, and not redirect then
    # we can't reuse the text of the original response, because parser is using streaming=True;
    # TODO: maybe we should still expose the response on the exception, we could at least reuse the status code
    # TODO: ParseError should be more specific, it should be clear if retrieving or parsing failed

    return redirect(url_for('preview_feed_list.feed_list', url=parse_error.url))


def init(app):
    app.register_blueprint(blueprint)
