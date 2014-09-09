#!/bin/bash
#

# Copyright (C) 2010, 2012 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
