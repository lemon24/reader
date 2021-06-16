import functools
import json
import logging
import os.path
import sys
import traceback
from contextlib import nullcontext
from datetime import datetime

import click
import yaml

import reader
from . import ParseError
from . import ReaderError
from . import StorageError
from ._config import make_reader_config
from ._config import make_reader_from_config
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


def get_default_config_path():
    return os.path.join(click.get_app_dir(APP_NAME), 'config.yaml')


def format_tb(e):
    return ''.join(traceback.format_exception(type(e), e, e.__traceback__))


def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


def make_reader_with_plugins(*, debug_storage=False, **kwargs):

    if debug_storage:
        # TODO: the web app should be able to do this too

        log_debug = logging.getLogger('reader._storage').debug
        pid = os.getpid()

        class Connection(DebugConnection):
            _io_counters = True

            @staticmethod
            def _log_method(data):
                data['pid'] = pid
                log_debug(json.dumps(data))

        kwargs['_storage_factory'] = Connection

    try:
        return make_reader_from_config(**kwargs)
    except StorageError as e:
        abort("{}: {}", kwargs['url'], e)
    except LoaderError as e:
        abort("{}; original traceback follows\n\n{}", e, format_tb(e.__cause__ or e))
    except Exception as e:
        abort("unexpected error; original traceback follows\n\n{}", format_tb(e))


def setup_logging(verbose):
    if verbose < 0:
        return
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


def make_log_verbose(expose_value=False, initial=0):
    def log_verbose(fn):
        @click.option('-v', '--verbose', count=True)
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            setup_logging(kwargs['verbose'] + initial)
            if not expose_value:
                del kwargs['verbose']
            return fn(*args, **kwargs)

        return wrapper

    return log_verbose


log_verbose = make_log_verbose()


def log_command(fn):
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
            if not isinstance(e, ReaderError):
                raise
            click.get_current_context().exit(1)

    return wrapper


def config_option(*args, **kwargs):
    def callback(ctx, param, value):
        # TODO: the default file is allowed to not exist, a user specified file must exist
        try:
            with open(value) as file:
                config = make_reader_config(yaml.safe_load(file))
        except FileNotFoundError as e:
            if value != param.default:
                raise click.BadParameter(str(e), ctx=ctx, param=param)
            config = make_reader_config({})

        ctx.default_map = config['cli'].get('defaults', {})

        ctx.obj = config
        return config

    def inner(fn):
        return click.option(
            *args,
            type=click.Path(dir_okay=False),
            callback=callback,
            is_eager=True,
            expose_value=False,
            **kwargs,
        )(fn)

    return inner


def pass_reader(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context().find_root()
        # TODO: replace with ctx.obj.make_reader('cli') when we get rid of debug_storage
        reader = make_reader_with_plugins(**ctx.obj.merged('cli').get('reader', {}))
        ctx.call_on_close(reader.close)
        return fn(reader, *args, **kwargs)

    return wrapper


@click.group()
@click.option(
    '--db',
    type=click.Path(dir_okay=False),
    envvar=reader._DB_ENVVAR,
    show_default=True,
    help=f"Path to the reader database. [default: {get_default_db_path()}]",
)
@click.option(
    '--plugin',
    multiple=True,
    envvar=reader._PLUGIN_ENVVAR,
    help="Import path to a reader plug-in. Can be passed multiple times.",
)
@config_option(
    '--config',
    envvar=reader._CONFIG_ENVVAR,
    help="Path to the reader config.",
    default=get_default_config_path(),
    show_default=True,
)
@click.option(
    '--debug-storage/--no-debug-storage',
    hidden=True,
    help="NOT TESTED. With -vv, log storage database calls.",
)
@click.version_option(reader.__version__, message='%(prog)s %(version)s')
@click.pass_obj
def cli(config, db, plugin, debug_storage):
    # TODO: mention in docs that --db/--plugin/envvars ALWAYS override the config
    # (same for wsgi envvars)
    # NOTE: we can never use click defaults for --db/--plugin, because they would override the config always

    if db:
        config.all['reader']['url'] = db
    else:
        # ... could be the 'cli' section, maybe...
        if not config['default'].get('reader', {}).get('url'):
            try:
                db = get_default_db_path(create_dir=True)
            except Exception as e:
                abort("{}", e)
            config.all['reader']['url'] = db

    if plugin:
        config.all['reader']['plugins'] = dict.fromkeys(plugin)

    # until we make debug_storage a proper make_reader argument,
    # and we get rid of make_reader_with_plugins
    config['default']['reader']['debug_storage'] = debug_storage


@cli.command()
@click.argument('url')
@click.option('--update/--no-update', help="Update the feed after adding it.")
@log_verbose
@pass_reader
def add(reader, url, update):
    """Add a new feed."""
    reader.add_feed(url)
    if update:
        reader.update_feed(url)


@cli.command()
@click.argument('url')
@log_verbose
@pass_reader
def remove(reader, url):
    """Remove an existing feed."""
    reader.delete_feed(url)


def red(text):
    return click.style(str(text), fg='bright_red')


def green(text):
    return click.style(str(text), fg='bright_green')


def get_update_status(value):
    if value is None:
        return None
    if isinstance(value, Exception):
        return False
    if not (value.new or value.modified):
        return None
    return True


def iter_update_status(it, length):
    start = datetime.now()

    for i, (url, value) in enumerate(it):
        elapsed = datetime.now() - start
        pos = f"{i}/{length or '?'}"

        update_status = get_update_status(value)

        if update_status is None:
            status = 'not modified'
        elif not update_status:
            status = red(value)
        else:
            status = green(f"{value.new} new, {value.modified} modified")

        click.echo(f"{elapsed}\t{pos}\t{url}\t{status}")

        yield url, value


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
@make_log_verbose(True, -2)
@log_command
@pass_reader
def update(reader, url, new_only, workers, verbose):
    """Update one or all feeds.

    If URL is not given, update all the feeds.

    Verbosity works like this:

    \b
        : progress bar + final status
        -v: + lines
        -vv: + warnings
        -vvv: + info
        -vvvv: + debug

    """
    if url:

        def make_it():
            try:
                yield url, reader.update_feed(url)
            except ParseError as e:
                yield url, e

        it = make_it()
    else:
        it = reader.update_feeds_iter(new=True if new_only else None, workers=workers)

    ok_count = 0
    not_modified_count = 0
    error_count = 0
    new_count = 0
    updated_count = 0

    def feed_stats(width=None):
        if not width:
            width, _ = click.get_terminal_size()
        if width < 80:
            return ''
        if width < 105:
            return f"{green(ok_count)}/{red(error_count)}/{not_modified_count}"
        return (
            f"{green(f'{ok_count} ok') if ok_count else '0 ok'}, "
            f"{red(f'{error_count} error') if error_count else '0 error'}, "
            f"{not_modified_count} not modified"
        )

    if url:
        length = 1
    else:
        if not new_only:
            length = reader.get_feed_counts(updates_enabled=True).total
        else:
            # TODO: pending https://github.com/lemon24/reader/issues/217
            length = None

    if not verbose:
        bar_context = click.progressbar(
            it,
            length=length,
            label='update',
            show_pos=True,
            show_eta=True,
            item_show_func=lambda _: feed_stats(),
            file=sys.stderr,
        )

    else:
        bar_context = nullcontext(iter_update_status(it, length))

    try:
        with bar_context as bar:
            for _, value in bar:
                update_status = get_update_status(value)
                if update_status is None:
                    not_modified_count += 1
                elif not update_status:
                    error_count += 1
                else:
                    ok_count += 1
                    new_count += value.new
                    updated_count += value.modified
    finally:
        click.echo(
            f"{feed_stats(9999)}; entries: {new_count} new, {updated_count} modified"
        )


@cli.group('list')
def list_cmd():
    """List feeds or entries."""


@list_cmd.command()
@pass_reader
def feeds(reader):
    """List all the feeds."""
    for feed in reader.get_feeds():
        click.echo(feed.url)


@list_cmd.command()
@pass_reader
def entries(reader):
    """List all the entries.

    Outputs one line per entry in the following format:

        <feed URL> <entry link or id>

    """
    for entry in reader.get_entries():
        click.echo("{} {}".format(entry.feed.url, entry.link or entry.id))


@cli.group()
def search():
    """Do various things related to search."""


@search.command('status')
@pass_reader
def search_status(reader):
    """Check search status."""
    click.echo(f"search: {'enabled' if reader.is_search_enabled() else 'disabled'}")


@search.command('enable')
@pass_reader
def search_enable(reader):
    """Enable search."""
    reader.enable_search()


@search.command('disable')
@pass_reader
def search_disable(reader):
    """Disable search."""
    reader.disable_search()


@search.command('update')
@log_verbose
@log_command
@pass_reader
def search_update(reader):
    """Update the search index."""
    reader.update_search()


@search.command('entries')
@click.argument('query')
@pass_reader
def search_entries(reader, query):
    """Search entries.

    Outputs one line per entry in the following format:

        <feed URL> <entry link or id>

    """
    for rv in reader.search_entries(query):
        entry = reader.get_entry(rv)
        click.echo("{} {}".format(entry.feed.url, entry.link or entry.id))


@cli.group()
def config():
    """Do various things related to config."""


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


@config.command()
@click.option('--merge/--no-merge')
@click.pass_obj
def dump(config, merge):
    if merge:
        config = config.merge_all()
    click.echo(yaml.dump(config.data, sort_keys=False, Dumper=Dumper))


try:
    from reader._app.cli import serve

    cli.add_command(serve)
except ImportError:
    pass


if __name__ == '__main__':
    cli()
