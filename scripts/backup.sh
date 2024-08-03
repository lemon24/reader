#!/bin/bash
#
# back up a SQLite database
#
# usage:
#   ./backup.sh src dst
#   ./backup.sh src
#
# example:
#   "./backup.sh /src/db.sqlite" -> ./db.sqlite.2023-01-28.gz
#

set -o nounset
set -o pipefail
set -o errexit

if (( $# == 1 )); then
    src=$1
    dst=$( pwd )/$( basename "$src" ).$( date -u +%Y-%m-%d )
elif (( $# == 2 )); then
    src=$1
    dst=$2
else
    exit 1
fi

tmpdir=$( mktemp -d )
trap 'rm -rf '"$tmpdir" EXIT

tmp=$tmpdir/$( basename "$src" )

du -sh "$src"
sqlite3 "$src" "VACUUM INTO '$tmp'"
du -sh "$tmp"
gzip -c "$tmp" > "$dst.gz"
du -sh "$dst.gz"
