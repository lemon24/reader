#!/bin/bash
#
# usage: ./run.sh command [argument ...]
#
# Commands for use during development / CI.
#


set -o nounset
set -o pipefail
set -o errexit


# Change the current directory to the project root.
script_root=${0%/*}
if [[ $0 != $script_root && $script_root != "" ]]; then
    cd "$script_root"
fi
unset script_root

# Store the absolute path to this script (useful for recursion).
readonly SCRIPT="$( pwd )/$( basename "$0" )"


function install-dev {
    pip install -e '.[search,cli,app,enclosure-tags,preview-feed-list,dev,docs]'
    # TODO: pre-commit
}


# TODO: test commands: test-fast, test


function coverage-all {
    coverage-run --cov-context=test "$@"
    coverage-report --show-contexts
}

function coverage-run {
    clean-pyc
    pytest --cov --runslow "$@"
}

function coverage-report {
    coverage html "$@"
    coverage report \
        --include '*/reader/*' \
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
        --fail-under 100
}


function typing {
    local implementation=$( python -c 'import sys; print(sys.implementation.name)' )

    if [[ $implementation == pypy ]]; then
        # mypy does not work on pypy as of January 2020
        # https://github.com/python/typed_ast/issues/97#issuecomment-484335190
        echo "mypy does not work on pypy, doing nothing"
        return
    fi

    mypy --strict src "$@"
}


function docs {
    make -C docs html "$@"
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
    flask run -h 0.0.0.0 -p 8000
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


function clean-pyc {
    local IFS=$'\n'
    find \
        $( ls-project-files | grep / | cut -d/ -f1 | uniq ) \
        -name '*.pyc' -or -name '*.pyo' \
        -exec rm -rf {} +
}


function ci-install {
    install-dev
}

function ci-run {
    coverage-run && coverage-report && typing
}


# Pass control to commands.
"$@"
