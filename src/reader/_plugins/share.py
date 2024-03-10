"""
share
~~~~~

Add social sharing links at the end of the entry page.

To load::

    READER_APP_PLUGIN='reader._plugins.share:init' \\
    python -m reader serve

"""

from urllib.parse import quote
from urllib.parse import urlparse


TEMPLATES = {
    'Twitter': "https://twitter.com/share?text={title}&url={url}",
    'HN': "https://news.ycombinator.com/submitlink?u={url}&t={title}",
    'Reddit': "https://www.reddit.com/submit?url={url}&title={title}",
}


def percent_encode(s, encoding="ascii"):
    return ''.join([f'%{b:0>2x}' for b in s.encode(encoding)])


def share(entry):
    if not entry.link:
        return
    link = quote(entry.link)
    title = quote(entry.title or '')

    for name, template in TEMPLATES.items():
        url = template.format(url=link, title=title)

        # prevent ad blockers from messing with these
        url = urlparse(url)
        url = url._replace(
            netloc=percent_encode(url.netloc),
            path='/'.join(
                percent_encode(c) if 'share' in c.lower() else c
                for c in url.path.split('/')
            ),
        )
        url = url.geturl()

        yield name, url


def init(app):
    app.reader_additional_links.append(share)
