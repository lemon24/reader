"""
twitter
~~~~~~~

.. module:: reader
  :noindex:

Create a feed out of a Twitter account.

Feed URLs must be of the of the form ``https://twitter.com/user`` (no query string).

In order to authenticate,
an `OAuth 2.0 Bearer Token (app-only)`_ is required
(corresponding `Tweepy documentation`_);
set the value of the ``.reader.twitter`` global tag to::

    {"token": "Bearer Token here"}

From within Python code::

    key = reader.make_reader_reserved_name('twitter')
    value = {"token": "Bearer Token here"}
    reader.set_tag((), key, value)

.. _OAuth 2.0 Bearer Token (app-only): https://developer.twitter.com/en/docs/authentication/oauth-2-0/bearer-tokens
.. _Tweepy documentation: https://docs.tweepy.org/en/stable/authentication.html#twitter-api-v2
.. _Essential access: https://developer.twitter.com/en/portal/products/essential

Each entry in the feed corresponds to a thread;
currently, replies from other users are not included.
An HTML version of the thread is available
as a :class:`Content` with type ``text/html``;
the original JSON data is also available with type ``application/x.twitter+json``.

On the first update, up to 1,000 tweets are retrieved;
on subsequent updates, only new tweets are retrieved
(for reference, `Essential access`_ caps at 500K tweets per month).
When a new tweet is published in an existing thread,
the corresponding entry is updated accordingly.

The HTML content can be rerendered from the existing JSON data
by adding the ``.reader.twitter.rerender`` tag to the feed;
on the next feed update, the plugin will rerender the HTML content
and remove the tag.


Screenshots:

.. figure:: screenshots/twitter-one.png
    :width: 240px

.. figure:: screenshots/twitter-two.png
    :width: 240px


To do (roughly in order of importance):

* retrieve media/polls in quoted/retweeted tweet
* media URL might be None
* retrieve retweets/quotes of retweets/quotes
* handle deleted tweets in conversations
  (currently leads to truncated/missing conversation)
* lower the initial tweet limit, but allow increasing it
* automatically re-render entry HTML on plugin update
* show images / expanded URLs only in the original tweet, not in retweets
* mark updated entries as unread
* better URL/entity expansion (feed subtitle, entry hashtags and usernames)
* better media rendering
* better poll rendering
* retrieve and render tweet replies (``https://twitter.com/user?replies=yes``)
* support previewing Twitter feeds in the web app


This plugin needs additional dependencies, use the ``unstable-plugins`` extra
to install them:

.. code-block:: bash

    pip install reader[unstable-plugins]

To load::

    READER_PLUGIN='reader._plugins.twitter:init_reader' \\
    python -m reader ...

..
    Implemented for https://github.com/lemon24/reader/issues/271


"""
from __future__ import annotations

import json
import logging
import posixpath
import re
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from datetime import timezone
from typing import NamedTuple
from urllib.parse import parse_qs
from urllib.parse import urlparse

import jinja2
import markupsafe
import tweepy

from reader import Content
from reader import HighlightedString
from reader import ParseError
from reader import Reader
from reader._parser import RetrieveResult
from reader._types import EntryData
from reader._types import FeedData


log = logging.getLogger('reader._plugins.twitter')


MIME_TYPE = 'application/x.twitter'
MIME_TYPE_JSON = MIME_TYPE + '+json'
MIME_TYPE_HTML = 'text/html'

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
    rerender_conversations: tuple[int, ...] = ()


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
        * the ids of recent converstations (so we can retrieve replies)

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

        rerender_key = self.reader.make_reader_reserved_name('twitter.rerender')
        missing = object()
        rerender_conversations = []
        if self.reader.get_tag(feed, rerender_key, missing) is not missing:
            rerender_conversations = []
            for entry in self.reader.get_entries(feed=feed):
                try:
                    id = int(entry.id)
                except ValueError:
                    continue
                else:
                    rerender_conversations.append(id)

            self.reader.delete_tag(feed, rerender_key, missing_ok=True)

        return feed._replace(
            http_etag=Etag(
                since_id=since_id,
                bearer_token=token,
                recent_conversations=tuple(recent_conversations),
                rerender_conversations=tuple(rerender_conversations),
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

        # store the id of newest tweet as etag
        since_ids = [t for d in data.conversations for t in d.tweets]
        if http_etag.since_id is not None:
            since_ids.append(http_etag.since_id)
        etag = None
        if since_ids:
            etag = str(max(since_ids))

        if http_etag.rerender_conversations:
            log.info("rerendering %s", http_etag.rerender_conversations)
            new_or_updated_conversations = {c.id for c in data.conversations}
            data = data._replace(
                conversations=data.conversations
                + [
                    Conversation(id)
                    for id in http_etag.rerender_conversations
                    if id not in new_or_updated_conversations
                ]
            )

        if not data.conversations:
            yield None
            return

        yield RetrieveResult(data, MIME_TYPE, http_etag=etag)


@dataclass(frozen=True)
class Twitter:
    """Light wrapper over tweepy.Client.

    Currently only supports user tweets without replies.

    https://github.com/lemon24/reader/issues/271#issuecomment-1111789547

    """

    client: tweepy.Client

    @classmethod
    def from_bearer_token(cls, bearer_token):
        # TODO: maybe use our own requests session
        return cls(tweepy.Client(bearer_token, wait_on_rate_limit=True))

    def retrieve_user(self, url: UserURL, etag: Etag) -> UserFile:
        user, responses = self.retrieve_user_responses(url, etag)
        conversations = {}
        for response in responses:
            update_with_response(conversations, response)
        return UserFile(user, list(conversations.values()))

    def retrieve_user_responses(self, url: UserURL, etag: Etag):
        user = self.client.get_user(
            username=url.username, user_fields=TWITTER_FIELDS_KWARGS['user_fields']
        ).data

        # are we getting billed twice for a tweet that's
        # both in .data and in .includes['tweets']?
        paginator = tweepy.Paginator(
            self.client.get_users_tweets,
            user.id,
            since_id=etag.since_id,
            # > the number of Tweets to try and retrieve,
            # > up to a maximum of 100 per distinct request
            max_results=100,
            limit=10,
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
    errors = list(response.errors)

    for error in response.errors:
        # {
        #   'value': '123',
        #   'detail': 'Could not find tweet with referenced_tweets.id: [123].',
        #   'title': 'Not Found Error',
        #   'resource_type': 'tweet',
        #   'parameter': 'referenced_tweets.id',
        #   'resource_id': '123',
        #   'type': 'https://api.twitter.com/2/problems/resource-not-found',
        # }
        if error['type'] == 'https://api.twitter.com/2/problems/resource-not-found':
            errors.remove(error)

    assert not errors, errors

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
                    (
                        json.loads(c.value)
                        for c in old.content
                        if c.type == MIME_TYPE_JSON
                    ),
                    None,
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

    conversation = entry.content[0].value
    assert isinstance(conversation, Conversation), conversation

    root = conversation.tweets[conversation.id]
    user = conversation.users[root.author_id]

    # TODO: maybe only keep the dates in the tree?
    dates = [
        t.created_at
        for t in conversation.tweets.values()
        if t.conversation_id == conversation.id
    ]
    published = min(dates).astimezone(timezone.utc).replace(tzinfo=None)
    updated = max(dates).astimezone(timezone.utc).replace(tzinfo=None)

    return entry._replace(
        updated=updated,
        title=render_user_title(conversation),
        link=f"{entry.feed_url}/status/{conversation.id}",
        author=f"@{user.username}",
        published=published,
        content=[
            Content(json.dumps(conversation.to_json()), MIME_TYPE_JSON),
            Content(
                render_user_html(conversation, parsed_url.with_replies), MIME_TYPE_HTML
            ),
        ],
    )

    # TODO: title and author should be of quoted tweet?


def render_user_title(conversation):
    # TODO: don't call conversation_tree() twice?
    tree = conversation_tree(conversation, False)
    title = expand_entities(tree)
    return title


def render_user_html(conversation, with_replies):
    tree = conversation_tree(conversation, with_replies)
    nodes = flatten_tree(tree)
    html = jinja_env.get_template('tweet.html').render(nodes=nodes)
    return html


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
                data.tweets.get(r.id)
                for r in tweet.referenced_tweets or ()
                if r.type == type
            ]

            if not tweets:
                return None

            # TODO: assert we got exactly one
            referenced_tweet = tweets[0]
            if not referenced_tweet:
                return Node(None, None)

            return make_node(referenced_tweet.id, wrapped=True)

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

{%- macro author_link(node, class=none) -%}
<a href="https://twitter.com/{{ node.author.username }}"
{%- if class %} class="{{ class }}"{% endif -%}
>{{ caller() }}</a>
{%- endmacro -%}

{%- macro tweet_link(node, class=none) -%}
<a href="https://twitter.com/{{ node.author.username }}/status/{{ node.tweet.id }}"
{%- if class %} class="{{ class }}"{% endif -%}
>{{ caller() }}</a>
{%- endmacro -%}


{%- macro do_node(node, level=0, class="tweet") -%}
<div{% if class %} class="{{ class }}"{% endif %}>
{% if node.tweet %}

<p class="top-line">
{% if not node.retweeted %}
{% call author_link(node, "name") %}{{ node.author.name }}{% endcall %}
{% call author_link(node, "username") %}@{{ node.author.username }}{% endcall %}
· {% call tweet_link(node, "created-at") %}{{ node.tweet.created_at.date() }}{% endcall %}
{% else %}
{% call author_link(node, "name-retweeted") %}{{ node.author.name }} retweeted{% endcall %}
{% endif %}
</p>

{% if not node.retweeted %}
<p class="text">{{ node | expand_entities | nl2br }}</p>
{% endif %}

{% for poll in node.polls %}
{% if poll %}
<ul class="poll">
{% for option in poll.options | sort(attribute='position') %}
<li><span class="label">{{ option.label }}</span> <span class="votes">{{ option.votes }}</span>
{% endfor %}
</ul>
{% else %}
<p class="poll"><em>[missing poll object]</em></p>
{% endif %}
{% endfor %}

{% for media in node.media %}
{% if media %}

{% if media.type in ('animated_gif', 'photo') %}

{% call tweet_link(node) %}
<img class="media {{ 'gif' if media.type == 'animated_gif' else media.type }}" src="{{ media.url }}"
    {%- if media.alt_text %} alt="{{ media.alt_text }}"{% endif -%}
>
{% endcall %}

{% elif media.type == 'video' %}

{% call tweet_link(node) %}
<img class="media video" src="{{ media.preview_image_url }}"
    {%- if media.alt_text %} alt="{{ media.alt_text }}"{% endif -%}
>
{% endcall %}

{% endif %}

{% else %}
<p class="media"><em>[missing media object]</em></p>
{% endif %}
{% endfor %}

{% if node.quoted %}
{{ do_node(node.quoted, class="tweet tweet-quote") }}
{% endif %}

{% if node.retweeted %}
{{ do_node(node.retweeted, class="tweet tweet-retweet") }}
{% endif %}

{% else %}
<p class="text"><em>[missing tweet object]</em></p>
{% endif %}
</div>


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


@jinja2.pass_eval_context
def nl2br(eval_ctx, value):
    # from https://jinja.palletsprojects.com/en/3.0.x/api/#writing-filters
    br = "<br>\n"
    if eval_ctx.autoescape:
        value = markupsafe.escape(value)
        br = markupsafe.Markup(br)
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    result = re.sub('\n', br, value)
    return markupsafe.Markup(result) if eval_ctx.autoescape else result


def expand_entities(node) -> str:
    tweet = node.tweet

    highlights = []
    replacements = {}

    have_media_keys = {m.media_key for m in node.media if m}
    for entity in (tweet.entities or {}).get('urls', ()):
        highlight = slice(entity['start'], entity['end'])
        original = tweet.text[highlight]

        if original in replacements:
            continue

        highlights.append(highlight)

        media_key = entity.get('media_key')
        if media_key and media_key in have_media_keys:
            # we're already showing it in media, no point in linking it
            replacements[original] = ''
        else:
            replacements[original] = (
                jinja_env.get_template('url.html')
                .render(original=original, entity=entity)
                .strip()
            )

    def func(part):
        return replacements.get(part, part)

    return HighlightedString(tweet.text, highlights).apply('', '', func)


URL_HTML_TEMPLATE = """
<a href="{{ entity.expanded_url }}"
{%- if entity.get('title') %} title="{{ entity.title }}"{% endif -%}
>{{ entity.display_url }}</a>
"""


jinja_env = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    loader=jinja2.DictLoader(
        {
            'tweet.html': TWEET_HTML_TEMPLATE,
            'url.html': URL_HTML_TEMPLATE,
        }
    ),
)

jinja_env.filters['nl2br'] = nl2br
jinja_env.filters['expand_entities'] = expand_entities


def init_reader(reader):
    reader._parser.mount_retriever(URL_PREFIX, Retriever(reader))
    reader._parser.mount_parser_by_mime_type(Parser(reader))
