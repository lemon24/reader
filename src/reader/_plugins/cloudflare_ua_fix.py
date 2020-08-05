"""
cloudflare_ua_fix
~~~~~~~~~~~~~~~~~

Cloudflare (sometimes) blocks requests coming from *reader*,
based on its user agent.

This plugin is a workaround until *reader* becomes a verified bot.
It retries requests blocked by Cloudflare with feedparser's user agent string,
which seems to already be verified.

To load::

    READER_PLUGIN='reader._plugins.cloudflare_ua_fix:init' \\
    python -m reader update -v

Implemented for https://github.com/lemon24/reader/issues/181.

"""
import feedparser


def cf_ua_fix(session, response, request, **kwargs):
    if not response.status_code == 403:
        return None
    if not response.headers.get('Server', '').lower().startswith('cloudflare'):
        return None

    ua = request.headers.get('User-Agent', session.headers.get('User-Agent'))
    if not ua:
        return None

    feedparser_ua = feedparser.USER_AGENT.partition(" ")[0]
    request.headers['User-Agent'] = f'{feedparser_ua} {ua}'

    return request


def init(reader):
    reader._parser.session_hooks.response.append(cf_ua_fix)
