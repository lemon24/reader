import logging
import os.path
import traceback

import click

import reader
from . import make_reader
from . import StorageError
from ._plugins import Loader
from ._plugins import LoaderError


APP_NAME = reader.__name__


def get_default_db_path(create_dir=False):
    app_dir = click.get_app_dir(APP_NAME)
    db_path = os.path.join(app_dir, 'db.sqlite')
    if create_dir:
        os.makedirs(app_dir, exist_ok=True)
    return db_path


def format_tb(e):
    return ''.join(traceback.format_exception(type(e), e, e.__traceback__))


def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


def make_reader_with_plugins(db_path, plugins):
    try:
        reader = make_reader(db_path)
    except StorageError as e:
        abort("{}: {}: {}", db_path, e, e.__cause__)
    except Exception as e:
        abort("unexpected error; original traceback follows\n\n{}", format_tb(e))

    try:
        loader = Loader(plugins)
        loader.load_plugins(reader)
    except LoaderError as e:
        abort("{}; original traceback follows\n\n{}", e, format_tb(e.__cause__ or e))

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
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)-7s %(message)s', '%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logging.getLogger('reader').addHandler(handler)


@click.group()
@click.option(
    '--db',
    type=click.Path(dir_okay=False),
    envvar=reader._DB_ENVVAR,
    help="Path to the reader database. Defaults to {}.".format(get_default_db_path()),
)
@click.option(
    '--plugin',
    multiple=True,
    envvar=reader._PLUGIN_ENVVAR,
    help="Import path to a plug-in. Can be passed multiple times.",
)
@click.version_option(reader.__version__, message='%(prog)s %(version)s')
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
@click.option('--update/--no-update', help="Update the feed after adding it.")
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def add(kwargs, url, update, verbose):
    """Add a new feed."""
    setup_logging(verbose)
    reader = make_reader_with_plugins(**kwargs)
    reader.add_feed(url)
    if update:
        reader.update_feed(url)


@cli.command()
@click.argument('url')
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def remove(kwargs, url, verbose):
    """Remove an existing feed."""
    setup_logging(verbose)
    reader = make_reader_with_plugins(**kwargs)
    reader.remove_feed(url)


@cli.command()
@click.argument('url', required=False)
@click.option(
    '--new-only/--no-new-only', help="Only update new (never updated before) feeds."
)
@click.option(
    '--workers',
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Number of threads to use when getting the feeds.",
)
@click.option('-v', '--verbose', count=True)
@click.pass_obj
def update(kwargs, url, new_only, workers, verbose):
    """Update one or all feeds.

    If URL is not given, update all the feeds.

    """
    setup_logging(verbose)
    reader = make_reader_with_plugins(**kwargs)
    if url:
        reader.update_feed(url)
    else:
        reader.update_feeds(new_only=new_only, workers=workers)


@cli.group()
def list():
    """List feeds or entries."""


@list.command()
@click.pass_obj
def feeds(kwargs):
    """List all the feeds."""
    reader = make_reader_with_plugins(**kwargs)
    for feed in reader.get_feeds():
        click.echo(feed.url)


@list.command()
@click.pass_obj
def entries(kwargs):
    """List all the entries.

    Outputs one line per entry in the following format:

        <feed URL> <entry link or id>

    """
    reader = make_reader_with_plugins(**kwargs)
    for entry in reader.get_entries():
        click.echo("{} {}".format(entry.feed.url, entry.link or entry.id))


@cli.group()
def search():
    """Do various things related to search."""


@search.command('status')
@click.pass_obj
def search_status(kwargs):
    """Check search status."""
    reader = make_reader_with_plugins(**kwargs)
    click.echo(f"search: {'enabled' if reader.is_search_enabled() else 'disabled'}")


@search.command('enable')
@click.pass_obj
def search_enable(kwargs):
    """Enable search."""
    reader = make_reader_with_plugins(**kwargs)
    reader.enable_search()


@search.command('disable')
@click.pass_obj
def search_disable(kwargs):
    """Disable search."""
    reader = make_reader_with_plugins(**kwargs)
    reader.disable_search()


@search.command('update')
@click.pass_obj
def search_update(kwargs):
    """Update the search index."""
    reader = make_reader_with_plugins(**kwargs)
    reader.update_search()


@search.command('entries')
@click.argument('query')
@click.pass_obj
def search_entries(kwargs, query):
    """Search entries.

    Outputs one line per entry in the following format:

        <feed URL> <entry link or id>

    """
    reader = make_reader_with_plugins(**kwargs)
    for rv in reader.search_entries(query):
        entry = reader.get_entry(rv)
        click.echo("{} {}".format(entry.feed.url, entry.link or entry.id))


try:
    from reader._app.cli import serve

    cli.add_command(serve)
except ImportError:
    pass


if __name__ == '__main__':
    cli()
