import os.path
import time
import datetime
import json

import click
import feedparser

from .db import open_db


APP_NAME = 'reader'


def get_default_db_path():
    return os.path.join(click.get_app_dir(APP_NAME), 'db')

def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


def datetime_from_timetuple(tt):
    return datetime.datetime.fromtimestamp(time.mktime(tt)) if tt else None


@click.group()
@click.option('--db', default=get_default_db_path, type=click.Path(dir_okay=False))
@click.pass_context
def cli(ctx, db):
    ctx.obj = open_db(db)


@cli.command()
@click.argument('url')
@click.pass_obj
def add(db, url):
    with db:
        db.execute("""
            INSERT INTO feeds (url)
            VALUES (:url);
        """, locals())


@cli.command()
@click.pass_obj
def update(db):
    cursor =  db.execute("""
        SELECT url, etag, modified_original FROM feeds
    """)

    for url, etag, modified_original in cursor:
        feed = feedparser.parse(url, etag=etag, modified=modified_original)

        if feed.get('status') == 304:
            continue

        with db:
            etag = feed.get('etag')
            modified_original = feed.get('modified')
            title = feed.feed.get('title')
            link = feed.feed.get('link')

            db.execute("""
                UPDATE feeds
                SET etag = :etag, modified_original = :modified_original, title = :title, link = :link
                WHERE url = :url;
            """, locals())

            for entry in feed.entries:
                updated = datetime_from_timetuple(entry.get('updated_parsed'))
                assert updated
                published = datetime_from_timetuple(entry.get('published_parsed'))

                assert entry.id
                db_tuple = db.execute("""
                    SELECT updated FROM entries
                    WHERE feed = ? AND id = ?;
                """, (url, entry.id)).fetchone()
                db_updated = db_tuple[0] if db_tuple else None

                if not db_updated:
                    db.execute("""
                        INSERT INTO entries (
                            id, feed, title, link, content, published, updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (
                        entry.id, url,
                        entry.get('title'), entry.get('link'),
                        json.dumps(entry.get('content')),
                        published, updated,
                    ))

                elif updated > db_updated:
                    db.execute("""
                        UPDATE entries
                        SET title = ?, link = ?, content = ?, published = ?, updated = ?
                        WHERE feed = ? AND id = ?;
                    """, (
                        entry.get('title'), entry.get('link'),
                        json.dumps(entry.get('content')),
                        published, updated,
                        url, entry.id,
                    ))


@cli.command()
@click.pass_obj
def serve(db):
    from werkzeug.serving import run_simple
    from .app import app
    app.db = db
    run_simple('localhost', 8080, app)








if __name__ == '__main__':
    cli(auto_envvar_prefix=APP_NAME.upper())
