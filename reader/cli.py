import os.path
import os

import click

from .db import open_db
from .reader import Reader


APP_NAME = 'reader'
DB_ENVVAR = '{}_DB'.format(APP_NAME.upper())


def get_default_db_path(create_dir=False):
    app_dir = click.get_app_dir(APP_NAME)
    db_path = os.path.join(app_dir, 'db.sqlite')
    if create_dir:
        os.makedirs(app_dir, exist_ok=True)
    return db_path


def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


@click.group()
@click.option('--db', type=click.Path(dir_okay=False), envvar=DB_ENVVAR)
@click.pass_context
def cli(ctx, db):
    if db is None:
        try:
            db = get_default_db_path(create_dir=True)
        except Exception as e:
            abort("{}", e)
    try:
        ctx.obj = open_db(db)
    except Exception as e:
        abort("{}: {}", db, e)


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
    cli()
