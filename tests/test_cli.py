import logging
import os
import pathlib
from datetime import timedelta

import click
import pytest
import yaml
from click.testing import CliRunner

from reader import Reader
from reader import ReaderError
from reader import UpdateHookError
from reader._cli import cli
from reader._cli import config_option
from reader.types import MISSING
from utils import make_url_base


@pytest.fixture(autouse=True)
def reset_logging(pytestconfig):
    # from https://github.com/pallets/flask/blob/1.1.x/tests/test_logging.py#L20

    root_handlers = logging.root.handlers[:]
    logging.root.handlers = []
    root_level = logging.root.level

    logger = logging.getLogger("reader")
    handlers = logger.handlers[:]
    level = logger.level

    logging_plugin = pytestconfig.pluginmanager.unregister(name="logging-plugin")

    yield

    logging.root.handlers[:] = root_handlers
    logging.root.setLevel(root_level)

    logger.handlers[:] = handlers
    logger.setLevel(level)

    if logging_plugin:
        pytestconfig.pluginmanager.register(logging_plugin, "logging-plugin")


@pytest.fixture(autouse=True)
def patch_app_dir(monkeypatch, tmp_path):
    """Ignore local config while running tests.

    https://github.com/lemon24/reader/issues/355

    """

    def get_app_dir(app_name):
        return str(tmp_path.joinpath('app_dir', app_name))

    monkeypatch.setattr('click.get_app_dir', get_app_dir)


@pytest.mark.slow
def test_cli(db_path, data_dir, monkeypatch):
    feed_filename = 'full.atom'
    feed_path = str(data_dir.joinpath(feed_filename))

    url_base, rel_base = make_url_base(feed_path)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.joinpath(feed_filename + '.py').read_text(), expected)

    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(cli, ('--db', db_path, '--feed-root', '') + args)

    result = invoke('list', 'feeds')
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('add', feed_path)
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('list', 'feeds')
    assert result.exit_code == 0
    assert result.output.splitlines() == [feed_path]

    result = invoke('list', 'entries')
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('update')
    assert result.exit_code == 0
    assert "1 ok, 0 error, 0 not modified; entries: 5 new, 0 modified" in result.output

    result = invoke('update')
    assert result.exit_code == 0
    assert "0 ok, 0 error, 1 not modified; entries: 0 new, 0 modified" in result.output

    result = invoke('update', '--scheduled')
    assert result.exit_code == 0
    assert "0 ok, 0 error, 0 not modified; entries: 0 new, 0 modified" in result.output

    now = Reader._now()
    monkeypatch.setattr(Reader, '_now', staticmethod(lambda: now + timedelta(hours=1)))

    result = invoke('update', '--scheduled')
    assert result.exit_code == 0
    assert "0 ok, 0 error, 1 not modified; entries: 0 new, 0 modified" in result.output

    result = invoke('list', 'feeds')
    assert result.exit_code == 0
    assert result.output.splitlines() == [feed_path]

    result = invoke('list', 'entries')
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == {
        (feed_path, e.link or e.id) for e in expected['entries']
    }

    result = invoke('search', 'status')
    assert result.exit_code == 0
    assert 'search: disabled' in result.output

    result = invoke('search', 'enable')
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('search', 'status')
    assert result.exit_code == 0
    assert 'search: enabled' in result.output

    result = invoke('search', 'entries', 'amok')
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('search', 'update')
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('search', 'entries', 'amok')
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == {
        (feed_path, e.link or e.id)
        for e in expected['entries']
        if e.title and 'amok' in e.title.lower()
    }

    result = invoke('search', 'entries', 'again')
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == {
        (feed_path, e.link or e.id)
        for e in expected['entries']
        if e.title and 'again' in e.title.lower()
    }

    result = invoke('search', 'entries', 'nope')
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == set()

    result = invoke('search', 'disable')
    assert result.exit_code == 0
    assert result.output == ''

    result = invoke('search', 'status')
    assert result.exit_code == 0
    assert 'search: disabled' in result.output


def raise_exception_plugin(thing):
    assert isinstance(thing, Reader)
    raise Exception("plug-in error")


@pytest.mark.slow
def test_cli_plugin(db_path, monkeypatch, tests_dir):
    monkeypatch.syspath_prepend(tests_dir)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            '--db',
            db_path,
            '--plugin',
            'test_cli:raise_exception_plugin',
            'list',
            'feeds',
        ],
        catch_exceptions=False,
    )

    assert result.exit_code != 0
    assert "plug-in error" in result.output


def raise_hook(*args):
    raise RuntimeError("plug-in error")


def raise_before_feeds_update(reader):
    reader.before_feeds_update_hooks.append(raise_hook)


def raise_before_feed_update(reader):
    reader.before_feed_update_hooks.append(raise_hook)


def raise_after_feeds_update(reader):
    reader.after_feeds_update_hooks.append(raise_hook)


@pytest.mark.slow
def test_cli_plugin_update_exception(db_path, data_dir, tests_dir, monkeypatch):
    monkeypatch.syspath_prepend(tests_dir)

    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(cli, ('--db', db_path, '--feed-root', '') + args)

    result = invoke('add', str(data_dir.joinpath('full.atom')))
    assert result.exit_code == 0
    result = invoke('add', str(data_dir.joinpath('full.rss')))
    assert result.exit_code == 0

    result = invoke('--plugin', 'test_cli:raise_before_feeds_update', 'update', '-v')
    assert result.exit_code != 0, result.output
    assert "0 ok, 0 error, 0 not modified; entries: 0 new, 0 modified" in result.output
    assert isinstance(result.exception, UpdateHookError)

    result = invoke('--plugin', 'test_cli:raise_before_feed_update', 'update', '-vv')
    assert result.exit_code == 0, result.output
    assert "0 ok, 2 error, 0 not modified; entries: 0 new, 0 modified" in result.output
    assert "unexpected hook error" in result.output
    assert "plug-in error" in result.output
    # TODO: the traceback only gets logged with -vv; we might want to fix this
    assert "got hook error; traceback follows" in result.output

    result = invoke('--plugin', 'test_cli:raise_after_feeds_update', 'update', '-v')
    assert result.exit_code != 0, result.output
    assert "2 ok, 0 error, 0 not modified; entries: 10 new, 0 modified" in result.output
    assert isinstance(result.exception, UpdateHookError)


store_reader_plugin = None


@pytest.mark.slow
def test_cli_plugin_builtin_and_import_path(db_path, tests_dir, monkeypatch):
    monkeypatch.syspath_prepend(tests_dir)

    def store_reader_plugin(reader):
        print('\n\nhello\n\n')
        store_reader_plugin.reader = reader

    monkeypatch.setattr('test_cli.store_reader_plugin', store_reader_plugin)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            '--db',
            db_path,
            '--plugin',
            'test_cli:store_reader_plugin',
            '--plugin',
            'reader.ua_fallback',
            '--plugin',
            'reader.plugins.ua_fallback:init_reader',
            'list',
            'feeds',
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert len(store_reader_plugin.reader._parser.session_factory.response_hooks) == 2


def raise_exception_app_plugin(thing):
    from flask import Flask

    assert isinstance(thing, Flask)
    raise Exception("plug-in error")


@pytest.mark.slow
def test_cli_app_plugin(db_path, tests_dir, monkeypatch):
    monkeypatch.syspath_prepend(tests_dir)

    def run_simple(*_):
        run_simple.called = True

    # make serve return instantly
    monkeypatch.setattr('werkzeug.serving.run_simple', run_simple)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            '--db',
            db_path,
            'serve',
            '--plugin',
            'test_cli:raise_exception_app_plugin',
        ],
        catch_exceptions=False,
    )

    # it doesn't fail, just skips the plugin
    assert result.exit_code == 0, result.output
    assert "plug-in error" in result.output

    assert run_simple.called


# TODO: also test plugins in the successful case, like we do in test_app_wsgi.py


@pytest.mark.slow
def test_cli_serve_calls_create_app(db_path, monkeypatch):
    exception = Exception("create_app error")

    def create_app(config):
        create_app.config = config
        raise exception

    monkeypatch.setattr('reader._app.create_app', create_app)

    runner = CliRunner()

    with pytest.raises(Exception) as excinfo:
        runner.invoke(cli, ['--db', db_path, 'serve'], catch_exceptions=False)

    assert excinfo.value is exception
    assert create_app.config.merged('app') == {
        'reader': {'url': db_path},
    }
    assert create_app.config.merged('default') == {
        'reader': {'url': db_path},
    }


def test_config_option(tmp_path):
    final_config = None

    @click.group()
    @click.option('--db')
    @click.option('--plugin', multiple=True)
    @config_option('--config')
    @click.pass_obj
    def cli(config, db, plugin):
        if db:
            config.all['reader']['url'] = db
        if plugin:
            config.all['reader']['plugins'] = dict.fromkeys(plugin)
        nonlocal final_config
        final_config = config.merged('cli')

    @cli.command()
    @click.pass_obj
    def update(config):
        pass

    @cli.command()
    @click.option('--plugin', multiple=True)
    @click.pass_obj
    def serve(config, plugin):
        if plugin:
            config.data['app']['plugins'] = dict.fromkeys(plugin)
        nonlocal final_config
        final_config = config.merged('app')

    config_path = tmp_path.joinpath('config.yaml')
    config_path.write_text(
        yaml.safe_dump(
            {
                'reader': {
                    'url': 'config-reader-url',
                    'plugins': {'config-reader-plugins': {}},
                },
                'cli': {
                    'reader': {'url': 'config-cli-url'},
                    'defaults': {'serve': {'plugin': ['defaults-app-plugins']}},
                },
                'app': {
                    'plugins': {'config-app-plugins': {}},
                },
            }
        )
    )

    runner = CliRunner()
    invoke = lambda *args: runner.invoke(*args, catch_exceptions=False)

    invoke(cli, ['--config', str(config_path), 'update'])
    assert final_config['reader'] == {
        'url': 'config-cli-url',
        'plugins': {'config-reader-plugins': {}},
    }

    invoke(cli, ['--config', str(config_path), '--db', 'user-url', 'update'])
    assert final_config['reader'] == {
        'url': 'user-url',
        'plugins': {'config-reader-plugins': {}},
    }

    invoke(cli, ['--config', str(config_path), 'serve'])
    assert final_config == {
        'reader': {
            'url': 'config-reader-url',
            'plugins': {'config-reader-plugins': {}},
        },
        'plugins': {'defaults-app-plugins': None},
    }

    invoke(
        cli,
        [
            '--config',
            str(config_path),
            '--db',
            'user-url',
            '--plugin',
            'user-plugins',
            'serve',
            '--plugin',
            'user-app-plugins',
        ],
    )
    assert final_config == {
        'reader': {
            'url': 'user-url',
            'plugins': {'user-plugins': None},
        },
        'plugins': {'user-app-plugins': None},
    }


def test_config_example(db_path, monkeypatch, tmp_path, root_dir):
    runner = CliRunner()

    config_path = tmp_path.joinpath('config.yaml')
    config_path.write_text(root_dir.joinpath('examples/config.yaml').read_text())

    if os.name == 'nt':
        with config_path.open() as f:
            config = yaml.safe_load(f)
        old_root = config['default']['reader']['feed_root']
        root = 'c:' + old_root.replace('/', '\\')
        config['default']['reader']['feed_root'] = root
        with config_path.open('w') as f:
            yaml.safe_dump(config, f)

    command_base = ['--db', db_path, '--config', str(config_path)]

    result = runner.invoke(cli, command_base + ['list', 'feeds'])
    assert result.exit_code == 0, result.output

    def run_simple(host, port, app):
        app.test_client().get('/')

    monkeypatch.setattr('werkzeug.serving.run_simple', run_simple)

    result = runner.invoke(cli, command_base + ['serve'])
    assert result.exit_code == 0, result.output
    assert 'ERROR' not in result.output
    assert 'Traceback' not in result.output
