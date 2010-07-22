#!/bin/bash

# Copyright (C) 2009 Google Inc.

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

# This is a live-testing script for most/all of the htools
# programs. It needs either to run on a live cluster or access to a
# cluster via ssh and an exported LUXI interface (via socat, for
# example). The cluster must not be empty (otherwise the hail relocate
# test will fail).

# Use: if running on a cluster master, just running it should be
# enough. If running remotely, set env vars as follows: LUXI to the
# export unix socket, RAPI to the cluster IP, CLUSTER to the command
# used to login on the cluster (e.g. CLUSTER="ssh root@cluster").

set -e
: ${RAPI:=localhost}
T=`mktemp -d`
trap 'rm -rf $T' EXIT
echo Using $T as temporary dir

echo Checking command line
for prog in hscan hbal hail hspace; do
    ./$prog --version
    ./$prog --help
done

echo Testing hscan/rapi
./hscan -d$T $RAPI -p
echo Testing hscan/luxi
./hscan -d$T -L$LUXI -p
echo Comparing hscan results...
diff -u $T/$RAPI.data $T/LOCAL.data

echo Testing hbal/luxi
./hbal -L$LUXI -p --print-instances -C$T/hbal-luxi-cmds.sh
bash -n $T/hbal-luxi-cmds.sh
echo Testing hbal/rapi
./hbal -m$RAPI -p --print-instances -C$T/hbal-rapi-cmds.sh
bash -n $T/hbal-rapi-cmds.sh
echo Testing hbal/text
./hbal -t$T/$RAPI.data -p --print-instances -C$T/hbal-text-cmds.sh
bash -n $T/hbal-text-cmds.sh

echo Testing hbal/text with evacuation mode
./hbal -t$T/$RAPI.data -E
echo Testing hbal/text with offline node mode
FN=$(head -n1 $T/$RAPI.data|cut -d \| -f1)
./hbal -t$T/$RAPI.data -O$FN

echo Getting data files for hail
IR=`$CLUSTER head -n1 /var/lib/ganeti/ssconf_instance_list`
for dtemplate in plain drbd; do
  $CLUSTER gnt-debug allocator --dir in --mode allocate --mem 128m \
      --disks 128m -t $dtemplate -o no_such_os no_such_instance \
      > $T/h-alloc-$dtemplate.json
done
$CLUSTER gnt-debug allocator --dir in --mode relocate \
    -o no_such_os $IR > $T/h-reloc.json
$CLUSTER gnt-debug allocator --dir in --mode multi-evacuate \
    $FN > $T/h-evacuate.json
for dtemplate in plain drbd; do
  echo Testing hail/allocate-$dtemplate
  ./hail $T/h-alloc-$dtemplate.json
done
echo Testing hail/relocate for instance $IR
./hail $T/h-reloc.json
echo Testing hail/evacuate for node $FN
./hail $T/h-evacuate.json

HOUT="$T/hspace.out"

check_hspace_out() {
    set -u
    set -e
    source "$HOUT"
    echo ALLOC_INSTANCES=$HTS_ALLOC_INSTANCES
    echo TSPEC=$HTS_TSPEC
    echo OK=$HTS_OK
}

TIER="--tiered 102400,8192,2"
echo Testing hspace/luxi
./hspace -L$LUXI $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/rapi
./hspace -m$RAPI $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/text
./hspace -t$T/$RAPI.data $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/simu
# ~6T disk space, 32G ram, 4 VCPUs
./hspace --simu=10,6835937,32768,4 $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo All OK
