"""
reader.ua_fallback
~~~~~~~~~~~~~~~~~~

Retry feed requests that get ``403 Forbidden``
with a different user agent.

Sometimes, servers blocks requests coming from *reader*
based on the user agent.
This plugin retries the request with feedparser's user agent,
which seems to be more widely accepted.

Servers/CDNs known to not accept the *reader* UA: Cloudflare, WP Engine.

.. todo::

    Maybe cache if the fallback is needed as reader metadata,
    and change the UA on the first request instead of retrying.

..
    Implemented for https://github.com/lemon24/reader/issues/181

"""
import logging

import feedparser

_LOG_HEADERS = ['Server', 'X-Powered-By']
_FEEDPARSER_UA_PREFIX = feedparser.USER_AGENT.partition(" ")[0]

log = logging.getLogger(__name__)


def _ua_fallback_response_hook(session, response, request, **kwargs):
    if not response.status_code == 403:
        return None

    ua = request.headers.get('User-Agent', session.headers.get('User-Agent'))
    if not ua:  # pragma: no cover
        return None

    request.headers['User-Agent'] = f'{_FEEDPARSER_UA_PREFIX} {ua}'

    log_headers = {
        h: response.headers[h] for h in _LOG_HEADERS if h in response.headers
    }
    log.info(
        "%s: got status code %i, "
        "retrying with feedparser User-Agent; "
        "relevant response headers: %s",
        request.url,
        response.status_code,
        log_headers,
    )

    return request


def init_reader(reader):
    reader._parser.session_hooks.response.append(_ua_fallback_response_hook)
