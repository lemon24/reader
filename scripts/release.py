import subprocess
import os
import re
import datetime

import click


def run(*args, **kwargs):
    return subprocess.run(*args, check=True, **kwargs)

def run_no_venv(*args, **kwargs):
    env = os.environ.copy()
    virtual_env = env.pop('VIRTUAL_ENV', None)
    if virtual_env:
        env['PATH'] = ':'.join(
            p for p in env['PATH'].split(':')
            if not p.startswith(virtual_env)
        )
    return run(*args, env=env, **kwargs)


def tox():
    run_no_venv('tox', shell=True)

def build():
    run('rm -rf dist/', shell=True)
    run('python setup.py build sdist', shell=True)
    run('python setup.py build bdist_wheel', shell=True)


def path_sub(pattern, repl, path):
    with open(path) as f:
        text = f.read()

    sub_count = 0
    def update(match):
        nonlocal sub_count
        sub_count += 1
        prefix, old, suffix = match.groups()
        return prefix + repl + suffix

    text = re.sub(pattern, update, text)
    assert sub_count == 1

    with open(path, 'w') as f:
        f.write(text)


INIT_VERSION_RE = r'(\n__version__ = )(.*?)(\n)'

def update_init_version(version):
    path_sub(INIT_VERSION_RE, repr(version), 'src/reader/__init__.py')

def update_changelog_date(version, date):
    title = 'Version {}'.format(version)
    path_sub(
        r'(\n{}\n{}\n\n)(Unreleased)(\n)'.format(re.escape(title), '-' * len(title)),
        str(date.date()),
        'CHANGES.rst',
    )

def add_changelog_section(version, new_version):
    title = 'Version {}'.format(version)
    new_title = 'Version {}'.format(new_version)
    path_sub(
        r'()()(\n{}\n{}\n\n)'.format(re.escape(title), '-' * len(title)),
        '\n{}\n{}\n\nUnreleased\n\n'.format(new_title, '-' * len(new_title)),
        'CHANGES.rst',
    )


def commit(message):
    run(['git', 'commit', '-a', '-m', message])


@click.command()
@click.argument('version')
@click.argument('new_version')
@click.option('--date', type=click.DateTime(), default=str(datetime.date.today()))
def main(version, new_version, date):
    update_init_version(version)
    update_changelog_date(version, date)
    commit("Release {}.".format(version))

    tox()
    build()

    new_version_full = "{}.dev0".format(new_version)
    update_init_version(new_version_full)
    add_changelog_section(version, new_version)
    commit("Bump version to {}.".format(new_version_full))


if __name__ == '__main__':
    main()

