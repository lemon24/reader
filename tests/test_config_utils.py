from textwrap import dedent

import click
import pytest
from click.testing import CliRunner

from reader._config_utils import *


@click.group(context_settings=dict(auto_envvar_prefix='CLI'))
@config_option('--config')
@click.option('--plugin', type=str.upper, multiple=True, callback=extend_defaults)
def cli(**kwargs):
    return load_config_from_context()


@cli.command()
@click.option('--option', type=str.upper, default='default')
def sub(**kwargs):
    return load_config_from_context()


@pytest.fixture
def with_config(tmp_path, monkeypatch):

    def with_config(config):
        config_path = tmp_path / 'config.toml'
        config_path.write_text(dedent(config))
        monkeypatch.setenv('CLI_CONFIG', str(config_path))

    return with_config


def invoke(cli, args=None, env=None):
    runner = CliRunner(catch_exceptions=False)
    result = runner.invoke(cli, args, env=env, standalone_mode=False)
    return result.return_value


def check_error(strings=(), exc_type=click.BadParameter):
    with pytest.raises(exc_type) as exc_info:
        invoke(cli, ['sub'])
    for s in strings:
        assert s in str(exc_info.value).lower()

    with pytest.raises(exc_type) as exc_info:
        loaded = load_config(cli)
    for s in strings:
        assert s in str(exc_info.value).lower()


def test_no_config():
    expected = {'': {'plugin': ()}, 'sub': {'option': 'DEFAULT'}}
    assert invoke(cli, ['sub']) == expected
    assert load_config(cli) == expected


def test_empty_config(with_config):
    with_config("[cli]")
    expected = {'': {'plugin': ()}, 'sub': {'option': 'DEFAULT'}}
    assert invoke(cli, ['sub']) == expected
    assert load_config(cli) == expected


def test_config(with_config):
    with_config("""\
        [cli]
        plugin=['config']
        [cli.sub]
        option='config'
        """)

    expected = {'': {'plugin': ('CONFIG',)}, 'sub': {'option': 'CONFIG'}}
    assert invoke(cli, ['sub']) == expected
    assert load_config(cli) == expected

    env = {'CLI_SUB_OPTION': 'env'}
    expected = {'': {'plugin': ('CONFIG', 'USER')}, 'sub': {'option': 'ENV'}}
    assert invoke(cli, ['--plugin', 'user', 'sub'], env=env)
    assert load_config(cli, ['--plugin', 'user'], env=env)


def test_toml_error(with_config):
    with_config("[cli")
    check_error(['toml error'])


def test_no_section_error(with_config):
    with_config("")
    check_error(['no [cli] section'])


def test_bad_section_type_error(with_config):
    with_config("cli = 1")
    check_error(['cli:', 'expected mapping'])


def test_unknown_option_error(with_config):
    with_config("[cli]\nunknown = 1")
    check_error(['cli.unknown:', 'no such option'])


def test_unknown_command_error(with_config):
    with_config("[cli.unknown]")
    check_error(['cli.unknown:', 'no such option'])
