#!/bin/bash
#
# usage: ./run.sh command [argument ...]
#
# Executable documentation for the development workflow.
#
# See https://death.andgravity.com/run-sh for how this works.


# preamble

set -o nounset
set -o pipefail
set -o errexit

PROJECT_ROOT=${0%/*}
if [[ $0 != $PROJECT_ROOT && $PROJECT_ROOT != "" ]]; then
    cd "$PROJECT_ROOT"
fi
readonly PROJECT_ROOT=$( pwd )
readonly SCRIPT="$PROJECT_ROOT/$( basename "$0" )"


# main development workflow

function install {
    pip install -e '.[all]' --group dev --upgrade --upgrade-strategy eager
    pre-commit install --install-hooks
}

function test {
    pytest --runslow "$@"
}

function test-all {
    tox run-parallel "$@"
}

function coverage {
    unset -f coverage
    coverage run -m pytest --runslow "$@"
    coverage html
    coverage-report
}

function typing {
    mypy "$@"
}

function docs {
    sphinx-build -E -W docs docs/_build/html "$@"
}


# "watch" versions of the main commands

function test-dev {
    watch pytest "$@"
}

function typing-dev {
    watch typing "$@"
}

function docs-dev {
    rm -r docs/_build/html
    watch sphinx-build -W docs docs/_build/html "$@"
}

function serve-dev {
    export READER_DB=db.sqlite
    flask -A reader._app.wsgi --debug run "$@"
}


# low level commands

function coverage-report {
    # --fail-under only for the library, not the CLI or the web app
    unset -f coverage
    coverage report \
        --omit "$(
            echo "
                */reader/_vendor/*
                */reader/__main__.py
                */reader/_cli*
                */reader/_config*
                */reader/_app/*
                */reader/_plugins/*
                tests/*
            " | xargs echo | sed 's/ /,/g'
        )" \
        --skip-covered \
        --show-missing \
        --fail-under $( on-pypy && echo 99 || echo 100 )
}


# utilities

function on-pypy {
    [[ $( python -c 'import sys; print(sys.implementation.name)' ) == pypy ]]
}

function watch {
    entr-project-files -cdr "$SCRIPT" "$@"
}

function entr-project-files {
    set +o errexit
    while true; do
        ls-project-files | entr "$@"
        if [[ $? -eq 0 ]]; then
            break
        fi
    done
}

function ls-project-files {
    git ls-files "$@"
    git ls-files --exclude-standard --others "$@"
}


"$@"
