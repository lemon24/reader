import os.path
import os
import logging

import click

from .reader import Reader
import reader.reader


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


def setup_logging(verbose):
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG
    reader.reader.log.setLevel(level)
    logging.basicConfig()


@click.group()
@click.option('--db', type=click.Path(dir_okay=False), envvar=DB_ENVVAR)
@click.pass_context
def cli(ctx, db):
    if db is None:
        try:
            db = get_default_db_path(create_dir=True)
        except Exception as e:
            abort("{}", e)
    ctx.obj = db


@cli.command()
@click.argument('url')
@click.pass_obj
def add(db_path, url):
    setup_logging(verbose)
    try:
        reader = Reader(db_path)
    except Exception as e:
        abort("{}: {}", db_path, e)
    reader.add_feed(url)


@cli.command()
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def update(db_path, verbose):
    setup_logging(verbose)
    try:
        reader = Reader(db_path)
    except Exception as e:
        abort("{}: {}", db_path, e)
    reader.update_feeds()


@cli.command()
@click.pass_obj
def serve(db_path):
    from werkzeug.serving import run_simple
    from .app import app
    app.config['READER_DB'] = db_path
    run_simple('localhost', 8080, app)








if __name__ == '__main__':
    cli()
