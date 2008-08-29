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
PROTOCOL_VERSION = 13
RELEASE_VERSION = _autoconf.PACKAGE_VERSION
OS_API_VERSION = 5
EXPORT_VERSION = 0
RAPI_VERSION = 2


# Format for CONFIG_VERSION:
#   01 03 0123 = 01030123
#   ^^ ^^ ^^^^
#   |  |  + Configuration version/revision
#   |  + Minor version
#   + Major version
#
# It stored as an integer. Make sure not to write an octal number.

# BuildVersion and SplitVersion must be in here because we can't import other
# modules. The cfgupgrade tool must be able to read and write version numbers
# and thus requires these functions. To avoid code duplication, they're kept in
# here.

def BuildVersion(major, minor, revision):
  """Calculates int version number from major, minor and revision numbers.

  Returns: int representing version number

  """
  assert isinstance(major, int)
  assert isinstance(minor, int)
  assert isinstance(revision, int)
  return (1000000 * major +
            10000 * minor +
                1 * revision)


def SplitVersion(version):
  """Splits version number stored in an int.

  Returns: tuple; (major, minor, revision)

  """
  assert isinstance(version, int)

  (major, remainder) = divmod(version, 1000000)
  (minor, revision) = divmod(remainder, 10000)

  return (major, minor, revision)


CONFIG_MAJOR = int(_autoconf.VERSION_MAJOR)
CONFIG_MINOR = int(_autoconf.VERSION_MINOR)
CONFIG_REVISION = 0
CONFIG_VERSION = BuildVersion(CONFIG_MAJOR, CONFIG_MINOR, CONFIG_REVISION)

# file paths
DATA_DIR = _autoconf.LOCALSTATEDIR + "/lib/ganeti"
RUN_DIR = _autoconf.LOCALSTATEDIR + "/run"
RUN_GANETI_DIR = RUN_DIR + "/ganeti"
BDEV_CACHE_DIR = RUN_GANETI_DIR + "/bdev-cache"
DISK_LINKS_DIR = RUN_GANETI_DIR + "/instance-disks"
# keep RUN_GANETI_DIR first here, to make sure all get created when the node
# daemon is started (this takes care of RUN_DIR being tmpfs)
SUB_RUN_DIRS = [ RUN_GANETI_DIR, BDEV_CACHE_DIR, DISK_LINKS_DIR ]
LOCK_DIR = _autoconf.LOCALSTATEDIR + "/lock"
CLUSTER_CONF_FILE = DATA_DIR + "/config.data"
SSL_CERT_FILE = DATA_DIR + "/server.pem"
WATCHER_STATEFILE = DATA_DIR + "/watcher.data"
SSH_KNOWN_HOSTS_FILE = DATA_DIR + "/known_hosts"
QUEUE_DIR = DATA_DIR + "/queue"
ETC_HOSTS = "/etc/hosts"
DEFAULT_FILE_STORAGE_DIR = _autoconf.FILE_STORAGE_DIR

# Quoting unix(7) on Linux:
#   Linux also supports an abstract namespace which is independent of the file
#   system. [...] If sun_path starts with a null byte ('\0'), then it refers to
#   the abstract namespace maintained by the Unix protocol module. The socket's
#   address in this namespace is given by the rest of the bytes in sun_path.
#
# By using this Linux-specific way we don't have to care about removing the
# socket file when quitting or starting (after an unclean shutdown).
#
# Sample output for "netstat -nlp":
#   unix 2 [ ACC ] STREAM LISTENING 247919 1234/python @ganeti-master
MASTER_SOCKET = "\0ganeti-master"

# PID files
MASTERD_PID = "ganeti-masterd"
NODED_PID = "ganeti-noded"
RAPI_PID = "ganeti-rapi"

NODE_INITD_SCRIPT = _autoconf.SYSCONFDIR + "/init.d/ganeti"
DEFAULT_NODED_PORT = 1811
FIRST_DRBD_PORT = 11000
LAST_DRBD_PORT = 14999
MASTER_SCRIPT = "ganeti-master"

LOG_DIR = _autoconf.LOCALSTATEDIR + "/log/ganeti/"
LOG_OS_DIR = LOG_DIR + "os"
LOG_NODESERVER = LOG_DIR + "node-daemon.log"
LOG_WATCHER = LOG_DIR + "watcher.log"
LOG_MASTERDAEMON = LOG_DIR + "master-daemon.log"
LOG_RAPISERVER = LOG_DIR + "rapi-daemon.log"
LOG_RAPIACCESS = LOG_DIR + "rapi-access.log"
LOG_COMMANDS = LOG_DIR + "commands.log"
LOG_BURNIN = LOG_DIR + "burnin.log"

OS_SEARCH_PATH = _autoconf.OS_SEARCH_PATH
EXPORT_DIR = _autoconf.EXPORT_DIR

EXPORT_CONF_FILE = "config.ini"

XEN_KERNEL = _autoconf.XEN_KERNEL
XEN_INITRD = _autoconf.XEN_INITRD

KVM_PATH = _autoconf.KVM_PATH

VALUE_DEFAULT = "default"
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
DT_DRBD8 = "drbd"
DT_FILE = "file"

# the set of network-mirrored disk templates
DTS_NET_MIRROR = frozenset([DT_DRBD8])

# the set of non-lvm-based disk templates
DTS_NOT_LVM = frozenset([DT_DISKLESS, DT_FILE])

# logical disk types
LD_LV = "lvm"
LD_DRBD8 = "drbd8"
LD_FILE = "file"

# file backend driver
FD_LOOP = "loop"
FD_BLKTAP = "blktap"

# the set of drbd-like disk types
LDS_DRBD = frozenset([LD_DRBD8])

# disk replacement mode
REPLACE_DISK_PRI = "replace_primary"
REPLACE_DISK_SEC = "replace_secondary"
REPLACE_DISK_ALL = "replace_all"

# instance creation modes
INSTANCE_CREATE = "create"
INSTANCE_IMPORT = "import"

DISK_TEMPLATES = frozenset([DT_DISKLESS, DT_PLAIN,
                            DT_DRBD8, DT_FILE])

FILE_DRIVER = frozenset([FD_LOOP, FD_BLKTAP])

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
MAX_TAG_LEN = 128
MAX_TAGS_PER_OBJ = 4096

# others
DEFAULT_BRIDGE = "xen-br0"
SYNC_SPEED = 30 * 1024
LOCALHOST_IP_ADDRESS = "127.0.0.1"
TCP_PING_TIMEOUT = 10
GANETI_RUNAS = "root"
DEFAULT_VG = "xenvg"
BIND_ADDRESS_GLOBAL = "0.0.0.0"
MIN_VG_SIZE = 20480

# valid os status
OS_VALID_STATUS = "VALID"

# ssh constants
SSH_INITD_SCRIPT = _autoconf.SSH_INITD_SCRIPT
SSH_CONFIG_DIR = "/etc/ssh/"
SSH_HOST_DSA_PRIV = SSH_CONFIG_DIR + "ssh_host_dsa_key"
SSH_HOST_DSA_PUB = SSH_HOST_DSA_PRIV + ".pub"
SSH_HOST_RSA_PRIV = SSH_CONFIG_DIR + "ssh_host_rsa_key"
SSH_HOST_RSA_PUB = SSH_HOST_RSA_PRIV + ".pub"
SSH = "ssh"
SCP = "scp"

# reboot types
INSTANCE_REBOOT_SOFT = "soft"
INSTANCE_REBOOT_HARD = "hard"
INSTANCE_REBOOT_FULL = "full"

# Hypervisor constants
HT_XEN_PVM30 = "xen-3.0"
HT_FAKE = "fake"
HT_XEN_HVM31 = "xen-hvm-3.1"
HT_KVM = "kvm"
HYPER_TYPES = frozenset([HT_XEN_PVM30, HT_FAKE, HT_XEN_HVM31, HT_KVM])
HTS_REQ_PORT = frozenset([HT_XEN_HVM31])

HT_HVM_VNC_BASE_PORT = 5900
HT_HVM_DEFAULT_BOOT_ORDER = 'dc'
VNC_PASSWORD_FILE = _autoconf.SYSCONFDIR + "/ganeti/vnc-cluster-password"
VNC_DEFAULT_BIND_ADDRESS = '0.0.0.0'

# HVM NIC types
HT_HVM_NIC_RTL8139 = "rtl8139"
HT_HVM_NIC_NE2K_PCI = "ne2k_pci"
HT_HVM_NIC_NE2K_ISA = "ne2k_isa"
HT_HVM_DEV_PARAVIRTUAL = "paravirtual"
HT_HVM_DEV_IOEMU = "ioemu"

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

# Job queue
JOB_QUEUE_VERSION = 1
JOB_QUEUE_LOCK_FILE = QUEUE_DIR + "/lock"
JOB_QUEUE_VERSION_FILE = QUEUE_DIR + "/version"
JOB_QUEUE_SERIAL_FILE = QUEUE_DIR + "/serial"
JOB_QUEUE_ARCHIVE_DIR = QUEUE_DIR + "/archive"

JOB_ID_TEMPLATE = r"\d+"

# unchanged job return
JOB_NOTCHANGED = "nochange"

# Job status
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_CANCELED = "canceled"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_ERROR = "error"

OP_STATUS_QUEUED = "queued"
OP_STATUS_RUNNING = "running"
OP_STATUS_CANCELED = "canceled"
OP_STATUS_SUCCESS = "success"
OP_STATUS_ERROR = "error"

# Execution log types
ELOG_MESSAGE = "message"
ELOG_PROGRESS = "progress"

# Temporary RAPI constants until we have cluster parameters
RAPI_ENABLE = True
RAPI_PORT = 5080
