import os.path
import os
import logging

import click

from . import Reader
from .plugin import load_plugins


APP_NAME = 'reader'
DB_ENVVAR = '{}_DB'.format(APP_NAME.upper())
PLUGIN_ENVVAR = '{}_PLUGIN'.format(APP_NAME.upper())


def get_default_db_path(create_dir=False):
    app_dir = click.get_app_dir(APP_NAME)
    db_path = os.path.join(app_dir, 'db.sqlite')
    if create_dir:
        os.makedirs(app_dir, exist_ok=True)
    return db_path


def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


def make_reader(db_path, plugins):
    try:
        reader = Reader(db_path)
    except Exception as e:
        abort("{}: {}", db_path, e)
    try:
        load_plugins(reader, plugins)
    except Exception as e:
        abort("while loading plugins: {}".format(e))
    return reader


def setup_logging(verbose):
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG
    logging.getLogger('reader').setLevel(level)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)-7s %(message)s', '%Y-%m-%dT%H:%M:%S')
    handler.setFormatter(formatter)
    logging.getLogger('reader').addHandler(handler)


@click.group()
@click.option('--db', type=click.Path(dir_okay=False), envvar=DB_ENVVAR,
    help="Path to the reader database. Defaults to {}."
         .format(get_default_db_path()))
@click.option('--plugin', multiple=True, envvar=PLUGIN_ENVVAR,
    help="Import path to a plug-in. Can be passed multiple times.")
@click.pass_context
def cli(ctx, db, plugin):
    if db is None:
        try:
            db = get_default_db_path(create_dir=True)
        except Exception as e:
            abort("{}", e)
    ctx.obj = {'db_path': db, 'plugins': plugin}


@cli.command()
@click.argument('url')
@click.option('--update/--no-update',
    help="Update the feed after adding it.")
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def add(kwargs, url, update, verbose):
    """Add a new feed.
    
    """
    setup_logging(verbose)
    reader = make_reader(**kwargs)
    reader.add_feed(url)
    if update:
        reader.update_feed(url)


@cli.command()
@click.argument('url')
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def remove(kwargs, url, verbose):
    """Remove an existing feed.
    
    """
    setup_logging(verbose)
    reader = make_reader(**kwargs)
    reader.remove_feed(url)


@cli.command()
@click.argument('url', required=False)
@click.option('--new-only/--no-new-only',
    help="Only update new (never updated before) feeds.")
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def update(kwargs, url, new_only, verbose):
    """Update one or all feeds.
    
    If URL is not given, update all the feeds.
    
    """
    setup_logging(verbose)
    reader = make_reader(**kwargs)
    if url:
        reader.update_feed(url)
    else:
        reader.update_feeds(new_only=new_only)


@cli.group()
def list():
    """List feeds or entries."""
    pass


@list.command()
@click.pass_obj
def feeds(kwargs):
    """List all the feeds.
    
    """
    reader = make_reader(**kwargs)
    for feed in reader.get_feeds():
        click.echo(feed.url)


@list.command()
@click.pass_obj
def entries(kwargs):
    """List all the entries.
    
    Outputs one line per entry in the following format:
    
        <feed URL> <entry link or id>
    
    """
    reader = make_reader(**kwargs)
    for entry in reader.get_entries():
        click.echo("{} {}".format(entry.feed.url, entry.link or entry.id))


try:
    from reader.app.cli import serve
    cli.add_command(serve)
except ImportError:
    pass


if __name__ == '__main__':
    cli()
