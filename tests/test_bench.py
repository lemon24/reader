import os.path
import sys

import pytest
from click.testing import CliRunner

from reader import make_reader
from test_cli import patch_app_dir
from test_reader_filter import setup_reader_for_tags


root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../scripts'))
import bench
from bench import cli


pytestmark = pytest.mark.slow
pytest.importorskip("numpy")


@pytest.fixture(scope='module')
def db_path(tmp_path_factory):
    dir = tmp_path_factory.mktemp("data")
    db_path = str(dir.joinpath('db.sqlite'))
    with make_reader(db_path) as reader:
        setup_reader_for_tags(reader)
    return db_path


@pytest.mark.parametrize('command', [['time', '-n1'], ['profile']])
def test_commands_work(command, db_path):
    runner = CliRunner()
    result = runner.invoke(
        cli, command + ['--db', db_path] + ['get_entries_all', 'show']
    )
    assert result.exit_code == 0, result.exception


def test_list():
    runner = CliRunner()
    result = runner.invoke(cli, ['list'])
    assert 'get_entries_all' in result.output.splitlines()
    assert 'show' in result.output.split()
