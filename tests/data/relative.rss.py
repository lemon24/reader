import datetime

from reader import Feed, Entry, Content, Enclosure


feed = Feed(
    url='{}relative.rss'.format(url_base),
    link='{}file.html'.format(rel_base),
)

entries = [
     Entry(
        id='7bd204c6-1655-4c27-aeee-53f933c5395f',
        updated=None,
        link='{}blog/post/1'.format(rel_base),
        enclosures=(
            # for RSS feedparser doesn't make relative links absolute
            # (it does for Atom)
            Enclosure(href='enclosure?q=a#fragment'),
        ),
    ),
]

