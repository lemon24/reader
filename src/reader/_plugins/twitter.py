import posixpath
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from datetime import timezone
from typing import NamedTuple
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import tweepy

from reader import Content
from reader import ParseError
from reader._parser import RetrieveResult
from reader._types import EntryData
from reader._types import FeedData

if TYPE_CHECKING:
    from reader import Reader
    from tweepy import Media, Tweet, User, Poll


MIME_TYPE = 'application/x.twitter'
MIME_TYPE_JSON = MIME_TYPE + '+json'
URL_PREFIX = 'https://twitter.com/'


class Etag(NamedTuple):
    since_id: 'int|None'
    bearer_token: str
    recent_conversations: 'list[int]'


class UserFile(NamedTuple):
    user: 'User'
    conversations: 'dict[int, Conversation]'


@dataclass(frozen=True)
class Retriever:
    reader: 'Reader'
    slow_to_read = False
    recent_threshold = timedelta(30)

    @contextmanager
    def __call__(self, url, http_etag, *_, **__):
        try:
            username = self._parse_url(url)
        except ValueError as e:
            raise ParseError(url, message=str(e)) from None

        data = retrieve_user(username, http_etag)
        if not data.conversations:
            yield None
            return

        etag = str(max(t for d in data.conversations.values() for t in d.tweets))

        yield RetrieveResult(data, MIME_TYPE, http_etag=etag)

    def validate_url(self, url):
        self._parse_url(url)

    def _parse_url(self, url):
        error = None
        if not url.startswith(URL_PREFIX):
            error = "unexpected prefix (scheme or netloc)"

        url_parsed = urlparse(url)
        if url_parsed.query:
            error = "query not allowed"
        if url_parsed.fragment:
            error = "fragment not allowed"

        path = posixpath.relpath(posixpath.normpath(url_parsed.path), '/')
        if '/' in path:
            error = "not a user URL (e.g. https://twitter.com/user)"

        if error:
            raise ValueError(f"invalid URL: {error}")
        return path

    def process_feed_for_update(self, feed):
        now = self.reader._now()

        since_id = int(feed.http_etag) if feed.http_etag else None

        key = self.reader.make_reader_reserved_name('twitter')
        value = self.reader.get_tag((), key, {})
        token = value.get('token')
        if not token:
            raise ParseError(feed.url, "no Twitter bearer token configured")

        recent_conversations = []
        for entry in self.reader.get_entries(feed=feed):
            published = (
                (entry.published or entry.added)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            if now - published > self.recent_threshold:
                break
            recent_conversations.append(int(entry.id))

        return feed._replace(
            http_etag=Etag(
                since_id=since_id,
                bearer_token=token,
                recent_conversations=recent_conversations,
            )
        )


@dataclass
class Conversation:
    id: int
    tweets: 'dict[int, Tweet]' = field(default_factory=dict)
    users: 'dict[int, User]' = field(default_factory=dict)
    media: 'dict[str, Media]' = field(default_factory=dict)
    polls: 'dict[str, Poll]' = field(default_factory=dict)

    _factories = dict(
        tweets=(int, tweepy.Tweet),
        users=(int, tweepy.User),
        media=(lambda k: k, tweepy.Media),
        polls=(lambda k: k, tweepy.Poll),
    )

    def to_json(self):
        rv = {'id': self.id}
        for name in self._factories:
            rv[name] = {str(k): v.data for k, v in getattr(self, name).items()}
        return rv

    @classmethod
    def from_json(cls, data):
        kwargs = {
            name: {k_cls(k): v_cls(v) for k, v in data[name].items()}
            for name, k_cls, v_cls in cls._factories
        }
        return cls(id=data['id'], **kwargs)

    def update(self, other):
        for name in self._factories:
            getattr(self, name).update(getattr(other, name))


def retrieve_user(username, etag):
    user, responses = retrieve_user_responses(username, etag)
    rv = {}
    for response in responses:
        update_with_response(rv, response)
    return UserFile(user, rv)


def retrieve_user_responses(username, etag):
    # TODO: maybe use our own requests session
    client = tweepy.Client(etag.bearer_token)
    user = client.get_user(username=username).data

    # FIXME: retries?
    # are we getting billed twice for a tweet that's in .data and in .includes['tweets']?

    paginator = tweepy.Paginator(
        client.get_users_tweets,
        user.id,
        since_id=etag.since_id,
        tweet_fields="id,text,author_id,conversation_id,created_at,referenced_tweets,attachments,entities,lang,public_metrics,source",
        exclude="replies",
        expansions="author_id,attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id,attachments.poll_ids",
        media_fields="duration_ms,height,media_key,preview_image_url,public_metrics,type,url,width,alt_text",
        user_fields="id,name,username,description,profile_image_url,url,verified,entities",
        # FIXME: more?
        max_results=20,
        limit=2,
    )

    # TODO: get new tweets from old conversations here

    return user, paginator


def update_with_response(rv, response):
    assert not response.errors, response.errors
    if not response.data:
        return

    incl_tweets = {t.id: t for t in response.includes.get('tweets', ())}
    incl_users = {u.id: u for u in response.includes.get('users', ())}
    incl_media = {m.media_key: m for m in response.includes.get('media', ())}
    incl_polls = {p.id: p for p in response.includes.get('polls', ())}

    for tweet in response.data:
        if tweet.conversation_id in rv:
            data = rv[tweet.conversation_id]
        else:
            data = rv[tweet.conversation_id] = Conversation(tweet.conversation_id)

        user_ids = {tweet.author_id}

        data.tweets[tweet.id] = tweet
        for ref in tweet.referenced_tweets or ():
            if ref.id in incl_tweets:
                ref_tweet = incl_tweets[ref.id]
                data.tweets[ref.id] = ref_tweet
                user_ids.add(ref_tweet.author_id)

        for user_id in user_ids:
            if user_id in incl_users:
                data.users[user_id] = incl_users[user_id]

        if tweet.attachments:
            for media_key in tweet.attachments.get('media_keys', ()):
                if media_key in incl_media:
                    data.media[media_key] = incl_media[media_key]

        if tweet.attachments:
            for poll_id in tweet.attachments.get('poll_ids', ()):
                if poll_id in incl_polls:
                    data.polls[poll_id] = incl_polls[poll_id]


@dataclass(frozen=True)
class Parser:
    reader: 'Reader'
    http_accept = MIME_TYPE

    def __call__(self, url, file, headers):
        user, data = file
        feed = render_user_feed(url, user)
        entries = (
            EntryData(
                url,
                conversation_id,
                # tweety objects converted to JSON in process_entry_pairs
                content=[Content(conversation)],
            )
            for conversation_id, conversation in data.items()
        )
        return feed, entries

    def process_entry_pairs(self, url, pairs):

        for new, old_for_update in pairs:
            old = None
            if old_for_update:
                old = self.reader.get_entry(old_for_update)
                old_json = next(
                    (c.value for c in old.content if c.type == MIME_TYPE_JSON), None
                )
                if old_json:
                    new.content[0].value.update(Conversation.from_json(old_json))

            new = render_user_entry(new, old)
            yield new, old_for_update

        # TODO: when we can get the content with old entry, just merge
        # TODO: use tweet.public_metrics to check for missing replies


def render_user_feed(url, user):
    title = f"{user.name} (@{user.username})"
    if user.verified:
        title += " ✓"

    feed = FeedData(
        url,
        # TODO: updated
        title=title,
        # TODO: expand from user.entities
        link=user.url,
        author=f"@{user.username}",
        # TODO: expand urls from user.entities
        subtitle=user.description,
        version="twitter",
    )

    return feed


def render_user_entry(new, old):
    data = new.content[0].value

    dates = [t.created_at for t in data.tweets.values() if t.conversation_id == data.id]
    root = data.tweets[data.id]
    user = data.users[root.author_id]

    return new._replace(
        published=min(dates).astimezone(timezone.utc).replace(tzinfo=None),
        updated=max(dates).astimezone(timezone.utc).replace(tzinfo=None),
        title=root.text,
        link=f"{new.feed_url}/status/{data.id}",
        author=f"@{user.username}",
        content=[
            Content(data.to_json(), MIME_TYPE_JSON),
            # TODO: render to html
        ],
    )

    # TODO: title and author should be of quoted tweet?


def init_reader(reader):
    reader._parser.mount_retriever(URL_PREFIX, Retriever(reader))
    reader._parser.mount_parser_by_mime_type(Parser(reader))
