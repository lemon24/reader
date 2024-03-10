import pytest

from reader._plugins.preview_feed_list import get_alternates
from test_app import make_app
from test_app import make_browser
from test_app import pytestmark


pytestmark = list(pytestmark)
pytestmark.append(
    pytest.mark.filterwarnings("ignore:No parser was explicitly specified")
)


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


@pytest.mark.slow
@pytest.mark.requires_lxml
def test_plugin(db_path, requests_mock):
    app = make_app(
        {
            'reader': {'url': db_path},
            'app': {'plugins': {'reader._plugins.preview_feed_list:init': None}},
        }
    )
    browser = make_browser(app)

    feed_url = 'http://example.com/'

    requests_mock.real_http = True
    requests_mock.get(
        feed_url,
        content=b"""
        <link
            rel="alternate"
            type="application/atom+xml"
            title="example.com news"
            href="http://example.com/feed.xml"
        />
        """,
    )

    browser.open('http://app/')
    form = browser.select_form('#top-bar form')
    form.input({'url': feed_url})
    response = browser.submit_selected(form.form.find('button', text='add feed'))
    assert response.status_code == 200

    page = browser.get_current_page()
    assert page.select('title')[0].text == 'Feeds for ' + feed_url

    items = page.select('.preview-feed-list li')
    assert len(items) == 1, items
    item = items[0]
    assert item.get_text(' ', strip=True) == "example.com news application/atom+xml"
    item.select_one('a').attrs[
        'href'
    ] == '/preview?url=http%3A%2F%2Fexample.com%2Ffeed.xml'
