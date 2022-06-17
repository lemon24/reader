import pytest
from tweepy import Media
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
from reader._plugins.twitter import Etag
from reader._plugins.twitter import UserFile
from reader._plugins.twitter import UserURL


"""
# testing strategy

## with_replies == False

mock retrieve_user_responses(),
* [x] check feed title
* [x] entry titleentry json
* [x] entry published/updated
* [x] assert etag
* [x] assert recent_conversations

* [ ] almost end-to-end: check entry html (plain)

* [ ] zero tweets
* update
  * [x] assert render html called with data
  * [x] assert entry json
  * two tweets, one convo; parametrize by:
    * content: [ ] plain, [ ] media, [ ] poll, [ ] quote, [ ] retweet
    * order: first plain, second fancy, [ ] first fancy, second plain
  * two convos, one tweet each (both plain)
    * sequence: [ ] 2+0, [ ] 1+1+0

render: conversation json -> html

* one tweet
    * [ ] plain, [ ] media, [ ] poll, [ ] quote, [ ] retweet
* two tweets
    * [ ] plain, [ ] media, [ ] poll, [ ] quote, [ ] retweet
    * first fancy, second plain
* [ ] stray reply should not show up in html even if in convo json

## with_replies == True

TODO

"""


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
    reader.set_tag((), '.reader.twitter', {'token': 'abcd'})
    return reader


@pytest.fixture
def update_with(reader, monkeypatch):
    def update(data, users, media=None, tweets=None):
        def retrieve_user_responses(self, url, etag):
            update.url, update.etag = url, etag
            return User(users[0]), [make_response(data, users, media, tweets)]

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
    'text': "two",
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
    tweet_0 = TWEET_0.copy()
    tweet_0.update(id='0', conversation_id='0', created_at='2100-01-01T00:00:00.000Z')
    tweet_1 = TWEET_0.copy()
    tweet_1.update(id='1', conversation_id='1', created_at='2100-01-20T00:00:00.000Z')
    tweet_2 = TWEET_0.copy()
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
    # rv = update_with([], [])

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

    user = USER.copy()
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


# preliminary tests; to be replaced by the ones above when they're all done


def test_basic(reader, update_with):
    rv = update_with([TWEET_MEDIA_0], [USER_0], [MEDIA_0])

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


def test_update_with_media(reader, update_with):
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
    rv = update_with([tweet], [user], [media])

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


def test_update_with_reply_and_quote(reader, update_with):
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
    rv = update_with(
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


def test_update_with_retweet(reader, update_with):
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
    rv = update_with(
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
