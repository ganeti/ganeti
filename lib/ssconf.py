#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Global Configuration data for Ganeti.

This module provides the interface to a special case of cluster
configuration data, which is mostly static and available to all nodes.

"""

import sys
import re
import os

from ganeti import errors
from ganeti import constants
from ganeti import utils
from ganeti import serializer


SSCONF_LOCK_TIMEOUT = 10

RE_VALID_SSCONF_NAME = re.compile(r'^[-_a-z0-9]+$')


class SimpleConfigReader(object):
  """Simple class to read configuration file.

  """
  def __init__(self, file_name=constants.CLUSTER_CONF_FILE):
    """Initializes this class.

    @type file_name: string
    @param file_name: Configuration file path

    """
    self._file_name = file_name
    self._last_inode = None
    self._last_mtime = None
    self._last_size = None
    # we need a forced reload at class init time, to initialize _last_*
    self._Load(force=True)

  def _Load(self, force=False):
    """Loads (or reloads) the config file.

    @type force: boolean
    @param force: whether to force the reload without checking the mtime
    @rtype: boolean
    @return: boolean values that says whether we reloaded the configuration or not
             (because we decided it was already up-to-date)

    """
    try:
      cfg_stat = os.stat(self._file_name)
    except EnvironmentError, err:
      raise errors.ConfigurationError("Cannot stat config file %s: %s" %
                                      (self._file_name, err))
    inode = cfg_stat.st_ino
    mtime = cfg_stat.st_mtime
    size = cfg_stat.st_size

    reload = False
    if force or inode != self._last_inode or \
       mtime > self._last_mtime or \
       size != self._last_size:
      self._last_inode = inode
      self._last_mtime = mtime
      self._last_size = size
      reload = True

    if not reload:
      return False

    try:
      self._config_data = serializer.Load(utils.ReadFile(self._file_name))
    except EnvironmentError, err:
      raise errors.ConfigurationError("Cannot read config file %s: %s" %
                                      (self._file_name, err))
    except ValueError, err:
      raise errors.ConfigurationError("Cannot load config file %s: %s" %
                                      (self._file_name, err))

    self._ip_to_instance = {}
    for iname in self._config_data['instances']:
      instance = self._config_data['instances'][iname]
      for nic in instance['nics']:
        if 'ip' in nic and nic['ip']:
          self._ip_to_instance[nic['ip']] = iname

    return True

  # Clients can request a reload of the config file, so we export our internal
  # _Load function as Reload.
  Reload = _Load

  def GetClusterName(self):
    return self._config_data["cluster"]["cluster_name"]

  def GetHostKey(self):
    return self._config_data["cluster"]["rsahostkeypub"]

  def GetMasterNode(self):
    return self._config_data["cluster"]["master_node"]

  def GetMasterIP(self):
    return self._config_data["cluster"]["master_ip"]

  def GetMasterNetdev(self):
    return self._config_data["cluster"]["master_netdev"]

  def GetFileStorageDir(self):
    return self._config_data["cluster"]["file_storage_dir"]

  def GetHypervisorType(self):
    return self._config_data["cluster"]["hypervisor"]

  def GetNodeList(self):
    return self._config_data["nodes"].keys()

  def GetConfigSerialNo(self):
    return self._config_data["serial_no"]

  def GetClusterSerialNo(self):
    return self._config_data["cluster"]["serial_no"]

  def GetNodeStatusFlags(self, node):
    """Get a node's status flags

    @type node: string
    @param node: node name
    @rtype: (bool, bool, bool)
    @return: (master_candidate, drained, offline) (or None if no such node)

    """
    if node not in self._config_data["nodes"]:
      return None

    master_candidate = self._config_data["nodes"][node]["master_candidate"]
    drained = self._config_data["nodes"][node]["drained"]
    offline = self._config_data["nodes"][node]["offline"]
    return master_candidate, drained, offline

  def GetInstanceByIp(self, ip):
    if ip not in self._ip_to_instance:
      return None
    return self._ip_to_instance[ip]

  def GetNodePrimaryIp(self, node):
    """Get a node's primary ip

    @type node: string
    @param node: node name
    @rtype: string, or None
    @return: node's primary ip, or None if no such node

    """
    if node not in self._config_data["nodes"]:
      return None
    return self._config_data["nodes"][node]["primary_ip"]

  def GetInstancePrimaryNode(self, instance):
    """Get an instance's primary node

    @type instance: string
    @param instance: instance name
    @rtype: string, or None
    @return: primary node, or None if no such instance

    """
    if instance not in self._config_data["instances"]:
      return None
    return self._config_data["instances"][instance]["primary_node"]


class SimpleStore(object):
  """Interface to static cluster data.

  This is different that the config.ConfigWriter and
  SimpleConfigReader classes in that it holds data that will always be
  present, even on nodes which don't have all the cluster data.

  Other particularities of the datastore:
    - keys are restricted to predefined values

  """
  _SS_FILEPREFIX = "ssconf_"
  _VALID_KEYS = (
    constants.SS_CLUSTER_NAME,
    constants.SS_CLUSTER_TAGS,
    constants.SS_FILE_STORAGE_DIR,
    constants.SS_MASTER_CANDIDATES,
    constants.SS_MASTER_CANDIDATES_IPS,
    constants.SS_MASTER_IP,
    constants.SS_MASTER_NETDEV,
    constants.SS_MASTER_NODE,
    constants.SS_NODE_LIST,
    constants.SS_NODE_PRIMARY_IPS,
    constants.SS_NODE_SECONDARY_IPS,
    constants.SS_OFFLINE_NODES,
    constants.SS_ONLINE_NODES,
    constants.SS_INSTANCE_LIST,
    constants.SS_RELEASE_VERSION,
    )
  _MAX_SIZE = 131072

  def __init__(self, cfg_location=None):
    if cfg_location is None:
      self._cfg_dir = constants.DATA_DIR
    else:
      self._cfg_dir = cfg_location

  def KeyToFilename(self, key):
    """Convert a given key into filename.

    """
    if key not in self._VALID_KEYS:
      raise errors.ProgrammerError("Invalid key requested from SSConf: '%s'"
                                   % str(key))

    filename = self._cfg_dir + '/' + self._SS_FILEPREFIX + key
    return filename

  def _ReadFile(self, key):
    """Generic routine to read keys.

    This will read the file which holds the value requested. Errors
    will be changed into ConfigurationErrors.

    """
    filename = self.KeyToFilename(key)
    try:
      data = utils.ReadFile(filename, size=self._MAX_SIZE)
    except EnvironmentError, err:
      raise errors.ConfigurationError("Can't read from the ssconf file:"
                                      " '%s'" % str(err))
    data = data.rstrip('\n')
    return data

  def WriteFiles(self, values):
    """Writes ssconf files used by external scripts.

    @type values: dict
    @param values: Dictionary of (name, value)

    """
    ssconf_lock = utils.FileLock(constants.SSCONF_LOCK_FILE)

    # Get lock while writing files
    ssconf_lock.Exclusive(blocking=True, timeout=SSCONF_LOCK_TIMEOUT)
    try:
      for name, value in values.iteritems():
        if value and not value.endswith("\n"):
          value += "\n"
        utils.WriteFile(self.KeyToFilename(name), data=value, mode=0444)
    finally:
      ssconf_lock.Unlock()

  def GetFileList(self):
    """Return the list of all config files.

    This is used for computing node replication data.

    """
    return [self.KeyToFilename(key) for key in self._VALID_KEYS]

  def GetClusterName(self):
    """Get the cluster name.

    """
    return self._ReadFile(constants.SS_CLUSTER_NAME)

  def GetFileStorageDir(self):
    """Get the file storage dir.

    """
    return self._ReadFile(constants.SS_FILE_STORAGE_DIR)

  def GetMasterCandidates(self):
    """Return the list of master candidates.

    """
    data = self._ReadFile(constants.SS_MASTER_CANDIDATES)
    nl = data.splitlines(False)
    return nl

  def GetMasterCandidatesIPList(self):
    """Return the list of master candidates' primary IP.

    """
    data = self._ReadFile(constants.SS_MASTER_CANDIDATES_IPS)
    nl = data.splitlines(False)
    return nl

  def GetMasterIP(self):
    """Get the IP of the master node for this cluster.

    """
    return self._ReadFile(constants.SS_MASTER_IP)

  def GetMasterNetdev(self):
    """Get the netdev to which we'll add the master ip.

    """
    return self._ReadFile(constants.SS_MASTER_NETDEV)

  def GetMasterNode(self):
    """Get the hostname of the master node for this cluster.

    """
    return self._ReadFile(constants.SS_MASTER_NODE)

  def GetNodeList(self):
    """Return the list of cluster nodes.

    """
    data = self._ReadFile(constants.SS_NODE_LIST)
    nl = data.splitlines(False)
    return nl

  def GetNodePrimaryIPList(self):
    """Return the list of cluster nodes' primary IP.

    """
    data = self._ReadFile(constants.SS_NODE_PRIMARY_IPS)
    nl = data.splitlines(False)
    return nl

  def GetNodeSecondaryIPList(self):
    """Return the list of cluster nodes' secondary IP.

    """
    data = self._ReadFile(constants.SS_NODE_SECONDARY_IPS)
    nl = data.splitlines(False)
    return nl

  def GetClusterTags(self):
    """Return the cluster tags.

    """
    data = self._ReadFile(constants.SS_CLUSTER_TAGS)
    nl = data.splitlines(False)
    return nl


def GetMasterAndMyself(ss=None):
  """Get the master node and my own hostname.

  This can be either used for a 'soft' check (compared to CheckMaster,
  which exits) or just for computing both at the same time.

  The function does not handle any errors, these should be handled in
  the caller (errors.ConfigurationError, errors.ResolverError).

  @param ss: either a sstore.SimpleConfigReader or a
      sstore.SimpleStore instance
  @rtype: tuple
  @return: a tuple (master node name, my own name)

  """
  if ss is None:
    ss = SimpleStore()
  return ss.GetMasterNode(), utils.HostInfo().name


def CheckMaster(debug, ss=None):
  """Checks the node setup.

  If this is the master, the function will return. Otherwise it will
  exit with an exit code based on the node status.

  """
  try:
    master_name, myself = GetMasterAndMyself(ss)
  except errors.ConfigurationError, err:
    print "Cluster configuration incomplete: '%s'" % str(err)
    sys.exit(constants.EXIT_NODESETUP_ERROR)
  except errors.ResolverError, err:
    sys.stderr.write("Cannot resolve my own name (%s)\n" % err.args[0])
    sys.exit(constants.EXIT_NODESETUP_ERROR)

  if myself != master_name:
    if debug:
      sys.stderr.write("Not master, exiting.\n")
    sys.exit(constants.EXIT_NOTMASTER)


def CheckMasterCandidate(debug, ss=None):
  """Checks the node setup.

  If this is a master candidate, the function will return. Otherwise it will
  exit with an exit code based on the node status.

  """
  try:
    if ss is None:
      ss = SimpleStore()
    myself = utils.HostInfo().name
    candidates = ss.GetMasterCandidates()
  except errors.ConfigurationError, err:
    print "Cluster configuration incomplete: '%s'" % str(err)
    sys.exit(constants.EXIT_NODESETUP_ERROR)
  except errors.ResolverError, err:
    sys.stderr.write("Cannot resolve my own name (%s)\n" % err.args[0])
    sys.exit(constants.EXIT_NODESETUP_ERROR)

  if myself not in candidates:
    if debug:
      sys.stderr.write("Not master candidate, exiting.\n")
    sys.exit(constants.EXIT_NOTCANDIDATE)

