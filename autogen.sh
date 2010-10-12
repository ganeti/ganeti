#!/bin/bash

if test ! -f configure.ac ; then
  echo "You must execute this script from the top level directory."
  exit 1
fi

set -e

rm -rf config.cache autom4te.cache

ACLOCAL_VERSION=$(${ACLOCAL:-aclocal} --version | head -1 | \
	          sed -e 's/^[^0-9]*\([0-9\.]*\)$/\1/')

if [[ "$ACLOCAL_VERSION" < "1.11.1" ]]; then
  echo "aclocal version $ACLOCAL_VERSION is too old (< 1.11.1)"
  exit 1
fi

${ACLOCAL:-aclocal} -I autotools
${AUTOCONF:-autoconf}
${AUTOMAKE:-automake} --add-missing

rm -rf autom4te.cache
