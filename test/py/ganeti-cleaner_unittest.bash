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

set -e -u
set -o pipefail

export PYTHON=${PYTHON:=python}

GNTC=daemons/ganeti-cleaner
CCE=$PWD/tools/check-cert-expired

# Expand relative PYTHONPATH passed as passed by the test environment.
if [ "x$PYTHONPATH" = "x.:./test/py" ]
then export PYTHONPATH=$PWD:$PWD/test/py
fi

err() {
  echo "$@"
  echo 'Aborting'
  exit 1
}

upto() {
  echo "$(date '+%F %T'):" "$@" '...'
}

gencert() {
  local path=$1 validity=$2
  VALIDITY=$validity $PYTHON \
    ${TOP_SRCDIR:-.}/test/py/import-export_unittest-helper \
    $path gencert
}

check_logfiles() {
  local n=$1 p=$2 path
  if [[ "$p" = master ]]; then
    path=$tmpls/log/ganeti/master-cleaner
  else
    path=$tmpls/log/ganeti/cleaner
  fi

  test -d $path || \
    err "Log file directory '$path' not created"

  [[ "$(find $path -mindepth 1 | wc -l)" -le "$n" ]] || \
    err "Found more than $n logfiles"
}

count_jobs() {
  local n=$1
  local count=$(find $queuedir -mindepth 1 -type f | wc -l)
  [[ "$count" -eq "$n" ]] || err "Found $count jobs instead of $n"
}

count_watcher() {
  local suffix="$1" n=$2
  local count=$(find $watcherdir -maxdepth 1 -type f \
                  -name "watcher.*-*-*-*.$suffix" | wc -l)
  [[ "$count" -eq "$n" ]] || \
    err "Found $count watcher files with suffix '$suffix' instead of $n"
}

count_and_check_certs() {
  local n=$1
  local count=$(find $cryptodir -mindepth 1 -type f -name cert | wc -l)
  [[ "$count" -eq "$n" ]] || err "Found $count certificates instead of $n"

  find $cryptodir -mindepth 1 -type d | \
  while read dir; do
    [[ ( -e $dir/key && -e $dir/cert ) ||
       ( ! -e $dir/cert && ! -e $dir/key ) ]] || \
      err 'Inconsistent cert/key directory found'
  done
}

run_cleaner() {
  CHECK_CERT_EXPIRED=$CCE LOCALSTATEDIR=$tmpls $GNTC $1
}

create_archived_jobs() {
  local i jobdir touchargs
  local jobarchive=$queuedir/archive
  local old_ts=$(date -d '25 days ago' +%Y%m%d%H%M)

  # Remove jobs from previous run
  find $jobarchive -mindepth 1 -type f | xargs -r rm

  i=0
  for job_id in {1..50} 469581574 19857 1420164 494433 2448521
  do
    jobdir=$jobarchive/$(( job_id / 10 ))
    test -d $jobdir || mkdir $jobdir

    if (( i % 3 == 0 || i % 7 == 0 )); then
      touchargs="-t $old_ts"
    else
      touchargs=
    fi
    touch $touchargs $jobdir/job-$job_id

    let ++i
  done
}

create_watcher_state() {
  local uuids=(
    6792a0d5-f8b6-4531-8d8c-3680c86b8a53
    ab74da37-f5f7-44c4-83ad-074159772593
    fced2e48-ffff-43ae-919e-2b77d37ecafa
    6e89ac57-2eb1-4a16-85a1-94daa815d643
    8714e8f5-59c4-47db-b2cb-196ec37978e5
    91763d73-e1f3-47c7-a735-57025d4e2a7d
    e27d3ff8-9546-4e86-86a4-04151223e140
    aa3f63dd-be17-4ac8-bd01-d71790e124cb
    05b6d7e2-003b-40d9-a6d6-ab61bf123a15
    54c93e4c-61fe-40de-b47e-2a8e6c805d02
    )

  i=0
  for uuid in ${uuids[@]}; do
    touch -d "$(( 5 * i )) days ago" \
      $watcherdir/watcher.$uuid.{data,instance-status}

    let ++i
  done
}

create_certdirs() {
  local cert=$1; shift
  local certdir
  for name in "$@"; do
    certdir=$cryptodir/$name
    mkdir $certdir
    if [[ -n "$cert" ]]; then
      cp $cert $certdir/cert
      cp $cert $certdir/key
    fi
  done
}

tmpdir=$(mktemp -d)
trap "rm -rf $tmpdir" EXIT

# Temporary localstatedir
tmpls=$tmpdir/var
queuedir=$tmpls/lib/ganeti/queue
cryptodir=$tmpls/run/ganeti/crypto
watcherdir=$tmpls/lib/ganeti

mkdir -p $tmpls/{lib,log,run}/ganeti $queuedir/archive $cryptodir

maxlog=50

upto 'Checking log directory creation'
test -d $tmpls/log/ganeti || err 'log/ganeti does not exist'
test -d $tmpls/log/ganeti/cleaner && \
  err 'log/ganeti/cleaner should not exist yet'
run_cleaner node
check_logfiles 1 node

test -d $tmpls/log/ganeti/master-cleaner && \
  err 'log/ganeti/master-cleaner should not exist yet'
run_cleaner master
check_logfiles 1 master

upto 'Checking number of retained log files (master)'
for (( i=0; i < (maxlog + 10); ++i )); do
  run_cleaner master
  check_logfiles 1 node
  check_logfiles $(( (i + 2) > $maxlog?$maxlog:(i + 2) )) master
done

upto 'Checking number of retained log files (node)'
for (( i=0; i < (maxlog + 10); ++i )); do
  run_cleaner node
  check_logfiles $(( (i + 2) > $maxlog?$maxlog:(i + 2) )) node
  check_logfiles $maxlog master
done

upto 'Removal of archived jobs (non-master)'
create_archived_jobs
count_jobs 55
test -f $tmpls/lib/ganeti/ssconf_master_node && \
  err 'ssconf_master_node should not exist'
run_cleaner node
count_jobs 55
run_cleaner master
count_jobs 55

upto 'Removal of archived jobs (master node)'
create_archived_jobs
count_jobs 55
echo $HOSTNAME > $tmpls/lib/ganeti/ssconf_master_node
run_cleaner node
count_jobs 55
run_cleaner master
count_jobs 31

upto 'Certificate expiration'
gencert $tmpdir/validcert 30 & vcpid=${!}
gencert $tmpdir/expcert -30 & ecpid=${!}
wait $vcpid $ecpid
create_certdirs $tmpdir/validcert foo{a,b,c}123 trvRMH4Wvt OfDlh6Pc2n
create_certdirs $tmpdir/expcert bar{x,y,z}999 fx0ljoImWr em3RBC0U8c
create_certdirs '' empty{1,2,3} gd2HCvRc iFG55Z0a PP28v5kg
count_and_check_certs 10
run_cleaner master
count_and_check_certs 10
run_cleaner node
count_and_check_certs 5

check_logfiles $maxlog node
check_logfiles $maxlog master
count_jobs 31

upto 'Watcher status files'
create_watcher_state
count_watcher data 10
count_watcher instance-status 10
run_cleaner master
count_watcher data 10
count_watcher instance-status 10
run_cleaner node
count_watcher data 5
count_watcher instance-status 5

exit 0
