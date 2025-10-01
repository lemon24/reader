import datetime
import os
import re
import subprocess

import click


def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


def confirm(message, *args, **kwargs):
    rv = click.prompt(message.format(*args, **kwargs), type=click.Choice(['y', 'n']))
    if rv != 'y':
        abort('aborted')


def run(*args, **kwargs):
    return subprocess.run(*args, check=True, **kwargs)


def run_no_venv(*args, **kwargs):
    env = os.environ.copy()
    virtual_env = env.pop('VIRTUAL_ENV', None)
    if virtual_env:
        env['PATH'] = ':'.join(
            p for p in env['PATH'].split(':') if not p.startswith(virtual_env)
        )
    return run(*args, env=env, **kwargs)


def run_tox():
    run_no_venv('tox -p all', shell=True)


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
    title = f'Version {version}'
    path_sub(
        r'(\n{}\n{}\n\n)(Unreleased)(\n)'.format(re.escape(title), '-' * len(title)),
        'Released ' + str(date.date()),
        'CHANGES.rst',
    )


def add_changelog_section(version, new_version):
    title = f'Version {version}'
    new_title = f'Version {new_version}'
    path_sub(
        r'()()(\n{}\n{}\n\n)'.format(re.escape(title), '-' * len(title)),
        '\n{}\n{}\n\nUnreleased\n\n'.format(new_title, '-' * len(new_title)),
        'CHANGES.rst',
    )


def commit(message):
    run(['git', 'commit', '-a', '-m', message])


def push():
    run(['git', 'push'])


def check_uncommited():
    p = run(
        ['git', 'status', '--untracked-files=no', '--porcelain'],
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if p.stdout.strip():
        abort("uncommited changes\n\n{}\n", p.stdout.strip('\n'))


def check_unpushed():
    p = run(
        ['git', 'log', '@{u}..', '--format=oneline'],
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if p.stdout.strip():
        abort("unpushed changes\n\n{}\n", p.stdout.strip('\n'))


def add_and_push_tags(tags):
    for tag in tags:
        run(['git', 'tag', '--force', tag])
    # https://stackoverflow.com/a/19300065
    refs = [f'refs/tags/{tag}:refs/tags/{tag}' for tag in tags]
    run(['git', 'push', '--force', 'origin'] + refs)


@click.command()
@click.argument('version')
@click.argument('new_version')
@click.option('--date', type=click.DateTime(), default=str(datetime.date.today()))
@click.option('--tox/--no-tox', default=True)
@click.option('--changelog/--no-changelog', default=True)
def main(version, new_version, date, tox, changelog):
    assert 'dev' not in new_version, new_version
    new_version_is_final = not re.search('[a-zA-Z]', new_version)

    check_uncommited()
    check_unpushed()

    update_init_version(version)
    if changelog:
        update_changelog_date(version, date)
    commit(f"Release {version}.")

    if tox:
        run_tox()

    confirm("Push version {}?", version)
    push()

    confirm("Wait for GitHub Actions / Read the Docs builds to pass.")

    tags = [version]
    version_x = version.partition('.')[0] + '.x'
    if new_version_is_final:
        tags.append(version_x)

    confirm(f"Add and push tags ({', '.join(tags)})?")
    add_and_push_tags(tags)

    confirm(
        "Approve publish workflow to upload to PyPI.\n  {}\nDone?",
        "https://github.com/lemon24/reader/actions/workflows/publish.yaml",
    )
    confirm(
        "Publish draft release {} in GitHub.\n  {}\nDone?",
        version,
        "https://github.com/lemon24/reader/releases",
    )

    new_version_full = f"{new_version}.dev0"
    update_init_version(new_version_full)
    if changelog:
        add_changelog_section(version, new_version)
    commit(f"Bump version to {new_version_full}.")

    confirm("Push version {}?", new_version_full)
    push()


if __name__ == '__main__':
    main()
