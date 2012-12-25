#!/bin/bash
#

# Copyright (C) 2010, 2011 Google Inc.
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

daemon_util=daemons/daemon-util

err() {
  echo "$@"
  echo 'Aborting'
  exit 1
}

if ! grep -q '^ENABLE_CONFD = ' lib/_autoconf.py; then
  err "Please update $0, confd enable feature is missing"
fi

if grep -q '^ENABLE_CONFD = True' lib/_autoconf.py; then
  DAEMONS="$(echo ganeti-{noded,masterd,rapi,confd})"
  STOPDAEMONS="$(echo ganeti-{confd,rapi,masterd,noded})"
else
  DAEMONS="$(echo ganeti-{noded,masterd,rapi})"
  STOPDAEMONS="$(echo ganeti-{rapi,masterd,noded})"
fi

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
