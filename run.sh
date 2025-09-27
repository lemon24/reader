#!/bin/bash
#
# usage: ./run.sh command [argument ...]
#
# Commands used during development / CI.
# Also, executable documentation for project dev practices.
#
# See https://death.andgravity.com/run-sh
# for an explanation of how it works and why it's useful.


# First, set up the environment.
# (Check the notes at the end when changing this.)

set -o nounset
set -o pipefail
set -o errexit

# Change the current directory to the project root.
PROJECT_ROOT=${0%/*}
if [[ $0 != $PROJECT_ROOT && $PROJECT_ROOT != "" ]]; then
    cd "$PROJECT_ROOT"
fi
readonly PROJECT_ROOT=$( pwd )

# Store the absolute path to this script (useful for recursion).
readonly SCRIPT="$PROJECT_ROOT/$( basename "$0" )"



# Commands follow.


function install-dev {
    pip install -e '.[all]' --group dev --upgrade --upgrade-strategy eager
    pre-commit install --install-hooks
}

function test {
    pytest --runslow "$@"
}

function coverage {
    unset -f coverage
    coverage run -m pytest --runslow "$@"
    coverage html
    coverage-report
}

function coverage-report {
    # library only "coverage report --fail-under 100"
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


function test-all {
    tox p "$@"
}


function typing {
    mypy "$@"
}


function docs {
    make -C docs html SPHINXOPTS="-W" "$@"
}


function test-dev {
    clean-pyc
    entr-project-files -cdr pytest "$@"
}

function typing-dev {
    entr-project-files -cdr "$SCRIPT" typing "$@"
}

function docs-dev {
    make -C docs clean
    entr-project-files -cdr "$SCRIPT" docs "$@"
}

function serve-dev {
    export FLASK_DEBUG=1
    export FLASK_TRAP_BAD_REQUEST_ERRORS=1
    export FLASK_APP=src/reader/_app/wsgi.py
    export READER_DB=db.sqlite
    flask run -p 8000 "$@"
}


function release {
    python scripts/release.py "$@"
}


function ls-project-files {
    git ls-files "$@"
    git ls-files --exclude-standard --others "$@"
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


function on-pypy {
    [[ $( python -c 'import sys; print(sys.implementation.name)' ) == pypy ]]
}



# Commands end. Dispatch to command.

"$@"



# Some dev notes for this script.
#
# The commands *require*:
#
# * The current working directory is the project root.
# * The shell options and globals are set as they are.
#
# Inspired by http://www.oilshell.org/blog/2020/02/good-parts-sketch.html
#
