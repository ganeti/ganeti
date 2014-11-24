#!/bin/bash
#

# Copyright (C) 2010, 2011 Google Inc.
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

daemon_util=daemons/daemon-util

err() {
  echo "$@"
  echo 'Aborting'
  exit 1
}

if ! grep -q '^ENABLE_MOND = ' lib/_constants.py; then
  err "Please update $0, mond enable feature is missing"
fi

DAEMONS_LIST="noded confd wconfd rapi luxid kvmd"
STOPDAEMONS_LIST="kvmd luxid rapi wconfd confd noded"

if grep -q '^ENABLE_MOND = True' lib/_constants.py; then
  DAEMONS_LIST="$DAEMONS_LIST mond"
  STOPDAEMONS_LIST="mond $STOPDAEMONS_LIST"
fi

STOPDAEMONS_LIST="metad $STOPDAEMONS_LIST"

DAEMONS=$(echo $(for d in $DAEMONS_LIST; do echo "ganeti-$d"; done))
STOPDAEMONS=$(echo $(for d in $STOPDAEMONS_LIST; do echo "ganeti-$d"; done))

$daemon_util >/dev/null 2>&1 &&
  err "daemon-util succeeded without command"

$daemon_util this-is-an-unimplemented-command >/dev/null 2>&1 &&
  err "daemon-util accepted unimplemented command"

$daemon_util list_start_daemons >/dev/null 2>&1 &&
  err "daemon-util accepted command with underscores"

$daemon_util check-exitcode 0 ||
  err "check-exitcode 0 failed"

for i in 1 2 3 4 20 25 33; do
  $daemon_util check-exitcode $i >/dev/null 2>&1 && rc=0 || rc=$?
  test "$rc" == 1 || err "check-exitcode $i didn't return 1"
done

$daemon_util check-exitcode 11 >/dev/null 2>&1 ||
  err "check-exitcode 11 (not master) didn't return 0"

tmp=$(echo $($daemon_util list-start-daemons))
test "$tmp" == "$DAEMONS" ||
  err "list-start-daemons didn't return correct list of daemons"

tmp=$(echo $($daemon_util list-stop-daemons))
test "$tmp" == "$STOPDAEMONS" ||
  err "list-stop-daemons didn't return correct list of daemons"

$daemon_util is-daemon-name >/dev/null 2>&1 &&
  err "is-daemon-name didn't require daemon name"

for i in '' '.' '..' '-' 'not-a-daemon'; do
  $daemon_util is-daemon-name "$i" >/dev/null 2>&1 &&
    err "is-daemon-name thinks '$i' is a daemon name"
done

for i in $DAEMONS; do
  $daemon_util is-daemon-name $i >/dev/null 2>&1 ||
    err "is-daemon-name doesn't think '$i' is a daemon name"
done
