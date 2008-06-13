#!/bin/sh

if test ! -f configure.ac ; then
  echo "You must execute this script from the top level directory."
  exit 1
fi

set -e

rm -rf config.cache autom4te.cache
mkdir -p autotools

${ACLOCAL:-aclocal} -I autotools
${AUTOCONF:-autoconf}
${AUTOMAKE:-automake} --add-missing

rm -rf autom4te.cache
