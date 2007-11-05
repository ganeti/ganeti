#
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

from ganeti import _autoconf

# various versions
CONFIG_VERSION = 3
PROTOCOL_VERSION = 6
RELEASE_VERSION = _autoconf.PACKAGE_VERSION
OS_API_VERSION = 5
EXPORT_VERSION = 0


# file paths
DATA_DIR = _autoconf.LOCALSTATEDIR + "/lib/ganeti"
BDEV_CACHE_DIR = _autoconf.LOCALSTATEDIR + "/run/ganeti"
CLUSTER_CONF_FILE = DATA_DIR + "/config.data"
SSL_CERT_FILE = DATA_DIR + "/server.pem"
WATCHER_STATEFILE = DATA_DIR + "/watcher.data"
SSH_KNOWN_HOSTS_FILE = DATA_DIR + "/known_hosts"

NODE_INITD_SCRIPT = _autoconf.SYSCONFDIR + "/init.d/ganeti"
DEFAULT_NODED_PORT = 1811
FIRST_DRBD_PORT = 11000
LAST_DRBD_PORT = 14999
MASTER_SCRIPT = "ganeti-master"

LOG_DIR = _autoconf.LOCALSTATEDIR + "/log/ganeti"
LOG_OS_DIR = LOG_DIR + "/os"
LOG_NODESERVER = LOG_DIR + "/node-daemon.log"
LOG_WATCHER = LOG_DIR + "/watcher.log"

OS_SEARCH_PATH = _autoconf.OS_SEARCH_PATH
EXPORT_DIR = _autoconf.EXPORT_DIR

EXPORT_CONF_FILE = "config.ini"

XEN_KERNEL = _autoconf.XEN_KERNEL
XEN_INITRD = _autoconf.XEN_INITRD

# hooks-related constants
HOOKS_BASE_DIR = _autoconf.SYSCONFDIR + "/ganeti/hooks"
HOOKS_PHASE_PRE = "pre"
HOOKS_PHASE_POST = "post"
HOOKS_NAME_CFGUPDATE = "config-update"
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
DT_DRBD8 = "drbd"

# the set of network-mirrored disk templates
DTS_NET_MIRROR = frozenset([DT_REMOTE_RAID1, DT_DRBD8])

# logical disk types
LD_LV = "lvm"
LD_MD_R1 = "md_raid1"
LD_DRBD7 = "drbd"
LD_DRBD8 = "drbd8"

# the set of drbd-like disk types
LDS_DRBD = frozenset([LD_DRBD7, LD_DRBD8])

# disk replacement mode
REPLACE_DISK_PRI = "replace_primary"
REPLACE_DISK_SEC = "replace_secondary"
REPLACE_DISK_ALL = "replace_all"

# instance creation modem
INSTANCE_CREATE = "create"
INSTANCE_IMPORT = "import"

DISK_TEMPLATES = frozenset([DT_DISKLESS, DT_PLAIN,
                            DT_LOCAL_RAID1, DT_REMOTE_RAID1,
                            DT_DRBD8])

# import/export config options
INISECT_EXP = "export"
INISECT_INS = "instance"

# common exit codes
EXIT_SUCCESS = 0
EXIT_NOTMASTER = 11
EXIT_NODESETUP_ERROR = 12
EXIT_CONFIRMATION = 13 # need user confirmation

# tags
TAG_CLUSTER = "cluster"
TAG_NODE = "node"
TAG_INSTANCE = "instance"
MAX_TAG_LEN = 128
MAX_TAGS_PER_OBJ = 4096

# others
DEFAULT_BRIDGE = "xen-br0"
SYNC_SPEED = 30 * 1024
LOCALHOST_IP_ADDRESS = "127.0.0.1"
TCP_PING_TIMEOUT = 10
GANETI_RUNAS = "root"

# valid os status
OS_VALID_STATUS = "VALID"

# ssh constants
SSH_INITD_SCRIPT = _autoconf.SSH_INITD_SCRIPT
SSH_CONFIG_DIR = "/etc/ssh/"
SSH_HOST_DSA_PRIV = SSH_CONFIG_DIR + "ssh_host_dsa_key"
SSH_HOST_DSA_PUB = SSH_HOST_DSA_PRIV + ".pub"
SSH_HOST_RSA_PRIV = SSH_CONFIG_DIR + "ssh_host_rsa_key"
SSH_HOST_RSA_PUB = SSH_HOST_RSA_PRIV + ".pub"

# reboot types
INSTANCE_REBOOT_SOFT = "soft"
INSTANCE_REBOOT_HARD = "hard"
INSTANCE_REBOOT_FULL = "full"
