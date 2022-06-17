"""

To do before the next release:

* docs
* clean up rendered HTML
  * say "there is a poll not shown"
  * show media as a list of plain elements (just <img src="..." />)
  * for retweets, don't show the retweeter's text
* basic CSS
* basic tests
* retrieve media/polls in quoted/retweeted tweet
* think of a mechanism to re-render entry HTML on plugin update
* remove Paginator(max_results=..., limit=...) used during development


To do after the next release:

* render media
* render polls
* expand urls
* mark updated entry as unread
* https://twitter.com/user?replies=yes

"""
from __future__ import annotations

import posixpath
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from datetime import timezone
from typing import NamedTuple
from urllib.parse import parse_qs
from urllib.parse import urlparse

import jinja2
import tweepy

from reader import Content
from reader import ParseError
from reader import Reader
from reader._parser import RetrieveResult
from reader._types import EntryData
from reader._types import FeedData


MIME_TYPE = 'application/x.twitter'
MIME_TYPE_JSON = MIME_TYPE + '+json'

URL_PREFIX = 'https://twitter.com/'


class UserURL(NamedTuple):
    username: str
    with_replies: bool = False


def parse_url(url: str) -> UserURL:
    error = None
    if not url.startswith(URL_PREFIX):
        error = "unexpected prefix (scheme or netloc)"

    url_parsed = urlparse(url)
    if url_parsed.fragment:
        error = "fragment not allowed"

    path = posixpath.relpath(posixpath.normpath(url_parsed.path), '/')
    if not path or '/' in path:
        error = "not a user URL (e.g. https://twitter.com/user)"

    query = parse_qs(url_parsed.query, keep_blank_values=True)
    if not query.keys() <= {'replies'}:
        error = "bad query string"
    replies_list = query.get('replies', ())

    if len(replies_list) == 0:
        with_replies = False
    elif len(replies_list) == 1:
        replies_str = replies_list[0]
        if replies_str in ('', 'yes'):
            with_replies = True
        elif replies_str == 'no':
            with_replies = False
        else:
            error = "bad query string"
    else:
        error = "bad query string"

    # TODO: remove when we have with_replies support
    if with_replies:
        error = "replies not supported yet"

    if error:
        raise ValueError(f"invalid URL: {error}")
    return UserURL(path, with_replies)


class Etag(NamedTuple):
    since_id: int | None
    bearer_token: str
    recent_conversations: tuple[int, ...] = ()


class UserFile(NamedTuple):
    user: tweepy.User
    conversations: list[Conversation]


@dataclass
class Conversation:
    """Collection of resources belonging to a conversation."""

    id: int
    tweets: dict[int, tweepy.Tweet] = field(default_factory=dict)
    users: dict[int, tweepy.User] = field(default_factory=dict)
    media: dict[str, tweepy.Media] = field(default_factory=dict)
    polls: dict[str, tweepy.Poll] = field(default_factory=dict)

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
            for name, (k_cls, v_cls) in cls._factories.items()
        }
        return cls(id=data['id'], **kwargs)

    def update(self, other):
        """Merge another conversation into this one."""
        for name in self._factories:
            getattr(self, name).update(getattr(other, name))


@dataclass(frozen=True)
class Retriever:
    reader: Reader
    slow_to_read = False
    recent_threshold = timedelta(30)

    def validate_url(self, url):
        parse_url(url)

    def process_feed_for_update(self, feed) -> RetrieveResult[UserFile]:
        """Enrich the etag that gets passed to __call__() with:

        * the bearer token (from global metadata)
        * the ids of recent converstations (so we can retrieve retries)

        """
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
                recent_conversations=tuple(recent_conversations),
            )
        )

    @contextmanager
    def __call__(self, url, http_etag: Etag, *_, **__):
        try:
            parsed_url = parse_url(url)
        except ValueError as e:
            raise ParseError(url, message=str(e)) from None

        twitter = Twitter.from_bearer_token(http_etag.bearer_token)

        data = twitter.retrieve_user(parsed_url, http_etag)
        if not data.conversations:
            yield None
            return

        # store the id of newest tweet as etag
        etag = str(max(t for d in data.conversations for t in d.tweets))

        yield RetrieveResult(data, MIME_TYPE, http_etag=etag)


@dataclass(frozen=True)
class Twitter:
    """Light wrapper over tweepy.Client.

    Currently only supports user tweets without replies.

    https://github.com/lemon24/reader/issues/271#issuecomment-1111789547

    """

    # TODO: do we need to handle retries?

    client: tweepy.Client

    @classmethod
    def from_bearer_token(cls, bearer_token):
        # TODO: maybe use our own requests session
        return cls(tweepy.Client(bearer_token))

    def retrieve_user(self, url: UserURL, etag: Etag) -> UserFile:
        user, responses = self.retrieve_user_responses(url, etag)
        conversations = {}
        for response in responses:
            update_with_response(conversations, response)
        return UserFile(user, list(conversations.values()))

    def retrieve_user_responses(self, url: UserURL, etag: Etag):
        user = self.client.get_user(username=url.username).data

        # are we getting billed twice for a tweet that's
        # both in .data and in .includes['tweets']?
        paginator = tweepy.Paginator(
            self.client.get_users_tweets,
            user.id,
            since_id=etag.since_id,
            # FIXME: these are good only for testing
            max_results=100,
            limit=2,
            **TWITTER_FIELDS_KWARGS,
        )

        # TODO: maybe get conversation root if it falls just before limit here

        # TODO: remove when we have with_replies support
        if url.with_replies:
            raise NotImplementedError(url.replies)

        return user, paginator


TWITTER_FIELDS_KWARGS = {
    'tweet_fields': [
        'id',
        'text',
        'author_id',
        'conversation_id',
        'created_at',
        'referenced_tweets',
        'attachments',
        'entities',
        'lang',
        'public_metrics',
        'source',
    ],
    'exclude': ['replies'],
    'expansions': [
        'author_id',
        'attachments.media_keys',
        'referenced_tweets.id',
        'referenced_tweets.id.author_id',
        'attachments.poll_ids',
    ],
    'media_fields': [
        'duration_ms',
        'height',
        'media_key',
        'preview_image_url',
        'public_metrics',
        'type',
        'url',
        'width',
        'alt_text',
    ],
    'user_fields': [
        'id',
        'name',
        'username',
        'description',
        'profile_image_url',
        'url',
        'verified',
        'entities',
    ],
}


def update_with_response(conversations, response):
    assert not response.errors, response.errors
    if not response.data:
        return

    # FIXME: retrieve media/polls in quoted/retweeted tweet

    incl_tweets = {t.id: t for t in response.includes.get('tweets', ())}
    incl_users = {u.id: u for u in response.includes.get('users', ())}
    incl_media = {m.media_key: m for m in response.includes.get('media', ())}
    incl_polls = {p.id: p for p in response.includes.get('polls', ())}

    for tweet in response.data:
        if tweet.conversation_id in conversations:
            conversation = conversations[tweet.conversation_id]
        else:
            conversation = Conversation(tweet.conversation_id)
            conversations[tweet.conversation_id] = conversation

        user_ids = {tweet.author_id}

        conversation.tweets[tweet.id] = tweet
        for ref in tweet.referenced_tweets or ():
            if ref.id in incl_tweets:
                ref_tweet = incl_tweets[ref.id]
                conversation.tweets[ref.id] = ref_tweet
                user_ids.add(ref_tweet.author_id)

        for user_id in user_ids:
            if user_id in incl_users:
                conversation.users[user_id] = incl_users[user_id]

        if tweet.attachments:
            for media_key in tweet.attachments.get('media_keys', ()):
                if media_key in incl_media:
                    conversation.media[media_key] = incl_media[media_key]

        if tweet.attachments:
            for poll_id in tweet.attachments.get('poll_ids', ()):
                if poll_id in incl_polls:
                    conversation.polls[poll_id] = incl_polls[poll_id]


@dataclass(frozen=True)
class Parser:
    reader: Reader
    http_accept = MIME_TYPE

    def __call__(self, url, file, headers):
        user, conversations = file
        feed = render_user_feed(url, user)
        entries = (
            EntryData(
                url,
                str(conversation.id),
                # tweety objects converted to JSON in process_entry_pairs
                content=[Content(conversation)],
            )
            for conversation in conversations
        )
        return feed, entries

    def process_entry_pairs(self, url, pairs):

        for new, old_for_update in pairs:
            old = None
            if old_for_update:
                old = self.reader.get_entry(new)
                old_json = next(
                    (c.value for c in old.content if c.type == MIME_TYPE_JSON), None
                )
                if old_json:
                    new.content[0].value.update(Conversation.from_json(old_json))

            # if we don't have the root, don't return the entry
            # TODO: alternatively, always retrieve the entire conversation
            if new.content[0].value.id not in new.content[0].value.tweets:
                continue

            new = render_user_entry(new)
            yield new, old_for_update

        # TODO: when we can get the content with old entry, just merge
        # TODO: maybe use tweet.public_metrics to check for missing replies


def render_user_feed(url: str, user: tweepy.User) -> FeedData:
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


def render_user_entry(entry: EntryData) -> EntryData:
    parsed_url = parse_url(entry.feed_url)

    data = entry.content[0].value
    assert isinstance(data, Conversation), data

    root = data.tweets[data.id]
    user = data.users[root.author_id]

    # TODO: maybe only keep the dates in the thread?
    dates = [t.created_at for t in data.tweets.values() if t.conversation_id == data.id]
    published = min(dates).astimezone(timezone.utc).replace(tzinfo=None)
    updated = max(dates).astimezone(timezone.utc).replace(tzinfo=None)

    tree = conversation_tree(data, parsed_url.with_replies)
    nodes = flatten_tree(tree)
    html = jinja_env.get_template('tweet.html').render(nodes=nodes)

    return entry._replace(
        updated=updated,
        title=root.text,
        link=f"{entry.feed_url}/status/{data.id}",
        author=f"@{user.username}",
        published=published,
        content=[Content(data.to_json(), MIME_TYPE_JSON), Content(html, 'text/html')],
    )

    # TODO: title and author should be of quoted tweet?


@dataclass
class Node:
    """Like a tweepy.Tweet, but all references are resolved."""

    tweet: tweepy.Tweet
    author: tweepy.User
    media: list[tweepy.Media] = field(default_factory=list)
    polls: list[tweepy.Poll] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    retweeted: Node | None = None
    quoted: Node | None = None


def conversation_tree(data: Conversation, with_replies: bool) -> Node:
    children_ids = {}

    for tweet in data.tweets.values():
        if tweet.conversation_id != data.id:
            continue
        children_ids.setdefault(tweet.id, [])
        for referenced in tweet.referenced_tweets or ():
            if referenced.type != 'replied_to':
                continue
            children_ids.setdefault(referenced.id, []).append(tweet.id)

    def make_node(id, wrapped=False):
        tweet = data.tweets[id]
        author = data.users[tweet.author_id]

        media = []
        polls = []
        if tweet.attachments:
            media.extend(
                data.media.get(k) for k in tweet.attachments.get('media_keys', ())
            )
            polls.extend(
                data.polls.get(k) for k in tweet.attachments.get('poll_ids', ())
            )

        def get_referenced(type):
            tweets = [
                data.tweets[r.id]
                for r in tweet.referenced_tweets or ()
                if r.type == type
            ]

            # TODO: assert we got exactly one
            if not tweets:
                return None

            return make_node(tweets[0].id, wrapped=True)

        if not wrapped:
            children = []
            for child_id in children_ids[id]:
                child_tweet = data.tweets[child_id]
                if (
                    not with_replies
                    and child_tweet.author_id != data.tweets[data.id].author_id
                ):
                    continue
                children.append(make_node(child_id))
            children.sort(key=lambda t: t.tweet.created_at.astimezone(timezone.utc))

            # TODO: handle retweeted/quoted of retweeted/quoted
            retweeted = get_referenced('retweeted')
            quoted = get_referenced('quoted')
        else:
            children = []
            retweeted = None
            quoted = None

        return Node(tweet, author, media, polls, children, retweeted, quoted)

    return make_node(data.id)


def flatten_tree(root: Node) -> None:
    rv = [root]

    def extract_thread_nodes(node):
        for child in list(node.children):
            if node.tweet.author_id != root.tweet.author_id:
                continue
            node.children.remove(child)
            rv.append(child)
            extract_thread_nodes(child)

    extract_thread_nodes(root)

    return rv


TWEET_HTML_TEMPLATE = r"""

{%- macro do_node(node, level=0, class="tweet") -%}

{% if class %}<div class="{{ class }}">{% endif %}

<p>{{ node.author.name }} @{{ node.author.username }} · {{ node.tweet.created_at.date() }}

<p>{{ node.tweet.text }}

{% if node.quoted %}
{{ do_node(node.quoted, class="tweet quoted") }}
{% endif %}

{% if node.retweeted %}
{{ do_node(node.retweeted, class="tweet retweeted") }}
{% endif %}

{% if class %}</div>{% endif -%}


{% if node.children %}
{% if level == 0 %}<details><summary>{{ node.children | length }} replies</summary>{% endif %}
{% for child in node.children %}
{{ do_node(child, level+1) }}
{% endfor %}
{% if level == 0 %}</details>{% endif %}
{% endif %}

{%- endmacro %}


{% for node in nodes %}
{{ do_node(node) }}
{% endfor %}


"""

jinja_env = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    loader=jinja2.DictLoader({'tweet.html': TWEET_HTML_TEMPLATE}),
)


def init_reader(reader):
    reader._parser.mount_retriever(URL_PREFIX, Retriever(reader))
    reader._parser.mount_parser_by_mime_type(Parser(reader))
