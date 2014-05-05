#!/bin/bash
#

# Copyright (C) 2014 Google Inc.
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
