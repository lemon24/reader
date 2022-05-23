import pytest
from tweepy import Media
from tweepy import Response
from tweepy import Tweet
from tweepy import User

from reader._plugins import twitter


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

TWEET_0 = {
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


def test_basic(make_reader, monkeypatch):
    def retrieve_user_responses(username, etag):
        assert username == 'user'
        assert etag.bearer_token == 'abcd'
        return User(USER_0), [make_response([TWEET_0], [USER_0], [MEDIA_0])]

    monkeypatch.setattr(twitter, 'retrieve_user_responses', retrieve_user_responses)

    reader = make_reader(':memory:', plugins=[twitter.init_reader])
    reader.add_feed('https://twitter.com/user')
    reader.set_tag((), reader.make_reader_reserved_name('twitter'), {'token': 'abcd'})

    reader.update_feeds()

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
        'tweets': {'2000': TWEET_0},
        'users': {'1000': USER_0},
        'media': {'3_3000': MEDIA_0},
        'polls': {},
    }
