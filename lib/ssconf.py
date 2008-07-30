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


"""Global Configuration data for Ganeti.

This module provides the interface to a special case of cluster
configuration data, which is mostly static and available to all nodes.

"""

import socket
import sys

from ganeti import errors
from ganeti import constants
from ganeti import utils


class SimpleStore:
  """Interface to static cluster data.

  This is different that the config.ConfigWriter class in that it
  holds data that is (mostly) constant after the cluster
  initialization. Its purpose is to allow limited customization of
  things which would otherwise normally live in constants.py. Note
  that this data cannot live in ConfigWriter as that is available only
  on the master node, and our data must be readable by both the master
  and the nodes.

  Other particularities of the datastore:
    - keys are restricted to predefined values
    - values are small (<4k)
    - some keys are handled specially (read from the system)

  """
  _SS_FILEPREFIX = "ssconf_"
  SS_HYPERVISOR = "hypervisor"
  SS_NODED_PASS = "node_pass"
  SS_MASTER_NODE = "master_node"
  SS_MASTER_IP = "master_ip"
  SS_MASTER_NETDEV = "master_netdev"
  SS_CLUSTER_NAME = "cluster_name"
  SS_FILE_STORAGE_DIR = "file_storage_dir"
  SS_CONFIG_VERSION = "config_version"
  _VALID_KEYS = (SS_HYPERVISOR, SS_NODED_PASS, SS_MASTER_NODE, SS_MASTER_IP,
                 SS_MASTER_NETDEV, SS_CLUSTER_NAME, SS_FILE_STORAGE_DIR,
                 SS_CONFIG_VERSION)
  _MAX_SIZE = 4096

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
      fh = file(filename, 'r')
      try:
        data = fh.readline(self._MAX_SIZE)
        data = data.rstrip('\n')
      finally:
        fh.close()
    except EnvironmentError, err:
      raise errors.ConfigurationError("Can't read from the ssconf file:"
                                      " '%s'" % str(err))
    return data

  def GetNodeDaemonPort(self):
    """Get the node daemon port for this cluster.

    Note that this routine does not read a ganeti-specific file, but
    instead uses socket.getservbyname to allow pre-customization of
    this parameter outside of ganeti.

    """
    try:
      port = socket.getservbyname("ganeti-noded", "tcp")
    except socket.error:
      port = constants.DEFAULT_NODED_PORT

    return port

  def GetHypervisorType(self):
    """Get the hypervisor type for this cluster.

    """
    return self._ReadFile(self.SS_HYPERVISOR)

  def GetNodeDaemonPassword(self):
    """Get the node password for this cluster.

    """
    return self._ReadFile(self.SS_NODED_PASS)

  def GetMasterNode(self):
    """Get the hostname of the master node for this cluster.

    """
    return self._ReadFile(self.SS_MASTER_NODE)

  def GetMasterIP(self):
    """Get the IP of the master node for this cluster.

    """
    return self._ReadFile(self.SS_MASTER_IP)

  def GetMasterNetdev(self):
    """Get the netdev to which we'll add the master ip.

    """
    return self._ReadFile(self.SS_MASTER_NETDEV)

  def GetClusterName(self):
    """Get the cluster name.

    """
    return self._ReadFile(self.SS_CLUSTER_NAME)

  def GetFileStorageDir(self):
    """Get the file storage dir.

    """
    return self._ReadFile(self.SS_FILE_STORAGE_DIR)

  def GetConfigVersion(self):
    """Get the configuration version.

    """
    value = self._ReadFile(self.SS_CONFIG_VERSION)
    try:
      return int(value)
    except (ValueError, TypeError), err:
      raise errors.ConfigurationError("Failed to convert config version %s to"
                                      " int: '%s'" % (value, str(err)))

  def GetFileList(self):
    """Return the list of all config files.

    This is used for computing node replication data.

    """
    return [self.KeyToFilename(key) for key in self._VALID_KEYS]


class WritableSimpleStore(SimpleStore):
  """This is a read/write interface to SimpleStore, which is used rarely, when
  values need to be changed. Since WriteFile handles updates in an atomic way
  it should be fine to use two WritableSimpleStore at the same time, but in
  the future we might want to put additional protection for this class.

  A WritableSimpleStore cannot be used to update system-dependent values.

  """

  def SetKey(self, key, value):
    """Set the value of a key.

    This should be used only when adding a node to a cluster, or in other
    infrequent operations such as cluster-rename or master-failover.

    """
    file_name = self.KeyToFilename(key)
    utils.WriteFile(file_name, data="%s\n" % str(value),
                    uid=0, gid=0, mode=0400)


def CheckMaster(debug):
  """Checks the node setup.

  If this is the master, the function will return. Otherwise it will
  exit with an exit code based on the node status.

  """
  try:
    ss = SimpleStore()
    master_name = ss.GetMasterNode()
  except errors.ConfigurationError, err:
    print "Cluster configuration incomplete: '%s'" % str(err)
    sys.exit(constants.EXIT_NODESETUP_ERROR)

  try:
    myself = utils.HostInfo()
  except errors.ResolverError, err:
    sys.stderr.write("Cannot resolve my own name (%s)\n" % err.args[0])
    sys.exit(constants.EXIT_NODESETUP_ERROR)

  if myself.name != master_name:
    if debug:
      sys.stderr.write("Not master, exiting.\n")
    sys.exit(constants.EXIT_NOTMASTER)
