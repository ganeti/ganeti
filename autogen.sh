#!/bin/sh

if test ! -f configure.ac ; then
  echo "You must execute this script from the top level directory."
  exit 1
fi

set -e

rm -rf config.cache autom4te.cache
mkdir -p autotools

aclocal-1.9
autoconf
automake-1.9 --add-missing -Wall -Wno-portability

rm -rf autom4te.cache
