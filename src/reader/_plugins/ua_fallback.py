"""
ua_fallback
~~~~~~~~~~~

Sometimes, servers blocks requests coming from *reader*,
based on its user agent.

This plugin retries the request with feedparser's user agent string,
which seems to be more widely accepted.

Servers/CDNs known to not accept the *reader* UA: Cloudflare, WP Engine.

To load::

    READER_PLUGIN='reader._plugins.ua_fallback:init' \\
    python -m reader update -v

Implemented for https://github.com/lemon24/reader/issues/181.

.. todo::

    Maybe cache if the fallback is needed as reader metadata,
    and change the UA on the first request instead of retrying.

"""
import logging

import feedparser

log = logging.getLogger(__name__)

LOG_HEADERS = ['Server', 'X-Powered-By']


def ua_fallback(session, response, request, **kwargs):
    if not response.status_code == 403:
        return None

    log_headers = {h: response.headers[h] for h in LOG_HEADERS if h in response.headers}
    log.info(
        "ua_fallback: %s: got status code %i, "
        "retrying with feedparser User-Agent; "
        "relevant response headers: %s",
        request.url,
        response.status_code,
        log_headers,
    )

    ua = request.headers.get('User-Agent', session.headers.get('User-Agent'))
    if not ua:
        return None

    feedparser_ua = feedparser.USER_AGENT.partition(" ")[0]
    request.headers['User-Agent'] = f'{feedparser_ua} {ua}'

    return request


def init(reader):
    reader._parser.session_hooks.response.append(ua_fallback)
