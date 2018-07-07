#!/bin/sh

build_dir=$1

if [ ! -e $build_dir/sqlite/libsqlite3.so.0 ]; then
    echo "compiling sqlite"
    wget https://sqlite.org/2018/sqlite-amalgamation-3220000.zip
    unzip sqlite-amalgamation-3220000.zip
    rm sqlite-amalgamation-3220000.zip
    mv sqlite-amalgamation-3220000 sqlite
    cd sqlite
    gcc -c -fPIC -O2 -I. \
        -DSQLITE_THREADSAFE=0 \
        -DSQLITE_ENABLE_FTS4 \
        -DSQLITE_ENABLE_FTS5 \
        -DSQLITE_ENABLE_JSON1 \
        -DSQLITE_ENABLE_RTREE \
        -DSQLITE_ENABLE_EXPLAIN_COMMENTS \
        -DHAVE_USLEEP \
        sqlite3.c
    gcc -shared -o libsqlite3.so -fPIC sqlite3.o -ldl -lpthread
    ln -s libsqlite3.so libsqlite3.so.0
    cd ..
    mv sqlite $build_dir
else
    echo "using existing sqlite"
fi

