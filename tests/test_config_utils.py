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


def check_all(args, expected, **kwargs):
    runner = CliRunner(catch_exceptions=False)

    result = runner.invoke(cli, args, standalone_mode=False, **kwargs)
    assert expected == result.return_value

    loaded = load_config(cli, args)
    assert expected == loaded


def check_error(args, strings=(), exc_type=click.BadParameter, **kwargs):
    runner = CliRunner(catch_exceptions=False)

    with pytest.raises(exc_type) as exc_info:
        runner.invoke(cli, args, standalone_mode=False, **kwargs)
    for s in strings:
        assert s in str(exc_info.value).lower()

    with pytest.raises(exc_type) as exc_info:
        loaded = load_config(cli, args)
    for s in strings:
        assert s in str(exc_info.value).lower()


def test_no_config():
    check_all(['sub'], {'': {'plugin': ()}, 'sub': {'option': 'DEFAULT'}})


def test_empty_config(with_config):
    with_config("[cli]")
    check_all(['sub'], {'': {'plugin': ()}, 'sub': {'option': 'DEFAULT'}})


def test_config(with_config):
    with_config(
        """\
        [cli]
        plugin=['config']
        [cli.sub]
        option='config'
        """
    )
    load_config(cli, []) == {'': {'plugin': ('CONFIG',)}}
    check_all(
        ['sub'],
        {
            '': {'plugin': ('CONFIG',)},
            'sub': {'option': 'CONFIG'},
        },
    )
    check_all(
        ['--plugin', 'user', 'sub', '--option', 'user'],
        {
            '': {'plugin': ('CONFIG', 'USER')},
            'sub': {'option': 'USER'},
        },
    )


def test_toml_error(with_config):
    with_config("[cli")
    check_error(['sub'], ['toml error'])


def test_no_section_error(with_config):
    with_config("")
    check_error(['sub'], ['no [cli] section'])


def test_bad_section_type_error(with_config):
    with_config("cli = 1")
    check_error(['sub'], ['cli:', 'expected mapping'])


def test_unknown_option_error(with_config):
    with_config("[cli]\nunknown = 1")
    check_error(['sub'], ['cli.unknown:', 'no such option'])


def test_unknown_command_error(with_config):
    with_config("[cli.unknown]")
    check_error(['sub'], ['cli.unknown:', 'no such option'])
