#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Module holding different constants."""

# various versions
CONFIG_VERSION = 2
PROTOCOL_VERSION = 2
RELEASE_VERSION = "1.2a1"
OS_API_VERSION = 4
EXPORT_VERSION = 0


# file paths
DATA_DIR = "/var/lib/ganeti"
CLUSTER_CONF_FILE = DATA_DIR + "/config.data"
CLUSTER_NAME_FILE = DATA_DIR + "/cluster-name"
SSL_CERT_FILE = DATA_DIR + "/server.pem"
HYPERCONF_FILE = DATA_DIR + "/hypervisor"
WATCHER_STATEFILE = DATA_DIR + "/restart_state"

ETC_DIR = "/etc/ganeti"

MASTER_CRON_FILE = ETC_DIR + "/master-cron"
MASTER_CRON_LINK = "/etc/cron.d/ganeti-master-cron"
NODE_INITD_SCRIPT = "/etc/init.d/ganeti"
NODE_INITD_NAME = "ganeti"
DEFAULT_NODED_PORT = 1811
FIRST_DRBD_PORT = 11000
LAST_DRBD_PORT = 14999
MASTER_INITD_SCRIPT = "/etc/init.d/ganeti-master"
MASTER_INITD_NAME = "ganeti-master"

LOG_DIR = "/var/log/ganeti"
LOG_OS_DIR = LOG_DIR + "/os"
LOG_NODESERVER = LOG_DIR + "/node-daemon.log"

OS_DIR = "/srv/ganeti/os"
EXPORT_DIR = "/srv/ganeti/export"

EXPORT_CONF_FILE = "config.ini"

# hooks-related constants
HOOKS_BASE_DIR = "/etc/ganeti/hooks"
HOOKS_PHASE_PRE = "pre"
HOOKS_PHASE_POST = "post"
HOOKS_VERSION = 1

# hooks subject type (what object type does the LU deal with)
HTYPE_CLUSTER = "CLUSTER"
HTYPE_NODE = "NODE"
HTYPE_INSTANCE = "INSTANCE"

HKR_SKIP = 0
HKR_FAIL = 1
HKR_SUCCESS = 2

# disk template types
DT_DISKLESS = "diskless"
DT_PLAIN = "plain"
DT_LOCAL_RAID1 = "local_raid1"
DT_REMOTE_RAID1 = "remote_raid1"

# instance creation modem
INSTANCE_CREATE = "create"
INSTANCE_IMPORT = "import"

DISK_TEMPLATES = frozenset([DT_DISKLESS, DT_PLAIN,
                            DT_LOCAL_RAID1, DT_REMOTE_RAID1])

# file groups
CLUSTER_CONF_FILES = ["/etc/hosts",
                      "/etc/ssh/ssh_known_hosts",
                      "/etc/ssh/ssh_host_dsa_key",
                      "/etc/ssh/ssh_host_dsa_key.pub",
                      "/etc/ssh/ssh_host_rsa_key",
                      "/etc/ssh/ssh_host_rsa_key.pub",
                      "/root/.ssh/authorized_keys",
                      "/root/.ssh/id_dsa",
                      "/root/.ssh/id_dsa.pub",
                      CLUSTER_CONF_FILE,
                      SSL_CERT_FILE,
                      MASTER_CRON_FILE,
                      ]

MASTER_CONFIGFILES = [MASTER_CRON_LINK,
                      "/etc/rc2.d/S21%s" % MASTER_INITD_NAME]

NODE_CONFIGFILES = [NODE_INITD_SCRIPT,
                    "/etc/rc2.d/S20%s" % NODE_INITD_NAME,
                    "/etc/rc0.d/K80%s" % NODE_INITD_NAME]

# import/export config options
INISECT_EXP = "export"
INISECT_INS = "instance"
