import functools
import json
import logging
import os.path
import traceback

import click

import reader
from . import make_reader
from . import StorageError
from ._plugins import Loader
from ._plugins import LoaderError
from ._sqlite_utils import DebugConnection


APP_NAME = reader.__name__

log = logging.getLogger(__name__)


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


def make_reader_with_plugins(db_path, plugins, debug_storage):

    kwargs = {}
    if debug_storage:
        log_debug = logging.getLogger('reader._storage').debug
        pid = os.getpid()

        class Connection(DebugConnection):
            @staticmethod
            def _log_method(data):
                data['pid'] = pid
                log_debug(json.dumps(data))

        kwargs['_storage_factory'] = Connection

    try:
        reader = make_reader(db_path, **kwargs)
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
        '%(asctime)s %(process)7s %(levelname)-8s %(message)s', '%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logging.getLogger('reader').addHandler(handler)


def log_verbose(fn):
    @click.option('-v', '--verbose', count=True)
    @functools.wraps(fn)
    def wrapper(*args, verbose, **kwargs):
        setup_logging(verbose)
        return fn(*args, **kwargs)

    return wrapper


def log_command(fn):
    @log_verbose
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        params = []
        while ctx:
            params.append((ctx.info_name, ctx.params))
            ctx = ctx.parent

        log.info(
            "command started: %s", ' '.join(f"{n} {p}" for n, p in reversed(params))
        )

        try:
            rv = fn(*args, **kwargs)
            log.info("command finished successfully")
            return rv

        except Exception as e:
            log.critical(
                "command failed due to unexpected error: %s; traceback follows",
                e,
                exc_info=True,
            )
            click.get_current_context().exit(1)

    return wrapper


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
@click.option(
    '--debug-storage/--no-debug-storage',
    hidden=True,
    help="NOT TESTED. With -vv, log storage database calls.",
)
@click.version_option(reader.__version__, message='%(prog)s %(version)s')
@click.pass_context
def cli(ctx, db, plugin, debug_storage):
    if db is None:
        try:
            db = get_default_db_path(create_dir=True)
        except Exception as e:
            abort("{}", e)
    ctx.obj = {'db_path': db, 'plugins': plugin, 'debug_storage': debug_storage}


@cli.command()
@click.argument('url')
@click.option('--update/--no-update', help="Update the feed after adding it.")
@click.pass_obj
@log_verbose
def add(kwargs, url, update):
    """Add a new feed."""
    reader = make_reader_with_plugins(**kwargs)
    reader.add_feed(url)
    if update:
        reader.update_feed(url)


@cli.command()
@click.argument('url')
@click.pass_obj
@log_verbose
def remove(kwargs, url):
    """Remove an existing feed."""
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
@click.pass_obj
@log_command
def update(kwargs, url, new_only, workers):
    """Update one or all feeds.

    If URL is not given, update all the feeds.

    """
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
@log_command
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
