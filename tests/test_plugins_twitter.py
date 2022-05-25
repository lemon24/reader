import pytest
from tweepy import Media
from tweepy import Response
from tweepy import Tweet
from tweepy import User
from utils import utc_datetime as datetime

from reader._plugins import twitter


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


def make_response(data=(), users=None, media=None, tweets=None):
    includes = {}
    if users:
        includes['users'] = list(map(User, users))
    if media:
        includes['media'] = list(map(Media, media))
    if tweets:
        includes['tweets'] = list(map(Tweet, tweets))

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
    reader.set_tag((), reader.make_reader_reserved_name('twitter'), {'token': 'abcd'})
    return reader


@pytest.fixture
def update_with_user_response(reader, monkeypatch):
    def update_with_user_response(data, users, media=None, tweets=None):
        def retrieve_user_responses(username, etag):
            assert username == 'user'
            assert etag.bearer_token == 'abcd'
            return User(users[0]), [make_response(data, users, media, tweets)]

        monkeypatch.setattr(twitter, 'retrieve_user_responses', retrieve_user_responses)

        return reader.update_feed('https://twitter.com/user')

    return update_with_user_response


def test_basic(reader, update_with_user_response):
    rv = update_with_user_response([TWEET_MEDIA_0], [USER_0], [MEDIA_0])

    (entry,) = reader.get_entries()
    assert entry.id == '2000'

    feed = entry.feed
    assert feed.url == 'https://twitter.com/user'
    assert feed.title == 'name (@user)'
    assert feed.link == 'https://t.co/url'
    assert feed.author == '@user'
    assert feed.subtitle == 'one https://t.co/example two'
    assert feed.version == 'twitter'

    (value,) = [
        c.value for c in entry.content if c.type == 'application/x.twitter+json'
    ]

    assert value == {
        'id': 2000,
        'tweets': {'2000': TWEET_MEDIA_0},
        'users': {'1000': USER_0},
        'media': {'3_3000': MEDIA_0},
        'polls': {},
    }


def get_entry_json(entry):
    content = [c.value for c in entry.content if c.type == 'application/x.twitter+json']
    assert len(content) == 1, entry
    return content[0]


def test_update_with_media(reader, update_with_user_response):
    tweet = {
        'created_at': '2022-01-01T00:20:00.000Z',
        'conversation_id': '2000',
        'text': 'text',
        'id': '2000',
        'attachments': {'media_keys': ['3_3000']},
        'author_id': '1000',
    }
    user = {'username': 'user', 'id': '1000', 'name': 'name'}
    media = {'media_key': '3_3000', 'type': 'photo'}
    rv = update_with_user_response([tweet], [user], [media])

    (entry,) = reader.get_entries()

    assert entry.id == '2000'
    assert entry.published == datetime(2022, 1, 1, 0, 20, 0)
    assert entry.updated == datetime(2022, 1, 1, 0, 20, 0)
    assert entry.title == 'text'
    assert entry.link == 'https://twitter.com/user/status/2000'
    assert entry.author == '@user'

    assert get_entry_json(entry) == {
        'id': 2000,
        'tweets': {'2000': tweet},
        'users': {'1000': user},
        'media': {'3_3000': media},
        'polls': {},
    }


def test_update_with_reply_and_quote(reader, update_with_user_response):
    # TODO: also test update in two parts, and also with quote in the second tweet

    tweet_0 = {
        'conversation_id': '2100',
        'referenced_tweets': [{'type': 'quoted', 'id': '2011'}],
        'created_at': '2022-01-01T00:21:00.000Z',
        'text': "one",
        'id': '2100',
        'author_id': '1000',
    }
    tweet_1 = {
        'conversation_id': '2100',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2100'}],
        'created_at': '2022-01-01T00:21:01.000Z',
        'text': "two",
        'id': '2101',
        'author_id': '1000',
    }
    tweet_quoted = {
        'conversation_id': '2000',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2000'}],
        'created_at': '2022-01-01T00:20:11.000Z',
        'text': "quote",
        'id': '2011',
        'author_id': '1101',
    }
    user = {'username': 'user', 'id': '1000', 'name': 'name'}
    user_quoted = {'id': '1101', 'username': 'quoteduser', 'name': 'quoted'}
    rv = update_with_user_response(
        [tweet_0, tweet_1], [user, user_quoted], tweets=[tweet_0, tweet_quoted]
    )

    (entry,) = reader.get_entries()

    assert entry.id == '2100'
    assert entry.published == datetime(2022, 1, 1, 0, 21, 0)
    assert entry.updated == datetime(2022, 1, 1, 0, 21, 1)
    assert entry.title == 'one'
    assert entry.link == 'https://twitter.com/user/status/2100'
    assert entry.author == '@user'

    assert get_entry_json(entry) == {
        'id': 2100,
        'tweets': {'2100': tweet_0, '2101': tweet_1, '2011': tweet_quoted},
        'users': {'1000': user, '1101': user_quoted},
        'media': {},
        'polls': {},
    }


def test_update_with_retweet(reader, update_with_user_response):
    tweet_0 = {
        'conversation_id': '2100',
        'referenced_tweets': [{'type': 'retweeted', 'id': '2000'}],
        'created_at': '2022-01-01T00:21:00.000Z',
        'text': "one",
        'id': '2100',
        'author_id': '1000',
    }
    tweet_retweeted = {
        'conversation_id': '2000',
        'referenced_tweets': [{'type': 'replied_to', 'id': '2000'}],
        'created_at': '2022-01-01T00:20:00.000Z',
        'text': "quote",
        'id': '2000',
        'author_id': '1100',
    }
    user = {'username': 'user', 'id': '1000', 'name': 'name'}
    user_retweeted = {'id': '1100', 'username': 'retweeteduser', 'name': 'also name'}
    rv = update_with_user_response(
        [tweet_0], [user, user_retweeted], tweets=[tweet_0, tweet_retweeted]
    )

    (entry,) = reader.get_entries()

    assert entry.id == '2100'
    assert entry.published == datetime(2022, 1, 1, 0, 21, 0)
    assert entry.updated == datetime(2022, 1, 1, 0, 21, 0)
    assert entry.title == 'one'
    assert entry.link == 'https://twitter.com/user/status/2100'
    assert entry.author == '@user'

    assert get_entry_json(entry) == {
        'id': 2100,
        'tweets': {'2100': tweet_0, '2000': tweet_retweeted},
        'users': {'1000': user, '1100': user_retweeted},
        'media': {},
        'polls': {},
    }
