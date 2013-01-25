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

import qa_error


_INSTANCE_CHECK_KEY = "instance-check"
_ENABLED_HV_KEY = "enabled-hypervisors"
# Key to store the cluster-wide run-time value of the exclusive storage flag
_EXCLUSIVE_STORAGE_KEY = "_exclusive_storage"


cfg = {}
options = None


def Load(path):
  """Loads the passed configuration file.

  """
  global cfg # pylint: disable=W0603

  cfg = serializer.LoadJson(utils.ReadFile(path))

  Validate()


def Validate():
  if len(cfg["nodes"]) < 1:
    raise qa_error.Error("Need at least one node")
  if len(cfg["instances"]) < 1:
    raise qa_error.Error("Need at least one instance")
  if len(cfg["disk"]) != len(cfg["disk-growth"]):
    raise qa_error.Error("Config options 'disk' and 'disk-growth' must have"
                         " the same number of items")

  check = GetInstanceCheckScript()
  if check:
    try:
      os.stat(check)
    except EnvironmentError, err:
      raise qa_error.Error("Can't find instance check script '%s': %s" %
                           (check, err))

  enabled_hv = frozenset(GetEnabledHypervisors())
  if not enabled_hv:
    raise qa_error.Error("No hypervisor is enabled")

  difference = enabled_hv - constants.HYPER_TYPES
  if difference:
    raise qa_error.Error("Unknown hypervisor(s) enabled: %s" %
                         utils.CommaJoin(difference))


def get(name, default=None):
  return cfg.get(name, default)


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
    _cfg = cfg

  # Get settings for all tests
  cfg_tests = _cfg.get("tests", {})

  # Get default setting
  default = cfg_tests.get("default", True)

  return _TestEnabledInner(lambda name: cfg_tests.get(name, default),
                           tests, compat.all)


def GetInstanceCheckScript():
  """Returns path to instance check script or C{None}.

  """
  return cfg.get(_INSTANCE_CHECK_KEY, None)


def GetEnabledHypervisors():
  """Returns list of enabled hypervisors.

  @rtype: list

  """
  try:
    value = cfg[_ENABLED_HV_KEY]
  except KeyError:
    return [constants.DEFAULT_ENABLED_HYPERVISOR]
  else:
    if isinstance(value, basestring):
      # The configuration key ("enabled-hypervisors") implies there can be
      # multiple values. Multiple hypervisors are comma-separated on the
      # command line option to "gnt-cluster init", so we need to handle them
      # equally here.
      return value.split(",")
    else:
      return value


def GetDefaultHypervisor():
  """Returns the default hypervisor to be used.

  """
  return GetEnabledHypervisors()[0]


def GetInstanceNicMac(inst, default=None):
  """Returns MAC address for instance's network interface.

  """
  return inst.get("nic.mac/0", default)


def GetMasterNode():
  return cfg["nodes"][0]


def AcquireInstance():
  """Returns an instance which isn't in use.

  """
  # Filter out unwanted instances
  tmp_flt = lambda inst: not inst.get("_used", False)
  instances = filter(tmp_flt, cfg["instances"])
  del tmp_flt

  if len(instances) == 0:
    raise qa_error.OutOfInstancesError("No instances left")

  inst = instances[0]
  inst["_used"] = True
  inst["_template"] = None
  return inst


def ReleaseInstance(inst):
  inst["_used"] = False


def GetInstanceTemplate(inst):
  """Return the disk template of an instance.

  """
  templ = inst["_template"]
  assert templ is not None
  return templ


def SetInstanceTemplate(inst, template):
  """Set the disk template for an instance.

  """
  inst["_template"] = template


def SetExclusiveStorage(value):
  """Set the expected value of the exclusive_storage flag for the cluster.

  """
  cfg[_EXCLUSIVE_STORAGE_KEY] = bool(value)


def GetExclusiveStorage():
  """Get the expected value of the exclusive_storage flag for the cluster.

  """
  val = cfg.get(_EXCLUSIVE_STORAGE_KEY)
  assert val is not None
  return val


def AcquireNode(exclude=None):
  """Returns the least used node.

  """
  master = GetMasterNode()

  # Filter out unwanted nodes
  # TODO: Maybe combine filters
  if exclude is None:
    nodes = cfg["nodes"][:]
  elif isinstance(exclude, (list, tuple)):
    nodes = filter(lambda node: node not in exclude, cfg["nodes"])
  else:
    nodes = filter(lambda node: node != exclude, cfg["nodes"])

  tmp_flt = lambda node: node.get("_added", False) or node == master
  nodes = filter(tmp_flt, nodes)
  del tmp_flt

  if len(nodes) == 0:
    raise qa_error.OutOfNodesError("No nodes left")

  # Get node with least number of uses
  def compare(a, b):
    result = cmp(a.get("_count", 0), b.get("_count", 0))
    if result == 0:
      result = cmp(a["primary"], b["primary"])
    return result

  nodes.sort(cmp=compare)

  node = nodes[0]
  node["_count"] = node.get("_count", 0) + 1
  return node


def AcquireManyNodes(num, exclude=None):
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
      n = AcquireNode(exclude=exclude)
      nodes.append(n)
      exclude.append(n)
  except qa_error.OutOfNodesError:
    ReleaseManyNodes(nodes)
    raise
  return nodes


def ReleaseNode(node):
  node["_count"] = node.get("_count", 0) - 1


def ReleaseManyNodes(nodes):
  for n in nodes:
    ReleaseNode(n)
