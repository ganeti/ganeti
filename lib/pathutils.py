#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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
BACKUP_DIR = vcluster.AddNodePrefix(_constants.BACKUP_DIR)
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
SSH_UPDATE = _constants.PKGLIBDIR + "/ssh-update"
NODE_DAEMON_SETUP = _constants.PKGLIBDIR + "/node-daemon-setup"
SSL_UPDATE = _constants.PKGLIBDIR + "/ssl-update"
XEN_CONSOLE_WRAPPER = _constants.PKGLIBDIR + "/tools/xen-console-wrapper"
CFGUPGRADE = _constants.PKGLIBDIR + "/tools/cfgupgrade"
POST_UPGRADE = _constants.PKGLIBDIR + "/tools/post-upgrade"
ENSURE_DIRS = _constants.PKGLIBDIR + "/ensure-dirs"
# Script to configure the metadata virtual network interface with Xen
XEN_VIF_METAD_SETUP = _constants.PKGLIBDIR + "/vif-ganeti-metad"
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
SSH_PUB_KEYS = DATA_DIR + "/ganeti_pub_keys"

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
LIVELOCK_DIR = RUN_DIR + "/livelocks"
LUXID_MESSAGE_DIR = RUN_DIR + "/luxidmessages"

SSCONF_LOCK_FILE = LOCK_DIR + "/ganeti-ssconf.lock"

CLUSTER_CONF_FILE = DATA_DIR + "/config.data"
RAPI_CERT_FILE = DATA_DIR + "/rapi.pem"
CONFD_HMAC_KEY = DATA_DIR + "/hmac.key"
SPICE_CERT_FILE = DATA_DIR + "/spice.pem"
SPICE_CACERT_FILE = DATA_DIR + "/spice-ca.pem"
CLUSTER_DOMAIN_SECRET_FILE = DATA_DIR + "/cluster-domain-secret"
SSH_KNOWN_HOSTS_FILE = DATA_DIR + "/known_hosts"
RAPI_DATA_DIR = DATA_DIR + "/rapi"
RAPI_USERS_FILE = RAPI_DATA_DIR + "/users"
QUEUE_DIR = DATA_DIR + "/queue"
INTENT_TO_UPGRADE = DATA_DIR + "/intent-to-upgrade"
CONF_DIR = SYSCONFDIR + "/ganeti"
XEN_IFUP_OS = CONF_DIR + "/xen-ifup-os"
USER_SCRIPTS_DIR = CONF_DIR + "/scripts"
VNC_PASSWORD_FILE = CONF_DIR + "/vnc-cluster-password"
HOOKS_BASE_DIR = CONF_DIR + "/hooks"
FILE_STORAGE_PATHS_FILE = CONF_DIR + "/file-storage-paths"
RESTRICTED_COMMANDS_DIR = CONF_DIR + "/restricted-commands"
REPAIR_COMMANDS_DIR = CONF_DIR + "/node-repair-commands"

#: Node daemon certificate path
NODED_CERT_FILE = DATA_DIR + "/server.pem"
NODED_CLIENT_CERT_FILE = DATA_DIR + "/client.pem"

#: Node daemon certificate file permissions
NODED_CERT_MODE = 0440

#: Locked in exclusive mode while noded verifies a remote command
RESTRICTED_COMMANDS_LOCK_FILE = LOCK_DIR + "/ganeti-restricted-commands.lock"

#: Locked in exclusive mode while noded verifies a remote command
REPAIR_COMMANDS_LOCK_FILE = LOCK_DIR + "/ganeti-repair-commands.lock"

#: Lock file for watcher, locked in shared mode by watcher; lock in exclusive
# mode to block watcher (see L{cli._RunWhileDaemonsStoppedHelper.Call}
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
#: WConfD socket
WCONFD_SOCKET = SOCKET_DIR + "/ganeti-wconfd"
#: Metad socket
METAD_SOCKET = SOCKET_DIR + "/ganeti-metad"

LOG_OS_DIR = LOG_DIR + "/os"
LOG_ES_DIR = LOG_DIR + "/extstorage"
#: Directory for storing Xen config files after failed instance starts
LOG_XEN_DIR = LOG_DIR + "/xen"
# Directory to store the output of kvm instances
LOG_KVM_DIR = LOG_DIR + "/kvm"

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
LOG_TOOLS = GetLogFilename("tools")
