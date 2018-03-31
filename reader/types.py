from collections import namedtuple


Feed = namedtuple('Feed', 'url updated title link user_title')

Entry = namedtuple('Entry', 'id updated title link published summary content enclosures read')

