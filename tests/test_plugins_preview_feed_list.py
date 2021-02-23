import pytest

from reader._plugins.preview_feed_list import get_alternates

pytestmark = pytest.mark.filterwarnings("ignore:No parser was explicitly specified")


MAIN_IN = """\
<link rel=alternate type=rss href=1 />
<link rel=alternate title=rss href=2 />
<link rel=alternate type=nope title=feed href=3 />
<link rel=alternate href=some/rss.xml />
<meta name=alternate type=whatever/atom href=4 />
<link rel=alternative type=feed href=5 />

<link rel=alternate title=nope href=nope />
<link rel=alternate title=also-nope />

"""

MAIN_OUT = [
    {'href': '1', 'type': 'rss'},
    {'href': '2', 'title': 'rss'},
    {'href': '3', 'title': 'feed', 'type': 'nope'},
    {'href': 'some/rss.xml'},
    {'href': '4', 'type': 'whatever/atom'},
    {'href': '5', 'type': 'feed'},
]

FALLBACK_IN = """\
<a href=1>rss</a>
<a href=some/atom.xml>text</a>
<a href=2 title=my-feed></a>
<a href=3 title=feed-title>feed-text</a>
<a href=4 type=whatever/rss> my  <span>text  </span> </a>

<a>feed nope</a>
<a href=nope>also-nope</a>

"""

FALLBACK_OUT = [
    {'href': '1', 'title': 'rss'},
    {'href': 'some/atom.xml', 'title': 'text'},
    {'href': '2', 'title': 'my-feed'},
    {'href': '3', 'title': 'feed-text'},
    {'href': '4', 'title': 'my text', 'type': 'whatever/rss'},
]


def setify(l):
    return frozenset(frozenset(d.items()) for d in l)


@pytest.mark.parametrize(
    'input, expected',
    [
        (MAIN_IN, MAIN_OUT),
        (FALLBACK_IN, FALLBACK_OUT),
        (MAIN_IN + FALLBACK_IN, MAIN_OUT),
    ],
    ids=['main', 'fallback', 'main+fallback'],
)
def test_get_alternates(input, expected):
    assert setify(get_alternates(input, '')) == setify(expected)


def test_get_alternates_relative():
    assert get_alternates("<link rel=alternate type=rss href=1 />", "url/") == [
        {'type': 'rss', 'href': 'url/1'}
    ]
