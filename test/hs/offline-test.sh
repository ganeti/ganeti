#!/bin/bash

# Copyright (C) 2012 Google Inc.
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

# This is an offline testing script for most/all of the htools
# programs, checking basic command line functionality.

# Optional argument that specifies the test files to run. If not
# specified, then all tests are run.
#
# For example, a value of 'balancing' runs the file
# 'shelltests/htools-balancing.test'.  Multiple files can be specified
# using shell notation, for example, '{balancing,basic}'.
TESTS=${1:-*}

set -e
set -o pipefail

. $(dirname $0)/cli-tests-defs.sh

echo Running offline htools tests

export T=`mktemp -d`
trap 'rm -rf $T' EXIT
trap 'echo FAIL to build test files' ERR
echo Using $T as temporary dir

echo -n Generating hspace simulation data for hinfo and hbal...
# this cluster spec should be fine
./test/hs/hspace --simu p,4,8T,64g,16 -S $T/simu-onegroup \
  --disk-template drbd -l 8 -v -v -v >/dev/null 2>&1
echo OK

echo -n Generating hinfo and hbal test files for multi-group...
./test/hs/hspace --simu p,4,8T,64g,16 --simu p,4,8T,64g,16 \
  -S $T/simu-twogroups --disk-template drbd -l 8 >/dev/null 2>&1
echo OK

echo -n Generating test files for rebalancing...
# we generate a cluster with two node groups, one with unallocable
# policy, then we change all nodes from this group to the allocable
# one, and we check for rebalancing
FROOT="$T/simu-rebal-orig"
./test/hs/hspace --simu u,4,8T,64g,16 --simu p,4,8T,64g,16 \
  -S $FROOT --disk-template drbd -l 8 >/dev/null 2>&1
for suffix in standard tiered; do
  RELOC="$T/simu-rebal-merged.$suffix"
  # this relocates the nodes
  sed -re 's/^(node-.*|fake-uuid-)-02(|.*)/\1-01\2/' \
    < $FROOT.$suffix > $RELOC
done
export BACKEND_BAL_STD="-t$T/simu-rebal-merged.standard"
export BACKEND_BAL_TIER="-t$T/simu-rebal-merged.tiered"
echo OK

# For various tests
export BACKEND_DYNU="-t $T/simu-onegroup.standard"
export BACKEND_EXCL="-t $T/simu-onegroup.standard"

echo -n Generating data files for IAllocator checks...
for evac_mode in primary-only secondary-only all; do
  sed -e 's/"evac_mode": "all"/"evac_mode": "'${evac_mode}'"/' \
    -e 's/"spindles": [0-9]\+,//' \
    < $TESTDATA_DIR/hail-node-evac.json \
    > $T/hail-node-evac.json.$evac_mode
done
for bf in hail-alloc-drbd hail-alloc-invalid-twodisks hail-alloc-twodisks \
  hail-change-group hail-node-evac hail-reloc-drbd hail-alloc-spindles; do
  f=$bf.json
  sed -e 's/"exclusive_storage": false/"exclusive_storage": true/' \
    < $TESTDATA_DIR/$f > $T/$f.excl-stor
  sed -e 's/"exclusive_storage": false/"exclusive_storage": true/' \
    -e 's/"spindles": [0-9]\+,//' \
    < $TESTDATA_DIR/$f > $T/$f.fail-excl-stor
done
echo OK

echo -n Checking file-based RAPI...
mkdir -p $T/hscan
export RAPI_URL="file://$TESTDATA_DIR/rapi"
./test/hs/hscan -d $T/hscan/ -p -v -v $RAPI_URL >/dev/null 2>&1
# check that we file parsing is correct, i.e. hscan saves correct text
# files, and is idempotent (rapi+text == rapi); more is tested in
# shelltest later
RAPI_TXT="$(ls $T/hscan/*.data|head -n1)"
./test/hs/hinfo -p --print-instances -m $RAPI_URL > $T/hscan/direct.hinfo 2>&1
./test/hs/hinfo -p --print-instances -t $RAPI_TXT > $T/hscan/fromtext.hinfo 2>&1
echo OK

echo Running shelltest...

shelltest $SHELLTESTARGS \
  ${TOP_SRCDIR:-.}/test/hs/shelltests/htools-$TESTS.test
