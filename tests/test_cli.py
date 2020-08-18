import click
import py.path
import pytest
import yaml
from click.testing import CliRunner
from utils import make_url_base

from reader import Reader
from reader._cli import cli
from reader._cli import config_option
from reader._cli import get_dict_path
from reader._cli import set_dict_path
from reader._config import merge_config
from reader.types import MISSING


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
    assert result.output == ''

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
    import sys

    monkeypatch.setattr(
        sys, 'path', [str(py.path.local(__file__).dirpath())] + sys.path
    )

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
        ['--db', db_path, 'serve', '--plugin', 'test_cli:raise_exception_app_plugin',],
        catch_exceptions=False,
    )

    # it doesn't fail, just skips the plugin
    assert result.exit_code == 0
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
    assert create_app.config == {
        'reader': {'url': db_path, 'plugins': {}},
        'app': {'plugins': {}},
        'cli': {},
    }


def test_config_option(tmpdir):
    final_config = None

    overrides = {
        ('ccc',): ('command', 'ccc'),
    }

    @click.command()
    @config_option('--config', overrides=overrides)
    @click.option('--aaa', default='aaa-cli-default')
    @click.option('--bbb/--no-bbb', default=False)
    @click.option('--ccc', type=int, default=1)
    @click.option('--ddd', default='ddd-cli-default')
    @click.option('--eee', type=int, default=1)
    @click.pass_obj
    def command(config, aaa, bbb, ccc, ddd, eee, **kwargs):
        options = {
            'aaa': aaa,
            'bbb': bbb,
            'ccc': ccc,
            'ddd': ddd,
            'eee': eee,
        }

        config.setdefault('command', {})
        config['command'] = merge_config(config['command'], options)

        nonlocal final_config
        final_config = config

    config_path = tmpdir.join('config.yaml')
    config_path.write(
        yaml.safe_dump(
            {
                'command': {
                    'ccc': 3,
                    'eee': 3,
                    'ddd': None,
                    'fff': 'fff-config-value',
                },
                'cli': {
                    'defaults': {'bbb': True, 'ccc': 2, 'eee': 2,},
                    'other-cli-stuff': 'stuff',
                },
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        command,
        ['--config', str(config_path), '--ddd', 'ddd-user-value'],
        catch_exceptions=False,
    )

    # cli default < config[cli][defaults] < config[command] < cli envvar,option
    assert final_config['command'] == {
        # cli default
        'aaa': 'aaa-cli-default',
        # config[cli][defaults]
        'bbb': True,
        # config[command], because there was an override
        'ccc': 3,
        # cli option
        'ddd': 'ddd-user-value',
        # config[cli][default], not config[command], because there was no override
        'eee': 2,
        # config[command], because it is not a CLI option
        'fff': 'fff-config-value',
    }


def test_get_dict_path():
    d = {'a': {'b': 'c'}}
    assert get_dict_path(d, ('a', 'b')) == 'c'
    assert get_dict_path(d, ('a', 'd', 'e')) is MISSING


def test_set_dict_path():
    d = {'a': {'b': 'c'}}
    set_dict_path(d, ('a', 'b'), 'd')
    assert d == {'a': {'b': 'd'}}
    set_dict_path(d, ('a', 'e', 'f'), 'g')
    assert d == {'a': {'b': 'd', 'e': {'f': 'g'}}}
