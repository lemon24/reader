from collections import namedtuple


Feed = namedtuple('Feed', 'url title link updated')

Entry = namedtuple('Entry', 'id title link updated published summary content enclosures read')

