#!/bin/bash
#

# Copyright (C) 2010, 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

set -e
set -o pipefail

export PYTHON=${PYTHON:=python}

CCE=tools/check-cert-expired

err() {
  echo "$@"
  echo 'Aborting'
  exit 1
}

impexpd_helper() {
  $PYTHON "${TOP_SRCDIR:-.}/test/py/import-export_unittest-helper" "$@"
}

$CCE 2>/dev/null && err 'Accepted empty argument list'
$CCE foo bar 2>/dev/null && err 'Accepted more than one argument'
$CCE foo bar baz 2>/dev/null && err 'Accepted more than one argument'

tmpdir=$(mktemp -d)
trap "rm -rf $tmpdir" EXIT

[[ -f "$tmpdir/cert-not" ]] && err 'File existed when it should not'
$CCE $tmpdir/cert-not 2>/dev/null && err 'Accepted non-existent file'

VALIDITY=1 impexpd_helper $tmpdir/cert-valid gencert
$CCE $tmpdir/cert-valid 2>/dev/null && \
  err 'Reported valid certificate as expired'

VALIDITY=-50 impexpd_helper $tmpdir/cert-expired gencert
$CCE $tmpdir/cert-expired 2>/dev/null || \
  err 'Reported expired certificate as valid'

echo > $tmpdir/cert-invalid
$CCE $tmpdir/cert-invalid 2>/dev/null && \
  err 'Reported invalid certificate as expired'

echo 'Hello World' > $tmpdir/cert-invalid2
$CCE $tmpdir/cert-invalid2 2>/dev/null && \
  err 'Reported invalid certificate as expired'

exit 0
