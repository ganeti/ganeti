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


"""Transportable objects for Ganeti.

This module provides small, mostly data-only objects which are safe to
pass to and from external parties.

"""


import simplejson
import ConfigParser
import re
from cStringIO import StringIO

from ganeti import errors
from ganeti import constants


__all__ = ["ConfigObject", "ConfigData", "NIC", "Disk", "Instance",
           "OS", "Node", "Cluster"]


# Check whether the simplejson module supports indentation
_JSON_INDENT = 2
try:
  simplejson.dumps(1, indent=_JSON_INDENT)
except TypeError:
  _JSON_INDENT = None


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
    for k, v in kwargs.iteritems():
      setattr(self, k, v)

  def __getattr__(self, name):
    if name not in self.__slots__:
      raise AttributeError("Invalid object attribute %s.%s" %
                           (type(self).__name__, name))
    return None

  def __setitem__(self, key, value):
    if key not in self.__slots__:
      raise KeyError(key)
    setattr(self, key, value)

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

  def Dump(self, fobj):
    """Dump to a file object.

    """
    data = self.ToDict()
    if _JSON_INDENT is None:
      simplejson.dump(data, fobj)
    else:
      simplejson.dump(data, fobj, indent=_JSON_INDENT)

  @classmethod
  def Load(cls, fobj):
    """Load data from the given stream.

    """
    return cls.FromDict(simplejson.load(fobj))

  def Dumps(self):
    """Dump and return the string representation."""
    buf = StringIO()
    self.Dump(buf)
    return buf.getvalue()

  @classmethod
  def Loads(cls, data):
    """Load data from a string."""
    return cls.Load(StringIO(data))

  def ToDict(self):
    """Convert to a dict holding only standard python types.

    The generic routine just dumps all of this object's attributes in
    a dict. It does not work if the class has children who are
    ConfigObjects themselves (e.g. the nics list in an Instance), in
    which case the object should subclass the function in order to
    make sure all objects returned are only standard python types.

    """
    return dict([(k, getattr(self, k, None)) for k in self.__slots__])

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
    obj = cls(**val_str)
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
    if c_type is dict:
      ret = dict([(k, e_type.FromDict(v)) for k, v in source.iteritems()])
    elif c_type in (list, tuple, set, frozenset):
      ret = c_type([e_type.FromDict(elem) for elem in source])
    else:
      raise TypeError("Invalid container type %s passed to"
                      " _ContainerFromDicts" % c_type)
    return ret

  def __repr__(self):
    """Implement __repr__ for ConfigObjects."""
    return repr(self.ToDict())


class TaggableObject(ConfigObject):
  """An generic class supporting tags.

  """
  __slots__ = ConfigObject.__slots__ + ["tags"]

  @staticmethod
  def ValidateTag(tag):
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
    if not re.match("^[ \w.+*/:-]+$", tag):
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
  __slots__ = ["cluster", "nodes", "instances"]

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


class NIC(ConfigObject):
  """Config object representing a network card."""
  __slots__ = ["mac", "ip", "bridge"]


class Disk(ConfigObject):
  """Config object representing a block device."""
  __slots__ = ["dev_type", "logical_id", "physical_id",
               "children", "iv_name", "size"]

  def CreateOnSecondary(self):
    """Test if this device needs to be created on a secondary node."""
    return self.dev_type in (constants.LD_DRBD7, constants.LD_DRBD8,
                             constants.LD_LV)

  def AssembleOnSecondary(self):
    """Test if this device needs to be assembled on a secondary node."""
    return self.dev_type in (constants.LD_DRBD7, constants.LD_DRBD8,
                             constants.LD_LV)

  def OpenOnSecondary(self):
    """Test if this device needs to be opened on a secondary node."""
    return self.dev_type in (constants.LD_LV,)

  def StaticDevPath(self):
    """Return the device path if this device type has a static one.

    Some devices (LVM for example) live always at the same /dev/ path,
    irrespective of their status. For such devices, we return this
    path, for others we return None.

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

  def GetNodes(self, node):
    """This function returns the nodes this device lives on.

    Given the node on which the parent of the device lives on (or, in
    case of a top-level device, the primary node of the devices'
    instance), this function will return a list of nodes on which this
    devices needs to (or can) be assembled.

    """
    if self.dev_type in [constants.LD_LV, constants.LD_MD_R1,
                         constants.LD_FILE]:
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
    return obj

  def __str__(self):
    """Custom str() formatter for disks.

    """
    if self.dev_type == constants.LD_LV:
      val =  "<LogicalVolume(/dev/%s/%s" % self.logical_id
    elif self.dev_type in constants.LDS_DRBD:
      if self.dev_type == constants.LD_DRBD7:
        val = "<DRBD7("
      else:
        val = "<DRBD8("
      if self.physical_id is None:
        phy = "unconfigured"
      else:
        phy = ("configured as %s:%s %s:%s" %
               (self.physical_id[0], self.physical_id[1],
                self.physical_id[2], self.physical_id[3]))

      val += ("hosts=%s-%s, port=%s, %s, " %
              (self.logical_id[0], self.logical_id[1], self.logical_id[2],
               phy))
      if self.children and self.children.count(None) == 0:
        val += "backend=%s, metadev=%s" % (self.children[0], self.children[1])
      else:
        val += "no local storage"
    elif self.dev_type == constants.LD_MD_R1:
      val = "<MD_R1(uuid=%s, children=%s" % (self.physical_id, self.children)
    else:
      val = ("<Disk(type=%s, logical_id=%s, physical_id=%s, children=%s" %
             (self.dev_type, self.logical_id, self.physical_id, self.children))
    if self.iv_name is None:
      val += ", not visible"
    else:
      val += ", visible as /dev/%s" % self.iv_name
    val += ", size=%dm)>" % self.size
    return val


class Instance(TaggableObject):
  """Config object representing an instance."""
  __slots__ = TaggableObject.__slots__ + [
    "name",
    "primary_node",
    "os",
    "status",
    "memory",
    "vcpus",
    "nics",
    "disks",
    "disk_template",
    "network_port",
    "kernel_path",
    "initrd_path",
    "hvm_boot_order",
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
      if device.dev_type in constants.LDS_DRBD:
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
      if dev.dev_type == constants.LD_LV:
        lvmap[node].append(dev.logical_id[1])

      elif dev.dev_type in constants.LDS_DRBD:
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

  def FindDisk(self, name):
    """Find a disk given having a specified name.

    This will return the disk which has the given iv_name.

    """
    for disk in self.disks:
      if disk.iv_name == name:
        return disk

    return None

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


class OS(ConfigObject):
  """Config object representing an operating system."""
  __slots__ = [
    "name",
    "path",
    "status",
    "api_version",
    "create_script",
    "export_script",
    "import_script",
    "rename_script",
    ]

  @classmethod
  def FromInvalidOS(cls, err):
    """Create an OS from an InvalidOS error.

    This routine knows how to convert an InvalidOS error to an OS
    object representing the broken OS with a meaningful error message.

    """
    if not isinstance(err, errors.InvalidOS):
      raise errors.ProgrammerError("Trying to initialize an OS from an"
                                   " invalid object of type %s" % type(err))

    return cls(name=err.args[0], path=err.args[1], status=err.args[2])

  def __nonzero__(self):
    return self.status == constants.OS_VALID_STATUS

  __bool__ = __nonzero__


class Node(TaggableObject):
  """Config object representing a node."""
  __slots__ = TaggableObject.__slots__ + [
    "name",
    "primary_ip",
    "secondary_ip",
    ]


class Cluster(TaggableObject):
  """Config object representing the cluster."""
  __slots__ = TaggableObject.__slots__ + [
    "config_version",
    "serial_no",
    "rsahostkeypub",
    "highest_used_port",
    "tcpudp_port_pool",
    "mac_prefix",
    "volume_group_name",
    "default_bridge",
    ]

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
