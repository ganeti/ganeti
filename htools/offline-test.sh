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

T=`mktemp -d`
trap 'rm -rf $T' EXIT
trap 'echo FAIL' ERR
echo Using $T as temporary dir

echo Checking command line basic options
for prog in $ALL_ROLES; do
  $prog --version >/dev/null
  $prog --help >/dev/null
  ! $prog --no-such-option 2>/dev/null
done
echo OK

echo Checking missing backend failure
for prog in hspace hinfo hbal; do
  ! $prog 2>/dev/null
done
echo OK

echo Checking hail missing input file
! hail 2>/dev/null
echo OK

echo Checking extra arguments
for prog in hspace hbal hinfo; do
  (! $prog unexpected-argument 2>&1 ) | \
    grep -q "Error: this program doesn't take any arguments"
done
echo OK

echo Checking failure on multiple backends
(! hbal -t /dev/null -m localhost 2>&1 ) | \
  grep -q "Error: Only one of the rapi, luxi, and data files options should be given."
echo OK

echo Checking hspace machine-readable mode
hspace --simu p,4,8T,64g,16 --machine-readable \
  --disk-template drbd -l 8 >$T/capacity
( . $T/capacity && test "$HTS_OK" = "1" )
echo OK

echo Checking hspace simulation to hinfo to hbal
# this cluster spec should be fine
hspace --simu p,4,8T,64g,16 -S $T/simu-onegroup \
  --disk-template drbd -l 8 -v -v -v >/dev/null 2>&1
# results in .tiered and .standard
for suffix in standard tiered; do
  BACKEND="-t$T/simu-onegroup.$suffix"
  hinfo -v -v -p --print-instances $BACKEND >/dev/null 2>&1
  hbal  -v -v -p --print-instances $BACKEND >/dev/null 2>&1
  # hbal should not be able to balance
  hbal $BACKEND | grep -qE "(Nothing to do, exiting|No solution found)"
done
echo OK

echo Checking hinfo and hbal on multi-nodegroup
hspace --simu p,4,8T,64g,16 --simu p,4,8T,64g,16 \
  -S $T/simu-twogroups --disk-template drbd -l 8 >/dev/null 2>&1
# results in .tiered and .standard
for suffix in standard tiered; do
  BACKEND="-t$T/simu-twogroups.$suffix"
  hinfo -v -v -p --print-instances $BACKEND >/dev/null 2>&1
  ! hbal $BACKEND >/dev/null 2>&1
  # hbal should not be able to balance
  ! hbal $BACKEND 2>&1 | grep -q "Found multiple node groups"
  # but hbal should be able to balance one node group
  hbal $BACKEND -G group-01 >/dev/null
  # and it should not find an invalid group
  ! hbal $BACKEND -G no-such-group >/dev/null 2>&1
done
echo OK

echo Checking rebalancing
# we generate a cluster with two node groups, one with unallocable
# policy, then we change all nodes from this group to the allocable
# one, and we check for rebalancing
FROOT="$T/simu-rebal-orig"
hspace --simu u,4,8T,64g,16 --simu p,4,8T,64g,16 \
  -S $FROOT --disk-template drbd -l 8 >/dev/null 2>&1
for suffix in standard tiered; do
  RELOC="$T/simu-rebal-merged.$suffix"
  # this relocates the nodes
  sed -re 's/^(node-.*|fake-uuid-)-02(|.*)/\1-01\2/' \
    < $FROOT.$suffix > $RELOC
  BACKEND="-t$RELOC"
  hinfo -v -v -p --print-instances $BACKEND >/dev/null 2>&1
  hbal -v -v -v -p --print-instances $BACKEND -G group-01 2>/dev/null | \
    grep -qE -v "(Nothing to do, exiting|No solution found)"
  hbal $BACKEND -G group-01 -C$T/rebal-cmds.$suffix \
    -S $T/simu-rebal.$suffix >/dev/null 2>&1
  grep -qE "gnt-instance (failover|migrate|replace-disks)" \
    $T/rebal-cmds.$suffix
  hbal $BACKEND -G group-01 -C \
    -S $T/simu-rebal.$suffix 2>/dev/null | \
    grep -qE "gnt-instance (failover|migrate|replace-disks)"
  # state saved by hbal should be original
  cmp $RELOC $T/simu-rebal.$suffix.original
  # and we can't double rebalance
  hbal -t $T/simu-rebal.$suffix.balanced \
    -G group-01 | \
    grep -qE "(Nothing to do, exiting|No solution found)"

done
echo OK

echo IAllocator checks
# test that on invalid files it can't parse the request
(! hail /dev/null 2>&1 ) | grep -q "Invalid JSON"
! hail <(echo '[]') >/dev/null 2>&1
(! hail <(echo '{}') 2>&1 ) | grep -q "key 'request' not found"
(! hail <(echo '{"request": 0}') 2>&1 ) | grep -q "key 'request'"
! hail $TESTDATA_DIR/hail-invalid-reloc.json >/dev/null 2>&1

# just test that it can read the file, print the cluster and generate
# pre and post allocation files
hail -v -v -v -p $TESTDATA_DIR/hail-alloc-drbd.json \
  -S $T/hail-alloc >/dev/null 2>&1
! cmp -s $T/hail-alloc.pre-ialloc $T/hail-alloc.post-ialloc
hail -v -v -v -p $TESTDATA_DIR/hail-reloc-drbd.json \
  -S $T/hail-reloc >/dev/null 2>&1
! cmp -s $T/hail-reloc.pre-ialloc $T/hail-reloc.post-ialloc

# and now start the real tests
hail $TESTDATA_DIR/hail-alloc-drbd.json | \
  grep -q '"success":true,.*,"result":\["node2","node1"\]'
hail $TESTDATA_DIR/hail-reloc-drbd.json | \
  grep -q '"success":true,.*,"result":\["node1"\]'

hail $TESTDATA_DIR/hail-node-evac.json | \
  grep -Fq '"success":true,"info":"Request successful: 0 instances failed to move and 1 were moved successfully"'

hail $TESTDATA_DIR/hail-change-group.json | \
  grep -Fq '"success":true,"info":"Request successful: 0 instances failed to move and 1 were moved successfully"'

for evac_mode in primary-only secondary-only all; do
  sed -e 's/"evac_mode": "all"/"evac_mode": "'${evac_mode}'"/' \
    < $TESTDATA_DIR/hail-node-evac.json \
    > $T/hail-node-evac.json.$evac_mode
  hail $T/hail-node-evac.json.$evac_mode | \
    grep -q '"success":true,"info":"Request successful: 0 instances failed to move and 1 were moved successfully"'
done

# check that hail can use the simu and text backends
hail --simu p,8,8T,16g,16 $TESTDATA_DIR/hail-alloc-drbd.json | \
  grep -q '"success":true,'
hail -t $T/simu-rebal-merged.standard $TESTDATA_DIR/hail-alloc-drbd.json | \
  grep -q '"success":true,'
echo OK

echo Checking file-based RAPI
mkdir -p $T/hscan
URL="file://$TESTDATA_DIR/rapi"
hinfo -v -v -p --print-instances -m $URL >/dev/null 2>&1
hbal -v -v -p --print-instances -m $URL >/dev/null 2>&1
hscan -d $T/hscan/ -p -v -v $URL >/dev/null 2>&1
# check that we file parsing is correct, i.e. hscan saves correct text
# files, and is idempotent (rapi+text == rapi)
HS="$(ls $T/hscan/*.data|head -n1)"
hinfo -p --print-instances -m $URL > $T/hscan/direct.hinfo 2>&1
hinfo -p --print-instances -t $HS  > $T/hscan/fromtext.hinfo 2>&1
cmp -s $T/hscan/direct.hinfo $T/hscan/fromtext.hinfo
echo OK

echo All OK
