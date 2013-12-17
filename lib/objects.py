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


"""Transportable objects for Ganeti.

This module provides small, mostly data-only objects which are safe to
pass to and from external parties.

"""

# pylint: disable=E0203,W0201,R0902

# E0203: Access to member %r before its definition, since we use
# objects.py which doesn't explicitly initialise its members

# W0201: Attribute '%s' defined outside __init__

# R0902: Allow instances of these objects to have more than 20 attributes

import ConfigParser
import re
import copy
import logging
import time
from cStringIO import StringIO

from ganeti import errors
from ganeti import constants
from ganeti import netutils
from ganeti import outils
from ganeti import utils

from socket import AF_INET


__all__ = ["ConfigObject", "ConfigData", "NIC", "Disk", "Instance",
           "OS", "Node", "NodeGroup", "Cluster", "FillDict", "Network"]

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
      if k in ret_dict:
        del ret_dict[k]
  return ret_dict


def FillIPolicy(default_ipolicy, custom_ipolicy):
  """Fills an instance policy with defaults.

  """
  assert frozenset(default_ipolicy.keys()) == constants.IPOLICY_ALL_KEYS
  ret_dict = copy.deepcopy(custom_ipolicy)
  for key in default_ipolicy:
    if key not in ret_dict:
      ret_dict[key] = copy.deepcopy(default_ipolicy[key])
    elif key == constants.ISPECS_STD:
      ret_dict[key] = FillDict(default_ipolicy[key], ret_dict[key])
  return ret_dict


def FillDiskParams(default_dparams, custom_dparams, skip_keys=None):
  """Fills the disk parameter defaults.

  @see: L{FillDict} for parameters and return value

  """
  assert frozenset(default_dparams.keys()) == constants.DISK_TEMPLATES

  return dict((dt, FillDict(default_dparams[dt], custom_dparams.get(dt, {}),
                             skip_keys=skip_keys))
              for dt in constants.DISK_TEMPLATES)


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


def UpgradeBeParams(target):
  """Update the be parameters dict to the new format.

  @type target: dict
  @param target: "be" parameters dict

  """
  if constants.BE_MEMORY in target:
    memory = target[constants.BE_MEMORY]
    target[constants.BE_MAXMEM] = memory
    target[constants.BE_MINMEM] = memory
    del target[constants.BE_MEMORY]


def UpgradeDiskParams(diskparams):
  """Upgrade the disk parameters.

  @type diskparams: dict
  @param diskparams: disk parameters to upgrade
  @rtype: dict
  @return: the upgraded disk parameters dict

  """
  if not diskparams:
    result = {}
  else:
    result = FillDiskParams(constants.DISK_DT_DEFAULTS, diskparams)

  return result


def UpgradeNDParams(ndparams):
  """Upgrade ndparams structure.

  @type ndparams: dict
  @param ndparams: disk parameters to upgrade
  @rtype: dict
  @return: the upgraded node parameters dict

  """
  if ndparams is None:
    ndparams = {}

  if (constants.ND_OOB_PROGRAM in ndparams and
      ndparams[constants.ND_OOB_PROGRAM] is None):
    # will be reset by the line below
    del ndparams[constants.ND_OOB_PROGRAM]
  return FillDict(constants.NDC_DEFAULTS, ndparams)


def MakeEmptyIPolicy():
  """Create empty IPolicy dictionary.

  """
  return {}


class ConfigObject(outils.ValidatedSlots):
  """A generic config object.

  It has the following properties:

    - provides somewhat safe recursive unpickling and pickling for its classes
    - unset attributes which are defined in slots are always returned
      as None instead of raising an error

  Classes derived from this must always declare __slots__ (we use many
  config objects and the memory reduction is useful)

  """
  __slots__ = []

  def __getattr__(self, name):
    if name not in self.GetAllSlots():
      raise AttributeError("Invalid object attribute %s.%s" %
                           (type(self).__name__, name))
    return None

  def __setstate__(self, state):
    slots = self.GetAllSlots()
    for name in state:
      if name in slots:
        setattr(self, name, state[name])

  def Validate(self):
    """Validates the slots.

    """

  def ToDict(self):
    """Convert to a dict holding only standard python types.

    The generic routine just dumps all of this object's attributes in
    a dict. It does not work if the class has children who are
    ConfigObjects themselves (e.g. the nics list in an Instance), in
    which case the object should subclass the function in order to
    make sure all objects returned are only standard python types.

    """
    result = {}
    for name in self.GetAllSlots():
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
    obj = cls(**val_str) # pylint: disable=W0142
    return obj

  def Copy(self):
    """Makes a deep copy of the current object and its children.

    """
    dict_form = self.ToDict()
    clone_obj = self.__class__.FromDict(dict_form)
    return clone_obj

  def __repr__(self):
    """Implement __repr__ for ConfigObjects."""
    return repr(self.ToDict())

  def __eq__(self, other):
    """Implement __eq__ for ConfigObjects."""
    return isinstance(other, self.__class__) and self.ToDict() == other.ToDict()

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
  VALID_TAG_RE = re.compile(r"^[\w.+*/:@-]+$")

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


class MasterNetworkParameters(ConfigObject):
  """Network configuration parameters for the master

  @ivar uuid: master nodes UUID
  @ivar ip: master IP
  @ivar netmask: master netmask
  @ivar netdev: master network device
  @ivar ip_family: master IP family

  """
  __slots__ = [
    "uuid",
    "ip",
    "netmask",
    "netdev",
    "ip_family",
    ]


class ConfigData(ConfigObject):
  """Top-level config object."""
  __slots__ = [
    "version",
    "cluster",
    "nodes",
    "nodegroups",
    "instances",
    "networks",
    "serial_no",
    ] + _TIMESTAMPS

  def ToDict(self):
    """Custom function for top-level config data.

    This just replaces the list of instances, nodes and the cluster
    with standard python types.

    """
    mydict = super(ConfigData, self).ToDict()
    mydict["cluster"] = mydict["cluster"].ToDict()
    for key in "nodes", "instances", "nodegroups", "networks":
      mydict[key] = outils.ContainerToDicts(mydict[key])

    return mydict

  @classmethod
  def FromDict(cls, val):
    """Custom function for top-level config data

    """
    obj = super(ConfigData, cls).FromDict(val)
    obj.cluster = Cluster.FromDict(obj.cluster)
    obj.nodes = outils.ContainerFromDicts(obj.nodes, dict, Node)
    obj.instances = \
      outils.ContainerFromDicts(obj.instances, dict, Instance)
    obj.nodegroups = \
      outils.ContainerFromDicts(obj.nodegroups, dict, NodeGroup)
    obj.networks = outils.ContainerFromDicts(obj.networks, dict, Network)
    return obj

  def HasAnyDiskOfType(self, dev_type):
    """Check if in there is at disk of the given type in the configuration.

    @type dev_type: L{constants.DTS_BLOCK}
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
    self._UpgradeEnabledDiskTemplates()
    if self.nodegroups is None:
      self.nodegroups = {}
    for nodegroup in self.nodegroups.values():
      nodegroup.UpgradeConfig()
      InstancePolicy.UpgradeDiskTemplates(
        nodegroup.ipolicy, self.cluster.enabled_disk_templates)
    if self.cluster.drbd_usermode_helper is None:
      if self.cluster.IsDiskTemplateEnabled(constants.DT_DRBD8):
        self.cluster.drbd_usermode_helper = constants.DEFAULT_DRBD_HELPER
    if self.networks is None:
      self.networks = {}
    for network in self.networks.values():
      network.UpgradeConfig()

  def _UpgradeEnabledDiskTemplates(self):
    """Upgrade the cluster's enabled disk templates by inspecting the currently
       enabled and/or used disk templates.

    """
    if not self.cluster.enabled_disk_templates:
      template_set = \
        set([inst.disk_template for inst in self.instances.values()])
      # Add drbd and plain, if lvm is enabled (by specifying a volume group)
      if self.cluster.volume_group_name:
        template_set.add(constants.DT_DRBD8)
        template_set.add(constants.DT_PLAIN)
      # Set enabled_disk_templates to the inferred disk templates. Order them
      # according to a preference list that is based on Ganeti's history of
      # supported disk templates.
      self.cluster.enabled_disk_templates = []
      for preferred_template in constants.DISK_TEMPLATE_PREFERENCE:
        if preferred_template in template_set:
          self.cluster.enabled_disk_templates.append(preferred_template)
          template_set.remove(preferred_template)
      self.cluster.enabled_disk_templates.extend(list(template_set))
    InstancePolicy.UpgradeDiskTemplates(
      self.cluster.ipolicy, self.cluster.enabled_disk_templates)


class NIC(ConfigObject):
  """Config object representing a network card."""
  __slots__ = ["name", "mac", "ip", "network",
               "nicparams", "netinfo", "pci"] + _UUID

  @classmethod
  def CheckParameterSyntax(cls, nicparams):
    """Check the given parameters for validity.

    @type nicparams:  dict
    @param nicparams: dictionary with parameter names/value
    @raise errors.ConfigurationError: when a parameter is not valid

    """
    mode = nicparams[constants.NIC_MODE]
    if (mode not in constants.NIC_VALID_MODES and
        mode != constants.VALUE_AUTO):
      raise errors.ConfigurationError("Invalid NIC mode '%s'" % mode)

    if (mode == constants.NIC_MODE_BRIDGED and
        not nicparams[constants.NIC_LINK]):
      raise errors.ConfigurationError("Missing bridged NIC link")


class Disk(ConfigObject):
  """Config object representing a block device."""
  __slots__ = (["name", "dev_type", "logical_id", "children", "iv_name",
                "size", "mode", "params", "spindles", "pci"] + _UUID +
               # dynamic_params is special. It depends on the node this instance
               # is sent to, and should not be persisted.
               ["dynamic_params"])

  def CreateOnSecondary(self):
    """Test if this device needs to be created on a secondary node."""
    return self.dev_type in (constants.DT_DRBD8, constants.DT_PLAIN)

  def AssembleOnSecondary(self):
    """Test if this device needs to be assembled on a secondary node."""
    return self.dev_type in (constants.DT_DRBD8, constants.DT_PLAIN)

  def OpenOnSecondary(self):
    """Test if this device needs to be opened on a secondary node."""
    return self.dev_type in (constants.DT_PLAIN,)

  def StaticDevPath(self):
    """Return the device path if this device type has a static one.

    Some devices (LVM for example) live always at the same /dev/ path,
    irrespective of their status. For such devices, we return this
    path, for others we return None.

    @warning: The path returned is not a normalized pathname; callers
        should check that it is a valid path.

    """
    if self.dev_type == constants.DT_PLAIN:
      return "/dev/%s/%s" % (self.logical_id[0], self.logical_id[1])
    elif self.dev_type == constants.DT_BLOCK:
      return self.logical_id[1]
    elif self.dev_type == constants.DT_RBD:
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
    if self.dev_type == constants.DT_DRBD8:
      return 0
    return -1

  def IsBasedOnDiskType(self, dev_type):
    """Check if the disk or its children are based on the given type.

    @type dev_type: L{constants.DTS_BLOCK}
    @param dev_type: the type to look for
    @rtype: boolean
    @return: boolean indicating if a device of the given type was found or not

    """
    if self.children:
      for child in self.children:
        if child.IsBasedOnDiskType(dev_type):
          return True
    return self.dev_type == dev_type

  def GetNodes(self, node_uuid):
    """This function returns the nodes this device lives on.

    Given the node on which the parent of the device lives on (or, in
    case of a top-level device, the primary node of the devices'
    instance), this function will return a list of nodes on which this
    devices needs to (or can) be assembled.

    """
    if self.dev_type in [constants.DT_PLAIN, constants.DT_FILE,
                         constants.DT_BLOCK, constants.DT_RBD,
                         constants.DT_EXT, constants.DT_SHARED_FILE,
                         constants.DT_GLUSTER]:
      result = [node_uuid]
    elif self.dev_type in constants.DTS_DRBD:
      result = [self.logical_id[0], self.logical_id[1]]
      if node_uuid not in result:
        raise errors.ConfigurationError("DRBD device passed unknown node")
    else:
      raise errors.ProgrammerError("Unhandled device type %s" % self.dev_type)
    return result

  def ComputeNodeTree(self, parent_node_uuid):
    """Compute the node/disk tree for this disk and its children.

    This method, given the node on which the parent disk lives, will
    return the list of all (node UUID, disk) pairs which describe the disk
    tree in the most compact way. For example, a drbd/lvm stack
    will be returned as (primary_node, drbd) and (secondary_node, drbd)
    which represents all the top-level devices on the nodes.

    """
    my_nodes = self.GetNodes(parent_node_uuid)
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

  def ComputeGrowth(self, amount):
    """Compute the per-VG growth requirements.

    This only works for VG-based disks.

    @type amount: integer
    @param amount: the desired increase in (user-visible) disk space
    @rtype: dict
    @return: a dictionary of volume-groups and the required size

    """
    if self.dev_type == constants.DT_PLAIN:
      return {self.logical_id[0]: amount}
    elif self.dev_type == constants.DT_DRBD8:
      if self.children:
        return self.children[0].ComputeGrowth(amount)
      else:
        return {}
    else:
      # Other disk types do not require VG space
      return {}

  def RecordGrow(self, amount):
    """Update the size of this disk after growth.

    This method recurses over the disks's children and updates their
    size correspondigly. The method needs to be kept in sync with the
    actual algorithms from bdev.

    """
    if self.dev_type in (constants.DT_PLAIN, constants.DT_FILE,
                         constants.DT_RBD, constants.DT_EXT,
                         constants.DT_SHARED_FILE, constants.DT_GLUSTER):
      self.size += amount
    elif self.dev_type == constants.DT_DRBD8:
      if self.children:
        self.children[0].RecordGrow(amount)
      self.size += amount
    else:
      raise errors.ProgrammerError("Disk.RecordGrow called for unsupported"
                                   " disk type %s" % self.dev_type)

  def Update(self, size=None, mode=None, spindles=None):
    """Apply changes to size, spindles and mode.

    """
    if self.dev_type == constants.DT_DRBD8:
      if self.children:
        self.children[0].Update(size=size, mode=mode)
    else:
      assert not self.children

    if size is not None:
      self.size = size
    if mode is not None:
      self.mode = mode
    if spindles is not None:
      self.spindles = spindles

  def UnsetSize(self):
    """Sets recursively the size to zero for the disk and its children.

    """
    if self.children:
      for child in self.children:
        child.UnsetSize()
    self.size = 0

  def UpdateDynamicDiskParams(self, target_node_uuid, nodes_ip):
    """Updates the dynamic disk params for the given node.

    This is mainly used for drbd, which needs ip/port configuration.

    Arguments:
      - target_node_uuid: the node UUID we wish to configure for
      - nodes_ip: a mapping of node name to ip

    The target_node must exist in nodes_ip, and should be one of the
    nodes in the logical ID if this device is a DRBD device.

    """
    if self.children:
      for child in self.children:
        child.UpdateDynamicDiskParams(target_node_uuid, nodes_ip)

    dyn_disk_params = {}
    if self.logical_id is not None and self.dev_type in constants.DTS_DRBD:
      pnode_uuid, snode_uuid, _, pminor, sminor, _ = self.logical_id
      if target_node_uuid not in (pnode_uuid, snode_uuid):
        # disk object is being sent to neither the primary nor the secondary
        # node. reset the dynamic parameters, the target node is not
        # supposed to use them.
        self.dynamic_params = dyn_disk_params
        return

      pnode_ip = nodes_ip.get(pnode_uuid, None)
      snode_ip = nodes_ip.get(snode_uuid, None)
      if pnode_ip is None or snode_ip is None:
        raise errors.ConfigurationError("Can't find primary or secondary node"
                                        " for %s" % str(self))
      if pnode_uuid == target_node_uuid:
        dyn_disk_params[constants.DDP_LOCAL_IP] = pnode_ip
        dyn_disk_params[constants.DDP_REMOTE_IP] = snode_ip
        dyn_disk_params[constants.DDP_LOCAL_MINOR] = pminor
        dyn_disk_params[constants.DDP_REMOTE_MINOR] = sminor
      else: # it must be secondary, we tested above
        dyn_disk_params[constants.DDP_LOCAL_IP] = snode_ip
        dyn_disk_params[constants.DDP_REMOTE_IP] = pnode_ip
        dyn_disk_params[constants.DDP_LOCAL_MINOR] = sminor
        dyn_disk_params[constants.DDP_REMOTE_MINOR] = pminor

    self.dynamic_params = dyn_disk_params

  # pylint: disable=W0221
  def ToDict(self, include_dynamic_params=False):
    """Disk-specific conversion to standard python types.

    This replaces the children lists of objects with lists of
    standard python types.

    """
    bo = super(Disk, self).ToDict()
    if not include_dynamic_params and "dynamic_params" in bo:
      del bo["dynamic_params"]

    for attr in ("children",):
      alist = bo.get(attr, None)
      if alist:
        bo[attr] = outils.ContainerToDicts(alist)
    return bo

  @classmethod
  def FromDict(cls, val):
    """Custom function for Disks

    """
    obj = super(Disk, cls).FromDict(val)
    if obj.children:
      obj.children = outils.ContainerFromDicts(obj.children, list, Disk)
    if obj.logical_id and isinstance(obj.logical_id, list):
      obj.logical_id = tuple(obj.logical_id)
    if obj.dev_type in constants.DTS_DRBD:
      # we need a tuple of length six here
      if len(obj.logical_id) < 6:
        obj.logical_id += (None,) * (6 - len(obj.logical_id))
    return obj

  def __str__(self):
    """Custom str() formatter for disks.

    """
    if self.dev_type == constants.DT_PLAIN:
      val = "<LogicalVolume(/dev/%s/%s" % self.logical_id
    elif self.dev_type in constants.DTS_DRBD:
      node_a, node_b, port, minor_a, minor_b = self.logical_id[:5]
      val = "<DRBD8("

      val += ("hosts=%s/%d-%s/%d, port=%s, " %
              (node_a, minor_a, node_b, minor_b, port))
      if self.children and self.children.count(None) == 0:
        val += "backend=%s, metadev=%s" % (self.children[0], self.children[1])
      else:
        val += "no local storage"
    else:
      val = ("<Disk(type=%s, logical_id=%s, children=%s" %
             (self.dev_type, self.logical_id, self.children))
    if self.iv_name is None:
      val += ", not visible"
    else:
      val += ", visible as /dev/%s" % self.iv_name
    if self.spindles is not None:
      val += ", spindles=%s" % self.spindles
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

    # FIXME: Make this configurable in Ganeti 2.7
    self.params = {}
    # add here config upgrade for this disk

    # map of legacy device types (mapping differing LD constants to new
    # DT constants)
    LEG_DEV_TYPE_MAP = {"lvm": constants.DT_PLAIN, "drbd8": constants.DT_DRBD8}
    if self.dev_type in LEG_DEV_TYPE_MAP:
      self.dev_type = LEG_DEV_TYPE_MAP[self.dev_type]

  @staticmethod
  def ComputeLDParams(disk_template, disk_params):
    """Computes Logical Disk parameters from Disk Template parameters.

    @type disk_template: string
    @param disk_template: disk template, one of L{constants.DISK_TEMPLATES}
    @type disk_params: dict
    @param disk_params: disk template parameters;
                        dict(template_name -> parameters
    @rtype: list(dict)
    @return: a list of dicts, one for each node of the disk hierarchy. Each dict
      contains the LD parameters of the node. The tree is flattened in-order.

    """
    if disk_template not in constants.DISK_TEMPLATES:
      raise errors.ProgrammerError("Unknown disk template %s" % disk_template)

    assert disk_template in disk_params

    result = list()
    dt_params = disk_params[disk_template]

    if disk_template == constants.DT_DRBD8:
      result.append(FillDict(constants.DISK_LD_DEFAULTS[constants.DT_DRBD8], {
        constants.LDP_RESYNC_RATE: dt_params[constants.DRBD_RESYNC_RATE],
        constants.LDP_BARRIERS: dt_params[constants.DRBD_DISK_BARRIERS],
        constants.LDP_NO_META_FLUSH: dt_params[constants.DRBD_META_BARRIERS],
        constants.LDP_DEFAULT_METAVG: dt_params[constants.DRBD_DEFAULT_METAVG],
        constants.LDP_DISK_CUSTOM: dt_params[constants.DRBD_DISK_CUSTOM],
        constants.LDP_NET_CUSTOM: dt_params[constants.DRBD_NET_CUSTOM],
        constants.LDP_PROTOCOL: dt_params[constants.DRBD_PROTOCOL],
        constants.LDP_DYNAMIC_RESYNC: dt_params[constants.DRBD_DYNAMIC_RESYNC],
        constants.LDP_PLAN_AHEAD: dt_params[constants.DRBD_PLAN_AHEAD],
        constants.LDP_FILL_TARGET: dt_params[constants.DRBD_FILL_TARGET],
        constants.LDP_DELAY_TARGET: dt_params[constants.DRBD_DELAY_TARGET],
        constants.LDP_MAX_RATE: dt_params[constants.DRBD_MAX_RATE],
        constants.LDP_MIN_RATE: dt_params[constants.DRBD_MIN_RATE],
        }))

      # data LV
      result.append(FillDict(constants.DISK_LD_DEFAULTS[constants.DT_PLAIN], {
        constants.LDP_STRIPES: dt_params[constants.DRBD_DATA_STRIPES],
        }))

      # metadata LV
      result.append(FillDict(constants.DISK_LD_DEFAULTS[constants.DT_PLAIN], {
        constants.LDP_STRIPES: dt_params[constants.DRBD_META_STRIPES],
        }))

    else:
      defaults = constants.DISK_LD_DEFAULTS[disk_template]
      values = {}
      for field in defaults:
        values[field] = dt_params[field]
      result.append(FillDict(defaults, values))

    return result


class InstancePolicy(ConfigObject):
  """Config object representing instance policy limits dictionary.

  Note that this object is not actually used in the config, it's just
  used as a placeholder for a few functions.

  """
  @classmethod
  def UpgradeDiskTemplates(cls, ipolicy, enabled_disk_templates):
    """Upgrades the ipolicy configuration."""
    if constants.IPOLICY_DTS in ipolicy:
      if not set(ipolicy[constants.IPOLICY_DTS]).issubset(
        set(enabled_disk_templates)):
        ipolicy[constants.IPOLICY_DTS] = list(
          set(ipolicy[constants.IPOLICY_DTS]) & set(enabled_disk_templates))

  @classmethod
  def CheckParameterSyntax(cls, ipolicy, check_std):
    """ Check the instance policy for validity.

    @type ipolicy: dict
    @param ipolicy: dictionary with min/max/std specs and policies
    @type check_std: bool
    @param check_std: Whether to check std value or just assume compliance
    @raise errors.ConfigurationError: when the policy is not legal

    """
    InstancePolicy.CheckISpecSyntax(ipolicy, check_std)
    if constants.IPOLICY_DTS in ipolicy:
      InstancePolicy.CheckDiskTemplates(ipolicy[constants.IPOLICY_DTS])
    for key in constants.IPOLICY_PARAMETERS:
      if key in ipolicy:
        InstancePolicy.CheckParameter(key, ipolicy[key])
    wrong_keys = frozenset(ipolicy.keys()) - constants.IPOLICY_ALL_KEYS
    if wrong_keys:
      raise errors.ConfigurationError("Invalid keys in ipolicy: %s" %
                                      utils.CommaJoin(wrong_keys))

  @classmethod
  def _CheckIncompleteSpec(cls, spec, keyname):
    missing_params = constants.ISPECS_PARAMETERS - frozenset(spec.keys())
    if missing_params:
      msg = ("Missing instance specs parameters for %s: %s" %
             (keyname, utils.CommaJoin(missing_params)))
      raise errors.ConfigurationError(msg)

  @classmethod
  def CheckISpecSyntax(cls, ipolicy, check_std):
    """Check the instance policy specs for validity.

    @type ipolicy: dict
    @param ipolicy: dictionary with min/max/std specs
    @type check_std: bool
    @param check_std: Whether to check std value or just assume compliance
    @raise errors.ConfigurationError: when specs are not valid

    """
    if constants.ISPECS_MINMAX not in ipolicy:
      # Nothing to check
      return

    if check_std and constants.ISPECS_STD not in ipolicy:
      msg = "Missing key in ipolicy: %s" % constants.ISPECS_STD
      raise errors.ConfigurationError(msg)
    stdspec = ipolicy.get(constants.ISPECS_STD)
    if check_std:
      InstancePolicy._CheckIncompleteSpec(stdspec, constants.ISPECS_STD)

    if not ipolicy[constants.ISPECS_MINMAX]:
      raise errors.ConfigurationError("Empty minmax specifications")
    std_is_good = False
    for minmaxspecs in ipolicy[constants.ISPECS_MINMAX]:
      missing = constants.ISPECS_MINMAX_KEYS - frozenset(minmaxspecs.keys())
      if missing:
        msg = "Missing instance specification: %s" % utils.CommaJoin(missing)
        raise errors.ConfigurationError(msg)
      for (key, spec) in minmaxspecs.items():
        InstancePolicy._CheckIncompleteSpec(spec, key)

      spec_std_ok = True
      for param in constants.ISPECS_PARAMETERS:
        par_std_ok = InstancePolicy._CheckISpecParamSyntax(minmaxspecs, stdspec,
                                                           param, check_std)
        spec_std_ok = spec_std_ok and par_std_ok
      std_is_good = std_is_good or spec_std_ok
    if not std_is_good:
      raise errors.ConfigurationError("Invalid std specifications")

  @classmethod
  def _CheckISpecParamSyntax(cls, minmaxspecs, stdspec, name, check_std):
    """Check the instance policy specs for validity on a given key.

    We check if the instance specs makes sense for a given key, that is
    if minmaxspecs[min][name] <= stdspec[name] <= minmaxspec[max][name].

    @type minmaxspecs: dict
    @param minmaxspecs: dictionary with min and max instance spec
    @type stdspec: dict
    @param stdspec: dictionary with standard instance spec
    @type name: string
    @param name: what are the limits for
    @type check_std: bool
    @param check_std: Whether to check std value or just assume compliance
    @rtype: bool
    @return: C{True} when specs are valid, C{False} when standard spec for the
        given name is not valid
    @raise errors.ConfigurationError: when min/max specs for the given name
        are not valid

    """
    minspec = minmaxspecs[constants.ISPECS_MIN]
    maxspec = minmaxspecs[constants.ISPECS_MAX]
    min_v = minspec[name]
    max_v = maxspec[name]

    if min_v > max_v:
      err = ("Invalid specification of min/max values for %s: %s/%s" %
             (name, min_v, max_v))
      raise errors.ConfigurationError(err)
    elif check_std:
      std_v = stdspec.get(name, min_v)
      return std_v >= min_v and std_v <= max_v
    else:
      return True

  @classmethod
  def CheckDiskTemplates(cls, disk_templates):
    """Checks the disk templates for validity.

    """
    if not disk_templates:
      raise errors.ConfigurationError("Instance policy must contain" +
                                      " at least one disk template")
    wrong = frozenset(disk_templates).difference(constants.DISK_TEMPLATES)
    if wrong:
      raise errors.ConfigurationError("Invalid disk template(s) %s" %
                                      utils.CommaJoin(wrong))

  @classmethod
  def CheckParameter(cls, key, value):
    """Checks a parameter.

    Currently we expect all parameters to be float values.

    """
    try:
      float(value)
    except (TypeError, ValueError), err:
      raise errors.ConfigurationError("Invalid value for key" " '%s':"
                                      " '%s', error: %s" % (key, value, err))


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
    "admin_state",
    "nics",
    "disks",
    "disk_template",
    "disks_active",
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
                             "List of names of secondary nodes")

  def _ComputeAllNodes(self):
    """Compute the list of all nodes.

    Since the data is already there (in the drbd disks), keeping it as
    a separate normal attribute is redundant and if not properly
    synchronised can cause problems. Thus it's better to compute it
    dynamically.

    """
    def _Helper(nodes, device):
      """Recursively computes nodes given a top device."""
      if device.dev_type in constants.DTS_DRBD:
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
                       "List of names of all the nodes of the instance")

  def MapLVsByNode(self, lvmap=None, devs=None, node_uuid=None):
    """Provide a mapping of nodes to LVs this instance owns.

    This function figures out what logical volumes should belong on
    which nodes, recursing through a device tree.

    @type lvmap: dict
    @param lvmap: optional dictionary to receive the
        'node' : ['lv', ...] data.
    @type devs: list of L{Disk}
    @param devs: disks to get the LV name for. If None, all disk of this
        instance are used.
    @type node_uuid: string
    @param node_uuid: UUID of the node to get the LV names for. If None, the
        primary node of this instance is used.
    @return: None if lvmap arg is given, otherwise, a dictionary of
        the form { 'node_uuid' : ['volume1', 'volume2', ...], ... };
        volumeN is of the form "vg_name/lv_name", compatible with
        GetVolumeList()

    """
    if node_uuid is None:
      node_uuid = self.primary_node

    if lvmap is None:
      lvmap = {
        node_uuid: [],
        }
      ret = lvmap
    else:
      if not node_uuid in lvmap:
        lvmap[node_uuid] = []
      ret = None

    if not devs:
      devs = self.disks

    for dev in devs:
      if dev.dev_type == constants.DT_PLAIN:
        lvmap[node_uuid].append(dev.logical_id[0] + "/" + dev.logical_id[1])

      elif dev.dev_type in constants.DTS_DRBD:
        if dev.children:
          self.MapLVsByNode(lvmap, dev.children, dev.logical_id[0])
          self.MapLVsByNode(lvmap, dev.children, dev.logical_id[1])

      elif dev.children:
        self.MapLVsByNode(lvmap, dev.children, node_uuid)

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
                                 " 0 to %d" % (idx, len(self.disks) - 1),
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
        nlist = outils.ContainerToDicts(alist)
      else:
        nlist = []
      bo[attr] = nlist
    return bo

  @classmethod
  def FromDict(cls, val):
    """Custom function for instances.

    """
    if "admin_state" not in val:
      if val.get("admin_up", False):
        val["admin_state"] = constants.ADMINST_UP
      else:
        val["admin_state"] = constants.ADMINST_DOWN
    if "admin_up" in val:
      del val["admin_up"]
    obj = super(Instance, cls).FromDict(val)
    obj.nics = outils.ContainerFromDicts(obj.nics, list, NIC)
    obj.disks = outils.ContainerFromDicts(obj.disks, list, Disk)
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
    UpgradeBeParams(self.beparams)
    if self.disks_active is None:
      self.disks_active = self.admin_state == constants.ADMINST_UP


class OS(ConfigObject):
  """Config object representing an operating system.

  @type supported_parameters: list
  @ivar supported_parameters: a list of tuples, name and description,
      containing the supported parameters by this OS

  @type VARIANT_DELIM: string
  @cvar VARIANT_DELIM: the variant delimiter

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

  VARIANT_DELIM = "+"

  @classmethod
  def SplitNameVariant(cls, name):
    """Splits the name into the proper name and variant.

    @param name: the OS (unprocessed) name
    @rtype: list
    @return: a list of two elements; if the original name didn't
        contain a variant, it's returned as an empty string

    """
    nv = name.split(cls.VARIANT_DELIM, 1)
    if len(nv) == 1:
      nv.append("")
    return nv

  @classmethod
  def GetName(cls, name):
    """Returns the proper name of the os (without the variant).

    @param name: the OS (unprocessed) name

    """
    return cls.SplitNameVariant(name)[0]

  @classmethod
  def GetVariant(cls, name):
    """Returns the variant the os (without the base name).

    @param name: the OS (unprocessed) name

    """
    return cls.SplitNameVariant(name)[1]


class ExtStorage(ConfigObject):
  """Config object representing an External Storage Provider.

  """
  __slots__ = [
    "name",
    "path",
    "create_script",
    "remove_script",
    "grow_script",
    "attach_script",
    "detach_script",
    "setinfo_script",
    "verify_script",
    "supported_parameters",
    ]


class NodeHvState(ConfigObject):
  """Hypvervisor state on a node.

  @ivar mem_total: Total amount of memory
  @ivar mem_node: Memory used by, or reserved for, the node itself (not always
    available)
  @ivar mem_hv: Memory used by hypervisor or lost due to instance allocation
    rounding
  @ivar mem_inst: Memory used by instances living on node
  @ivar cpu_total: Total node CPU core count
  @ivar cpu_node: Number of CPU cores reserved for the node itself

  """
  __slots__ = [
    "mem_total",
    "mem_node",
    "mem_hv",
    "mem_inst",
    "cpu_total",
    "cpu_node",
    ] + _TIMESTAMPS


class NodeDiskState(ConfigObject):
  """Disk state on a node.

  """
  __slots__ = [
    "total",
    "reserved",
    "overhead",
    ] + _TIMESTAMPS


class Node(TaggableObject):
  """Config object representing a node.

  @ivar hv_state: Hypervisor state (e.g. number of CPUs)
  @ivar hv_state_static: Hypervisor state overriden by user
  @ivar disk_state: Disk state (e.g. free space)
  @ivar disk_state_static: Disk state overriden by user

  """
  __slots__ = [
    "name",
    "primary_ip",
    "secondary_ip",
    "serial_no",
    "master_candidate",
    "offline",
    "drained",
    "group",
    "master_capable",
    "vm_capable",
    "ndparams",
    "powered",
    "hv_state",
    "hv_state_static",
    "disk_state",
    "disk_state_static",
    ] + _TIMESTAMPS + _UUID

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    # pylint: disable=E0203
    # because these are "defined" via slots, not manually
    if self.master_capable is None:
      self.master_capable = True

    if self.vm_capable is None:
      self.vm_capable = True

    if self.ndparams is None:
      self.ndparams = {}
    # And remove any global parameter
    for key in constants.NDC_GLOBALS:
      if key in self.ndparams:
        logging.warning("Ignoring %s node parameter for node %s",
                        key, self.name)
        del self.ndparams[key]

    if self.powered is None:
      self.powered = True

  def ToDict(self):
    """Custom function for serializing.

    """
    data = super(Node, self).ToDict()

    hv_state = data.get("hv_state", None)
    if hv_state is not None:
      data["hv_state"] = outils.ContainerToDicts(hv_state)

    disk_state = data.get("disk_state", None)
    if disk_state is not None:
      data["disk_state"] = \
        dict((key, outils.ContainerToDicts(value))
             for (key, value) in disk_state.items())

    return data

  @classmethod
  def FromDict(cls, val):
    """Custom function for deserializing.

    """
    obj = super(Node, cls).FromDict(val)

    if obj.hv_state is not None:
      obj.hv_state = \
        outils.ContainerFromDicts(obj.hv_state, dict, NodeHvState)

    if obj.disk_state is not None:
      obj.disk_state = \
        dict((key, outils.ContainerFromDicts(value, dict, NodeDiskState))
             for (key, value) in obj.disk_state.items())

    return obj


class NodeGroup(TaggableObject):
  """Config object representing a node group."""
  __slots__ = [
    "name",
    "members",
    "ndparams",
    "diskparams",
    "ipolicy",
    "serial_no",
    "hv_state_static",
    "disk_state_static",
    "alloc_policy",
    "networks",
    ] + _TIMESTAMPS + _UUID

  def ToDict(self):
    """Custom function for nodegroup.

    This discards the members object, which gets recalculated and is only kept
    in memory.

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

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    if self.ndparams is None:
      self.ndparams = {}

    if self.serial_no is None:
      self.serial_no = 1

    if self.alloc_policy is None:
      self.alloc_policy = constants.ALLOC_POLICY_PREFERRED

    # We only update mtime, and not ctime, since we would not be able
    # to provide a correct value for creation time.
    if self.mtime is None:
      self.mtime = time.time()

    if self.diskparams is None:
      self.diskparams = {}
    if self.ipolicy is None:
      self.ipolicy = MakeEmptyIPolicy()

    if self.networks is None:
      self.networks = {}

  def FillND(self, node):
    """Return filled out ndparams for L{objects.Node}

    @type node: L{objects.Node}
    @param node: A Node object to fill
    @return a copy of the node's ndparams with defaults filled

    """
    return self.SimpleFillND(node.ndparams)

  def SimpleFillND(self, ndparams):
    """Fill a given ndparams dict with defaults.

    @type ndparams: dict
    @param ndparams: the dict to fill
    @rtype: dict
    @return: a copy of the passed in ndparams with missing keys filled
        from the node group defaults

    """
    return FillDict(self.ndparams, ndparams)


class Cluster(TaggableObject):
  """Config object representing the cluster."""
  __slots__ = [
    "serial_no",
    "rsahostkeypub",
    "dsahostkeypub",
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
    "master_netmask",
    "use_external_mip_script",
    "cluster_name",
    "file_storage_dir",
    "shared_file_storage_dir",
    "gluster_storage_dir",
    "enabled_hypervisors",
    "hvparams",
    "ipolicy",
    "os_hvp",
    "beparams",
    "osparams",
    "nicparams",
    "ndparams",
    "diskparams",
    "candidate_pool_size",
    "modify_etc_hosts",
    "modify_ssh_setup",
    "maintain_node_health",
    "uid_pool",
    "default_iallocator",
    "default_iallocator_params",
    "hidden_os",
    "blacklisted_os",
    "primary_ip_family",
    "prealloc_wipe_disks",
    "hv_state_static",
    "disk_state_static",
    "enabled_disk_templates",
    ] + _TIMESTAMPS + _UUID

  def UpgradeConfig(self):
    """Fill defaults for missing configuration values.

    """
    # pylint: disable=E0203
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

    self.ndparams = UpgradeNDParams(self.ndparams)

    self.beparams = UpgradeGroupedParams(self.beparams,
                                         constants.BEC_DEFAULTS)
    for beparams_group in self.beparams:
      UpgradeBeParams(self.beparams[beparams_group])

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

    # default_bridge is no longer used in 2.1. The slot is left there to
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

    if self.default_iallocator_params is None:
      self.default_iallocator_params = {}

    # reserved_lvs added before 2.2
    if self.reserved_lvs is None:
      self.reserved_lvs = []

    # hidden and blacklisted operating systems added before 2.2.1
    if self.hidden_os is None:
      self.hidden_os = []

    if self.blacklisted_os is None:
      self.blacklisted_os = []

    # primary_ip_family added before 2.3
    if self.primary_ip_family is None:
      self.primary_ip_family = AF_INET

    if self.master_netmask is None:
      ipcls = netutils.IPAddress.GetClassFromIpFamily(self.primary_ip_family)
      self.master_netmask = ipcls.iplen

    if self.prealloc_wipe_disks is None:
      self.prealloc_wipe_disks = False

    # shared_file_storage_dir added before 2.5
    if self.shared_file_storage_dir is None:
      self.shared_file_storage_dir = ""

    # gluster_storage_dir added in 2.11
    if self.gluster_storage_dir is None:
      self.gluster_storage_dir = ""

    if self.use_external_mip_script is None:
      self.use_external_mip_script = False

    if self.diskparams:
      self.diskparams = UpgradeDiskParams(self.diskparams)
    else:
      self.diskparams = constants.DISK_DT_DEFAULTS.copy()

    # instance policy added before 2.6
    if self.ipolicy is None:
      self.ipolicy = FillIPolicy(constants.IPOLICY_DEFAULTS, {})
    else:
      # we can either make sure to upgrade the ipolicy always, or only
      # do it in some corner cases (e.g. missing keys); note that this
      # will break any removal of keys from the ipolicy dict
      wrongkeys = frozenset(self.ipolicy.keys()) - constants.IPOLICY_ALL_KEYS
      if wrongkeys:
        # These keys would be silently removed by FillIPolicy()
        msg = ("Cluster instance policy contains spurious keys: %s" %
               utils.CommaJoin(wrongkeys))
        raise errors.ConfigurationError(msg)
      self.ipolicy = FillIPolicy(constants.IPOLICY_DEFAULTS, self.ipolicy)

  @property
  def primary_hypervisor(self):
    """The first hypervisor is the primary.

    Useful, for example, for L{Node}'s hv/disk state.

    """
    return self.enabled_hypervisors[0]

  def ToDict(self):
    """Custom function for cluster.

    """
    mydict = super(Cluster, self).ToDict()

    if self.tcpudp_port_pool is None:
      tcpudp_port_pool = []
    else:
      tcpudp_port_pool = list(self.tcpudp_port_pool)

    mydict["tcpudp_port_pool"] = tcpudp_port_pool

    return mydict

  @classmethod
  def FromDict(cls, val):
    """Custom function for cluster.

    """
    obj = super(Cluster, cls).FromDict(val)

    if obj.tcpudp_port_pool is None:
      obj.tcpudp_port_pool = set()
    elif not isinstance(obj.tcpudp_port_pool, set):
      obj.tcpudp_port_pool = set(obj.tcpudp_port_pool)

    return obj

  def SimpleFillDP(self, diskparams):
    """Fill a given diskparams dict with cluster defaults.

    @param diskparams: The diskparams
    @return: The defaults dict

    """
    return FillDiskParams(self.diskparams, diskparams)

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

  @staticmethod
  def SimpleFillHvState(hv_state):
    """Fill an hv_state sub dict with cluster defaults.

    """
    return FillDict(constants.HVST_DEFAULTS, hv_state)

  @staticmethod
  def SimpleFillDiskState(disk_state):
    """Fill an disk_state sub dict with cluster defaults.

    """
    return FillDict(constants.DS_DEFAULTS, disk_state)

  def FillND(self, node, nodegroup):
    """Return filled out ndparams for L{objects.NodeGroup} and L{objects.Node}

    @type node: L{objects.Node}
    @param node: A Node object to fill
    @type nodegroup: L{objects.NodeGroup}
    @param nodegroup: A Node object to fill
    @return a copy of the node's ndparams with defaults filled

    """
    return self.SimpleFillND(nodegroup.FillND(node))

  def FillNDGroup(self, nodegroup):
    """Return filled out ndparams for just L{objects.NodeGroup}

    @type nodegroup: L{objects.NodeGroup}
    @param nodegroup: A Node object to fill
    @return a copy of the node group's ndparams with defaults filled

    """
    return self.SimpleFillND(nodegroup.SimpleFillND({}))

  def SimpleFillND(self, ndparams):
    """Fill a given ndparams dict with defaults.

    @type ndparams: dict
    @param ndparams: the dict to fill
    @rtype: dict
    @return: a copy of the passed in ndparams with missing keys filled
        from the cluster defaults

    """
    return FillDict(self.ndparams, ndparams)

  def SimpleFillIPolicy(self, ipolicy):
    """ Fill instance policy dict with defaults.

    @type ipolicy: dict
    @param ipolicy: the dict to fill
    @rtype: dict
    @return: a copy of passed ipolicy with missing keys filled from
      the cluster defaults

    """
    return FillIPolicy(self.ipolicy, ipolicy)

  def IsDiskTemplateEnabled(self, disk_template):
    """Checks if a particular disk template is enabled.

    """
    return utils.storage.IsDiskTemplateEnabled(
        disk_template, self.enabled_disk_templates)

  def IsFileStorageEnabled(self):
    """Checks if file storage is enabled.

    """
    return utils.storage.IsFileStorageEnabled(self.enabled_disk_templates)

  def IsSharedFileStorageEnabled(self):
    """Checks if shared file storage is enabled.

    """
    return utils.storage.IsSharedFileStorageEnabled(
        self.enabled_disk_templates)


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
  @ivar ipv6: Whether to use IPv6
  @ivar connect_timeout: Number of seconds for establishing connection

  """
  __slots__ = [
    "key_name",
    "ca_pem",
    "compress",
    "magic",
    "ipv6",
    "connect_timeout",
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


class QueryFieldDefinition(ConfigObject):
  """Object holding a query field definition.

  @ivar name: Field name
  @ivar title: Human-readable title
  @ivar kind: Field type
  @ivar doc: Human-readable description

  """
  __slots__ = [
    "name",
    "title",
    "kind",
    "doc",
    ]


class _QueryResponseBase(ConfigObject):
  __slots__ = [
    "fields",
    ]

  def ToDict(self):
    """Custom function for serializing.

    """
    mydict = super(_QueryResponseBase, self).ToDict()
    mydict["fields"] = outils.ContainerToDicts(mydict["fields"])
    return mydict

  @classmethod
  def FromDict(cls, val):
    """Custom function for de-serializing.

    """
    obj = super(_QueryResponseBase, cls).FromDict(val)
    obj.fields = \
      outils.ContainerFromDicts(obj.fields, list, QueryFieldDefinition)
    return obj


class QueryResponse(_QueryResponseBase):
  """Object holding the response to a query.

  @ivar fields: List of L{QueryFieldDefinition} objects
  @ivar data: Requested data

  """
  __slots__ = [
    "data",
    ]


class QueryFieldsRequest(ConfigObject):
  """Object holding a request for querying available fields.

  """
  __slots__ = [
    "what",
    "fields",
    ]


class QueryFieldsResponse(_QueryResponseBase):
  """Object holding the response to a query for fields.

  @ivar fields: List of L{QueryFieldDefinition} objects

  """
  __slots__ = []


class MigrationStatus(ConfigObject):
  """Object holding the status of a migration.

  """
  __slots__ = [
    "status",
    "transferred_ram",
    "total_ram",
    ]


class InstanceConsole(ConfigObject):
  """Object describing how to access the console of an instance.

  """
  __slots__ = [
    "instance",
    "kind",
    "message",
    "host",
    "port",
    "user",
    "command",
    "display",
    ]

  def Validate(self):
    """Validates contents of this object.

    """
    assert self.kind in constants.CONS_ALL, "Unknown console type"
    assert self.instance, "Missing instance name"
    assert self.message or self.kind in [constants.CONS_SSH,
                                         constants.CONS_SPICE,
                                         constants.CONS_VNC]
    assert self.host or self.kind == constants.CONS_MESSAGE
    assert self.port or self.kind in [constants.CONS_MESSAGE,
                                      constants.CONS_SSH]
    assert self.user or self.kind in [constants.CONS_MESSAGE,
                                      constants.CONS_SPICE,
                                      constants.CONS_VNC]
    assert self.command or self.kind in [constants.CONS_MESSAGE,
                                         constants.CONS_SPICE,
                                         constants.CONS_VNC]
    assert self.display or self.kind in [constants.CONS_MESSAGE,
                                         constants.CONS_SPICE,
                                         constants.CONS_SSH]
    return True


class Network(TaggableObject):
  """Object representing a network definition for ganeti.

  """
  __slots__ = [
    "name",
    "serial_no",
    "mac_prefix",
    "network",
    "network6",
    "gateway",
    "gateway6",
    "reservations",
    "ext_reservations",
    ] + _TIMESTAMPS + _UUID

  def HooksDict(self, prefix=""):
    """Export a dictionary used by hooks with a network's information.

    @type prefix: String
    @param prefix: Prefix to prepend to the dict entries

    """
    result = {
      "%sNETWORK_NAME" % prefix: self.name,
      "%sNETWORK_UUID" % prefix: self.uuid,
      "%sNETWORK_TAGS" % prefix: " ".join(self.GetTags()),
    }
    if self.network:
      result["%sNETWORK_SUBNET" % prefix] = self.network
    if self.gateway:
      result["%sNETWORK_GATEWAY" % prefix] = self.gateway
    if self.network6:
      result["%sNETWORK_SUBNET6" % prefix] = self.network6
    if self.gateway6:
      result["%sNETWORK_GATEWAY6" % prefix] = self.gateway6
    if self.mac_prefix:
      result["%sNETWORK_MAC_PREFIX" % prefix] = self.mac_prefix

    return result

  @classmethod
  def FromDict(cls, val):
    """Custom function for networks.

    Remove deprecated network_type and family.

    """
    if "network_type" in val:
      del val["network_type"]
    if "family" in val:
      del val["family"]
    obj = super(Network, cls).FromDict(val)
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

  @classmethod
  def Loads(cls, data):
    """Load data from a string."""
    buf = StringIO(data)
    cfp = cls()
    cfp.readfp(buf)
    return cfp


class LvmPvInfo(ConfigObject):
  """Information about an LVM physical volume (PV).

  @type name: string
  @ivar name: name of the PV
  @type vg_name: string
  @ivar vg_name: name of the volume group containing the PV
  @type size: float
  @ivar size: size of the PV in MiB
  @type free: float
  @ivar free: free space in the PV, in MiB
  @type attributes: string
  @ivar attributes: PV attributes
  @type lv_list: list of strings
  @ivar lv_list: names of the LVs hosted on the PV
  """
  __slots__ = [
    "name",
    "vg_name",
    "size",
    "free",
    "attributes",
    "lv_list"
    ]

  def IsEmpty(self):
    """Is this PV empty?

    """
    return self.size <= (self.free + 1)

  def IsAllocatable(self):
    """Is this PV allocatable?

    """
    return ("a" in self.attributes)
