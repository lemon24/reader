import posixpath
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from datetime import timezone
from typing import NamedTuple
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import jinja2
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
        max_results=100,
        limit=2,
    )

    # TODO: get convo root if it falls just before limit here

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

            # check if we have the root tweet; if not, don't return the entry;
            # TODO: alternatively, ensure we get all the tweets in a thread
            if new.content[0].value.id not in new.content[0].value.tweets:
                continue

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
    assert isinstance(data, Conversation), data

    root = data.tweets[data.id]
    user = data.users[root.author_id]

    # TODO: maybe only keep the dates in the thread?
    dates = [t.created_at for t in data.tweets.values() if t.conversation_id == data.id]
    published = min(dates).astimezone(timezone.utc).replace(tzinfo=None)
    updated = max(dates).astimezone(timezone.utc).replace(tzinfo=None)

    # TODO: move rendering to post (get_entries() plugin), so we don't have to re-retrieve while testing (we can still cache it in metadata if needed)
    tree = conversation_tree(data)
    nodes = flatten_tree(tree)
    html = jinja_env.get_template('tweet.html').render(nodes=nodes)

    return new._replace(
        updated=updated,
        title=root.text,
        link=f"{new.feed_url}/status/{data.id}",
        author=f"@{user.username}",
        published=published,
        content=[Content(data.to_json(), MIME_TYPE_JSON), Content(html, 'text/html')],
    )

    # TODO: title and author should be of quoted tweet?


@dataclass
class Node:
    """Like a Tweet, but all references are resolved."""

    tweet: 'Tweet'
    author: 'User'
    media: 'list[Media]' = field(default_factory=list)
    polls: 'list[Poll]' = field(default_factory=list)
    children: 'list[Node]' = field(default_factory=list)
    retweeted: 'Node|None' = None
    quoted: 'Node|None' = None


def conversation_tree(data):
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
            # FIXME: retrieve media/polls in quoted/retweeted tweet
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

            # FIXME: assert max one
            if not tweets:
                return None

            return make_node(tweets[0].id, wrapped=True)

        # TODO: make configurable
        with_replies = False

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

            # FIXME: handle retweeted/quoted of retweeted/quoted
            retweeted = get_referenced('retweeted')
            quoted = get_referenced('quoted')
        else:
            children = []
            retweeted = None
            quoted = None

        return Node(tweet, author, media, polls, children, retweeted, quoted)

    return make_node(data.id)


def flatten_tree(root):
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

<p>id: {{ node.tweet.id }}, referenced_tweets: {{ node.tweet.referenced_tweets | e }}

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


<pre>{{ nodes | pprint | escape }}</pre>


"""

jinja_env = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    loader=jinja2.DictLoader({'tweet.html': TWEET_HTML_TEMPLATE}),
)


def init_reader(reader):
    reader._parser.mount_retriever(URL_PREFIX, Retriever(reader))
    reader._parser.mount_parser_by_mime_type(Parser(reader))
