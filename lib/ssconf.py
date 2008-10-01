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

import socket
import sys

from ganeti import errors
from ganeti import constants
from ganeti import utils
from ganeti import serializer


class SimpleConfigReader:
  """Simple class to read configuration file.

  """
  def __init__(self, file_name=constants.CLUSTER_CONF_FILE):
    """Initializes this class.

    @type file_name: string
    @param file_name: Configuration file path

    """
    self._file_name = file_name
    self._config_data = serializer.Load(utils.ReadFile(file_name))
    # TODO: Error handling

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


class SimpleConfigWriter(SimpleConfigReader):
  """Simple class to write configuration file.

  """
  def SetMasterNode(self, node):
    """Change master node.

    """
    self._config_data["cluster"]["master_node"] = node

  def Save(self):
    """Writes configuration file.

    Warning: Doesn't take care of locking or synchronizing with other
    processes.

    """
    utils.WriteFile(self._file_name,
                    data=serializer.Dump(self._config_data),
                    mode=0600)


def GetMasterAndMyself(ss=None):
  """Get the master node and my own hostname.

  This can be either used for a 'soft' check (compared to CheckMaster,
  which exits) or just for computing both at the same time.

  The function does not handle any errors, these should be handled in
  the caller (errors.ConfigurationError, errors.ResolverError).

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
