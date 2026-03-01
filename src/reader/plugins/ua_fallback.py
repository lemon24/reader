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


log = logging.getLogger(__name__)


def init_reader(reader):
    """Initialize the UA fallback plugin.
    
    This sets up a UAFallbackAuth handler that will automatically retry
    403 responses with feedparser's User-Agent.
    """
    # lazy import to avoid circular dependency
    from .._parser.feedparser import feedparser
    from .._parser.requests import UAFallbackAuth
    
    # Create and register the auth handler
    reader._parser.session_factory.custom_auth = UAFallbackAuth(
        fallback_ua=feedparser.USER_AGENT
    )

