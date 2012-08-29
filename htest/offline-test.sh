#!/bin/bash

# Copyright (C) 2012 Google Inc.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

# This is an offline testing script for most/all of the htools
# programs, checking basic command line functionality.

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
./htest/hspace --simu p,4,8T,64g,16 -S $T/simu-onegroup \
  --disk-template drbd -l 8 -v -v -v >/dev/null 2>&1
echo OK

echo -n Generating hinfo and hbal test files for multi-group...
./htest/hspace --simu p,4,8T,64g,16 --simu p,4,8T,64g,16 \
  -S $T/simu-twogroups --disk-template drbd -l 8 >/dev/null 2>&1
echo OK

echo -n Generating test files for rebalancing...
# we generate a cluster with two node groups, one with unallocable
# policy, then we change all nodes from this group to the allocable
# one, and we check for rebalancing
FROOT="$T/simu-rebal-orig"
./htest/hspace --simu u,4,8T,64g,16 --simu p,4,8T,64g,16 \
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
    < $TESTDATA_DIR/hail-node-evac.json \
    > $T/hail-node-evac.json.$evac_mode
done
echo OK

echo -n Checking file-based RAPI...
mkdir -p $T/hscan
export RAPI_URL="file://$TESTDATA_DIR/rapi"
./htest/hscan -d $T/hscan/ -p -v -v $RAPI_URL >/dev/null 2>&1
# check that we file parsing is correct, i.e. hscan saves correct text
# files, and is idempotent (rapi+text == rapi); more is tested in
# shelltest later
RAPI_TXT="$(ls $T/hscan/*.data|head -n1)"
./htest/hinfo -p --print-instances -m $RAPI_URL > $T/hscan/direct.hinfo 2>&1
./htest/hinfo -p --print-instances -t $RAPI_TXT > $T/hscan/fromtext.hinfo 2>&1
echo OK

echo Running shelltest...

shelltest $SHELLTESTARGS \
  ${TOP_SRCDIR:-.}/htest/shelltests/htools-*.test \
  -- --hide-successes

echo All OK
