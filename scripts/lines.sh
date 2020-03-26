#!/bin/sh

# Print various Python and wc lines of code.

function sloc {
    coverage report \
    | grep -A9999 ^--- \
    | grep -B9999 ^--- \
    | grep -v ^-- \
    | awk '{ print $1 "\t" $2 }'
}

function count {
    sloc | grep "$@" | cut -f2 | paste -sd+ - | bc
    sloc | grep "$@" | cut -f1 | xargs wc -l | tail -n-1 | awk '{ print $1 }'
}

# cache sloc output
_sloc=$( sloc )
function sloc {
    echo "$_sloc"
}

{
    echo '' stmts lines
    echo src $( count ^src/ )
    echo core $( count -e ^src/reader/core/ -e ^src/reader/__init__.py )
    echo cli $( count ^src/reader/cli )
    echo app $( count ^src/reader/app/ )
    echo plugins $( count ^src/reader/plugins/ )
    echo tests $( count ^tests/ )
    echo total $( count '.' )
} \
| tr ' ' '\t'
