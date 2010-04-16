#!/bin/bash
#

# Copyright (C) 2010 Google Inc.
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

impexpd="$PYTHON daemons/import-export --connect-timeout=1 --connect-retries=1"

# Add "-d" for debugging
#impexpd+=' -d'

err() {
  echo "$@"
  echo 'Aborting'
  exit 1
}

checkpids() {
  local result=0

  # Unlike combining the "wait" commands using || or &&, this ensures we
  # actually wait for all PIDs.
  for pid in "$@"; do
    if ! wait $pid; then
      result=1
    fi
  done

  return $result
}

get_testpath() {
  echo "${TOP_SRCDIR:-.}/test"
}

get_testfile() {
  echo "$(get_testpath)/data/$1"
}

statusdir=$(mktemp -d)
trap "rm -rf $statusdir" EXIT

src_statusfile=$statusdir/src.status
src_x509=$statusdir/src.pem

dst_statusfile=$statusdir/dst.status
dst_x509=$statusdir/dst.pem
dst_portfile=$statusdir/dst.port

other_x509=$statusdir/other.pem

testdata=$statusdir/data1

cmd_prefix=
cmd_suffix=

$impexpd >/dev/null 2>&1 &&
  err "daemon-util succeeded without parameters"

$impexpd foo bar baz moo boo >/dev/null 2>&1 &&
  err "daemon-util succeeded with wrong parameters"

$impexpd $src_statusfile >/dev/null 2>&1 &&
  err "daemon-util succeeded with insufficient parameters"

$impexpd $src_statusfile invalidmode >/dev/null 2>&1 &&
  err "daemon-util succeeded with invalid mode"

cat $(get_testfile proc_drbd8.txt) $(get_testfile cert1.pem) > $testdata

impexpd_helper() {
  $PYTHON $(get_testpath)/import-export_unittest-helper "$@"
}

reset_status() {
  rm -f $src_statusfile $dst_statusfile $dst_portfile
}

write_data() {
  # Wait for connection to be established
  impexpd_helper $dst_statusfile connected

  cat $testdata
}

do_export() {
  # Wait for listening port
  impexpd_helper $dst_statusfile listen-port > $dst_portfile

  local port=$(< $dst_portfile)

  test -n "$port" || err 'Empty port file'

  do_export_to_port $port
}

do_export_to_port() {
  local port=$1

  $impexpd $src_statusfile export --bind=127.0.0.1 \
    --host=127.0.0.1 --port=$port \
    --key=$src_x509 --cert=$src_x509 --ca=$dst_x509 \
    --cmd-prefix="$cmd_prefix" --cmd-suffix="$cmd_suffix"
}

do_import() {
  $impexpd $dst_statusfile import --bind=127.0.0.1 \
    --host=127.0.0.1 \
    --key=$dst_x509 --cert=$dst_x509 --ca=$src_x509 \
    --cmd-prefix="$cmd_prefix" --cmd-suffix="$cmd_suffix"
}

# Generate X509 certificates and keys
impexpd_helper $src_x509 gencert
impexpd_helper $dst_x509 gencert
impexpd_helper $other_x509 gencert

# Normal case
reset_status
do_import > $statusdir/recv1 & imppid=$!
write_data | do_export & exppid=$!
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv1 || err 'Received data does not match input'

# Export using wrong CA
reset_status
do_import > /dev/null 2>&1 & imppid=$!
: | dst_x509=$other_x509 do_export 2>/dev/null & exppid=$!
checkpids $exppid $imppid && err 'Export did not fail when using wrong CA'

# Import using wrong CA
reset_status
src_x509=$other_x509 do_import > /dev/null 2>&1 & imppid=$!
: | do_export 2> /dev/null & exppid=$!
checkpids $exppid $imppid && err 'Import did not fail when using wrong CA'

# Suffix command on import
reset_status
cmd_suffix="| cksum > $statusdir/recv2" do_import & imppid=$!
write_data | do_export & exppid=$!
checkpids $exppid $imppid || err 'Testing additional commands failed'
cmp $statusdir/recv2 <(cksum < $testdata) || \
  err 'Checksum of received data does not match'

# Prefix command on export
reset_status
do_import > $statusdir/recv3 & imppid=$!
write_data | cmd_prefix="cksum |" do_export & exppid=$!
checkpids $exppid $imppid || err 'Testing additional commands failed'
cmp $statusdir/recv3 <(cksum < $testdata) || \
  err 'Received checksum does not match'

# Failing prefix command on export
reset_status
: | cmd_prefix='exit 1;' do_export_to_port 0 & exppid=$!
checkpids $exppid && err 'Prefix command on export did not fail when it should'

# Failing suffix command on export
reset_status
do_import > /dev/null & imppid=$!
: | cmd_suffix='| exit 1' do_export & exppid=$!
checkpids $imppid $exppid && \
  err 'Suffix command on export did not fail when it should'

# Failing prefix command on import
reset_status
cmd_prefix='exit 1;' do_import > /dev/null & imppid=$!
checkpids $imppid && err 'Prefix command on import did not fail when it should'

# Failing suffix command on import
reset_status
cmd_suffix='| exit 1' do_import > /dev/null & imppid=$!
: | do_export & exppid=$!
checkpids $imppid $exppid && \
  err 'Suffix command on import did not fail when it should'

exit 0
