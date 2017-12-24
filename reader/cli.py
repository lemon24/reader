import os.path

import click
import feedparser

from .db import open_db


APP_NAME = 'reader'


def get_default_db_path():
    return os.path.join(click.get_app_dir(APP_NAME), 'db')

def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


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












if __name__ == '__main__':
    cli(auto_envvar_prefix=APP_NAME.upper())
