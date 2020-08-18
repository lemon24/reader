import copy
import functools
import json
import logging
import os.path
import traceback

import click

import reader
from . import StorageError
from ._config import load_config
from ._config import make_reader_from_config
from ._config import merge_config
from ._plugins import LoaderError
from ._sqlite_utils import DebugConnection


APP_NAME = reader.__name__

log = logging.getLogger(__name__)


def get_default_db_path(create_dir=False):
    app_dir = click.get_app_dir(APP_NAME)
    db_path = os.path.join(app_dir, 'db.sqlite')
    if create_dir:
        os.makedirs(app_dir, exist_ok=True)
    return wrap_default(db_path)


def get_default_config_path():
    return wrap_default(os.path.join(click.get_app_dir(APP_NAME), 'config.yaml'))


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
        abort("{}: {}: {}", kwargs['url'], e, e.__cause__)
    except LoaderError as e:
        abort("{}; original traceback follows\n\n{}", e, format_tb(e.__cause__ or e))
    except Exception as e:
        abort("unexpected error; original traceback follows\n\n{}", format_tb(e))


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


# BEGIN defaults
# stupid way of marking some values as defaults;
# a better way would be to use a proxy;
# FIXME: we should use https://wrapt.readthedocs.io/en/latest/wrappers.html


class Default:
    pass


class Default_bool(int, Default):
    # workaround for it not being possible to subclass bool.
    # however, this breaks Click, see wrap_param_default() for details.
    def __str__(self):
        return str(bool(self))


@functools.lru_cache()
def make_default_wrapper(cls):
    if cls is bool:
        return Default_bool
    return type('Default_' + cls.__name__, (cls, Default), {})


def wrap_default(thing):
    # assumes type(thing)(thing) will return another thing;
    # to support other constructor types, we could
    #   thing.__class__ = make_default_wrapper(type(thing))
    # but that works only for heap types.
    assert type(thing) in (int, bool, float, str, bytes, list, tuple, dict), thing
    return make_default_wrapper(type(thing))(thing)


def is_default(thing):
    return isinstance(thing, Default)


def split_defaults(dict):
    defaults = {}
    options = {}
    for k, v in dict.items():
        if not v:
            continue
        (defaults if is_default(v) else options)[k] = v
    return defaults, options


def wrap_param_default(param, value):
    # can't use our Default_bool for click defaults, because
    # BoolParamType calls isinstance(value, bool); if false,
    # it assumes it's a string that looks like a boolean ("true", "yes" etc.),
    # so we make our value look like that (while still marking it as default).
    if isinstance(value, bool) and isinstance(param.type, click.types.BoolParamType):
        return wrap_default(str(bool(value)).lower())
    return wrap_default(value)


def mark_command_defaults(command):
    # decorator for commands with options that end up in the config
    # passed to make_reader_from_config;
    # if not used, the config order won't work properly
    for param in command.params:
        if param.default is not None:
            param.default = wrap_param_default(param, param.default)
    return command


def mark_default_map_defaults(command, defaults):
    for param in command.params:
        if param.name in defaults:
            defaults[param.name] = wrap_param_default(param, defaults[param.name])
    for command_name, command in getattr(command, 'commands', {}).items():
        mark_default_map_defaults(command, defaults.get(command_name, {}))


# END defaults


def load_config_callback(ctx, param, value):
    try:
        with open(value) as file:
            config = load_config(file)
    except FileNotFoundError as e:
        if not is_default(value):
            raise click.BadParameter(str(e), ctx=ctx, param=param)
        config = {}

    for key in 'reader', 'cli', 'app':
        config.setdefault(key, {})

    ctx.default_map = copy.deepcopy(config.get('cli', {}).get('defaults', {}))
    mark_default_map_defaults(ctx.command, ctx.default_map)
    ctx.obj = config
    return config


def pass_reader(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context().find_root()
        reader = make_reader_with_plugins(**ctx.obj['reader'])
        ctx.call_on_close(reader.close)
        return fn(reader, *args, **kwargs)

    return wrapper


@click.group()
@click.option(
    '--db',
    type=click.Path(dir_okay=False),
    envvar=reader._DB_ENVVAR,
    default=get_default_db_path(),
    show_default=True,
    help="Path to the reader database.",
)
@click.option(
    '--plugin',
    multiple=True,
    envvar=reader._PLUGIN_ENVVAR,
    help="Import path to a plug-in. Can be passed multiple times.",
)
@click.option(
    '--config',
    type=click.Path(dir_okay=False),
    envvar=reader._CONFIG_ENVVAR,
    help="Path to the reader config.",
    default=get_default_config_path(),
    show_default=True,
    callback=load_config_callback,
    is_eager=True,
    expose_value=False,
)
@click.option(
    '--debug-storage/--no-debug-storage',
    hidden=True,
    help="NOT TESTED. With -vv, log storage database calls.",
)
@click.version_option(reader.__version__, message='%(prog)s %(version)s')
@click.pass_obj
def cli(config, db, plugin, debug_storage):
    # TODO: there's a better way of doing this
    if db == get_default_config_path() and is_default(db):
        try:
            db = get_default_db_path(create_dir=True)
        except Exception as e:
            abort("{}", e)

    default_options, user_options = split_defaults(
        {
            'url': db,
            'plugins': {p: None for p in plugin},
            # until we make debug_storage a proper make_reader argument,
            # and we get rid of make_reader_with_plugins
            'debug_storage': debug_storage,
        }
    )

    # wrap reader section with options;
    # will be used by app to spawn non-app readers
    config['reader'] = merge_config(default_options, config['reader'], user_options)


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
@log_command
@pass_reader
def update(reader, url, new_only, workers):
    """Update one or all feeds.

    If URL is not given, update all the feeds.

    """
    if url:
        reader.update_feed(url)
    else:
        reader.update_feeds(new_only=new_only, workers=workers)


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


try:
    from reader._app.cli import serve

    cli.add_command(serve)
except ImportError:
    pass


if __name__ == '__main__':
    cli()
