import os.path

import click
import feedparser

from .db import open_db
from .reader import Reader

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
    Reader(db).add_feed(url)


@cli.command()
@click.pass_obj
def update(db):
    Reader(db).update_feeds()


@cli.command()
@click.pass_obj
def serve(db):
    from werkzeug.serving import run_simple
    from .app import app
    app.reader = Reader(db)
    run_simple('localhost', 8080, app)








if __name__ == '__main__':
    cli(auto_envvar_prefix=APP_NAME.upper())
