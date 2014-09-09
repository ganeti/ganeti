#!/bin/bash
#

# Copyright (C) 2010, 2012 Google Inc.
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
  if [[ -s "$gencert_output" ]]; then
    echo
    echo 'Generating certificates:'
    cat $gencert_output
  fi
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

upto() {
  echo "$(date '+%F %T'):" "$@" '...'
}

statusdir=$(mktemp -d)
trap "rm -rf $statusdir" EXIT

gencert_output=$statusdir/gencert.output

src_statusfile=$statusdir/src.status
src_output=$statusdir/src.output
src_x509=$statusdir/src.pem

dst_statusfile=$statusdir/dst.status
dst_output=$statusdir/dst.output
dst_x509=$statusdir/dst.pem

other_x509=$statusdir/other.pem

testdata=$statusdir/data1
largetestdata=$statusdir/data2

upto 'Command line parameter tests'

$impexpd >/dev/null 2>&1 &&
  err "daemon-util succeeded without parameters"

$impexpd foo bar baz moo boo >/dev/null 2>&1 &&
  err "daemon-util succeeded with wrong parameters"

$impexpd $src_statusfile >/dev/null 2>&1 &&
  err "daemon-util succeeded with insufficient parameters"

$impexpd $src_statusfile invalidmode >/dev/null 2>&1 &&
  err "daemon-util succeeded with invalid mode"

for mode in import export; do
  $impexpd $src_statusfile $mode --compression=rot13 >/dev/null 2>&1 &&
    err "daemon-util succeeded with invalid compression"

  for host in '' '  ' ' s p a c e' ... , foo.example.net... \
              'some"evil"name' 'x\ny\tmoo'; do
    $impexpd $src_statusfile $mode --host="$host" >/dev/null 2>&1 &&
      err "daemon-util succeeded with invalid host '$host'"
  done

  for port in '' ' ' -1234 'some ` port " here'; do
    $impexpd $src_statusfile $mode --port="$port" >/dev/null 2>&1 &&
      err "daemon-util succeeded with invalid port '$port'"
  done

  for magic in '' ' ' 'this`is' 'invalid!magic' 'he"re'; do
    $impexpd $src_statusfile $mode --magic="$magic" >/dev/null 2>&1 &&
      err "daemon-util succeeded with invalid magic '$magic'"
  done
done

upto 'Generate test data'
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
  $PYTHON $(get_testpath)/py/import-export_unittest-helper "$@"
}

start_test() {
  upto "$@"

  rm -f $src_statusfile $dst_output $dst_statusfile $dst_output
  rm -f $gencert_output

  imppid=
  exppid=

  cmd_prefix=
  cmd_suffix=
  connect_timeout=30
  connect_retries=1
  compress=gzip
  magic=
}

wait_import_ready() {
  # Wait for listening port
  impexpd_helper $dst_statusfile listen-port
}

do_export() {
  local port=$1

  $impexpd $src_statusfile export --bind=127.0.0.1 \
    --host=127.0.0.1 --port=$port \
    --key=$src_x509 --cert=$src_x509 --ca=$dst_x509 \
    --cmd-prefix="$cmd_prefix" --cmd-suffix="$cmd_suffix" \
    --connect-timeout=$connect_timeout \
    --connect-retries=$connect_retries \
    --compress=$compress ${magic:+--magic="$magic"}
}

do_import() {
  $impexpd $dst_statusfile import --bind=127.0.0.1 \
    --host=127.0.0.1 \
    --key=$dst_x509 --cert=$dst_x509 --ca=$src_x509 \
    --cmd-prefix="$cmd_prefix" --cmd-suffix="$cmd_suffix" \
    --connect-timeout=$connect_timeout \
    --connect-retries=$connect_retries \
    --compress=$compress ${magic:+--magic="$magic"}
}

upto 'Generate X509 certificates and keys'
impexpd_helper $src_x509 gencert 2>$gencert_output & srccertpid=$!
impexpd_helper $dst_x509 gencert 2>$gencert_output & dstcertpid=$!
impexpd_helper $other_x509 gencert 2>$gencert_output & othercertpid=$!
checkpids $srccertpid $dstcertpid $othercertpid || \
  err 'Failed to generate certificates'

start_test 'Normal case'
do_import > $statusdir/recv1 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv1 || err 'Received data does not match input'

start_test 'Export using wrong CA'
# Setting lower timeout to not wait for too long
connect_timeout=1 do_import &>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  : | dst_x509=$other_x509 do_export $port >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid && err 'Export did not fail when using wrong CA'

start_test 'Import using wrong CA'
# Setting lower timeout to not wait for too long
src_x509=$other_x509 connect_timeout=1 do_import &>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  : | do_export $port >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid && err 'Import did not fail when using wrong CA'

start_test 'Suffix command on import'
cmd_suffix="| cksum > $statusdir/recv2" do_import &>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'Testing additional commands failed'
cmp $statusdir/recv2 <(cksum < $testdata) || \
  err 'Checksum of received data does not match'

start_test 'Prefix command on export'
do_import > $statusdir/recv3 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  cmd_prefix='cksum |' do_export $port <$testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'Testing additional commands failed'
cmp $statusdir/recv3 <(cksum < $testdata) || \
  err 'Received checksum does not match'

start_test 'Failing prefix command on export'
: | cmd_prefix='exit 1;' do_export 0 &>$src_output & exppid=$!
checkpids $exppid && err 'Prefix command on export did not fail when it should'

start_test 'Failing suffix command on export'
do_import >&$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  : | cmd_suffix='| exit 1' do_export $port >>$src_output 2>&1 & exppid=$!
fi
checkpids $imppid $exppid && \
  err 'Suffix command on export did not fail when it should'

start_test 'Failing prefix command on import'
cmd_prefix='exit 1;' do_import &>$dst_output & imppid=$!
checkpids $imppid && err 'Prefix command on import did not fail when it should'

start_test 'Failing suffix command on import'
cmd_suffix='| exit 1' do_import &>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  : | do_export $port >>$src_output 2>&1 & exppid=$!
fi
checkpids $imppid $exppid && \
  err 'Suffix command on import did not fail when it should'

start_test 'Listen timeout A'
# Setting lower timeout to not wait too long (there won't be anything trying to
# connect)
connect_timeout=1 do_import &>$dst_output & imppid=$!
checkpids $imppid && \
  err 'Listening with timeout did not fail when it should'

start_test 'Listen timeout B'
do_import &>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  { sleep 1; : | do_export $port; } >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || \
  err 'Listening with timeout failed when it should not'

start_test 'Connect timeout'
# Setting lower timeout as nothing will be listening on port 0
: | connect_timeout=1 do_export 0 &>$src_output & exppid=$!
checkpids $exppid && err 'Connection did not time out when it should'

start_test 'No compression'
compress=none do_import > $statusdir/recv-nocompr 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  compress=none do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv-nocompr || \
  err 'Received data does not match input'

start_test 'Compression mismatch A'
compress=none do_import > $statusdir/recv-miscompr 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  compress=gzip do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'An error occurred'
cmp -s $testdata $statusdir/recv-miscompr && \
  err 'Received data matches input when it should not'

start_test 'Compression mismatch B'
compress=gzip do_import > $statusdir/recv-miscompr2 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  compress=none do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid && err 'Did not fail when it should'
cmp -s $testdata $statusdir/recv-miscompr2 && \
  err 'Received data matches input when it should not'

start_test 'Magic without compression'
compress=none magic=MagicValue13582 \
do_import > $statusdir/recv-magic1 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  compress=none magic=MagicValue13582 \
  do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv-magic1 || err 'Received data does not match input'

start_test 'Magic with compression'
compress=gzip magic=yzD1FBH7Iw \
do_import > $statusdir/recv-magic2 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  compress=gzip magic=yzD1FBH7Iw \
  do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'An error occurred'
cmp $testdata $statusdir/recv-magic2 || err 'Received data does not match input'

start_test 'Magic mismatch A (same length)'
magic=h0tmIKXK do_import > $statusdir/recv-magic3 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  magic=bo6m9uAw do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid && err 'Did not fail when it should'

start_test 'Magic mismatch B'
magic=AUxVEWXVr5GK do_import > $statusdir/recv-magic4 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  magic=74RiP9KP do_export $port < $testdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid && err 'Did not fail when it should'

start_test 'Large transfer'
do_import > $statusdir/recv-large 2>$dst_output & imppid=$!
if port=$(wait_import_ready 2>$src_output); then
  do_export $port < $largetestdata >>$src_output 2>&1 & exppid=$!
fi
checkpids $exppid $imppid || err 'An error occurred'
cmp $largetestdata $statusdir/recv-large || \
  err 'Received data does not match input'

exit 0
