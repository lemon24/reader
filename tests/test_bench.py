import os.path
import sys

import pytest
from click.testing import CliRunner

root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../scripts'))
import bench
from bench import cli


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif("os.name != 'posix'"),
    # risks triggering sqlite3.InterfaceError: Error binding parameter ...
    pytest.mark.skipif("sys.implementation.name == 'pypy'"),
]


@pytest.mark.parametrize('command', [['time', '-n1'], ['profile']])
def test_commands_work(command, monkeypatch):
    monkeypatch.setattr(bench, 'TIMINGS_PARAMS_LIST', bench.TIMINGS_PARAMS_LIST[:2])
    monkeypatch.setattr(bench, 'PROFILE_PARAMS', bench.TIMINGS_PARAMS_LIST[0])

    runner = CliRunner()
    result = runner.invoke(cli, command + ['get_entries_all', 'show'])
    assert result.exit_code == 0


def test_list():
    runner = CliRunner()
    result = runner.invoke(cli, ['list'])
    assert 'get_entries_all' in result.output.splitlines()
    assert 'show' in result.output.split()
