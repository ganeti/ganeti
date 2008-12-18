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
PROTOCOL_VERSION = 15
RELEASE_VERSION = _autoconf.PACKAGE_VERSION
OS_API_VERSION = 5
EXPORT_VERSION = 0
RAPI_VERSION = 1


# file paths
DATA_DIR = _autoconf.LOCALSTATEDIR + "/lib/ganeti"
RUN_DIR = _autoconf.LOCALSTATEDIR + "/run"
RUN_GANETI_DIR = RUN_DIR + "/ganeti"
BDEV_CACHE_DIR = RUN_GANETI_DIR # TODO(2.0): move deeper
DISK_LINKS_DIR = RUN_GANETI_DIR + "/instance-disks"
# keep RUN_GANETI_DIR first here, to make sure all get created when the node
# daemon is started (this takes care of RUN_DIR being tmpfs)
SUB_RUN_DIRS = [ RUN_GANETI_DIR, BDEV_CACHE_DIR, DISK_LINKS_DIR ]
LOCK_DIR = _autoconf.LOCALSTATEDIR + "/lock"
CLUSTER_CONF_FILE = DATA_DIR + "/config.data"
SSL_CERT_FILE = DATA_DIR + "/server.pem"
WATCHER_STATEFILE = DATA_DIR + "/watcher.data"
SSH_KNOWN_HOSTS_FILE = DATA_DIR + "/known_hosts"
ETC_HOSTS = "/etc/hosts"

NODE_INITD_SCRIPT = _autoconf.SYSCONFDIR + "/init.d/ganeti"
DEFAULT_NODED_PORT = 1811
FIRST_DRBD_PORT = 11000
LAST_DRBD_PORT = 14999
MASTER_SCRIPT = "ganeti-master"

LOG_DIR = _autoconf.LOCALSTATEDIR + "/log/ganeti"
LOG_OS_DIR = LOG_DIR + "/os"
LOG_NODESERVER = LOG_DIR + "/node-daemon.log"
LOG_RAPISERVER = LOG_DIR + "/rapi-daemon.log"
LOG_RAPIACCESS = LOG_DIR + "/rapi-access.log"
LOG_WATCHER = LOG_DIR + "/watcher.log"

OS_SEARCH_PATH = _autoconf.OS_SEARCH_PATH
EXPORT_DIR = _autoconf.EXPORT_DIR

EXPORT_CONF_FILE = "config.ini"

XEN_KERNEL = _autoconf.XEN_KERNEL
XEN_INITRD = _autoconf.XEN_INITRD

VALUE_DEFAULT = "default"
VALUE_AUTO = "auto"
VALUE_GENERATE = "generate"
VALUE_NONE = "none"

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

# instance creation modes
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
EXIT_FAILURE = 1
EXIT_NOTMASTER = 11
EXIT_NODESETUP_ERROR = 12
EXIT_CONFIRMATION = 13 # need user confirmation

# tags
TAG_CLUSTER = "cluster"
TAG_NODE = "node"
TAG_INSTANCE = "instance"
MAX_TAG_LEN = 64
MAX_TAGS_PER_OBJ = 48

# others
DEFAULT_BRIDGE = "xen-br0"
SYNC_SPEED = 60 * 1024
LOCALHOST_IP_ADDRESS = "127.0.0.1"
TCP_PING_TIMEOUT = 10
GANETI_RUNAS = "root"
BIND_ADDRESS_GLOBAL = "0.0.0.0"

# migration rpc steps
(DRBD_RECONF_RPC_INIT,
 DRBD_RECONF_RPC_DISCONNECT,
 DRBD_RECONF_RPC_RECONNECT,
 DRBD_RECONF_RPC_SECONDARY,
 DRBD_RECONF_RPC_WFSYNC,
 ) = range(5)

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

# Hypervisor constants
HT_XEN_PVM30 = "xen-3.0"
HT_FAKE = "fake"
HT_XEN_HVM31 = "xen-hvm-3.1"
HYPER_TYPES = frozenset([HT_XEN_PVM30, HT_FAKE, HT_XEN_HVM31])
HTS_REQ_PORT = frozenset([HT_XEN_HVM31])

HT_HVM_VNC_BASE_PORT = 5900
HT_HVM_DEFAULT_BOOT_ORDER = 'dc'
HT_HVM_DEFAULT_ACPI_MODE = '1'
HT_HVM_DEFAULT_PAE_MODE = '1'
VNC_PASSWORD_FILE = _autoconf.SYSCONFDIR + "/ganeti/vnc-cluster-password"
VNC_DEFAULT_BIND_ADDRESS = '0.0.0.0'

# HVM NIC types
HT_HVM_NIC_RTL8139 = "rtl8139"
HT_HVM_NIC_NE2K_PCI = "ne2k_pci"
HT_HVM_NIC_NE2K_ISA = "ne2k_isa"
HT_HVM_DEV_PARAVIRTUAL = "paravirtual"
HT_HVM_DEV_IOEMU = "ioemu"
HT_HVM_VALID_NIC_TYPES = frozenset([HT_HVM_NIC_RTL8139, HT_HVM_NIC_NE2K_PCI,
                                    HT_HVM_NIC_NE2K_ISA,
                                    HT_HVM_DEV_PARAVIRTUAL])
HT_HVM_VALID_DISK_TYPES = frozenset([HT_HVM_DEV_PARAVIRTUAL, HT_HVM_DEV_IOEMU])

# Cluster Verify steps
VERIFY_NPLUSONE_MEM = 'nplusone_mem'
VERIFY_OPTIONAL_CHECKS = frozenset([VERIFY_NPLUSONE_MEM])

# Allocator framework constants
IALLOCATOR_DIR_IN = "in"
IALLOCATOR_DIR_OUT = "out"
IALLOCATOR_MODE_ALLOC = "allocate"
IALLOCATOR_MODE_RELOC = "relocate"
IALLOCATOR_SEARCH_PATH = _autoconf.IALLOCATOR_SEARCH_PATH
IARUN_NOTFOUND = 1
IARUN_FAILURE = 2
IARUN_SUCCESS = 3

# Remote API constants
RAPI_ENABLE = _autoconf.RAPI_ENABLE
RAPI_PORT = 5080
