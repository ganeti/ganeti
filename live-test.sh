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

echo Testing hscan
./hscan -d$T $RAPI

echo Testing hbal/luxi
./hbal -L$LUXI
echo Testing hbal/rapi
./hbal -m$RAPI
echo Testing hbal/text
./hbal -t$T/$RAPI.data

echo Getting data files for hail
IR=`$CLUSTER head -n1 /var/lib/ganeti/ssconf_instance_list`
$CLUSTER gnt-debug allocator --dir in --mode allocate --mem 128m \
    --disks 128m -t drbd -o no_such_os no_such_instance \
    > $T/h-alloc.json
$CLUSTER gnt-debug allocator --dir in --mode relocate --mem 128m \
    --disks 128m -t drbd -o no_such_os $IR > $T/h-reloc.json
echo Testing hail/allocate
./hail $T/h-alloc.json
echo Testing hail/relocate
./hail $T/h-reloc.json

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
./hspace -L$LUXI $TIER > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/rapi
./hspace -m$RAPI $TIER > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/text
./hspace -t$T/$RAPI.data $TIER > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/simu
# ~6T disk space, 32G ram, 4 VCPUs
./hspace --simu=10,6835937,32768,4 $TIER > $HOUT
( check_hspace_out ) || exit 1
echo All OK
