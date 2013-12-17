#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Module containing constants and functions for filesystem paths.

"""

from ganeti import _constants
from ganeti import compat
from ganeti import vcluster


# Build-time constants
DEFAULT_FILE_STORAGE_DIR = "/srv/ganeti/file-storage"
DEFAULT_FILE_STORAGE_DIR = vcluster.AddNodePrefix(DEFAULT_FILE_STORAGE_DIR)
DEFAULT_SHARED_FILE_STORAGE_DIR = "/srv/ganeti/shared-file-storage"
DEFAULT_SHARED_FILE_STORAGE_DIR = \
    vcluster.AddNodePrefix(DEFAULT_SHARED_FILE_STORAGE_DIR)
DEFAULT_GLUSTER_STORAGE_DIR = "/var/run/ganeti/gluster"
DEFAULT_GLUSTER_STORAGE_DIR = \
    vcluster.AddNodePrefix(DEFAULT_GLUSTER_STORAGE_DIR)
EXPORT_DIR = vcluster.AddNodePrefix(_constants.EXPORT_DIR)
OS_SEARCH_PATH = _constants.OS_SEARCH_PATH
ES_SEARCH_PATH = _constants.ES_SEARCH_PATH
SSH_CONFIG_DIR = _constants.SSH_CONFIG_DIR
XEN_CONFIG_DIR = vcluster.AddNodePrefix(_constants.XEN_CONFIG_DIR)
SYSCONFDIR = vcluster.AddNodePrefix(_constants.SYSCONFDIR)
TOOLSDIR = _constants.TOOLSDIR
PKGLIBDIR = _constants.PKGLIBDIR
SHAREDIR = _constants.SHAREDIR
LOCALSTATEDIR = vcluster.AddNodePrefix(_constants.LOCALSTATEDIR)

# Paths which don't change for a virtual cluster
DAEMON_UTIL = _constants.PKGLIBDIR + "/daemon-util"
IMPORT_EXPORT_DAEMON = _constants.PKGLIBDIR + "/import-export"
KVM_CONSOLE_WRAPPER = _constants.PKGLIBDIR + "/tools/kvm-console-wrapper"
KVM_IFUP = _constants.PKGLIBDIR + "/kvm-ifup"
PREPARE_NODE_JOIN = _constants.PKGLIBDIR + "/prepare-node-join"
NODE_DAEMON_SETUP = _constants.PKGLIBDIR + "/node-daemon-setup"
XEN_CONSOLE_WRAPPER = _constants.PKGLIBDIR + "/tools/xen-console-wrapper"
CFGUPGRADE = _constants.PKGLIBDIR + "/tools/cfgupgrade"
ENSURE_DIRS = _constants.PKGLIBDIR + "/ensure-dirs"
ETC_HOSTS = vcluster.ETC_HOSTS

# Top-level paths
DATA_DIR = LOCALSTATEDIR + "/lib/ganeti"
LOCK_DIR = LOCALSTATEDIR + "/lock"
LOG_DIR = LOCALSTATEDIR + "/log/ganeti"
RUN_DIR = LOCALSTATEDIR + "/run/ganeti"

#: Script to configure master IP address
DEFAULT_MASTER_SETUP_SCRIPT = TOOLSDIR + "/master-ip-setup"

SSH_HOST_DSA_PRIV = _constants.SSH_HOST_DSA_PRIV
SSH_HOST_DSA_PUB = _constants.SSH_HOST_DSA_PUB
SSH_HOST_RSA_PRIV = _constants.SSH_HOST_RSA_PRIV
SSH_HOST_RSA_PUB = _constants.SSH_HOST_RSA_PUB

BDEV_CACHE_DIR = RUN_DIR + "/bdev-cache"
DISK_LINKS_DIR = RUN_DIR + "/instance-disks"
SOCKET_DIR = RUN_DIR + "/socket"
CRYPTO_KEYS_DIR = RUN_DIR + "/crypto"
IMPORT_EXPORT_DIR = RUN_DIR + "/import-export"
INSTANCE_STATUS_FILE = RUN_DIR + "/instance-status"
INSTANCE_REASON_DIR = RUN_DIR + "/instance-reason"
#: User-id pool lock directory (used user IDs have a corresponding lock file in
#: this directory)
UIDPOOL_LOCKDIR = RUN_DIR + "/uid-pool"

SSCONF_LOCK_FILE = LOCK_DIR + "/ganeti-ssconf.lock"

CLUSTER_CONF_FILE = DATA_DIR + "/config.data"
RAPI_CERT_FILE = DATA_DIR + "/rapi.pem"
CONFD_HMAC_KEY = DATA_DIR + "/hmac.key"
SPICE_CERT_FILE = DATA_DIR + "/spice.pem"
SPICE_CACERT_FILE = DATA_DIR + "/spice-ca.pem"
CLUSTER_DOMAIN_SECRET_FILE = DATA_DIR + "/cluster-domain-secret"
SSH_KNOWN_HOSTS_FILE = DATA_DIR + "/known_hosts"
RAPI_USERS_FILE = DATA_DIR + "/rapi/users"
QUEUE_DIR = DATA_DIR + "/queue"
INTENT_TO_UPGRADE = DATA_DIR + "/intent-to-upgrade"
CONF_DIR = SYSCONFDIR + "/ganeti"
USER_SCRIPTS_DIR = CONF_DIR + "/scripts"
VNC_PASSWORD_FILE = CONF_DIR + "/vnc-cluster-password"
HOOKS_BASE_DIR = CONF_DIR + "/hooks"
FILE_STORAGE_PATHS_FILE = CONF_DIR + "/file-storage-paths"
RESTRICTED_COMMANDS_DIR = CONF_DIR + "/restricted-commands"

#: Node daemon certificate path
NODED_CERT_FILE = DATA_DIR + "/server.pem"

#: Node daemon certificate file permissions
NODED_CERT_MODE = 0440

#: Locked in exclusive mode while noded verifies a remote command
RESTRICTED_COMMANDS_LOCK_FILE = LOCK_DIR + "/ganeti-restricted-commands.lock"

#: Lock file for watcher, locked in shared mode by watcher; lock in exclusive
# mode to block watcher (see L{cli._RunWhileClusterStoppedHelper.Call}
WATCHER_LOCK_FILE = LOCK_DIR + "/ganeti-watcher.lock"

#: Status file for per-group watcher, locked in exclusive mode by watcher
WATCHER_GROUP_STATE_FILE = DATA_DIR + "/watcher.%s.data"

#: File for per-group instance status, merged into L{INSTANCE_STATUS_FILE} by
#: per-group processes
WATCHER_GROUP_INSTANCE_STATUS_FILE = DATA_DIR + "/watcher.%s.instance-status"

#: File containing Unix timestamp until which watcher should be paused
WATCHER_PAUSEFILE = DATA_DIR + "/watcher.pause"

#: User-provided master IP setup script
EXTERNAL_MASTER_SETUP_SCRIPT = USER_SCRIPTS_DIR + "/master-ip-setup"

#: LUXI socket used for job execution
MASTER_SOCKET = SOCKET_DIR + "/ganeti-master"
#: LUXI socket used for queries only
QUERY_SOCKET = SOCKET_DIR + "/ganeti-query"

LOG_OS_DIR = LOG_DIR + "/os"
LOG_ES_DIR = LOG_DIR + "/extstorage"
#: Directory for storing Xen config files after failed instance starts
LOG_XEN_DIR = LOG_DIR + "/xen"

# Job queue paths
JOB_QUEUE_LOCK_FILE = QUEUE_DIR + "/lock"
JOB_QUEUE_VERSION_FILE = QUEUE_DIR + "/version"
JOB_QUEUE_SERIAL_FILE = QUEUE_DIR + "/serial"
JOB_QUEUE_ARCHIVE_DIR = QUEUE_DIR + "/archive"
JOB_QUEUE_DRAIN_FILE = QUEUE_DIR + "/drain"

ALL_CERT_FILES = compat.UniqueFrozenset([
  NODED_CERT_FILE,
  RAPI_CERT_FILE,
  SPICE_CERT_FILE,
  SPICE_CACERT_FILE,
  ])


def GetLogFilename(daemon_name):
  """Returns the full path for a daemon's log file.

  """
  return "%s/%s.log" % (LOG_DIR, daemon_name)


LOG_WATCHER = GetLogFilename("watcher")
LOG_COMMANDS = GetLogFilename("commands")
LOG_BURNIN = GetLogFilename("burnin")
