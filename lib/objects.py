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


"""Transportable objects for Ganeti.

This module provides small, mostly data-only objects which are safe to
pass to and from external parties.

"""


import cPickle
from cStringIO import StringIO
import ConfigParser

from ganeti import errors


__all__ = ["ConfigObject", "ConfigData", "NIC", "Disk", "Instance",
           "OS", "Node", "Cluster"]


class ConfigObject(object):
  """A generic config object.

  It has the following properties:

    - provides somewhat safe recursive unpickling and pickling for its classes
    - unset attributes which are defined in slots are always returned
      as None instead of raising an error

  Classes derived from this must always declare __slots__ (we use many
  config objects and the memory reduction is useful.

  """
  __slots__ = []

  def __init__(self, **kwargs):
    for i in kwargs:
      setattr(self, i, kwargs[i])

  def __getattr__(self, name):
    if name not in self.__slots__:
      raise AttributeError, ("Invalid object attribute %s.%s" %
                             (type(self).__name__, name))
    return None

  def __getstate__(self):
    state = {}
    for name in self.__slots__:
      if hasattr(self, name):
        state[name] = getattr(self, name)
    return state

  def __setstate__(self, state):
    for name in state:
      if name in self.__slots__:
        setattr(self, name, state[name])

  @staticmethod
  def FindGlobal(module, name):
    """Function filtering the allowed classes to be un-pickled.

    Currently, we only allow the classes from this module which are
    derived from ConfigObject.

    """
    # Also support the old module name (ganeti.config)
    cls = None
    if module == "ganeti.config" or module == "ganeti.objects":
      if name == "ConfigData":
        cls = ConfigData
      elif name == "NIC":
        cls = NIC
      elif name == "Disk" or name == "BlockDev":
        cls = Disk
      elif name == "Instance":
        cls = Instance
      elif name == "OS":
        cls = OS
      elif name == "Node":
        cls = Node
      elif name == "Cluster":
        cls = Cluster
    if cls is None:
      raise cPickle.UnpicklingError, ("Class %s.%s not allowed due to"
                                      " security concerns" % (module, name))
    return cls

  def Dump(self, fobj):
    """Dump this instance to a file object.

    Note that we use the HIGHEST_PROTOCOL, as it brings benefits for
    the new classes.

    """
    dumper = cPickle.Pickler(fobj, cPickle.HIGHEST_PROTOCOL)
    dumper.dump(self)

  @staticmethod
  def Load(fobj):
    """Unpickle data from the given stream.

    This uses the `FindGlobal` function to filter the allowed classes.

    """
    loader = cPickle.Unpickler(fobj)
    loader.find_global = ConfigObject.FindGlobal
    return loader.load()

  def Dumps(self):
    """Dump this instance and return the string representation."""
    buf = StringIO()
    self.Dump(buf)
    return buf.getvalue()

  @staticmethod
  def Loads(data):
    """Load data from a string."""
    return ConfigObject.Load(StringIO(data))


class ConfigData(ConfigObject):
  """Top-level config object."""
  __slots__ = ["cluster", "nodes", "instances"]


class NIC(ConfigObject):
  """Config object representing a network card."""
  __slots__ = ["mac", "ip", "bridge"]


class Disk(ConfigObject):
  """Config object representing a block device."""
  __slots__ = ["dev_type", "logical_id", "physical_id",
               "children", "iv_name", "size"]

  def CreateOnSecondary(self):
    """Test if this device needs to be created on a secondary node."""
    return self.dev_type in ("drbd", "lvm")

  def AssembleOnSecondary(self):
    """Test if this device needs to be assembled on a secondary node."""
    return self.dev_type in ("drbd", "lvm")

  def OpenOnSecondary(self):
    """Test if this device needs to be opened on a secondary node."""
    return self.dev_type in ("lvm",)

  def GetNodes(self, node):
    """This function returns the nodes this device lives on.

    Given the node on which the parent of the device lives on (or, in
    case of a top-level device, the primary node of the devices'
    instance), this function will return a list of nodes on which this
    devices needs to (or can) be assembled.

    """
    if self.dev_type == "lvm" or self.dev_type == "md_raid1":
      result = [node]
    elif self.dev_type == "drbd":
      result = [self.logical_id[0], self.logical_id[1]]
      if node not in result:
        raise errors.ConfigurationError, ("DRBD device passed unknown node")
    else:
      raise errors.ProgrammerError, "Unhandled device type %s" % self.dev_type
    return result

  def ComputeNodeTree(self, parent_node):
    """Compute the node/disk tree for this disk and its children.

    This method, given the node on which the parent disk lives, will
    return the list of all (node, disk) pairs which describe the disk
    tree in the most compact way. For example, a md/drbd/lvm stack
    will be returned as (primary_node, md) and (secondary_node, drbd)
    which represents all the top-level devices on the nodes. This
    means that on the primary node we need to activate the the md (and
    recursively all its children) and on the secondary node we need to
    activate the drbd device (and its children, the two lvm volumes).

    """
    my_nodes = self.GetNodes(parent_node)
    result = [(node, self) for node in my_nodes]
    if not self.children:
      # leaf device
      return result
    for node in my_nodes:
      for child in self.children:
        child_result = child.ComputeNodeTree(node)
        if len(child_result) == 1:
          # child (and all its descendants) is simple, doesn't split
          # over multiple hosts, so we don't need to describe it, our
          # own entry for this node describes it completely
          continue
        else:
          # check if child nodes differ from my nodes; note that
          # subdisk can differ from the child itself, and be instead
          # one of its descendants
          for subnode, subdisk in child_result:
            if subnode not in my_nodes:
              result.append((subnode, subdisk))
            # otherwise child is under our own node, so we ignore this
            # entry (but probably the other results in the list will
            # be different)
    return result


class Instance(ConfigObject):
  """Config object representing an instance."""
  __slots__ = [
    "name",
    "primary_node",
    "os",
    "status",
    "memory",
    "vcpus",
    "nics",
    "disks",
    "disk_template",
    ]

  def _ComputeSecondaryNodes(self):
    """Compute the list of secondary nodes.

    Since the data is already there (in the drbd disks), keeping it as
    a separate normal attribute is redundant and if not properly
    synchronised can cause problems. Thus it's better to compute it
    dynamically.

    """
    def _Helper(primary, sec_nodes, device):
      """Recursively computes secondary nodes given a top device."""
      if device.dev_type == 'drbd':
        nodea, nodeb, dummy = device.logical_id
        if nodea == primary:
          candidate = nodeb
        else:
          candidate = nodea
        if candidate not in sec_nodes:
          sec_nodes.append(candidate)
      if device.children:
        for child in device.children:
          _Helper(primary, sec_nodes, child)

    secondary_nodes = []
    for device in self.disks:
      _Helper(self.primary_node, secondary_nodes, device)
    return tuple(secondary_nodes)

  secondary_nodes = property(_ComputeSecondaryNodes, None, None,
                             "List of secondary nodes")

  def MapLVsByNode(self, lvmap=None, devs=None, node=None):
    """Provide a mapping of nodes to LVs this instance owns.

    This function figures out what logical volumes should belong on which
    nodes, recursing through a device tree.

    Args:
      lvmap: (optional) a dictionary to receive the 'node' : ['lv', ...] data.

    Returns:
      None if lvmap arg is given.
      Otherwise, { 'nodename' : ['volume1', 'volume2', ...], ... }

    """

    if node == None:
      node = self.primary_node

    if lvmap is None:
      lvmap = { node : [] }
      ret = lvmap
    else:
      if not node in lvmap:
        lvmap[node] = []
      ret = None

    if not devs:
      devs = self.disks

    for dev in devs:
      if dev.dev_type == "lvm":
        lvmap[node].append(dev.logical_id[1])

      elif dev.dev_type == "drbd":
        if dev.logical_id[0] not in lvmap:
          lvmap[dev.logical_id[0]] = []

        if dev.logical_id[1] not in lvmap:
          lvmap[dev.logical_id[1]] = []

        if dev.children:
          self.MapLVsByNode(lvmap, dev.children, dev.logical_id[0])
          self.MapLVsByNode(lvmap, dev.children, dev.logical_id[1])

      elif dev.children:
        self.MapLVsByNode(lvmap, dev.children, node)

    return ret


class OS(ConfigObject):
  """Config object representing an operating system."""
  __slots__ = [
    "name",
    "path",
    "api_version",
    "create_script",
    "export_script",
    "import_script"
    ]


class Node(ConfigObject):
  """Config object representing a node."""
  __slots__ = ["name", "primary_ip", "secondary_ip"]


class Cluster(ConfigObject):
  """Config object representing the cluster."""
  __slots__ = [
    "config_version",
    "serial_no",
    "master_node",
    "name",
    "rsahostkeypub",
    "highest_used_port",
    "mac_prefix",
    "volume_group_name",
    "default_bridge",
    ]

class SerializableConfigParser(ConfigParser.SafeConfigParser):
  """Simple wrapper over ConfigParse that allows serialization.

  This class is basically ConfigParser.SafeConfigParser with two
  additional methods that allow it to serialize/unserialize to/from a
  buffer.

  """
  def Dumps(self):
    """Dump this instance and return the string representation."""
    buf = StringIO()
    self.write(buf)
    return buf.getvalue()

  @staticmethod
  def Loads(data):
    """Load data from a string."""
    buf = StringIO(data)
    cfp = SerializableConfigParser()
    cfp.readfp(buf)
    return cfp
