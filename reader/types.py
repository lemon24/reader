from collections import namedtuple


Feed = namedtuple('Feed', 'url updated title link user_title')
Feed.__new__.__defaults__ = (None, None, None, None)

Entry = namedtuple('Entry', 'id updated title link published summary content enclosures read')
Entry.__new__.__defaults__ = (None, None, None, None, None, None, False)

