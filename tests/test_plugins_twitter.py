import json
from copy import deepcopy

import pytest
from tweepy import Media
from tweepy import Poll
from tweepy import Response
from tweepy import Tweet
from tweepy import User
from utils import naive_datetime
from utils import utc_datetime
from utils import utc_datetime as datetime

from reader import Entry
from reader import Feed
from reader import UpdatedFeed
from reader._plugins import twitter
from reader._plugins.twitter import Conversation
from reader._plugins.twitter import Etag
from reader._plugins.twitter import UserFile
from reader._plugins.twitter import UserURL


"""
# testing strategy

## with_replies == False

mock retrieve_user_responses()
* [x] check feed title
* [x] entry titleentry json
* [x] entry published/updated
* [x] assert etag
* [x] assert recent_conversations

* [x] almost end-to-end: check entry html (plain)

* [x] zero tweets
* update
  * assert render html called with data
  * assert entry json
  * [x] two tweets, one convo; parametrize by:
    * content: [x] plain, [x] media, [x] poll, [x] quote, [x] retweet
    * order: [x] first plain, second fancy, [x] first fancy, second plain
  * [x] two convos, one tweet each (both plain)
    * sequence: [x] 2+0, [x] 1+1+0
  * [x] two tweets, across 2 pages
  * [ ] resources for quoted/retweeted are included
  * [ ] entry title has entities expanded
  * missing [ ] plain, [x] quote, [x] retweet

render: conversation json -> html

* two tweets
    * [x] plain, [x] media, [x] poll, [x] quote, [x] retweet
    * first fancy, second plain
    * missing [ ] plain, [x] quote, [x] retweet
* [ ] stray reply should not show up in html even if in convo json

## with_replies == True

TODO

"""


def make_response(data=(), users=None, *, media=None, polls=None, tweets=None):
    includes = {}
    if users:
        includes['users'] = list(map(User, users))
    if media:
        includes['media'] = list(map(Media, media))
    if tweets:
        includes['tweets'] = list(map(Tweet, tweets))
    if polls:
        includes['polls'] = list(map(Poll, polls))

    return Response(
        data=list(map(Tweet, data)),
        includes=includes,
        errors=[],
        meta={},
    )


@pytest.fixture
def reader(make_reader):
    reader = make_reader(':memory:', plugins=[twitter.init_reader])
    reader.add_feed('https://twitter.com/user')
    reader.set_tag((), '.reader.twitter', {'token': 'abcd'})
    return reader


@pytest.fixture
def update_with(reader, monkeypatch):
    def update(data=None, users=None, *, pages=None, **kwargs):
        if bool(data or users or kwargs) + bool(pages) != 1:
            raise ValueError("either update_with(data, users, ...) or data(pages)")

        if not pages:
            user = users[0]
            responses = [make_response(data, users, **kwargs)]
        else:
            user = pages[0]['users'][0]
            responses = [make_response(**page) for page in pages]

        def retrieve_user_responses(self, url, etag):
            update.url, update.etag = url, etag
            return User(user), responses

        monkeypatch.setattr(
            twitter.Twitter, 'retrieve_user_responses', retrieve_user_responses
        )
        return reader.update_feed('https://twitter.com/user')

    return update


TWEET_0 = {
    'conversation_id': '2100',
    'created_at': '2100-01-01T00:00:00.000Z',
    'text': "one",
    'id': '2100',
    'author_id': '1000',
}
TWEET_1 = {
    'conversation_id': '2100',
    'referenced_tweets': [{'type': 'replied_to', 'id': '2100'}],
    'created_at': '2101-01-01T00:00:00.000Z',
    'text': "two",
    'id': '2101',
    'author_id': '1000',
}
TWEET_2 = {
    'conversation_id': '2100',
    'referenced_tweets': [{'type': 'replied_to', 'id': '2101'}],
    'created_at': '2102-01-01T00:00:00.000Z',
    'text': "three",
    'id': '2102',
    'author_id': '1000',
}
USER = {'username': 'user', 'id': '1000', 'name': 'name'}


def test_retrieve_user_responses_args(reader, update_with):
    reader._now = lambda: naive_datetime(2102, 1, 1)

    update_with([TWEET_0, TWEET_1], [USER])

    assert update_with.url == UserURL('user', with_replies=False)
    assert update_with.etag == Etag(None, bearer_token='abcd')

    reader.set_tag((), '.reader.twitter', {'token': 'efgh'})
    update_with([TWEET_2], [USER])

    assert update_with.url == UserURL('user', with_replies=False)
    assert update_with.etag == Etag(2101, bearer_token='efgh')


def test_etag_recent_conversations(reader, update_with):
    tweet_0 = deepcopy(TWEET_0)
    tweet_0.update(id='0', conversation_id='0', created_at='2100-01-01T00:00:00.000Z')
    tweet_1 = deepcopy(TWEET_0)
    tweet_1.update(id='1', conversation_id='1', created_at='2100-01-20T00:00:00.000Z')
    tweet_2 = deepcopy(TWEET_0)
    tweet_2.update(id='2', conversation_id='2', created_at='2100-01-20T00:00:00.000Z')

    reader._now = lambda: naive_datetime(2100, 1, 25)
    update_with([tweet_1, tweet_0, tweet_2], [USER])
    assert update_with.etag.recent_conversations == ()

    reader._now = lambda: naive_datetime(2100, 2, 15)
    update_with([], [USER])
    assert update_with.etag.recent_conversations == (1, 2)
    update_with([TWEET_2], [USER])
    assert update_with.etag.recent_conversations == (1, 2)

    reader._now = lambda: naive_datetime(2100, 3, 1)
    update_with([], [USER])
    assert update_with.etag.recent_conversations == ()


def test_update_result(reader, update_with):
    rv = update_with([], [USER])
    assert rv == None

    rv = update_with([TWEET_0, TWEET_1], [USER])
    assert rv == UpdatedFeed('https://twitter.com/user', new=1, modified=0)

    rv = update_with([TWEET_2], [USER])
    assert rv == UpdatedFeed('https://twitter.com/user', new=0, modified=1)


def test_entry_data_attribs(reader, update_with):
    def get_entry():
        (entry,) = reader.get_entries()
        return entry._replace(feed=None, content=(), added=None, last_updated=None)

    expected = Entry(
        id='2100',
        updated=datetime(2101, 1, 1),
        title='one',
        link='https://twitter.com/user/status/2100',
        author='@user',
        published=datetime(2100, 1, 1),
        summary=None,
        enclosures=(),
        added_by='feed',
        original_feed_url='https://twitter.com/user',
    )

    update_with([TWEET_0, TWEET_1], [USER])
    assert get_entry() == expected

    update_with([TWEET_2], [USER])
    assert get_entry() == expected._replace(updated=datetime(2102, 1, 1))


def test_feed_attribs(reader, update_with):
    def get_feed():
        (feed,) = reader.get_feeds()
        return feed._replace(added=None, last_updated=None)

    update_with([], [USER])
    assert get_feed() == Feed(url='https://twitter.com/user')

    expected = Feed(
        url='https://twitter.com/user',
        updated=None,
        title='name (@user)',
        link=None,
        author='@user',
        subtitle=None,
        version='twitter',
    )

    update_with([TWEET_0, TWEET_1], [USER])
    assert get_feed() == expected

    user = deepcopy(USER)
    user.update(
        {
            'name': 'newname',
            'verified': True,
            'url': 'https://t.co/url',
            'description': 'one https://t.co/example two',
            'profile_image_url': 'https://pbs.twimg.com/profile/0.png',
            'entities': {
                'url': {
                    'urls': [
                        {
                            'start': 0,
                            'end': 16,
                            'url': 'https://t.co/url',
                            'expanded_url': 'https://url.org',
                            'display_url': 'url.org',
                        }
                    ]
                },
                'description': {
                    'urls': [
                        {
                            'start': 4,
                            'end': 24,
                            'url': 'https://t.co/example',
                            'expanded_url': 'http://example.com',
                            'display_url': 'example.com',
                        }
                    ]
                },
            },
        }
    )

    update_with([TWEET_2], [user])
    assert get_feed() == expected._replace(
        title='newname (@user) ✓',
        link='https://t.co/url',
        subtitle='one https://t.co/example two',
    )


def update_data_plain(tweet, page, expected_json):
    pass


def update_data_plain_missing_one_of_two(tweet, page, expected_json):
    page['data'] = [t for t in page['data'] if t['id'] != '2100']
    del expected_json['tweets']['2100']


def update_data_plain_missing_two_of_three(tweet, page, expected_json):
    three = deepcopy(TWEET_2)
    page['data'] = [t for t in page['data'] if t['id'] != '2101'] + [three]
    del expected_json['tweets']['2101']
    expected_json['tweets']['2102'] = three


def update_data_media(tweet, page, expected_json):
    photo = {'media_key': '3_3000', 'type': 'photo', 'url': './photo.jpg'}
    video = {
        'media_key': '3_3001',
        'type': 'video',
        'preview_image_url': './video.webp',
    }
    tweet.setdefault('attachments', {}).setdefault('media_keys', []).extend(
        ['3_3000', '3_3001']
    )
    page.setdefault('media', []).extend([photo, video])
    expected_json['media']['3_3000'] = photo
    expected_json['media']['3_3001'] = video


def update_data_poll(tweet, page, expected_json):
    poll = {
        'id': '4000',
        'options': [
            {'position': 1, 'label': "first", 'votes': 123},
            {'position': 2, 'label': "second", 'votes': 321},
        ],
    }

    tweet.setdefault('attachments', {}).setdefault('poll_ids', []).append('4000')
    page.setdefault('polls', []).append(poll)
    expected_json['polls']['4000'] = poll


def update_data_quote(tweet, page, expected_json):
    tweet_quoted = {
        'conversation_id': '2000',
        'created_at': '2000-01-01T00:00:00.000Z',
        'text': "quote",
        'id': '2000',
        'author_id': '1100',
    }
    user_quoted = {'id': '1100', 'username': 'quoteduser', 'name': 'quoted'}

    tweet.setdefault('referenced_tweets', []).append({'type': 'quoted', 'id': '2000'})
    page.setdefault('tweets', []).append(tweet_quoted)
    page.setdefault('users', []).append(user_quoted)

    expected_json['tweets']['2000'] = tweet_quoted
    expected_json['users']['1100'] = user_quoted


def update_data_retweet(tweet, page, expected_json):
    tweet_retweeted = {
        'conversation_id': '2000',
        'created_at': '2000-01-01T00:00:00.000Z',
        'text': "retweet",
        'id': '2000',
        'author_id': '1100',
    }
    user_retweeted = {'id': '1100', 'username': 'retweeteduser', 'name': 'retweeted'}

    tweet.setdefault('referenced_tweets', []).append(
        {'type': 'retweeted', 'id': '2000'}
    )
    page.setdefault('tweets', []).append(tweet_retweeted)
    page.setdefault('users', []).append(user_retweeted)

    expected_json['tweets']['2000'] = tweet_retweeted
    expected_json['users']['1100'] = user_retweeted


def update_data_quote_missing(tweet, page, expected_json):
    update_data_quote(tweet, page, expected_json)
    page['tweets'].pop()
    del expected_json['tweets']['2000']
    del expected_json['users']['1100']


def update_data_retweet_missing(tweet, page, expected_json):
    update_data_retweet(tweet, page, expected_json)
    page['tweets'].pop()
    del expected_json['tweets']['2000']
    del expected_json['users']['1100']


DEFAULT_UPDATE_DATA_FNS = [
    update_data_plain,
    # update_data_plain_missing_one_of_two,
    # update_data_plain_missing_two_of_three,
    update_data_media,
    update_data_poll,
    update_data_quote,
    update_data_quote_missing,
    update_data_retweet,
    update_data_retweet_missing,
]


def with_update_data(fn=None, update_fns=tuple(DEFAULT_UPDATE_DATA_FNS)):
    decorator = pytest.mark.parametrize('update_data', update_fns)
    if fn:
        return decorator(fn)
    return decorator


@pytest.fixture
def render_user_html(monkeypatch):
    original = twitter.render_user_html

    def wrapper(conversation, with_replies):
        wrapper.conversation = conversation
        # for now
        assert with_replies is False
        return original(conversation, with_replies)

    monkeypatch.setattr(twitter, 'render_user_html', wrapper)
    return wrapper


# TODO: should Entry.get_content() do this?


def get_entry_content(entry, mime_type):
    content = [c.value for c in entry.content if c.type == mime_type]
    assert len(content) == 1, entry
    return content[0]


def get_entry_json(entry):
    return json.loads(get_entry_content(entry, 'application/x.twitter+json'))


def get_entry_html(entry):
    return get_entry_content(entry, 'text/html')


def clean_html(html):
    lines = []
    for line in html.splitlines():
        line = line.strip()
        if line:
            lines.append(line)
    return '\n'.join(lines)


def test_update_end_to_end(reader, update_with):
    # ... almost end to end, to make sure everything is called
    tweets = [deepcopy(TWEET_0), deepcopy(TWEET_1)]
    update_with(tweets, [USER])

    (entry,) = reader.get_entries()
    assert get_entry_json(entry) == {
        'id': 2100,
        'tweets': {'2100': tweets[0], '2101': tweets[1]},
        'users': {'1000': USER},
        'media': {},
        'polls': {},
    }
    assert clean_html(get_entry_html(entry)) == clean_html(TWEET_0_HTML + TWEET_1_HTML)


@with_update_data
@pytest.mark.parametrize('index', [0, 1])
def test_update_one_call(reader, update_with, render_user_html, update_data, index):
    tweets = [deepcopy(TWEET_0), deepcopy(TWEET_1)]

    expected_json = {
        'id': 2100,
        'tweets': {'2100': tweets[0], '2101': tweets[1]},
        'users': {'1000': USER},
        'media': {},
        'polls': {},
    }

    page = {'data': list(tweets), 'users': [USER]}
    update_data(tweets[index], page, expected_json)
    update_with(**page)

    assert render_user_html.conversation == Conversation.from_json(expected_json)
    (entry,) = reader.get_entries()
    assert get_entry_json(entry) == expected_json


@with_update_data
@pytest.mark.parametrize('index', [0, 1])
def test_update_two_calls(reader, update_with, render_user_html, update_data, index):
    tweets = [deepcopy(TWEET_0), deepcopy(TWEET_1)]

    expected_json = {
        'id': 2100,
        'tweets': {'2100': tweets[0], '2101': tweets[1]},
        'users': {'1000': USER},
        'media': {},
        'polls': {},
    }

    pages = []
    for tweet in tweets:
        pages.append({'data': [tweet], 'users': [USER]})
    update_data(tweets[index], pages[index], expected_json)
    for page in pages:
        update_with(**page)

    assert render_user_html.conversation == Conversation.from_json(expected_json)
    (entry,) = reader.get_entries()
    assert get_entry_json(entry) == expected_json


@with_update_data
@pytest.mark.parametrize('index', [0, 1])
def test_update_two_responses(
    reader, update_with, render_user_html, update_data, index
):
    tweets = [deepcopy(TWEET_0), deepcopy(TWEET_1)]

    expected_json = {
        'id': 2100,
        'tweets': {'2100': tweets[0], '2101': tweets[1]},
        'users': {'1000': USER},
        'media': {},
        'polls': {},
    }

    pages = []
    for tweet in tweets:
        pages.append({'data': [tweet], 'users': [USER]})
    update_data(tweets[index], pages[index], expected_json)
    update_with(pages=pages)

    assert render_user_html.conversation == Conversation.from_json(expected_json)
    (entry,) = reader.get_entries()
    assert get_entry_json(entry) == expected_json


@with_update_data(
    update_fns=[
        f
        for f in DEFAULT_UPDATE_DATA_FNS
        if f
        not in (
            update_data_plain_missing_one_of_two,
            update_data_plain_missing_two_of_three,
        )
    ]
)
@pytest.mark.parametrize('index', [0, 1])
def test_update_two_entries(reader, update_with, update_data, index):
    tweets = [deepcopy(TWEET_0), deepcopy(TWEET_0)]
    tweets[1].update(id='2200', conversation_id='2200', text="two")

    expected_jsons = [
        {
            'id': 2100,
            'tweets': {'2100': tweets[0]},
            'users': {'1000': USER},
            'media': {},
            'polls': {},
        },
        {
            'id': 2200,
            'tweets': {'2200': tweets[1]},
            'users': {'1000': USER},
            'media': {},
            'polls': {},
        },
    ]

    page = {'data': list(tweets), 'users': [USER]}
    update_data(tweets[index], page, expected_jsons[index])
    update_with(**page)

    actual_jsons = [
        get_entry_json(e) for e in sorted(reader.get_entries(), key=lambda e: e.id)
    ]
    assert actual_jsons == expected_jsons


def update_data_entities(tweet, page, expected_json):
    assert not page
    tweet['text'] = 'interesting article https://t.co/article https://t.co/screenshot'
    tweet['entities'] = {
        'urls': [
            {
                'start': 20,
                'end': 40,
                'url': 'https://t.co/article',
                'expanded_url': 'https://example.com/article',
                'display_url': 'example.com/article',
                'images': [
                    {
                        'url': 'https://pbs.twimg.com/news_img/article?format=jpg&name=orig',
                        'width': 1200,
                        'height': 600,
                    },
                    {
                        'url': 'https://pbs.twimg.com/news_img/article?format=jpg&name=150x150',
                        'width': 150,
                        'height': 150,
                    },
                ],
                'status': 200,
                'title': 'Article Title',
                'description': 'Article description.',
                'unwound_url': 'https://example.com/article',
            },
            {
                'start': 41,
                'end': 64,
                'url': 'https://t.co/screenshot',
                'expanded_url': 'https://twitter.com/user/status/2000/photo/1',
                'display_url': 'pic.twitter.com/screenshot',
                'media_key': '3_3000',
            },
        ]
    }


def update_data_nl2br(tweet, page, expected_json):
    tweet['text'] = "intro:\n\n* one\r\n* two\r* three"


TWEET_0_HTML = """
<div class="tweet">
<p class="top-line">
<a href="https://twitter.com/user" class="name">name</a>
<a href="https://twitter.com/user" class="username">@user</a>
· <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
</p>

<p class="text">one</p>

</div>
"""

TWEET_1_HTML = """
<div class="tweet">
<p class="top-line">
<a href="https://twitter.com/user" class="name">name</a>
<a href="https://twitter.com/user" class="username">@user</a>
· <a href="https://twitter.com/user/status/2101" class="created-at">2101-01-01</a>
</p>

<p class="text">two</p>

</div>
"""

UPDATE_FN_TO_HTML = {
    update_data_plain: TWEET_0_HTML,
    update_data_media: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name">name</a>
        <a href="https://twitter.com/user" class="username">@user</a>
        · <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
        </p>

        <p class="text">one</p>

        <a href="https://twitter.com/user/status/2100">
        <img class="media photo" src="./photo.jpg">
        </a>
        <a href="https://twitter.com/user/status/2100">
        <img class="media video" src="./video.webp">
        </a>

        </div>
        """,
    update_data_poll: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name">name</a>
        <a href="https://twitter.com/user" class="username">@user</a>
        · <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
        </p>

        <p class="text">one</p>

        <ul class="poll">
        <li><span class="label">first</span> <span class="votes">123</span>
        <li><span class="label">second</span> <span class="votes">321</span>
        </ul>

        </div>
        """,
    update_data_quote: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name">name</a>
        <a href="https://twitter.com/user" class="username">@user</a>
        · <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
        </p>

        <p class="text">one</p>

        <div class="tweet tweet-quote">
        <p class="top-line">
        <a href="https://twitter.com/quoteduser" class="name">quoted</a>
        <a href="https://twitter.com/quoteduser" class="username">@quoteduser</a>
        · <a href="https://twitter.com/quoteduser/status/2000" class="created-at">2000-01-01</a>
        </p>

        <p class="text">quote</p>

        </div>
        </div>
        """,
    update_data_quote_missing: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name">name</a>
        <a href="https://twitter.com/user" class="username">@user</a>
        · <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
        </p>

        <p class="text">one</p>

        <div class="tweet tweet-quote">
        <p class="text"><em>[missing tweet object]</em></p>

        </div>
        </div>
        """,
    update_data_retweet: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name-retweeted">name retweeted</a>
        </p>

        <div class="tweet tweet-retweet">
        <p class="top-line">
        <a href="https://twitter.com/retweeteduser" class="name">retweeted</a>
        <a href="https://twitter.com/retweeteduser" class="username">@retweeteduser</a>
        · <a href="https://twitter.com/retweeteduser/status/2000" class="created-at">2000-01-01</a>
        </p>

        <p class="text">retweet</p>

        </div>
        </div>
        """,
    update_data_retweet_missing: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name-retweeted">name retweeted</a>
        </p>

        <div class="tweet tweet-retweet">
        <p class="text"><em>[missing tweet object]</em></p>

        </div>
        </div>
        """,
    update_data_entities: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name">name</a>
        <a href="https://twitter.com/user" class="username">@user</a>
        · <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
        </p>

        <p class="text">interesting article <a href="https://example.com/article" title="Article Title">example.com/article</a> <a href="https://twitter.com/user/status/2000/photo/1">pic.twitter.com/screenshot</a></p>

        </div>
        """,
    update_data_nl2br: """
        <div class="tweet">
        <p class="top-line">
        <a href="https://twitter.com/user" class="name">name</a>
        <a href="https://twitter.com/user" class="username">@user</a>
        · <a href="https://twitter.com/user/status/2100" class="created-at">2100-01-01</a>
        </p>

        <p class="text">intro:<br>
        <br>
        * one<br>
        * two<br>
        * three</p>

        </div>
    """,
}


@with_update_data(update_fns=UPDATE_FN_TO_HTML)
def test_render_user_html(reader, update_with, update_data):
    tweets = [deepcopy(TWEET_0), deepcopy(TWEET_1)]

    expected_json = {
        'id': 2100,
        'tweets': {'2100': tweets[0], '2101': tweets[1]},
        'users': {'1000': USER},
        'media': {},
        'polls': {},
    }

    update_data(tweets[0], {}, expected_json)

    conversation = Conversation.from_json(expected_json)
    actual_html = clean_html(twitter.render_user_html(conversation, False))

    assert actual_html == clean_html(UPDATE_FN_TO_HTML[update_data] + TWEET_1_HTML)


# preliminary tests; to be replaced by the ones above when they're all done


def test_update_with_lots_of_replies(reader, update_with):
    tweet_0 = {
        'created_at': '2022-01-01T00:20:00.000Z',
        'conversation_id': '2000',
        'text': 'one',
        'id': '2000',
        'author_id': '1000',
    }
    tweet_0_1 = {
        'created_at': '2022-01-01T00:21:00.000Z',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2000'}],
        'conversation_id': '2000',
        'text': 'reply to one',
        'id': '2100',
        'author_id': '1100',
    }
    tweet_1 = {
        'created_at': '2022-01-01T00:20:01.000Z',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2000'}],
        'conversation_id': '2000',
        'text': 'two',
        'id': '2001',
        'author_id': '1000',
    }
    tweet_1_0 = {
        'created_at': '2022-01-01T00:21:01.000Z',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2001'}],
        'conversation_id': '2000',
        'text': 'reply to two',
        'id': '2101',
        'author_id': '1100',
    }
    tweet_1_0_0 = {
        'created_at': '2022-01-01T00:22:00.000Z',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2101'}],
        'conversation_id': '2000',
        'text': 'first reply to reply',
        'id': '2200',
        'author_id': '1100',
    }
    tweet_1_0_1 = {
        'created_at': '2022-01-01T00:22:01.000Z',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2101'}],
        'conversation_id': '2000',
        'text': 'second reply to reply',
        'id': '2201',
        'author_id': '1000',
    }
    tweet_2 = {
        'created_at': '2022-01-01T00:20:02.000Z',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2001'}],
        'conversation_id': '2000',
        'text': 'two',
        'id': '2002',
        'author_id': '1000',
    }

    user_0 = {'username': 'user', 'id': '1000', 'name': 'name'}
    user_1 = {'username': 'user', 'id': '1100', 'name': 'name'}

    # this is for user's tweets only; the replies need to come in a separate call (and another test)
    rv = update_with(
        [tweet_0, tweet_1, tweet_2, tweet_1_0_1],
        [user_0],
        tweets=[tweet_0, tweet_1, tweet_1_0_0],
    )

    (entry,) = reader.get_entries()

    # print('>>>')
    # print(entry.content[1].value)
    # print('<<<')


# redacted real-world conversations; not used directly in tests
#
# scenario "media":
#   USER_0 tweets TWEET_MEDIA_0 including MEDIA_0
#
# scenario "replyquote"
#   USER_0 tweets thread TWEET_REPLYQUOTE_0 and TWEET_REPLYQUOTE_1;
#   TWEET_REPLYQUOTE_0 quotes TWEET_REPLYQUOTE_QUOTED of USER_QUOTED;
#   TWEET_REPLYQUOTE_QUOTED replies to some other user, mentioning them;
#   both TWEET_REPLYQUOTE_0 and TWEET_REPLYQUOTE_QUOTED are in includes
#
# scenario "retweet":
#   USER_0 retweets TWEET_RETWEET_RETWEETED by USER_RETWEETED in TWEET_RETWEET_0

USER_0 = {
    'description': 'one https://t.co/example two',
    'profile_image_url': 'https://pbs.twimg.com/profile/0.png',
    'verified': False,
    'entities': {
        'url': {
            'urls': [
                {
                    'start': 0,
                    'end': 16,
                    'url': 'https://t.co/url',
                    'expanded_url': 'https://url.org',
                    'display_url': 'url.org',
                }
            ]
        },
        'description': {
            'urls': [
                {
                    'start': 4,
                    'end': 24,
                    'url': 'https://t.co/example',
                    'expanded_url': 'http://example.com',
                    'display_url': 'example.com',
                }
            ]
        },
    },
    'username': 'user',
    'id': '1000',
    'url': 'https://t.co/url',
    'name': 'name',
}

TWEET_MEDIA_0 = {
    'created_at': '2022-01-01T00:00:00.000Z',
    'lang': 'en',
    'entities': {
        'urls': [
            {
                'start': 20,
                'end': 40,
                'url': 'https://t.co/article',
                'expanded_url': 'https://example.com/article',
                'display_url': 'example.com/article',
                'images': [
                    {
                        'url': 'https://pbs.twimg.com/news_img/article?format=jpg&name=orig',
                        'width': 1200,
                        'height': 600,
                    },
                    {
                        'url': 'https://pbs.twimg.com/news_img/article?format=jpg&name=150x150',
                        'width': 150,
                        'height': 150,
                    },
                ],
                'status': 200,
                'title': 'Article Title',
                'description': 'Article description.',
                'unwound_url': 'https://example.com/article',
            },
            {
                'start': 41,
                'end': 64,
                'url': 'https://t.co/screenshot',
                'expanded_url': 'https://twitter.com/user/status/2000/photo/1',
                'display_url': 'pic.twitter.com/screenshot',
                'media_key': '3_3000',
            },
        ]
    },
    'conversation_id': '2000',
    'text': 'interesting article https://t.co/article https://t.co/screenshot',
    'id': '2000',
    'attachments': {'media_keys': ['3_3000']},
    'public_metrics': {
        'retweet_count': 1,
        'reply_count': 0,
        'like_count': 2,
        'quote_count': 3,
    },
    'author_id': '1000',
    'source': 'Twitter Web App',
}

MEDIA_0 = {
    'media_key': '3_3000',
    'url': 'https://pbs.twimg.com/media/0.png',
    'width': 640,
    'type': 'photo',
    'height': 480,
}


TWEET_REPLYQUOTE_0 = {
    'entities': {
        'urls': [
            {
                'start': 4,
                'end': 28,
                'url': 'https://t.co/quotedtweet',
                'expanded_url': 'https://twitter.com/quoteduser/status/2011',
                'display_url': 'twitter.com/quoteduser/…',
            }
        ]
    },
    'conversation_id': '2100',
    'referenced_tweets': [{'type': 'quoted', 'id': '2011'}],
    'lang': 'en',
    'created_at': '2022-01-01T00:21:00.000Z',
    'public_metrics': {
        'retweet_count': 10,
        'reply_count': 1,
        'like_count': 11,
        'quote_count': 12,
    },
    'text': "one https://t.co/quotedtweet indeed",
    'source': 'Twitter Web App',
    'id': '2100',
    'author_id': '1000',
}

TWEET_REPLYQUOTE_1 = {
    'conversation_id': '2100',
    'referenced_tweets': [{'type': 'replied_to', 'id': '2100'}],
    'lang': 'en',
    'created_at': '2022-01-01T00:21:01.000Z',
    'public_metrics': {
        'retweet_count': 21,
        'reply_count': 0,
        'like_count': 22,
        'quote_count': 23,
    },
    'text': "two",
    'source': 'Twitter Web App',
    'id': '2101',
    'author_id': '1000',
}

TWEET_REPLYQUOTE_QUOTED = {
    'conversation_id': '2000',
    'referenced_tweets': [{'type': 'replied_to', 'id': '2000'}],
    'entities': {
        'mentions': [{'start': 6, 'end': 18, 'username': 'someoneelse', 'id': '1102'}]
    },
    'lang': 'en',
    'created_at': '2022-01-01T00:20:11.000Z',
    'public_metrics': {
        'retweet_count': 100,
        'reply_count': 200,
        'like_count': 300,
        'quote_count': 400,
    },
    'text': "re to @someoneelse yes",
    'source': 'some.app',
    'id': '2011',
    'author_id': '1101',
}

USER_QUOTED = {
    'id': '1101',
    'profile_image_url': 'https://pbs.twimg.com/profile/1101.jpg',
    'username': 'quoteduser',
    'description': 'whatever',
    'verified': False,
    'name': 'Quoted User',
}


TWEET_RETWEET_0 = {
    'conversation_id': '2100',
    'referenced_tweets': [{'type': 'retweeted', 'id': '2000'}],
    'entities': {
        'mentions': [{'start': 3, 'end': 17, 'username': 'retweeteduser', 'id': '1100'}]
    },
    'lang': 'en',
    'created_at': '2022-01-01T00:21:00.000Z',
    'public_metrics': {
        'retweet_count': 10,
        'reply_count': 0,
        'like_count': 0,
        'quote_count': 0,
    },
    'text': "RT @retweeteduser: original tweet",
    'source': 'Twitter Web App',
    'id': '2100',
    'author_id': '1000',
}

TWEET_RETWEET_RETWEETED = {
    'conversation_id': '2000',
    'lang': 'en',
    'created_at': '2022-01-01T00:20:00.000Z',
    'public_metrics': {
        'retweet_count': 5,
        'reply_count': 1,
        'like_count': 2,
        'quote_count': 3,
    },
    'text': "original tweet",
    'source': 'Twitter for Android',
    'id': '2000',
    'author_id': '1100',
}

USER_RETWEETED = {
    'id': '1100',
    'profile_image_url': 'https://pbs.twimg.com/profile/1100.jpg',
    'username': 'retweeteduser',
    'description': 'also whatever',
    'verified': True,
    'name': 'also name',
}
