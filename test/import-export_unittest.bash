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

impexpd="$PYTHON daemons/import-export -d"

err() {
  echo "$@"
  echo 'Aborting'
  show_output
  exit 1
}

show_output() {
  if [[ -s "$dst_output" ]]; then
    echo
    echo 'Import output:'
    cat $dst_output
  fi
  if [[ -s "$src_output" ]]; then
    echo
    echo 'Export output:'
    cat $src_output
  fi
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
src_output=$statusdir/src.output
src_x509=$statusdir/src.pem

dst_statusfile=$statusdir/dst.status
dst_output=$statusdir/dst.output
dst_x509=$statusdir/dst.pem
dst_portfile=$statusdir/dst.port

other_x509=$statusdir/other.pem

testdata=$statusdir/data1
largetestdata=$statusdir/data2

cmd_prefix=
cmd_suffix=
connect_timeout=10
connect_retries=1
compress=gzip

$impexpd >/dev/null 2>&1 &&
  err "daemon-util succeeded without parameters"

$impexpd foo bar baz moo boo >/dev/null 2>&1 &&
  err "daemon-util succeeded with wrong parameters"

$impexpd $src_statusfile >/dev/null 2>&1 &&
  err "daemon-util succeeded with insufficient parameters"

$impexpd $src_statusfile invalidmode >/dev/null 2>&1 &&
  err "daemon-util succeeded with invalid mode"

$impexpd $src_statusfile import --compression=rot13 >/dev/null 2>&1 &&
  err "daemon-util succeeded with invalid compression"

cat $(get_testfile proc_drbd8.txt) $(get_testfile cert1.pem) > $testdata

# Generate about 7.5 MB of test data
{ tmp="$(<$testdata)"
  for (( i=0; i < 100; ++i )); do
    echo "$tmp $tmp $tmp $tmp $tmp $tmp"
  done
  dd if=/dev/zero bs=1024 count=4096 2>/dev/null
  for (( i=0; i < 100; ++i )); do
    echo "$tmp $tmp $tmp $tmp $tmp $tmp"
  done
} > $largetestdata

impexpd_helper() {
  $PYTHON $(get_testpath)/import-export_unittest-helper "$@"
}

upto() {
  echo "$(date '+%F %T'):" "$@" '...'
}

reset_status() {
  rm -f $src_statusfile $dst_output $dst_statusfile $dst_output $dst_portfile
}

write_data() {
  local fname=${1:-$testdata}

  # Wait for connection to be established
  impexpd_helper $dst_statusfile connected

  cat $fname
}

do_export() {
  # Wait for listening port
  impexpd_helper $dst_statusfile listen-port > $dst_portfile

  local port=$(< $dst_portfile)

  test -n "$port" || err 'Empty port file'
  test "$port" != None || err 'Missing port'

  do_export_to_port $port
}

do_export_to_port() {
  local port=$1

  $impexpd $src_statusfile export --bind=127.0.0.1 \
    --host=127.0.0.1 --port=$port \
    --key=$src_x509 --cert=$src_x509 --ca=$dst_x509 \
    --cmd-prefix="$cmd_prefix" --cmd-suffix="$cmd_suffix" \
    --connect-timeout=$connect_timeout \
    --connect-retries=$connect_retries \
    --compress=$compress
}

do_import() {
  $impexpd $dst_statusfile import --bind=127.0.0.1 \
    --host=127.0.0.1 \
    --key=$dst_x509 --cert=$dst_x509 --ca=$src_x509 \
    --cmd-prefix="$cmd_prefix" --cmd-suffix="$cmd_suffix" \
    --connect-timeout=$connect_timeout \
    --connect-retries=$connect_retries \
    --compress=$compress
}

upto 'Generate X509 certificates and keys'
impexpd_helper $src_x509 gencert
impexpd_helper $dst_x509 gencert
impexpd_helper $other_x509 gencert

upto 'Normal case'
reset_status
do_import > $statusdir/recv1 2>$dst_output & imppid=$!
{ write_data | do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv1 || err 'Received data does not match input'

upto 'Export using wrong CA'
reset_status
# Setting lower timeout to not wait for too long
connect_timeout=1 do_import &>$dst_output & imppid=$!
: | dst_x509=$other_x509 do_export &>$src_output & exppid=$!
checkpids $exppid $imppid && err 'Export did not fail when using wrong CA'

upto 'Import using wrong CA'
reset_status
# Setting lower timeout to not wait for too long
src_x509=$other_x509 connect_timeout=1 do_import &>$dst_output & imppid=$!
: | do_export &>$src_output & exppid=$!
checkpids $exppid $imppid && err 'Import did not fail when using wrong CA'

upto 'Suffix command on import'
reset_status
cmd_suffix="| cksum > $statusdir/recv2" do_import &>$dst_output & imppid=$!
{ write_data | do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || err 'Testing additional commands failed'
cmp $statusdir/recv2 <(cksum < $testdata) || \
  err 'Checksum of received data does not match'

upto 'Prefix command on export'
reset_status
do_import > $statusdir/recv3 2>$dst_output & imppid=$!
{ write_data | cmd_prefix="cksum |" do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || err 'Testing additional commands failed'
cmp $statusdir/recv3 <(cksum < $testdata) || \
  err 'Received checksum does not match'

upto 'Failing prefix command on export'
reset_status
: | cmd_prefix='exit 1;' do_export_to_port 0 &>$src_output & exppid=$!
checkpids $exppid && err 'Prefix command on export did not fail when it should'

upto 'Failing suffix command on export'
reset_status
do_import >&$src_output & imppid=$!
: | cmd_suffix='| exit 1' do_export &>$dst_output & exppid=$!
checkpids $imppid $exppid && \
  err 'Suffix command on export did not fail when it should'

upto 'Failing prefix command on import'
reset_status
cmd_prefix='exit 1;' do_import &>$dst_output & imppid=$!
checkpids $imppid && err 'Prefix command on import did not fail when it should'

upto 'Failing suffix command on import'
reset_status
cmd_suffix='| exit 1' do_import &>$dst_output & imppid=$!
: | do_export &>$src_output & exppid=$!
checkpids $imppid $exppid && \
  err 'Suffix command on import did not fail when it should'

upto 'Listen timeout A'
reset_status
# Setting lower timeout to not wait too long (there won't be anything trying to
# connect)
connect_timeout=1 do_import &>$dst_output & imppid=$!
checkpids $imppid && \
  err 'Listening with timeout did not fail when it should'

upto 'Listen timeout B'
reset_status
do_import &>$dst_output & imppid=$!
{ sleep 1; : | do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || \
  err 'Listening with timeout failed when it should not'

upto 'No compression'
reset_status
compress=none do_import > $statusdir/recv-nocompr 2>$dst_output & imppid=$!
{ write_data | compress=none do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv-nocompr || \
  err 'Received data does not match input'

upto 'Compression mismatch A'
reset_status
compress=none do_import > $statusdir/recv-miscompr 2>$dst_output & imppid=$!
{ write_data | compress=gzip do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || err 'An error occurred'
cmp -s $testdata $statusdir/recv-miscompr && \
  err 'Received data matches input when it should not'

upto 'Compression mismatch B'
reset_status
compress=gzip do_import > $statusdir/recv-miscompr2 2>$dst_output & imppid=$!
{ write_data | compress=none do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid && err 'Did not fail when it should'
cmp -s $testdata $statusdir/recv-miscompr2 && \
  err 'Received data matches input when it should not'

upto 'Large transfer'
reset_status
do_import > $statusdir/recv-large 2>$dst_output & imppid=$!
{ write_data $largetestdata | do_export; } &>$src_output & exppid=$!
checkpids $exppid $imppid || err 'An error occurred'
cmp $largetestdata $statusdir/recv-large || \
  err 'Received data does not match input'

exit 0
