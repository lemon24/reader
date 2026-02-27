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


_LOG_HEADERS = ['Server', 'X-Powered-By']

log = logging.getLogger(__name__)


def _ua_fallback_response_hook(response):
    """httpx response hook: retry 403 responses with feedparser User-Agent.
    
    Args:
        response: The httpx.Response object.
        
    Note:
        Sets response.next_request to trigger a retry with modified headers.
    """
    if response.status_code != 403:
        return

    request = response.request
    ua = request.headers.get('User-Agent')
    if not ua:  # pragma: no cover
        return

    # lazy import (https://github.com/lemon24/reader/issues/297)
    from .._parser.feedparser import feedparser

    ua_prefix = feedparser.USER_AGENT.partition(" ")[0]
    
    # Create a new request with modified User-Agent
    retry_request = request.copy()
    retry_request.headers['User-Agent'] = f'{ua_prefix} {ua}'

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

    # Trigger retry by setting next_request
    response.next_request = retry_request


def init_reader(reader):
    reader._parser.session_factory.response_hooks.append(_ua_fallback_response_hook)
