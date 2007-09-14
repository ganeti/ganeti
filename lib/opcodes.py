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


"""OpCodes module

This module implements the data structures which define the cluster
operations - the so-called opcodes.


This module implements the logic for doing operations in the cluster. There
are two kinds of classes defined:
  - opcodes, which are small classes only holding data for the task at hand
  - logical units, which know how to deal with their specific opcode only

"""

# this are practically structures, so disable the message about too
# few public methods:
# pylint: disable-msg=R0903

class OpCode(object):
  """Abstract OpCode"""
  OP_ID = "OP_ABSTRACT"
  __slots__ = []

  def __init__(self, **kwargs):
    for key in kwargs:
      if key not in self.__slots__:
        raise TypeError("OpCode %s doesn't support the parameter '%s'" %
                        (self.__class__.__name__, key))
      setattr(self, key, kwargs[key])


class OpInitCluster(OpCode):
  """Initialise the cluster."""
  OP_ID = "OP_CLUSTER_INIT"
  __slots__ = ["cluster_name", "secondary_ip", "hypervisor_type",
               "vg_name", "mac_prefix", "def_bridge", "master_netdev"]


class OpDestroyCluster(OpCode):
  """Destroy the cluster."""
  OP_ID = "OP_CLUSTER_DESTROY"
  __slots__ = []


class OpQueryClusterInfo(OpCode):
  """Query cluster information."""
  OP_ID = "OP_CLUSTER_QUERY"
  __slots__ = []


class OpClusterCopyFile(OpCode):
  """Copy a file to multiple nodes."""
  OP_ID = "OP_CLUSTER_COPYFILE"
  __slots__ = ["nodes", "filename"]


class OpRunClusterCommand(OpCode):
  """Run a command on multiple nodes."""
  OP_ID = "OP_CLUSTER_RUNCOMMAND"
  __slots__ = ["nodes", "command"]


class OpVerifyCluster(OpCode):
  """Verify the cluster state."""
  OP_ID = "OP_CLUSTER_VERIFY"
  __slots__ = []


class OpMasterFailover(OpCode):
  """Do a master failover."""
  OP_ID = "OP_CLUSTER_MASTERFAILOVER"
  __slots__ = []


class OpDumpClusterConfig(OpCode):
  """Dump the cluster configuration."""
  OP_ID = "OP_CLUSTER_DUMPCONFIG"
  __slots__ = []


class OpRemoveNode(OpCode):
  """Remove a node."""
  OP_ID = "OP_NODE_REMOVE"
  __slots__ = ["node_name"]


class OpAddNode(OpCode):
  """Add a node."""
  OP_ID = "OP_NODE_ADD"
  __slots__ = ["node_name", "primary_ip", "secondary_ip"]


class OpQueryNodes(OpCode):
  """Compute the list of nodes."""
  OP_ID = "OP_NODE_QUERY"
  __slots__ = ["output_fields", "nodes"]


class OpQueryNodeVolumes(OpCode):
  """Get list of volumes on node."""
  OP_ID = "OP_NODE_QUERYVOLS"
  __slots__ = ["nodes", "output_fields"]


# instance opcodes

class OpCreateInstance(OpCode):
  """Create an instance."""
  OP_ID = "OP_INSTANCE_CREATE"
  __slots__ = ["instance_name", "mem_size", "disk_size", "os_type", "pnode",
               "disk_template", "snode", "swap_size", "mode",
               "vcpus", "ip", "bridge", "src_node", "src_path", "start",
               "wait_for_sync"]


class OpReinstallInstance(OpCode):
  """Reinstall an instance's OS."""
  OP_ID = "OP_INSTANCE_REINSTALL"
  __slots__ = ["instance_name", "os_type"]


class OpRemoveInstance(OpCode):
  """Remove an instance."""
  OP_ID = "OP_INSTANCE_REMOVE"
  __slots__ = ["instance_name"]


class OpStartupInstance(OpCode):
  """Startup an instance."""
  OP_ID = "OP_INSTANCE_STARTUP"
  __slots__ = ["instance_name", "force", "extra_args"]


class OpShutdownInstance(OpCode):
  """Shutdown an instance."""
  OP_ID = "OP_INSTANCE_SHUTDOWN"
  __slots__ = ["instance_name"]


class OpAddMDDRBDComponent(OpCode):
  """Add a MD-DRBD component."""
  OP_ID = "OP_INSTANCE_ADD_MDDRBD"
  __slots__ = ["instance_name", "remote_node", "disk_name"]


class OpRemoveMDDRBDComponent(OpCode):
  """Remove a MD-DRBD component."""
  OP_ID = "OP_INSTANCE_REMOVE_MDDRBD"
  __slots__ = ["instance_name", "disk_name", "disk_id"]


class OpReplaceDisks(OpCode):
  """Replace the disks of an instance."""
  OP_ID = "OP_INSTANCE_REPLACE_DISKS"
  __slots__ = ["instance_name", "remote_node"]


class OpFailoverInstance(OpCode):
  """Failover an instance."""
  OP_ID = "OP_INSTANCE_FAILOVER"
  __slots__ = ["instance_name", "ignore_consistency"]


class OpConnectConsole(OpCode):
  """Connect to an instance's console."""
  OP_ID = "OP_INSTANCE_CONSOLE"
  __slots__ = ["instance_name"]


class OpActivateInstanceDisks(OpCode):
  """Activate an instance's disks."""
  OP_ID = "OP_INSTANCE_ACTIVATE_DISKS"
  __slots__ = ["instance_name"]


class OpDeactivateInstanceDisks(OpCode):
  """Deactivate an instance's disks."""
  OP_ID = "OP_INSTANCE_DEACTIVATE_DISKS"
  __slots__ = ["instance_name"]


class OpQueryInstances(OpCode):
  """Compute the list of instances."""
  OP_ID = "OP_INSTANCE_QUERY"
  __slots__ = ["output_fields"]


class OpQueryInstanceData(OpCode):
  """Compute the run-time status of instances."""
  OP_ID = "OP_INSTANCE_QUERY_DATA"
  __slots__ = ["instances"]


class OpSetInstanceParms(OpCode):
  """Change the parameters of an instance."""
  OP_ID = "OP_INSTANCE_SET_PARMS"
  __slots__ = ["instance_name", "mem", "vcpus", "ip", "bridge"]


# OS opcodes
class OpDiagnoseOS(OpCode):
  """Compute the list of guest operating systems."""
  OP_ID = "OP_OS_DIAGNOSE"
  __slots__ = []

# Exports opcodes
class OpQueryExports(OpCode):
  """Compute the list of exported images."""
  OP_ID = "OP_BACKUP_QUERY"
  __slots__ = ["nodes"]

class OpExportInstance(OpCode):
  """Export an instance."""
  OP_ID = "OP_BACKUP_EXPORT"
  __slots__ = ["instance_name", "target_node", "shutdown"]


# Tags opcodes
class OpGetTags(OpCode):
  """Returns the tags of the given object."""
  OP_ID = "OP_TAGS_GET"
  __slots__ = ["kind", "name"]


class OpSetTag(OpCode):
  """Sets the value of a tag on a given object."""
  OP_ID = "OP_TAGS_SET"
  __slots__ = ["kind", "name", "tag"]


class OpDelTag(OpCode):
  """Remove a tag from a given object."""
  OP_ID = "OP_TAGS_DEL"
  __slots__ = ["kind", "name", "tag"]
