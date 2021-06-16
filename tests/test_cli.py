import logging
import os

import click
import py.path
import pytest
import yaml
from click.testing import CliRunner
from utils import make_url_base

from reader import Reader
from reader._cli import cli
from reader._cli import config_option
from reader.types import MISSING


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


@pytest.mark.slow
def test_cli(db_path, data_dir):
    feed_filename = 'full.atom'
    feed_path = str(data_dir.join(feed_filename))

    url_base, rel_base = make_url_base(feed_path)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    runner = CliRunner()

    result = runner.invoke(cli, ['--db', db_path, 'list', 'feeds'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'add', feed_path])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'list', 'feeds'])
    assert result.exit_code == 0
    assert result.output.splitlines() == [feed_path]

    result = runner.invoke(cli, ['--db', db_path, 'list', 'entries'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'update'])
    assert result.exit_code == 0
    assert "1 ok, 0 error, 0 not modified; entries: 2 new, 0 modified" in result.output

    result = runner.invoke(cli, ['--db', db_path, 'list', 'feeds'])
    assert result.exit_code == 0
    assert result.output.splitlines() == [feed_path]

    result = runner.invoke(cli, ['--db', db_path, 'list', 'entries'])
    assert result.exit_code == 0
    assert [l.split() for l in result.output.splitlines()] == [
        [feed_path, e.link or e.id]
        for e in sorted(expected['entries'], key=lambda e: e.updated, reverse=True)
    ]

    result = runner.invoke(cli, ['--db', db_path, 'search', 'status'])
    assert result.exit_code == 0
    assert 'search: disabled' in result.output

    result = runner.invoke(cli, ['--db', db_path, 'search', 'update'])
    assert result.exit_code != 0

    result = runner.invoke(cli, ['--db', db_path, 'search', 'entries', 'amok'])
    assert result.exit_code != 0

    result = runner.invoke(cli, ['--db', db_path, 'search', 'enable'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'search', 'status'])
    assert result.exit_code == 0
    assert 'search: enabled' in result.output

    result = runner.invoke(cli, ['--db', db_path, 'search', 'entries', 'amok'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'search', 'update'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'search', 'entries', 'amok'])
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == {
        (feed_path, e.link or e.id) for e in expected['entries']
    }

    result = runner.invoke(cli, ['--db', db_path, 'search', 'entries', 'again'])
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == {
        (feed_path, e.link or e.id)
        for e in expected['entries']
        if 'again' in e.title.lower()
    }

    result = runner.invoke(cli, ['--db', db_path, 'search', 'entries', 'nope'])
    assert result.exit_code == 0
    assert {tuple(l.split()) for l in result.output.splitlines()} == set()

    result = runner.invoke(cli, ['--db', db_path, 'search', 'disable'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'search', 'status'])
    assert result.exit_code == 0
    assert 'search: disabled' in result.output


def raise_exception_plugin(thing):
    assert isinstance(thing, Reader)
    raise Exception("plug-in error")


@pytest.mark.slow
def test_cli_plugin(db_path, monkeypatch):
    monkeypatch.syspath_prepend(str(py.path.local(__file__).dirpath()))

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
    )

    assert result.exit_code != 0
    assert "plug-in error" in result.output


store_reader_plugin = None


@pytest.mark.slow
def test_cli_plugin_builtin_and_import_path(db_path, monkeypatch):
    monkeypatch.syspath_prepend(str(py.path.local(__file__).dirpath()))

    def store_reader_plugin(reader):
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
    )

    assert len(store_reader_plugin.reader._parser.session_hooks.response) == 2


def raise_exception_app_plugin(thing):
    from flask import Flask

    assert isinstance(thing, Flask)
    raise Exception("plug-in error")


@pytest.mark.slow
def test_cli_app_plugin(db_path, monkeypatch):
    import sys

    monkeypatch.setattr(
        sys, 'path', [str(py.path.local(__file__).dirpath())] + sys.path
    )

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


def test_config_option(tmpdir):
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

    config_path = tmpdir.join('config.yaml')
    config_path.write(
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


def test_config_example(db_path, monkeypatch, tmp_path):
    runner = CliRunner()

    config_path = tmp_path.joinpath('config.yaml')

    py.path.local(__file__).dirpath().join('../examples/config.yaml').copy(
        py.path.local(str(config_path))
    )
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
