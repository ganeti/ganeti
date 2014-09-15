#!/bin/bash
#

# Copyright (C) 2014 Google Inc.
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

for dname in $($daemon_util list-start-daemons; $daemon_util list-stop-daemons); do
  service="doc/examples/systemd/${dname}.service"
  test -f "$service" || err "No systemd unit found for ${dname}"

  usergroup=$($daemon_util -daemon-usergroup ${dname#ganeti-})
  user=${usergroup%:*}
  group=${usergroup#*:}

  service_user=$(grep ^User $service | cut -d '=' -f 2 | tr -d ' ')
  service_group=$(grep ^Group $service | cut -d '=' -f 2 | tr -d ' ')

  test "${service_user:-root}" == "$user" ||
     err "Systemd service for ${dname} has user ${service_user}" \
         "instead of ${user}"

  test "${service_group:-root}" == "$group" ||
     err "Systemd service for ${dname} has group ${service_group}" \
         "instead of ${group}"
done
