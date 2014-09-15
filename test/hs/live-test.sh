#!/bin/bash

# Copyright (C) 2009, 2010, 2011, 2012 Google Inc.
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

# This is a live-testing script for most/all of the htools
# programs. It needs either to run on a live cluster or access to a
# cluster via ssh and an exported LUXI interface (via socat, for
# example). The cluster must not be empty (otherwise the hail relocate
# test will fail).

# Use: if running on a cluster master, just running it should be
# enough. If running remotely, set env vars as follows: LUXI to the
# export unix socket, RAPI to the cluster IP, CLUSTER to the command
# used to login on the cluster (e.g. CLUSTER="ssh root@cluster"). Note
# that when run against a multi-group cluster, the GROUP variable
# should be set to one of the groups (some operations work only on one
# group)

set -e
: ${RAPI:=localhost}
GROUP=${GROUP:+-G $GROUP}

. $(dirname $0)/cli-tests-defs.sh

T=`mktemp -d`
trap 'rm -rf $T' EXIT
echo Using $T as temporary dir

echo Checking command line
for prog in $ALL_ROLES; do
  $prog --version
  $prog --help >/dev/null
  ! $prog --no-such-option 2>/dev/null
done

echo Testing hscan/rapi
hscan -d$T $RAPI -p
echo Testing hscan/luxi
hscan -d$T -L$LUXI -p
echo Comparing hscan results...
diff -u $T/$RAPI.data $T/LOCAL.data

FN=$($CLUSTER head -n1 /var/lib/ganeti/ssconf_node_list)
FI=$($CLUSTER head -n1 /var/lib/ganeti/ssconf_instance_list)


echo Testing hbal/luxi
hbal -L$LUXI $GROUP -p --print-instances -C$T/hbal-luxi-cmds.sh
bash -n $T/hbal-luxi-cmds.sh
echo Testing hbal/rapi
hbal -m$RAPI $GROUP -p --print-instances -C$T/hbal-rapi-cmds.sh
bash -n $T/hbal-rapi-cmds.sh
echo Testing hbal/text
hbal -t$T/$RAPI.data $GROUP -p --print-instances -C$T/hbal-text-cmds.sh
bash -n $T/hbal-text-cmds.sh
echo Comparing hbal results
diff -u $T/hbal-luxi-cmds.sh $T/hbal-rapi-cmds.sh
diff -u $T/hbal-luxi-cmds.sh $T/hbal-text-cmds.sh


echo Testing hbal/text with evacuation mode
hbal -t$T/$RAPI.data $GROUP -E
echo Testing hbal/text with no disk moves
hbal -t$T/$RAPI.data $GROUP --no-disk-moves
echo Testing hbal/text with no instance moves
hbal -t$T/$RAPI.data $GROUP --no-instance-moves
echo Testing hbal/text with offline node mode
hbal -t$T/$RAPI.data $GROUP -O$FN
echo Testing hbal/text with utilization data
echo "$FI 2 2 2 2" > $T/util.data
hbal -t$T/$RAPI.data $GROUP -U $T/util.data
echo Testing hbal/text with bad utilization data
echo "$FI 2 a 3b" > $T/util.data
! hbal -t$T/$RAPI.data $GROUP -U $T/util.data
echo Testing hbal/text with instance exclusion/selection
hbal -t$T/$RAPI.data $GROUP --exclude-instances=$FI
hbal -t$T/$RAPI.data $GROUP --select-instances=$FI
! hbal -t$T/$RAPI.data --exclude-instances=no_such_instance
! hbal -t$T/$RAPI.data --select-instances=no_such_instance
echo Testing hbal/text with tag exclusion
hbal -t $T/$RAPI.data $GROUP --exclusion-tags=no_such_tag
echo Testing hbal multiple backend failure
! hbal -t $T/$RAPI.data -L$LUXI
echo Testing hbal no backend failure
! hbal

echo Getting data files for hail
for dtemplate in plain drbd; do
  $CLUSTER gnt-debug allocator --dir in --mode allocate --mem 128m \
      --disks 128m -t $dtemplate -o no_such_os no_such_instance \
      > $T/h-alloc-$dtemplate.json
done
$CLUSTER gnt-debug allocator --dir in --mode relocate \
    -o no_such_os $FI > $T/h-reloc.json
$CLUSTER gnt-debug allocator --dir in --mode multi-evacuate \
    $FN > $T/h-evacuate.json
for dtemplate in plain drbd; do
  echo Testing hail/allocate-$dtemplate
  hail $T/h-alloc-$dtemplate.json
done
echo Testing hail/relocate for instance $FI
hail $T/h-reloc.json
echo Testing hail/evacuate for node $FN
hail $T/h-evacuate.json

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
SIMU="--simu=preferred,10,6835937,32768,4"
echo Testing hspace/luxi
hspace -L$LUXI $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/rapi
hspace -m$RAPI $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/text
hspace -t$T/$RAPI.data $TIER -v > $HOUT
( check_hspace_out ) || exit 1
echo Testing hspace/simu
# ~6T disk space, 32G ram, 4 VCPUs
hspace $SIMU $TIER -v > $HOUT
( check_hspace_out ) || exit 1
# Wrong tiered spec input
! hspace $SIMU --tiered 1,2,3x
! hspace $SIMU --tiered 1,2,x
! hspace $SIMU --tiered 1,2
# Wrong simu spec
! hspace --simu=1,2,x

echo All OK
