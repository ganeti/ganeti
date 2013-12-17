#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
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


"""QA configuration.

"""

import os

from ganeti import constants
from ganeti import utils
from ganeti import serializer
from ganeti import compat
from ganeti import ht

import qa_error


_INSTANCE_CHECK_KEY = "instance-check"
_ENABLED_HV_KEY = "enabled-hypervisors"
_VCLUSTER_MASTER_KEY = "vcluster-master"
_VCLUSTER_BASEDIR_KEY = "vcluster-basedir"
_ENABLED_DISK_TEMPLATES_KEY = "enabled-disk-templates"

# The path of an optional JSON Patch file (as per RFC6902) that modifies QA's
# configuration.
_PATCH_JSON = os.path.join(os.path.dirname(__file__), "qa-patch.json")

#: QA configuration (L{_QaConfig})
_config = None


class _QaInstance(object):
  __slots__ = [
    "name",
    "nicmac",
    "_used",
    "_disk_template",
    ]

  def __init__(self, name, nicmac):
    """Initializes instances of this class.

    """
    self.name = name
    self.nicmac = nicmac
    self._used = None
    self._disk_template = None

  @classmethod
  def FromDict(cls, data):
    """Creates instance object from JSON dictionary.

    """
    nicmac = []

    macaddr = data.get("nic.mac/0")
    if macaddr:
      nicmac.append(macaddr)

    return cls(name=data["name"], nicmac=nicmac)

  def __repr__(self):
    status = [
      "%s.%s" % (self.__class__.__module__, self.__class__.__name__),
      "name=%s" % self.name,
      "nicmac=%s" % self.nicmac,
      "used=%s" % self._used,
      "disk_template=%s" % self._disk_template,
      ]

    return "<%s at %#x>" % (" ".join(status), id(self))

  def Use(self):
    """Marks instance as being in use.

    """
    assert not self._used
    assert self._disk_template is None

    self._used = True

  def Release(self):
    """Releases instance and makes it available again.

    """
    assert self._used, \
      ("Instance '%s' was never acquired or released more than once" %
       self.name)

    self._used = False
    self._disk_template = None

  def GetNicMacAddr(self, idx, default):
    """Returns MAC address for NIC.

    @type idx: int
    @param idx: NIC index
    @param default: Default value

    """
    if len(self.nicmac) > idx:
      return self.nicmac[idx]
    else:
      return default

  def SetDiskTemplate(self, template):
    """Set the disk template.

    """
    assert template in constants.DISK_TEMPLATES

    self._disk_template = template

  @property
  def used(self):
    """Returns boolean denoting whether instance is in use.

    """
    return self._used

  @property
  def disk_template(self):
    """Returns the current disk template.

    """
    return self._disk_template


class _QaNode(object):
  __slots__ = [
    "primary",
    "secondary",
    "_added",
    "_use_count",
    ]

  def __init__(self, primary, secondary):
    """Initializes instances of this class.

    """
    self.primary = primary
    self.secondary = secondary
    self._added = False
    self._use_count = 0

  @classmethod
  def FromDict(cls, data):
    """Creates node object from JSON dictionary.

    """
    return cls(primary=data["primary"], secondary=data.get("secondary"))

  def __repr__(self):
    status = [
      "%s.%s" % (self.__class__.__module__, self.__class__.__name__),
      "primary=%s" % self.primary,
      "secondary=%s" % self.secondary,
      "added=%s" % self._added,
      "use_count=%s" % self._use_count,
      ]

    return "<%s at %#x>" % (" ".join(status), id(self))

  def Use(self):
    """Marks a node as being in use.

    """
    assert self._use_count >= 0

    self._use_count += 1

    return self

  def Release(self):
    """Release a node (opposite of L{Use}).

    """
    assert self.use_count > 0

    self._use_count -= 1

  def MarkAdded(self):
    """Marks node as having been added to a cluster.

    """
    assert not self._added
    self._added = True

  def MarkRemoved(self):
    """Marks node as having been removed from a cluster.

    """
    assert self._added
    self._added = False

  @property
  def added(self):
    """Returns whether a node is part of a cluster.

    """
    return self._added

  @property
  def use_count(self):
    """Returns number of current uses (controlled by L{Use} and L{Release}).

    """
    return self._use_count


_RESOURCE_CONVERTER = {
  "instances": _QaInstance.FromDict,
  "nodes": _QaNode.FromDict,
  }


def _ConvertResources((key, value)):
  """Converts cluster resources in configuration to Python objects.

  """
  fn = _RESOURCE_CONVERTER.get(key, None)
  if fn:
    return (key, map(fn, value))
  else:
    return (key, value)


class _QaConfig(object):
  def __init__(self, data):
    """Initializes instances of this class.

    """
    self._data = data

    #: Cluster-wide run-time value of the exclusive storage flag
    self._exclusive_storage = None

  @classmethod
  def Load(cls, filename):
    """Loads a configuration file and produces a configuration object.

    @type filename: string
    @param filename: Path to configuration file
    @rtype: L{_QaConfig}

    """
    data = serializer.LoadJson(utils.ReadFile(filename))

    # Patch the document using JSON Patch (RFC6902) in file _PATCH_JSON, if
    # available
    try:
      patch = serializer.LoadJson(utils.ReadFile(_PATCH_JSON))
      if patch:
        mod = __import__("jsonpatch", fromlist=[])
        data = mod.apply_patch(data, patch)
    except IOError:
      pass
    except ImportError:
      raise qa_error.Error("If you want to use the QA JSON patching feature,"
                           " you need to install Python modules"
                           " 'jsonpatch' and 'jsonpointer'.")

    result = cls(dict(map(_ConvertResources,
                          data.items()))) # pylint: disable=E1103
    result.Validate()

    return result

  def Validate(self):
    """Validates loaded configuration data.

    """
    if not self.get("name"):
      raise qa_error.Error("Cluster name is required")

    if not self.get("nodes"):
      raise qa_error.Error("Need at least one node")

    if not self.get("instances"):
      raise qa_error.Error("Need at least one instance")

    disks = self.GetDiskOptions()
    if disks is None:
      raise qa_error.Error("Config option 'disks' must exist")
    else:
      for d in disks:
        if d.get("size") is None or d.get("growth") is None:
          raise qa_error.Error("Config options `size` and `growth` must exist"
                               " for all `disks` items")
    check = self.GetInstanceCheckScript()
    if check:
      try:
        os.stat(check)
      except EnvironmentError, err:
        raise qa_error.Error("Can't find instance check script '%s': %s" %
                             (check, err))

    enabled_hv = frozenset(self.GetEnabledHypervisors())
    if not enabled_hv:
      raise qa_error.Error("No hypervisor is enabled")

    difference = enabled_hv - constants.HYPER_TYPES
    if difference:
      raise qa_error.Error("Unknown hypervisor(s) enabled: %s" %
                           utils.CommaJoin(difference))

    (vc_master, vc_basedir) = self.GetVclusterSettings()
    if bool(vc_master) != bool(vc_basedir):
      raise qa_error.Error("All or none of the config options '%s' and '%s'"
                           " must be set" %
                           (_VCLUSTER_MASTER_KEY, _VCLUSTER_BASEDIR_KEY))

    if vc_basedir and not utils.IsNormAbsPath(vc_basedir):
      raise qa_error.Error("Path given in option '%s' must be absolute and"
                           " normalized" % _VCLUSTER_BASEDIR_KEY)

  def __getitem__(self, name):
    """Returns configuration value.

    @type name: string
    @param name: Name of configuration entry

    """
    return self._data[name]

  def __setitem__(self, key, value):
    """Sets a configuration value.

    """
    self._data[key] = value

  def __delitem__(self, key):
    """Deletes a value from the configuration.

    """
    del(self._data[key])

  def __len__(self):
    """Return the number of configuration items.

    """
    return len(self._data)

  def get(self, name, default=None):
    """Returns configuration value.

    @type name: string
    @param name: Name of configuration entry
    @param default: Default value

    """
    return self._data.get(name, default)

  def GetMasterNode(self):
    """Returns the default master node for the cluster.

    """
    return self["nodes"][0]

  def GetInstanceCheckScript(self):
    """Returns path to instance check script or C{None}.

    """
    return self._data.get(_INSTANCE_CHECK_KEY, None)

  def GetEnabledHypervisors(self):
    """Returns list of enabled hypervisors.

    @rtype: list

    """
    return self._GetStringListParameter(
      _ENABLED_HV_KEY,
      [constants.DEFAULT_ENABLED_HYPERVISOR])

  def GetDefaultHypervisor(self):
    """Returns the default hypervisor to be used.

    """
    return self.GetEnabledHypervisors()[0]

  def GetEnabledDiskTemplates(self):
    """Returns the list of enabled disk templates.

    @rtype: list

    """
    return self._GetStringListParameter(
      _ENABLED_DISK_TEMPLATES_KEY,
      constants.DEFAULT_ENABLED_DISK_TEMPLATES)

  def GetEnabledStorageTypes(self):
    """Returns the list of enabled storage types.

    @rtype: list
    @returns: the list of storage types enabled for QA

    """
    enabled_disk_templates = self.GetEnabledDiskTemplates()
    enabled_storage_types = list(
        set([constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[dt]
             for dt in enabled_disk_templates]))
    # Storage type 'lvm-pv' cannot be activated via a disk template,
    # therefore we add it if 'lvm-vg' is present.
    if constants.ST_LVM_VG in enabled_storage_types:
      enabled_storage_types.append(constants.ST_LVM_PV)
    return enabled_storage_types

  def GetDefaultDiskTemplate(self):
    """Returns the default disk template to be used.

    """
    return self.GetEnabledDiskTemplates()[0]

  def _GetStringListParameter(self, key, default_values):
    """Retrieves a parameter's value that is supposed to be a list of strings.

    @rtype: list

    """
    try:
      value = self._data[key]
    except KeyError:
      return default_values
    else:
      if value is None:
        return []
      elif isinstance(value, basestring):
        return value.split(",")
      else:
        return value

  def SetExclusiveStorage(self, value):
    """Set the expected value of the C{exclusive_storage} flag for the cluster.

    """
    self._exclusive_storage = bool(value)

  def GetExclusiveStorage(self):
    """Get the expected value of the C{exclusive_storage} flag for the cluster.

    """
    value = self._exclusive_storage
    assert value is not None
    return value

  def IsTemplateSupported(self, templ):
    """Is the given disk template supported by the current configuration?

    """
    enabled = templ in self.GetEnabledDiskTemplates()
    return enabled and (not self.GetExclusiveStorage() or
                        templ in constants.DTS_EXCL_STORAGE)

  def IsStorageTypeSupported(self, storage_type):
    """Is the given storage type supported by the current configuration?

    This is determined by looking if at least one of the disk templates
    which is associated with the storage type is enabled in the configuration.

    """
    enabled_disk_templates = self.GetEnabledDiskTemplates()
    if storage_type == constants.ST_LVM_PV:
      disk_templates = utils.GetDiskTemplatesOfStorageTypes(constants.ST_LVM_VG)
    else:
      disk_templates = utils.GetDiskTemplatesOfStorageTypes(storage_type)
    return bool(set(enabled_disk_templates).intersection(set(disk_templates)))

  def AreSpindlesSupported(self):
    """Are spindles supported by the current configuration?

    """
    return self.GetExclusiveStorage()

  def GetVclusterSettings(self):
    """Returns settings for virtual cluster.

    """
    master = self.get(_VCLUSTER_MASTER_KEY)
    basedir = self.get(_VCLUSTER_BASEDIR_KEY)

    return (master, basedir)

  def GetDiskOptions(self):
    """Return options for the disks of the instances.

    Get 'disks' parameter from the configuration data. If 'disks' is missing,
    try to create it from the legacy 'disk' and 'disk-growth' parameters.

    """
    try:
      return self._data["disks"]
    except KeyError:
      pass

    # Legacy interface
    sizes = self._data.get("disk")
    growths = self._data.get("disk-growth")
    if sizes or growths:
      if (sizes is None or growths is None or len(sizes) != len(growths)):
        raise qa_error.Error("Config options 'disk' and 'disk-growth' must"
                             " exist and have the same number of items")
      disks = []
      for (size, growth) in zip(sizes, growths):
        disks.append({"size": size, "growth": growth})
      return disks
    else:
      return None


def Load(path):
  """Loads the passed configuration file.

  """
  global _config # pylint: disable=W0603

  _config = _QaConfig.Load(path)


def GetConfig():
  """Returns the configuration object.

  """
  if _config is None:
    raise RuntimeError("Configuration not yet loaded")

  return _config


def get(name, default=None):
  """Wrapper for L{_QaConfig.get}.

  """
  return GetConfig().get(name, default=default)


class Either:
  def __init__(self, tests):
    """Initializes this class.

    @type tests: list or string
    @param tests: List of test names
    @see: L{TestEnabled} for details

    """
    self.tests = tests


def _MakeSequence(value):
  """Make sequence of single argument.

  If the single argument is not already a list or tuple, a list with the
  argument as a single item is returned.

  """
  if isinstance(value, (list, tuple)):
    return value
  else:
    return [value]


def _TestEnabledInner(check_fn, names, fn):
  """Evaluate test conditions.

  @type check_fn: callable
  @param check_fn: Callback to check whether a test is enabled
  @type names: sequence or string
  @param names: Test name(s)
  @type fn: callable
  @param fn: Aggregation function
  @rtype: bool
  @return: Whether test is enabled

  """
  names = _MakeSequence(names)

  result = []

  for name in names:
    if isinstance(name, Either):
      value = _TestEnabledInner(check_fn, name.tests, compat.any)
    elif isinstance(name, (list, tuple)):
      value = _TestEnabledInner(check_fn, name, compat.all)
    elif callable(name):
      value = name()
    else:
      value = check_fn(name)

    result.append(value)

  return fn(result)


def TestEnabled(tests, _cfg=None):
  """Returns True if the given tests are enabled.

  @param tests: A single test as a string, or a list of tests to check; can
    contain L{Either} for OR conditions, AND is default

  """
  if _cfg is None:
    cfg = GetConfig()
  else:
    cfg = _cfg

  # Get settings for all tests
  cfg_tests = cfg.get("tests", {})

  # Get default setting
  default = cfg_tests.get("default", True)

  return _TestEnabledInner(lambda name: cfg_tests.get(name, default),
                           tests, compat.all)


def GetInstanceCheckScript(*args):
  """Wrapper for L{_QaConfig.GetInstanceCheckScript}.

  """
  return GetConfig().GetInstanceCheckScript(*args)


def GetEnabledHypervisors(*args):
  """Wrapper for L{_QaConfig.GetEnabledHypervisors}.

  """
  return GetConfig().GetEnabledHypervisors(*args)


def GetDefaultHypervisor(*args):
  """Wrapper for L{_QaConfig.GetDefaultHypervisor}.

  """
  return GetConfig().GetDefaultHypervisor(*args)


def GetEnabledDiskTemplates(*args):
  """Wrapper for L{_QaConfig.GetEnabledDiskTemplates}.

  """
  return GetConfig().GetEnabledDiskTemplates(*args)


def GetEnabledStorageTypes(*args):
  """Wrapper for L{_QaConfig.GetEnabledStorageTypes}.

  """
  return GetConfig().GetEnabledStorageTypes(*args)


def GetDefaultDiskTemplate(*args):
  """Wrapper for L{_QaConfig.GetDefaultDiskTemplate}.

  """
  return GetConfig().GetDefaultDiskTemplate(*args)


def GetMasterNode():
  """Wrapper for L{_QaConfig.GetMasterNode}.

  """
  return GetConfig().GetMasterNode()


def AcquireInstance(_cfg=None):
  """Returns an instance which isn't in use.

  """
  if _cfg is None:
    cfg = GetConfig()
  else:
    cfg = _cfg

  # Filter out unwanted instances
  instances = filter(lambda inst: not inst.used, cfg["instances"])

  if not instances:
    raise qa_error.OutOfInstancesError("No instances left")

  instance = instances[0]
  instance.Use()

  return instance


def SetExclusiveStorage(value):
  """Wrapper for L{_QaConfig.SetExclusiveStorage}.

  """
  return GetConfig().SetExclusiveStorage(value)


def GetExclusiveStorage():
  """Wrapper for L{_QaConfig.GetExclusiveStorage}.

  """
  return GetConfig().GetExclusiveStorage()


def IsTemplateSupported(templ):
  """Wrapper for L{_QaConfig.IsTemplateSupported}.

  """
  return GetConfig().IsTemplateSupported(templ)


def IsStorageTypeSupported(storage_type):
  """Wrapper for L{_QaConfig.IsTemplateSupported}.

  """
  return GetConfig().IsStorageTypeSupported(storage_type)


def AreSpindlesSupported():
  """Wrapper for L{_QaConfig.AreSpindlesSupported}.

  """
  return GetConfig().AreSpindlesSupported()


def _NodeSortKey(node):
  """Returns sort key for a node.

  @type node: L{_QaNode}

  """
  return (node.use_count, utils.NiceSortKey(node.primary))


def AcquireNode(exclude=None, _cfg=None):
  """Returns the least used node.

  """
  if _cfg is None:
    cfg = GetConfig()
  else:
    cfg = _cfg

  master = cfg.GetMasterNode()

  # Filter out unwanted nodes
  # TODO: Maybe combine filters
  if exclude is None:
    nodes = cfg["nodes"][:]
  elif isinstance(exclude, (list, tuple)):
    nodes = filter(lambda node: node not in exclude, cfg["nodes"])
  else:
    nodes = filter(lambda node: node != exclude, cfg["nodes"])

  nodes = filter(lambda node: node.added or node == master, nodes)

  if not nodes:
    raise qa_error.OutOfNodesError("No nodes left")

  # Return node with least number of uses
  return sorted(nodes, key=_NodeSortKey)[0].Use()


class AcquireManyNodesCtx(object):
  """Returns the least used nodes for use with a `with` block

  """
  def __init__(self, num, exclude=None, cfg=None):
    self._num = num
    self._exclude = exclude
    self._cfg = cfg

  def __enter__(self):
    self._nodes = AcquireManyNodes(self._num, exclude=self._exclude,
                                   cfg=self._cfg)
    return self._nodes

  def __exit__(self, exc_type, exc_value, exc_tb):
    ReleaseManyNodes(self._nodes)


def AcquireManyNodes(num, exclude=None, cfg=None):
  """Return the least used nodes.

  @type num: int
  @param num: Number of nodes; can be 0.
  @type exclude: list of nodes or C{None}
  @param exclude: nodes to be excluded from the choice
  @rtype: list of nodes
  @return: C{num} different nodes

  """
  nodes = []
  if exclude is None:
    exclude = []
  elif isinstance(exclude, (list, tuple)):
    # Don't modify the incoming argument
    exclude = list(exclude)
  else:
    exclude = [exclude]

  try:
    for _ in range(0, num):
      n = AcquireNode(exclude=exclude, _cfg=cfg)
      nodes.append(n)
      exclude.append(n)
  except qa_error.OutOfNodesError:
    ReleaseManyNodes(nodes)
    raise
  return nodes


def ReleaseManyNodes(nodes):
  for node in nodes:
    node.Release()


def GetVclusterSettings():
  """Wrapper for L{_QaConfig.GetVclusterSettings}.

  """
  return GetConfig().GetVclusterSettings()


def UseVirtualCluster(_cfg=None):
  """Returns whether a virtual cluster is used.

  @rtype: bool

  """
  if _cfg is None:
    cfg = GetConfig()
  else:
    cfg = _cfg

  (master, _) = cfg.GetVclusterSettings()

  return bool(master)


@ht.WithDesc("No virtual cluster")
def NoVirtualCluster():
  """Used to disable tests for virtual clusters.

  """
  return not UseVirtualCluster()


def GetDiskOptions():
  """Wrapper for L{_QaConfig.GetDiskOptions}.

  """
  return GetConfig().GetDiskOptions()
