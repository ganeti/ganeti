#
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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

# pylint: disable-msg=E0203,W0201

# E0203: Access to member %r before its definition, since we use
# objects.py which doesn't explicitely initialise its members

# W0201: Attribute '%s' defined outside __init__

import ConfigParser
import re
import copy
from cStringIO import StringIO

from ganeti import errors
from ganeti import constants

from socket import AF_INET


__all__ = ["ConfigObject", "ConfigData", "NIC", "Disk", "Instance",
           "OS", "Node", "NodeGroup", "Cluster", "FillDict"]

_TIMESTAMPS = ["ctime", "mtime"]
_UUID = ["uuid"]


def FillDict(defaults_dict, custom_dict, skip_keys=None):
  """Basic function to apply settings on top a default dict.

  @type defaults_dict: dict
  @param defaults_dict: dictionary holding the default values
  @type custom_dict: dict
  @param custom_dict: dictionary holding customized value
  @type skip_keys: list
  @param skip_keys: which keys not to fill
  @rtype: dict
  @return: dict with the 'full' values

  """
  ret_dict = copy.deepcopy(defaults_dict)
  ret_dict.update(custom_dict)
  if skip_keys:
    for k in skip_keys:
      try:
        del ret_dict[k]
      except KeyError:
        pass
  return ret_dict


def UpgradeGroupedParams(target, defaults):
  """Update all groups for the target parameter.

  @type target: dict of dicts
  @param target: {group: {parameter: value}}
  @type defaults: dict
  @param defaults: default parameter values

  """
  if target is None:
    target = {constants.PP_DEFAULT: defaults}
  else:
    for group in target:
      target[group] = FillDict(defaults, target[group])
  return target


class ConfigObject(object):
  """A generic config object.

  It has the following properties:

    - provides somewhat safe recursive unpickling and pickling for its classes
    - unset attributes which are defined in slots are always returned
      as None instead of raising an error

  Classes derived from this must always declare __slots__ (we use many
  config objects and the memory reduction is useful)

  """
  __slots__ = []

  def __init__(self, **kwargs):
    for k, v in kwargs.iteritems():
      setattr(self, k, v)

  def __getattr__(self, name):
    if name not in self._all_slots():
      raise AttributeError("Invalid object attribute %s.%s" %
                           (type(self).__name__, name))
    return None

  def __setstate__(self, state):
    slots = self._all_slots()
    for name in state:
      if name in slots:
        setattr(self, name, state[name])

  @classmethod
  def _all_slots(cls):
    """Compute the list of all declared slots for a class.

    """
    slots = []
    for parent in cls.__mro__:
      slots.extend(getattr(parent, "__slots__", []))
    return slots

  def ToDict(self):
    """Convert to a dict holding only standard python types.

    The generic routine just dumps all of this object's attributes in
    a dict. It does not work if the class has children who are
    ConfigObjects themselves (e.g. the nics list in an Instance), in
    which case the object should subclass the function in order to
    make sure all objects returned are only standard python types.

    """
    result = {}
    for name in self._all_slots():
      value = getattr(self, name, None)
      if value is not None:
        result[name] = value
    return result

  __getstate__ = ToDict

  @classmethod
  def FromDict(cls, val):
    """Create an object from a dictionary.

    This generic routine takes a dict, instantiates a new instance of
    the given class, and sets attributes based on the dict content.

    As for `ToDict`, this does not work if the class has children
    who are ConfigObjects themselves (e.g. the nics list in an
    Instance), in which case the object should subclass the function
    and alter the objects.

    """
    if not isinstance(val, dict):
      raise errors.ConfigurationError("Invalid object passed to FromDict:"
                                      " expected dict, got %s" % type(val))
    val_str = dict([(str(k), v) for k, v in val.iteritems()])
    obj = cls(**val_str) # pylint: disable-msg=W0142
    return obj

  @staticmethod
  def _ContainerToDicts(container):
    """Convert the elements of a container to standard python types.

    This method converts a container with elements derived from
    ConfigData to standard python types. If the container is a dict,
    we don't touch the keys, only the values.

    """
    if isinstance(container, dict):
      ret = dict([(k, v.ToDict()) for k, v in container.iteritems()])
    elif isinstance(container, (list, tuple, set, frozenset)):
      ret = [elem.ToDict() for elem in container]
    else:
      raise TypeError("Invalid type %s passed to _ContainerToDicts" %
                      type(container))
    return ret

  @staticmethod
  def _ContainerFromDicts(source, c_type, e_type):
    """Convert a container from standard python types.

    This method converts a container with standard python types to
    ConfigData objects. If the container is a dict, we don't touch the
    keys, only the values.

    """
    if not isinstance(c_type, type):
      raise TypeError("Container type %s passed to _ContainerFromDicts is"
                      " not a type" % type(c_type))
    if source is None:
      source = c_type()
    if c_type is dict:
      ret = dict([(k, e_type.FromDict(v)) for k, v in source.iteritems()])
    elif c_type in (list, tuple, set, frozenset):
      ret = c_type([e_type.FromDict(elem) for elem in source])
    else:
      raise TypeError("Invalid container type %s passed to"
                      " _ContainerFromDicts" % c_type)
    return ret

  def Copy(self):
    """Makes a deep copy of the current object and its children.

    """
    dict_form = self.ToDict()
    clone_obj = self.__class__.FromDict(dict_form)
    return clone_obj

  def __repr__(self):
    """Implement __repr__ for ConfigObjects."""
    return repr(self.ToDict())

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    This method will be called at configuration load time, and its
    implementation will be object dependent.

    """
    pass


class TaggableObject(ConfigObject):
  """An generic class supporting tags.

  """
  __slots__ = ["tags"]
  VALID_TAG_RE = re.compile("^[\w.+*/:@-]+$")

  @classmethod
  def ValidateTag(cls, tag):
    """Check if a tag is valid.

    If the tag is invalid, an errors.TagError will be raised. The
    function has no return value.

    """
    if not isinstance(tag, basestring):
      raise errors.TagError("Invalid tag type (not a string)")
    if len(tag) > constants.MAX_TAG_LEN:
      raise errors.TagError("Tag too long (>%d characters)" %
                            constants.MAX_TAG_LEN)
    if not tag:
      raise errors.TagError("Tags cannot be empty")
    if not cls.VALID_TAG_RE.match(tag):
      raise errors.TagError("Tag contains invalid characters")

  def GetTags(self):
    """Return the tags list.

    """
    tags = getattr(self, "tags", None)
    if tags is None:
      tags = self.tags = set()
    return tags

  def AddTag(self, tag):
    """Add a new tag.

    """
    self.ValidateTag(tag)
    tags = self.GetTags()
    if len(tags) >= constants.MAX_TAGS_PER_OBJ:
      raise errors.TagError("Too many tags")
    self.GetTags().add(tag)

  def RemoveTag(self, tag):
    """Remove a tag.

    """
    self.ValidateTag(tag)
    tags = self.GetTags()
    try:
      tags.remove(tag)
    except KeyError:
      raise errors.TagError("Tag not found")

  def ToDict(self):
    """Taggable-object-specific conversion to standard python types.

    This replaces the tags set with a list.

    """
    bo = super(TaggableObject, self).ToDict()

    tags = bo.get("tags", None)
    if isinstance(tags, set):
      bo["tags"] = list(tags)
    return bo

  @classmethod
  def FromDict(cls, val):
    """Custom function for instances.

    """
    obj = super(TaggableObject, cls).FromDict(val)
    if hasattr(obj, "tags") and isinstance(obj.tags, list):
      obj.tags = set(obj.tags)
    return obj


class ConfigData(ConfigObject):
  """Top-level config object."""
  __slots__ = (["version", "cluster", "nodes", "instances", "serial_no"] +
               _TIMESTAMPS)

  def ToDict(self):
    """Custom function for top-level config data.

    This just replaces the list of instances, nodes and the cluster
    with standard python types.

    """
    mydict = super(ConfigData, self).ToDict()
    mydict["cluster"] = mydict["cluster"].ToDict()
    for key in "nodes", "instances":
      mydict[key] = self._ContainerToDicts(mydict[key])

    return mydict

  @classmethod
  def FromDict(cls, val):
    """Custom function for top-level config data

    """
    obj = super(ConfigData, cls).FromDict(val)
    obj.cluster = Cluster.FromDict(obj.cluster)
    obj.nodes = cls._ContainerFromDicts(obj.nodes, dict, Node)
    obj.instances = cls._ContainerFromDicts(obj.instances, dict, Instance)
    return obj

  def HasAnyDiskOfType(self, dev_type):
    """Check if in there is at disk of the given type in the configuration.

    @type dev_type: L{constants.LDS_BLOCK}
    @param dev_type: the type to look for
    @rtype: boolean
    @return: boolean indicating if a disk of the given type was found or not

    """
    for instance in self.instances.values():
      for disk in instance.disks:
        if disk.IsBasedOnDiskType(dev_type):
          return True
    return False

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    self.cluster.UpgradeConfig()
    for node in self.nodes.values():
      node.UpgradeConfig()
    for instance in self.instances.values():
      instance.UpgradeConfig()
    if self.cluster.drbd_usermode_helper is None:
      # To decide if we set an helper let's check if at least one instance has
      # a DRBD disk. This does not cover all the possible scenarios but it
      # gives a good approximation.
      if self.HasAnyDiskOfType(constants.LD_DRBD8):
        self.cluster.drbd_usermode_helper = constants.DEFAULT_DRBD_HELPER


class NIC(ConfigObject):
  """Config object representing a network card."""
  __slots__ = ["mac", "ip", "bridge", "nicparams"]

  @classmethod
  def CheckParameterSyntax(cls, nicparams):
    """Check the given parameters for validity.

    @type nicparams:  dict
    @param nicparams: dictionary with parameter names/value
    @raise errors.ConfigurationError: when a parameter is not valid

    """
    if nicparams[constants.NIC_MODE] not in constants.NIC_VALID_MODES:
      err = "Invalid nic mode: %s" % nicparams[constants.NIC_MODE]
      raise errors.ConfigurationError(err)

    if (nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED and
        not nicparams[constants.NIC_LINK]):
      err = "Missing bridged nic link"
      raise errors.ConfigurationError(err)

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    if self.nicparams is None:
      self.nicparams = {}
      if self.bridge is not None:
        self.nicparams[constants.NIC_MODE] = constants.NIC_MODE_BRIDGED
        self.nicparams[constants.NIC_LINK] = self.bridge
    # bridge is no longer used it 2.1. The slot is left there to support
    # upgrading, but can be removed once upgrades to the current version
    # straight from 2.0 are deprecated.
    if self.bridge is not None:
      self.bridge = None


class Disk(ConfigObject):
  """Config object representing a block device."""
  __slots__ = ["dev_type", "logical_id", "physical_id",
               "children", "iv_name", "size", "mode"]

  def CreateOnSecondary(self):
    """Test if this device needs to be created on a secondary node."""
    return self.dev_type in (constants.LD_DRBD8, constants.LD_LV)

  def AssembleOnSecondary(self):
    """Test if this device needs to be assembled on a secondary node."""
    return self.dev_type in (constants.LD_DRBD8, constants.LD_LV)

  def OpenOnSecondary(self):
    """Test if this device needs to be opened on a secondary node."""
    return self.dev_type in (constants.LD_LV,)

  def StaticDevPath(self):
    """Return the device path if this device type has a static one.

    Some devices (LVM for example) live always at the same /dev/ path,
    irrespective of their status. For such devices, we return this
    path, for others we return None.

    @warning: The path returned is not a normalized pathname; callers
        should check that it is a valid path.

    """
    if self.dev_type == constants.LD_LV:
      return "/dev/%s/%s" % (self.logical_id[0], self.logical_id[1])
    return None

  def ChildrenNeeded(self):
    """Compute the needed number of children for activation.

    This method will return either -1 (all children) or a positive
    number denoting the minimum number of children needed for
    activation (only mirrored devices will usually return >=0).

    Currently, only DRBD8 supports diskless activation (therefore we
    return 0), for all other we keep the previous semantics and return
    -1.

    """
    if self.dev_type == constants.LD_DRBD8:
      return 0
    return -1

  def IsBasedOnDiskType(self, dev_type):
    """Check if the disk or its children are based on the given type.

    @type dev_type: L{constants.LDS_BLOCK}
    @param dev_type: the type to look for
    @rtype: boolean
    @return: boolean indicating if a device of the given type was found or not

    """
    if self.children:
      for child in self.children:
        if child.IsBasedOnDiskType(dev_type):
          return True
    return self.dev_type == dev_type

  def GetNodes(self, node):
    """This function returns the nodes this device lives on.

    Given the node on which the parent of the device lives on (or, in
    case of a top-level device, the primary node of the devices'
    instance), this function will return a list of nodes on which this
    devices needs to (or can) be assembled.

    """
    if self.dev_type in [constants.LD_LV, constants.LD_FILE]:
      result = [node]
    elif self.dev_type in constants.LDS_DRBD:
      result = [self.logical_id[0], self.logical_id[1]]
      if node not in result:
        raise errors.ConfigurationError("DRBD device passed unknown node")
    else:
      raise errors.ProgrammerError("Unhandled device type %s" % self.dev_type)
    return result

  def ComputeNodeTree(self, parent_node):
    """Compute the node/disk tree for this disk and its children.

    This method, given the node on which the parent disk lives, will
    return the list of all (node, disk) pairs which describe the disk
    tree in the most compact way. For example, a drbd/lvm stack
    will be returned as (primary_node, drbd) and (secondary_node, drbd)
    which represents all the top-level devices on the nodes.

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

  def RecordGrow(self, amount):
    """Update the size of this disk after growth.

    This method recurses over the disks's children and updates their
    size correspondigly. The method needs to be kept in sync with the
    actual algorithms from bdev.

    """
    if self.dev_type == constants.LD_LV or self.dev_type == constants.LD_FILE:
      self.size += amount
    elif self.dev_type == constants.LD_DRBD8:
      if self.children:
        self.children[0].RecordGrow(amount)
      self.size += amount
    else:
      raise errors.ProgrammerError("Disk.RecordGrow called for unsupported"
                                   " disk type %s" % self.dev_type)

  def UnsetSize(self):
    """Sets recursively the size to zero for the disk and its children.

    """
    if self.children:
      for child in self.children:
        child.UnsetSize()
    self.size = 0

  def SetPhysicalID(self, target_node, nodes_ip):
    """Convert the logical ID to the physical ID.

    This is used only for drbd, which needs ip/port configuration.

    The routine descends down and updates its children also, because
    this helps when the only the top device is passed to the remote
    node.

    Arguments:
      - target_node: the node we wish to configure for
      - nodes_ip: a mapping of node name to ip

    The target_node must exist in in nodes_ip, and must be one of the
    nodes in the logical ID for each of the DRBD devices encountered
    in the disk tree.

    """
    if self.children:
      for child in self.children:
        child.SetPhysicalID(target_node, nodes_ip)

    if self.logical_id is None and self.physical_id is not None:
      return
    if self.dev_type in constants.LDS_DRBD:
      pnode, snode, port, pminor, sminor, secret = self.logical_id
      if target_node not in (pnode, snode):
        raise errors.ConfigurationError("DRBD device not knowing node %s" %
                                        target_node)
      pnode_ip = nodes_ip.get(pnode, None)
      snode_ip = nodes_ip.get(snode, None)
      if pnode_ip is None or snode_ip is None:
        raise errors.ConfigurationError("Can't find primary or secondary node"
                                        " for %s" % str(self))
      p_data = (pnode_ip, port)
      s_data = (snode_ip, port)
      if pnode == target_node:
        self.physical_id = p_data + s_data + (pminor, secret)
      else: # it must be secondary, we tested above
        self.physical_id = s_data + p_data + (sminor, secret)
    else:
      self.physical_id = self.logical_id
    return

  def ToDict(self):
    """Disk-specific conversion to standard python types.

    This replaces the children lists of objects with lists of
    standard python types.

    """
    bo = super(Disk, self).ToDict()

    for attr in ("children",):
      alist = bo.get(attr, None)
      if alist:
        bo[attr] = self._ContainerToDicts(alist)
    return bo

  @classmethod
  def FromDict(cls, val):
    """Custom function for Disks

    """
    obj = super(Disk, cls).FromDict(val)
    if obj.children:
      obj.children = cls._ContainerFromDicts(obj.children, list, Disk)
    if obj.logical_id and isinstance(obj.logical_id, list):
      obj.logical_id = tuple(obj.logical_id)
    if obj.physical_id and isinstance(obj.physical_id, list):
      obj.physical_id = tuple(obj.physical_id)
    if obj.dev_type in constants.LDS_DRBD:
      # we need a tuple of length six here
      if len(obj.logical_id) < 6:
        obj.logical_id += (None,) * (6 - len(obj.logical_id))
    return obj

  def __str__(self):
    """Custom str() formatter for disks.

    """
    if self.dev_type == constants.LD_LV:
      val =  "<LogicalVolume(/dev/%s/%s" % self.logical_id
    elif self.dev_type in constants.LDS_DRBD:
      node_a, node_b, port, minor_a, minor_b = self.logical_id[:5]
      val = "<DRBD8("
      if self.physical_id is None:
        phy = "unconfigured"
      else:
        phy = ("configured as %s:%s %s:%s" %
               (self.physical_id[0], self.physical_id[1],
                self.physical_id[2], self.physical_id[3]))

      val += ("hosts=%s/%d-%s/%d, port=%s, %s, " %
              (node_a, minor_a, node_b, minor_b, port, phy))
      if self.children and self.children.count(None) == 0:
        val += "backend=%s, metadev=%s" % (self.children[0], self.children[1])
      else:
        val += "no local storage"
    else:
      val = ("<Disk(type=%s, logical_id=%s, physical_id=%s, children=%s" %
             (self.dev_type, self.logical_id, self.physical_id, self.children))
    if self.iv_name is None:
      val += ", not visible"
    else:
      val += ", visible as /dev/%s" % self.iv_name
    if isinstance(self.size, int):
      val += ", size=%dm)>" % self.size
    else:
      val += ", size='%s')>" % (self.size,)
    return val

  def Verify(self):
    """Checks that this disk is correctly configured.

    """
    all_errors = []
    if self.mode not in constants.DISK_ACCESS_SET:
      all_errors.append("Disk access mode '%s' is invalid" % (self.mode, ))
    return all_errors

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    if self.children:
      for child in self.children:
        child.UpgradeConfig()
    # add here config upgrade for this disk


class Instance(TaggableObject):
  """Config object representing an instance."""
  __slots__ = [
    "name",
    "primary_node",
    "os",
    "hypervisor",
    "hvparams",
    "beparams",
    "osparams",
    "admin_up",
    "nics",
    "disks",
    "disk_template",
    "network_port",
    "serial_no",
    ] + _TIMESTAMPS + _UUID

  def _ComputeSecondaryNodes(self):
    """Compute the list of secondary nodes.

    This is a simple wrapper over _ComputeAllNodes.

    """
    all_nodes = set(self._ComputeAllNodes())
    all_nodes.discard(self.primary_node)
    return tuple(all_nodes)

  secondary_nodes = property(_ComputeSecondaryNodes, None, None,
                             "List of secondary nodes")

  def _ComputeAllNodes(self):
    """Compute the list of all nodes.

    Since the data is already there (in the drbd disks), keeping it as
    a separate normal attribute is redundant and if not properly
    synchronised can cause problems. Thus it's better to compute it
    dynamically.

    """
    def _Helper(nodes, device):
      """Recursively computes nodes given a top device."""
      if device.dev_type in constants.LDS_DRBD:
        nodea, nodeb = device.logical_id[:2]
        nodes.add(nodea)
        nodes.add(nodeb)
      if device.children:
        for child in device.children:
          _Helper(nodes, child)

    all_nodes = set()
    all_nodes.add(self.primary_node)
    for device in self.disks:
      _Helper(all_nodes, device)
    return tuple(all_nodes)

  all_nodes = property(_ComputeAllNodes, None, None,
                       "List of all nodes of the instance")

  def MapLVsByNode(self, lvmap=None, devs=None, node=None):
    """Provide a mapping of nodes to LVs this instance owns.

    This function figures out what logical volumes should belong on
    which nodes, recursing through a device tree.

    @param lvmap: optional dictionary to receive the
        'node' : ['lv', ...] data.

    @return: None if lvmap arg is given, otherwise, a dictionary
        of the form { 'nodename' : ['volume1', 'volume2', ...], ... }

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
      if dev.dev_type == constants.LD_LV:
        lvmap[node].append(dev.logical_id[1])

      elif dev.dev_type in constants.LDS_DRBD:
        if dev.children:
          self.MapLVsByNode(lvmap, dev.children, dev.logical_id[0])
          self.MapLVsByNode(lvmap, dev.children, dev.logical_id[1])

      elif dev.children:
        self.MapLVsByNode(lvmap, dev.children, node)

    return ret

  def FindDisk(self, idx):
    """Find a disk given having a specified index.

    This is just a wrapper that does validation of the index.

    @type idx: int
    @param idx: the disk index
    @rtype: L{Disk}
    @return: the corresponding disk
    @raise errors.OpPrereqError: when the given index is not valid

    """
    try:
      idx = int(idx)
      return self.disks[idx]
    except (TypeError, ValueError), err:
      raise errors.OpPrereqError("Invalid disk index: '%s'" % str(err),
                                 errors.ECODE_INVAL)
    except IndexError:
      raise errors.OpPrereqError("Invalid disk index: %d (instace has disks"
                                 " 0 to %d" % (idx, len(self.disks)),
                                 errors.ECODE_INVAL)

  def ToDict(self):
    """Instance-specific conversion to standard python types.

    This replaces the children lists of objects with lists of standard
    python types.

    """
    bo = super(Instance, self).ToDict()

    for attr in "nics", "disks":
      alist = bo.get(attr, None)
      if alist:
        nlist = self._ContainerToDicts(alist)
      else:
        nlist = []
      bo[attr] = nlist
    return bo

  @classmethod
  def FromDict(cls, val):
    """Custom function for instances.

    """
    obj = super(Instance, cls).FromDict(val)
    obj.nics = cls._ContainerFromDicts(obj.nics, list, NIC)
    obj.disks = cls._ContainerFromDicts(obj.disks, list, Disk)
    return obj

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    for nic in self.nics:
      nic.UpgradeConfig()
    for disk in self.disks:
      disk.UpgradeConfig()
    if self.hvparams:
      for key in constants.HVC_GLOBALS:
        try:
          del self.hvparams[key]
        except KeyError:
          pass
    if self.osparams is None:
      self.osparams = {}


class OS(ConfigObject):
  """Config object representing an operating system.

  @type supported_parameters: list
  @ivar supported_parameters: a list of tuples, name and description,
      containing the supported parameters by this OS

  """
  __slots__ = [
    "name",
    "path",
    "api_versions",
    "create_script",
    "export_script",
    "import_script",
    "rename_script",
    "verify_script",
    "supported_variants",
    "supported_parameters",
    ]


class Node(TaggableObject):
  """Config object representing a node."""
  __slots__ = [
    "name",
    "primary_ip",
    "secondary_ip",
    "serial_no",
    "master_candidate",
    "offline",
    "drained",
    ] + _TIMESTAMPS + _UUID


class NodeGroup(ConfigObject):
  """Config object representing a node group."""
  __slots__ = [
    "name",
    "members",
    ] + _TIMESTAMPS + _UUID

  def ToDict(self):
    """Custom function for nodegroup.

    This discards the members object, which gets recalculated and is only kept in memory.

    """
    mydict = super(NodeGroup, self).ToDict()
    del mydict["members"]
    return mydict

  @classmethod
  def FromDict(cls, val):
    """Custom function for nodegroup.

    The members slot is initialized to an empty list, upon deserialization.

    """
    obj = super(NodeGroup, cls).FromDict(val)
    obj.members = []
    return obj


class Cluster(TaggableObject):
  """Config object representing the cluster."""
  __slots__ = [
    "serial_no",
    "rsahostkeypub",
    "highest_used_port",
    "tcpudp_port_pool",
    "mac_prefix",
    "volume_group_name",
    "reserved_lvs",
    "drbd_usermode_helper",
    "default_bridge",
    "default_hypervisor",
    "master_node",
    "master_ip",
    "master_netdev",
    "cluster_name",
    "file_storage_dir",
    "enabled_hypervisors",
    "hvparams",
    "os_hvp",
    "beparams",
    "osparams",
    "nicparams",
    "candidate_pool_size",
    "modify_etc_hosts",
    "modify_ssh_setup",
    "maintain_node_health",
    "uid_pool",
    "default_iallocator",
    "primary_ip_family",
    ] + _TIMESTAMPS + _UUID

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    # pylint: disable-msg=E0203
    # because these are "defined" via slots, not manually
    if self.hvparams is None:
      self.hvparams = constants.HVC_DEFAULTS
    else:
      for hypervisor in self.hvparams:
        self.hvparams[hypervisor] = FillDict(
            constants.HVC_DEFAULTS[hypervisor], self.hvparams[hypervisor])

    if self.os_hvp is None:
      self.os_hvp = {}

    # osparams added before 2.2
    if self.osparams is None:
      self.osparams = {}

    self.beparams = UpgradeGroupedParams(self.beparams,
                                         constants.BEC_DEFAULTS)
    migrate_default_bridge = not self.nicparams
    self.nicparams = UpgradeGroupedParams(self.nicparams,
                                          constants.NICC_DEFAULTS)
    if migrate_default_bridge:
      self.nicparams[constants.PP_DEFAULT][constants.NIC_LINK] = \
        self.default_bridge

    if self.modify_etc_hosts is None:
      self.modify_etc_hosts = True

    if self.modify_ssh_setup is None:
      self.modify_ssh_setup = True

    # default_bridge is no longer used it 2.1. The slot is left there to
    # support auto-upgrading. It can be removed once we decide to deprecate
    # upgrading straight from 2.0.
    if self.default_bridge is not None:
      self.default_bridge = None

    # default_hypervisor is just the first enabled one in 2.1. This slot and
    # code can be removed once upgrading straight from 2.0 is deprecated.
    if self.default_hypervisor is not None:
      self.enabled_hypervisors = ([self.default_hypervisor] +
        [hvname for hvname in self.enabled_hypervisors
         if hvname != self.default_hypervisor])
      self.default_hypervisor = None

    # maintain_node_health added after 2.1.1
    if self.maintain_node_health is None:
      self.maintain_node_health = False

    if self.uid_pool is None:
      self.uid_pool = []

    if self.default_iallocator is None:
      self.default_iallocator = ""

    # reserved_lvs added before 2.2
    if self.reserved_lvs is None:
      self.reserved_lvs = []

    # primary_ip_family added before 2.3
    if self.primary_ip_family is None:
      self.primary_ip_family = AF_INET

  def ToDict(self):
    """Custom function for cluster.

    """
    mydict = super(Cluster, self).ToDict()
    mydict["tcpudp_port_pool"] = list(self.tcpudp_port_pool)
    return mydict

  @classmethod
  def FromDict(cls, val):
    """Custom function for cluster.

    """
    obj = super(Cluster, cls).FromDict(val)
    if not isinstance(obj.tcpudp_port_pool, set):
      obj.tcpudp_port_pool = set(obj.tcpudp_port_pool)
    return obj

  def GetHVDefaults(self, hypervisor, os_name=None, skip_keys=None):
    """Get the default hypervisor parameters for the cluster.

    @param hypervisor: the hypervisor name
    @param os_name: if specified, we'll also update the defaults for this OS
    @param skip_keys: if passed, list of keys not to use
    @return: the defaults dict

    """
    if skip_keys is None:
      skip_keys = []

    fill_stack = [self.hvparams.get(hypervisor, {})]
    if os_name is not None:
      os_hvp = self.os_hvp.get(os_name, {}).get(hypervisor, {})
      fill_stack.append(os_hvp)

    ret_dict = {}
    for o_dict in fill_stack:
      ret_dict = FillDict(ret_dict, o_dict, skip_keys=skip_keys)

    return ret_dict

  def SimpleFillHV(self, hv_name, os_name, hvparams, skip_globals=False):
    """Fill a given hvparams dict with cluster defaults.

    @type hv_name: string
    @param hv_name: the hypervisor to use
    @type os_name: string
    @param os_name: the OS to use for overriding the hypervisor defaults
    @type skip_globals: boolean
    @param skip_globals: if True, the global hypervisor parameters will
        not be filled
    @rtype: dict
    @return: a copy of the given hvparams with missing keys filled from
        the cluster defaults

    """
    if skip_globals:
      skip_keys = constants.HVC_GLOBALS
    else:
      skip_keys = []

    def_dict = self.GetHVDefaults(hv_name, os_name, skip_keys=skip_keys)
    return FillDict(def_dict, hvparams, skip_keys=skip_keys)

  def FillHV(self, instance, skip_globals=False):
    """Fill an instance's hvparams dict with cluster defaults.

    @type instance: L{objects.Instance}
    @param instance: the instance parameter to fill
    @type skip_globals: boolean
    @param skip_globals: if True, the global hypervisor parameters will
        not be filled
    @rtype: dict
    @return: a copy of the instance's hvparams with missing keys filled from
        the cluster defaults

    """
    return self.SimpleFillHV(instance.hypervisor, instance.os,
                             instance.hvparams, skip_globals)

  def SimpleFillBE(self, beparams):
    """Fill a given beparams dict with cluster defaults.

    @type beparams: dict
    @param beparams: the dict to fill
    @rtype: dict
    @return: a copy of the passed in beparams with missing keys filled
        from the cluster defaults

    """
    return FillDict(self.beparams.get(constants.PP_DEFAULT, {}), beparams)

  def FillBE(self, instance):
    """Fill an instance's beparams dict with cluster defaults.

    @type instance: L{objects.Instance}
    @param instance: the instance parameter to fill
    @rtype: dict
    @return: a copy of the instance's beparams with missing keys filled from
        the cluster defaults

    """
    return self.SimpleFillBE(instance.beparams)

  def SimpleFillNIC(self, nicparams):
    """Fill a given nicparams dict with cluster defaults.

    @type nicparams: dict
    @param nicparams: the dict to fill
    @rtype: dict
    @return: a copy of the passed in nicparams with missing keys filled
        from the cluster defaults

    """
    return FillDict(self.nicparams.get(constants.PP_DEFAULT, {}), nicparams)

  def SimpleFillOS(self, os_name, os_params):
    """Fill an instance's osparams dict with cluster defaults.

    @type os_name: string
    @param os_name: the OS name to use
    @type os_params: dict
    @param os_params: the dict to fill with default values
    @rtype: dict
    @return: a copy of the instance's osparams with missing keys filled from
        the cluster defaults

    """
    name_only = os_name.split("+", 1)[0]
    # base OS
    result = self.osparams.get(name_only, {})
    # OS with variant
    result = FillDict(result, self.osparams.get(os_name, {}))
    # specified params
    return FillDict(result, os_params)


class BlockDevStatus(ConfigObject):
  """Config object representing the status of a block device."""
  __slots__ = [
    "dev_path",
    "major",
    "minor",
    "sync_percent",
    "estimated_time",
    "is_degraded",
    "ldisk_status",
    ]


class ImportExportStatus(ConfigObject):
  """Config object representing the status of an import or export."""
  __slots__ = [
    "recent_output",
    "listen_port",
    "connected",
    "progress_mbytes",
    "progress_throughput",
    "progress_eta",
    "progress_percent",
    "exit_status",
    "error_message",
    ] + _TIMESTAMPS


class ImportExportOptions(ConfigObject):
  """Options for import/export daemon

  @ivar key_name: X509 key name (None for cluster certificate)
  @ivar ca_pem: Remote peer CA in PEM format (None for cluster certificate)
  @ivar compress: Compression method (one of L{constants.IEC_ALL})
  @ivar magic: Used to ensure the connection goes to the right disk

  """
  __slots__ = [
    "key_name",
    "ca_pem",
    "compress",
    "magic",
    ]


class ConfdRequest(ConfigObject):
  """Object holding a confd request.

  @ivar protocol: confd protocol version
  @ivar type: confd query type
  @ivar query: query request
  @ivar rsalt: requested reply salt

  """
  __slots__ = [
    "protocol",
    "type",
    "query",
    "rsalt",
    ]


class ConfdReply(ConfigObject):
  """Object holding a confd reply.

  @ivar protocol: confd protocol version
  @ivar status: reply status code (ok, error)
  @ivar answer: confd query reply
  @ivar serial: configuration serial number

  """
  __slots__ = [
    "protocol",
    "status",
    "answer",
    "serial",
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

  @classmethod
  def Loads(cls, data):
    """Load data from a string."""
    buf = StringIO(data)
    cfp = cls()
    cfp.readfp(buf)
    return cfp
