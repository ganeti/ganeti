#
#

# Copyright (C) 2010 Google Inc.
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


"""Module for query operations"""

import logging
import operator
import re

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import compat
from ganeti import objects
from ganeti import ht


(NQ_CONFIG,
 NQ_INST,
 NQ_LIVE,
 NQ_GROUP) = range(1, 5)

(IQ_CONFIG,
 IQ_LIVE,
 IQ_DISKUSAGE) = range(100, 103)

(LQ_MODE,
 LQ_OWNER,
 LQ_PENDING) = range(10, 13)

FIELD_NAME_RE = re.compile(r"^[a-z0-9/._]+$")
TITLE_RE = re.compile(r"^[^\s]+$")

#: Verification function for each field type
_VERIFY_FN = {
  constants.QFT_UNKNOWN: ht.TNone,
  constants.QFT_TEXT: ht.TString,
  constants.QFT_BOOL: ht.TBool,
  constants.QFT_NUMBER: ht.TInt,
  constants.QFT_UNIT: ht.TInt,
  constants.QFT_TIMESTAMP: ht.TOr(ht.TInt, ht.TFloat),
  constants.QFT_OTHER: lambda _: True,
  }


def _GetUnknownField(ctx, item): # pylint: disable-msg=W0613
  """Gets the contents of an unknown field.

  """
  return (constants.QRFS_UNKNOWN, None)


def _GetQueryFields(fielddefs, selected):
  """Calculates the internal list of selected fields.

  Unknown fields are returned as L{constants.QFT_UNKNOWN}.

  @type fielddefs: dict
  @param fielddefs: Field definitions
  @type selected: list of strings
  @param selected: List of selected fields

  """
  result = []

  for name in selected:
    try:
      fdef = fielddefs[name]
    except KeyError:
      fdef = (_MakeField(name, name, constants.QFT_UNKNOWN),
              None, _GetUnknownField)

    assert len(fdef) == 3

    result.append(fdef)

  return result


def GetAllFields(fielddefs):
  """Extract L{objects.QueryFieldDefinition} from field definitions.

  @rtype: list of L{objects.QueryFieldDefinition}

  """
  return [fdef for (fdef, _, _) in fielddefs]


class Query:
  def __init__(self, fieldlist, selected):
    """Initializes this class.

    The field definition is a dictionary with the field's name as a key and a
    tuple containing, in order, the field definition object
    (L{objects.QueryFieldDefinition}, the data kind to help calling code
    collect data and a retrieval function. The retrieval function is called
    with two parameters, in order, the data container and the item in container
    (see L{Query.Query}).

    Users of this class can call L{RequestedData} before preparing the data
    container to determine what data is needed.

    @type fieldlist: dictionary
    @param fieldlist: Field definitions
    @type selected: list of strings
    @param selected: List of selected fields

    """
    self._fields = _GetQueryFields(fieldlist, selected)

  def RequestedData(self):
    """Gets requested kinds of data.

    @rtype: frozenset

    """
    return frozenset(datakind
                     for (_, datakind, _) in self._fields
                     if datakind is not None)

  def GetFields(self):
    """Returns the list of fields for this query.

    Includes unknown fields.

    @rtype: List of L{objects.QueryFieldDefinition}

    """
    return GetAllFields(self._fields)

  def Query(self, ctx):
    """Execute a query.

    @param ctx: Data container passed to field retrieval functions, must
      support iteration using C{__iter__}

    """
    result = [[fn(ctx, item) for (_, _, fn) in self._fields]
              for item in ctx]

    # Verify result
    if __debug__:
      for (idx, row) in enumerate(result):
        assert _VerifyResultRow(self._fields, row), \
               ("Inconsistent result for fields %s in row %s: %r" %
                (GetAllFields(self._fields), idx, row))

    return result

  def OldStyleQuery(self, ctx):
    """Query with "old" query result format.

    See L{Query.Query} for arguments.

    """
    unknown = set(fdef.name
                  for (fdef, _, _) in self._fields
                  if fdef.kind == constants.QFT_UNKNOWN)
    if unknown:
      raise errors.OpPrereqError("Unknown output fields selected: %s" %
                                 (utils.CommaJoin(unknown), ),
                                 errors.ECODE_INVAL)

    return [[value for (_, value) in row]
            for row in self.Query(ctx)]


def _VerifyResultRow(fields, row):
  """Verifies the contents of a query result row.

  @type fields: list
  @param fields: Field definitions for result
  @type row: list of tuples
  @param row: Row data

  """
  return (len(row) == len(fields) and
          compat.all((status == constants.QRFS_NORMAL and
                      _VERIFY_FN[fdef.kind](value)) or
                     # Value for an abnormal status must be None
                     (status != constants.QRFS_NORMAL and value is None)
                     for ((status, value), (fdef, _, _)) in zip(row, fields)))


def _PrepareFieldList(fields):
  """Prepares field list for use by L{Query}.

  Converts the list to a dictionary and does some verification.

  @type fields: list of tuples; (L{objects.QueryFieldDefinition}, data kind,
    retrieval function)
  @param fields: List of fields
  @rtype: dict
  @return: Field dictionary for L{Query}

  """
  if __debug__:
    duplicates = utils.FindDuplicates(fdef.title.lower()
                                      for (fdef, _, _) in fields)
    assert not duplicates, "Duplicate title(s) found: %r" % duplicates

  result = {}

  for field in fields:
    (fdef, _, fn) = field

    assert fdef.name and fdef.title, "Name and title are required"
    assert FIELD_NAME_RE.match(fdef.name)
    assert TITLE_RE.match(fdef.title)
    assert callable(fn)
    assert fdef.name not in result, \
           "Duplicate field name '%s' found" % fdef.name

    result[fdef.name] = field

  assert len(result) == len(fields)
  assert compat.all(name == fdef.name
                    for (name, (fdef, _, _)) in result.items())

  return result


def GetQueryResponse(query, ctx):
  """Prepares the response for a query.

  @type query: L{Query}
  @param ctx: Data container, see L{Query.Query}

  """
  return objects.QueryResponse(data=query.Query(ctx),
                               fields=query.GetFields()).ToDict()


def QueryFields(fielddefs, selected):
  """Returns list of available fields.

  @type fielddefs: dict
  @param fielddefs: Field definitions
  @type selected: list of strings
  @param selected: List of selected fields
  @return: List of L{objects.QueryFieldDefinition}

  """
  if selected is None:
    # Client requests all fields, sort by name
    fdefs = utils.NiceSort(GetAllFields(fielddefs.values()),
                           key=operator.attrgetter("name"))
  else:
    # Keep order as requested by client
    fdefs = Query(fielddefs, selected).GetFields()

  return objects.QueryFieldsResponse(fields=fdefs).ToDict()


def _MakeField(name, title, kind):
  """Wrapper for creating L{objects.QueryFieldDefinition} instances.

  @param name: Field name as a regular expression
  @param title: Human-readable title
  @param kind: Field type

  """
  return objects.QueryFieldDefinition(name=name, title=title, kind=kind)


def _GetNodeRole(node, master_name):
  """Determine node role.

  @type node: L{objects.Node}
  @param node: Node object
  @type master_name: string
  @param master_name: Master node name

  """
  if node.name == master_name:
    return "M"
  elif node.master_candidate:
    return "C"
  elif node.drained:
    return "D"
  elif node.offline:
    return "O"
  else:
    return "R"


def _GetItemAttr(attr):
  """Returns a field function to return an attribute of the item.

  @param attr: Attribute name

  """
  getter = operator.attrgetter(attr)
  return lambda _, item: (constants.QRFS_NORMAL, getter(item))


def _GetItemTimestamp(getter):
  """Returns function for getting timestamp of item.

  @type getter: callable
  @param getter: Function to retrieve timestamp attribute

  """
  def fn(_, item):
    """Returns a timestamp of item.

    """
    timestamp = getter(item)
    if timestamp is None:
      # Old configs might not have all timestamps
      return (constants.QRFS_UNAVAIL, None)
    else:
      return (constants.QRFS_NORMAL, timestamp)

  return fn


def _GetItemTimestampFields(datatype):
  """Returns common timestamp fields.

  @param datatype: Field data type for use by L{Query.RequestedData}

  """
  return [
    (_MakeField("ctime", "CTime", constants.QFT_TIMESTAMP), datatype,
     _GetItemTimestamp(operator.attrgetter("ctime"))),
    (_MakeField("mtime", "MTime", constants.QFT_TIMESTAMP), datatype,
     _GetItemTimestamp(operator.attrgetter("mtime"))),
    ]


class NodeQueryData:
  """Data container for node data queries.

  """
  def __init__(self, nodes, live_data, master_name, node_to_primary,
               node_to_secondary, groups):
    """Initializes this class.

    """
    self.nodes = nodes
    self.live_data = live_data
    self.master_name = master_name
    self.node_to_primary = node_to_primary
    self.node_to_secondary = node_to_secondary
    self.groups = groups

    # Used for individual rows
    self.curlive_data = None

  def __iter__(self):
    """Iterate over all nodes.

    This function has side-effects and only one instance of the resulting
    generator should be used at a time.

    """
    for node in self.nodes:
      if self.live_data:
        self.curlive_data = self.live_data.get(node.name, None)
      else:
        self.curlive_data = None
      yield node


#: Fields that are direct attributes of an L{objects.Node} object
_NODE_SIMPLE_FIELDS = {
  "drained": ("Drained", constants.QFT_BOOL),
  "master_candidate": ("MasterC", constants.QFT_BOOL),
  "master_capable": ("MasterCapable", constants.QFT_BOOL),
  "name": ("Node", constants.QFT_TEXT),
  "offline": ("Offline", constants.QFT_BOOL),
  "serial_no": ("SerialNo", constants.QFT_NUMBER),
  "uuid": ("UUID", constants.QFT_TEXT),
  "vm_capable": ("VMCapable", constants.QFT_BOOL),
  }


#: Fields requiring talking to the node
_NODE_LIVE_FIELDS = {
  "bootid": ("BootID", constants.QFT_TEXT, "bootid"),
  "cnodes": ("CNodes", constants.QFT_NUMBER, "cpu_nodes"),
  "csockets": ("CSockets", constants.QFT_NUMBER, "cpu_sockets"),
  "ctotal": ("CTotal", constants.QFT_NUMBER, "cpu_total"),
  "dfree": ("DFree", constants.QFT_UNIT, "vg_free"),
  "dtotal": ("DTotal", constants.QFT_UNIT, "vg_size"),
  "mfree": ("MFree", constants.QFT_UNIT, "memory_free"),
  "mnode": ("MNode", constants.QFT_UNIT, "memory_dom0"),
  "mtotal": ("MTotal", constants.QFT_UNIT, "memory_total"),
  }


def _GetNodeGroup(ctx, node):
  """Returns the name of a node's group.

  @type ctx: L{NodeQueryData}
  @type node: L{objects.Node}
  @param node: Node object

  """
  ng = ctx.groups.get(node.group, None)
  if ng is None:
    # Nodes always have a group, or the configuration is corrupt
    return (constants.QRFS_UNAVAIL, None)

  return (constants.QRFS_NORMAL, ng.name)


def _GetLiveNodeField(field, kind, ctx, node):
  """Gets the value of a "live" field from L{NodeQueryData}.

  @param field: Live field name
  @param kind: Data kind, one of L{constants.QFT_ALL}
  @type ctx: L{NodeQueryData}
  @type node: L{objects.Node}
  @param node: Node object

  """
  if node.offline:
    return (constants.QRFS_OFFLINE, None)

  if not ctx.curlive_data:
    return (constants.QRFS_NODATA, None)

  try:
    value = ctx.curlive_data[field]
  except KeyError:
    return (constants.QRFS_UNAVAIL, None)

  if kind == constants.QFT_TEXT:
    return (constants.QRFS_NORMAL, value)

  assert kind in (constants.QFT_NUMBER, constants.QFT_UNIT)

  # Try to convert into number
  try:
    return (constants.QRFS_NORMAL, int(value))
  except (ValueError, TypeError):
    logging.exception("Failed to convert node field '%s' (value %r) to int",
                      value, field)
    return (constants.QRFS_UNAVAIL, None)


def _BuildNodeFields():
  """Builds list of fields for node queries.

  """
  fields = [
    (_MakeField("pip", "PrimaryIP", constants.QFT_TEXT), NQ_CONFIG,
     lambda ctx, node: (constants.QRFS_NORMAL, node.primary_ip)),
    (_MakeField("sip", "SecondaryIP", constants.QFT_TEXT), NQ_CONFIG,
     lambda ctx, node: (constants.QRFS_NORMAL, node.secondary_ip)),
    (_MakeField("tags", "Tags", constants.QFT_OTHER), NQ_CONFIG,
     lambda ctx, node: (constants.QRFS_NORMAL, list(node.GetTags()))),
    (_MakeField("master", "IsMaster", constants.QFT_BOOL), NQ_CONFIG,
     lambda ctx, node: (constants.QRFS_NORMAL, node.name == ctx.master_name)),
    (_MakeField("role", "Role", constants.QFT_TEXT), NQ_CONFIG,
     lambda ctx, node: (constants.QRFS_NORMAL,
                        _GetNodeRole(node, ctx.master_name))),
    (_MakeField("group", "Group", constants.QFT_TEXT), NQ_GROUP, _GetNodeGroup),
    (_MakeField("group.uuid", "GroupUUID", constants.QFT_TEXT),
     NQ_CONFIG, lambda ctx, node: (constants.QRFS_NORMAL, node.group)),
    ]

  def _GetLength(getter):
    return lambda ctx, node: (constants.QRFS_NORMAL,
                              len(getter(ctx)[node.name]))

  def _GetList(getter):
    return lambda ctx, node: (constants.QRFS_NORMAL,
                              list(getter(ctx)[node.name]))

  # Add fields operating on instance lists
  for prefix, titleprefix, getter in \
      [("p", "Pri", operator.attrgetter("node_to_primary")),
       ("s", "Sec", operator.attrgetter("node_to_secondary"))]:
    fields.extend([
      (_MakeField("%sinst_cnt" % prefix, "%sinst" % prefix.upper(),
                  constants.QFT_NUMBER),
       NQ_INST, _GetLength(getter)),
      (_MakeField("%sinst_list" % prefix, "%sInstances" % titleprefix,
                  constants.QFT_OTHER),
       NQ_INST, _GetList(getter)),
      ])

  # Add simple fields
  fields.extend([(_MakeField(name, title, kind), NQ_CONFIG, _GetItemAttr(name))
                 for (name, (title, kind)) in _NODE_SIMPLE_FIELDS.items()])

  # Add fields requiring live data
  fields.extend([
    (_MakeField(name, title, kind), NQ_LIVE,
     compat.partial(_GetLiveNodeField, nfield, kind))
    for (name, (title, kind, nfield)) in _NODE_LIVE_FIELDS.items()
    ])

  # Add timestamps
  fields.extend(_GetItemTimestampFields(NQ_CONFIG))

  return _PrepareFieldList(fields)


class InstanceQueryData:
  """Data container for instance data queries.

  """
  def __init__(self, instances, cluster, disk_usage, offline_nodes, bad_nodes,
               live_data):
    """Initializes this class.

    @param instances: List of instance objects
    @param cluster: Cluster object
    @type disk_usage: dict; instance name as key
    @param disk_usage: Per-instance disk usage
    @type offline_nodes: list of strings
    @param offline_nodes: List of offline nodes
    @type bad_nodes: list of strings
    @param bad_nodes: List of faulty nodes
    @type live_data: dict; instance name as key
    @param live_data: Per-instance live data

    """
    assert len(set(bad_nodes) & set(offline_nodes)) == len(offline_nodes), \
           "Offline nodes not included in bad nodes"
    assert not (set(live_data.keys()) & set(bad_nodes)), \
           "Found live data for bad or offline nodes"

    self.instances = instances
    self.cluster = cluster
    self.disk_usage = disk_usage
    self.offline_nodes = offline_nodes
    self.bad_nodes = bad_nodes
    self.live_data = live_data

    # Used for individual rows
    self.inst_hvparams = None
    self.inst_beparams = None
    self.inst_nicparams = None

  def __iter__(self):
    """Iterate over all instances.

    This function has side-effects and only one instance of the resulting
    generator should be used at a time.

    """
    for inst in self.instances:
      self.inst_hvparams = self.cluster.FillHV(inst, skip_globals=True)
      self.inst_beparams = self.cluster.FillBE(inst)
      self.inst_nicparams = [self.cluster.SimpleFillNIC(nic.nicparams)
                             for nic in inst.nics]

      yield inst


def _GetInstOperState(ctx, inst):
  """Get instance's operational status.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  # Can't use QRFS_OFFLINE here as it would describe the instance to be offline
  # when we actually don't know due to missing data
  if inst.primary_node in ctx.bad_nodes:
    return (constants.QRFS_NODATA, None)
  else:
    return (constants.QRFS_NORMAL, bool(ctx.live_data.get(inst.name)))


def _GetInstLiveData(name):
  """Build function for retrieving live data.

  @type name: string
  @param name: Live data field name

  """
  def fn(ctx, inst):
    """Get live data for an instance.

    @type ctx: L{InstanceQueryData}
    @type inst: L{objects.Instance}
    @param inst: Instance object

    """
    if (inst.primary_node in ctx.bad_nodes or
        inst.primary_node in ctx.offline_nodes):
      # Can't use QRFS_OFFLINE here as it would describe the instance to be
      # offline when we actually don't know due to missing data
      return (constants.QRFS_NODATA, None)

    if inst.name in ctx.live_data:
      data = ctx.live_data[inst.name]
      if name in data:
        return (constants.QRFS_NORMAL, data[name])

    return (constants.QRFS_UNAVAIL, None)

  return fn


def _GetInstStatus(ctx, inst):
  """Get instance status.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  if inst.primary_node in ctx.offline_nodes:
    return (constants.QRFS_NORMAL, "ERROR_nodeoffline")

  if inst.primary_node in ctx.bad_nodes:
    return (constants.QRFS_NORMAL, "ERROR_nodedown")

  if bool(ctx.live_data.get(inst.name)):
    if inst.admin_up:
      return (constants.QRFS_NORMAL, "running")
    else:
      return (constants.QRFS_NORMAL, "ERROR_up")

  if inst.admin_up:
    return (constants.QRFS_NORMAL, "ERROR_down")

  return (constants.QRFS_NORMAL, "ADMIN_down")


def _GetInstDiskSize(index):
  """Build function for retrieving disk size.

  @type index: int
  @param index: Disk index

  """
  def fn(_, inst):
    """Get size of a disk.

    @type inst: L{objects.Instance}
    @param inst: Instance object

    """
    try:
      return (constants.QRFS_NORMAL, inst.disks[index].size)
    except IndexError:
      return (constants.QRFS_UNAVAIL, None)

  return fn


def _GetInstNic(index, cb):
  """Build function for calling another function with an instance NIC.

  @type index: int
  @param index: NIC index
  @type cb: callable
  @param cb: Callback

  """
  def fn(ctx, inst):
    """Call helper function with instance NIC.

    @type ctx: L{InstanceQueryData}
    @type inst: L{objects.Instance}
    @param inst: Instance object

    """
    try:
      nic = inst.nics[index]
    except IndexError:
      return (constants.QRFS_UNAVAIL, None)

    return cb(ctx, index, nic)

  return fn


def _GetInstNicIp(ctx, _, nic): # pylint: disable-msg=W0613
  """Get a NIC's IP address.

  @type ctx: L{InstanceQueryData}
  @type nic: L{objects.NIC}
  @param nic: NIC object

  """
  if nic.ip is None:
    return (constants.QRFS_UNAVAIL, None)
  else:
    return (constants.QRFS_NORMAL, nic.ip)


def _GetInstNicBridge(ctx, index, _):
  """Get a NIC's bridge.

  @type ctx: L{InstanceQueryData}
  @type index: int
  @param index: NIC index

  """
  assert len(ctx.inst_nicparams) >= index

  nicparams = ctx.inst_nicparams[index]

  if nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
    return (constants.QRFS_NORMAL, nicparams[constants.NIC_LINK])
  else:
    return (constants.QRFS_UNAVAIL, None)


def _GetInstAllNicBridges(ctx, inst):
  """Get all network bridges for an instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  assert len(ctx.inst_nicparams) == len(inst.nics)

  result = []

  for nicp in ctx.inst_nicparams:
    if nicp[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
      result.append(nicp[constants.NIC_LINK])
    else:
      result.append(None)

  assert len(result) == len(inst.nics)

  return (constants.QRFS_NORMAL, result)


def _GetInstNicParam(name):
  """Build function for retrieving a NIC parameter.

  @type name: string
  @param name: Parameter name

  """
  def fn(ctx, index, _):
    """Get a NIC's bridge.

    @type ctx: L{InstanceQueryData}
    @type inst: L{objects.Instance}
    @param inst: Instance object
    @type nic: L{objects.NIC}
    @param nic: NIC object

    """
    assert len(ctx.inst_nicparams) >= index
    return (constants.QRFS_NORMAL, ctx.inst_nicparams[index][name])

  return fn


def _GetInstanceNetworkFields():
  """Get instance fields involving network interfaces.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
  nic_mac_fn = lambda ctx, _, nic: (constants.QRFS_NORMAL, nic.mac)
  nic_mode_fn = _GetInstNicParam(constants.NIC_MODE)
  nic_link_fn = _GetInstNicParam(constants.NIC_LINK)

  fields = [
    # First NIC (legacy)
    (_MakeField("ip", "IP_address", constants.QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, _GetInstNicIp)),
    (_MakeField("mac", "MAC_address", constants.QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, nic_mac_fn)),
    (_MakeField("bridge", "Bridge", constants.QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, _GetInstNicBridge)),
    (_MakeField("nic_mode", "NIC_Mode", constants.QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, nic_mode_fn)),
    (_MakeField("nic_link", "NIC_Link", constants.QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, nic_link_fn)),

    # All NICs
    (_MakeField("nic.count", "NICs", constants.QFT_NUMBER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, len(inst.nics))),
    (_MakeField("nic.macs", "NIC_MACs", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, [nic.mac for nic in inst.nics])),
    (_MakeField("nic.ips", "NIC_IPs", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, [nic.ip for nic in inst.nics])),
    (_MakeField("nic.modes", "NIC_modes", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL,
                        [nicp[constants.NIC_MODE]
                         for nicp in ctx.inst_nicparams])),
    (_MakeField("nic.links", "NIC_links", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL,
                        [nicp[constants.NIC_LINK]
                         for nicp in ctx.inst_nicparams])),
    (_MakeField("nic.bridges", "NIC_bridges", constants.QFT_OTHER), IQ_CONFIG,
     _GetInstAllNicBridges),
    ]

  # NICs by number
  for i in range(constants.MAX_NICS):
    fields.extend([
      (_MakeField("nic.ip/%s" % i, "NicIP/%s" % i, constants.QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, _GetInstNicIp)),
      (_MakeField("nic.mac/%s" % i, "NicMAC/%s" % i, constants.QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, nic_mac_fn)),
      (_MakeField("nic.mode/%s" % i, "NicMode/%s" % i, constants.QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, nic_mode_fn)),
      (_MakeField("nic.link/%s" % i, "NicLink/%s" % i, constants.QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, nic_link_fn)),
      (_MakeField("nic.bridge/%s" % i, "NicBridge/%s" % i, constants.QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, _GetInstNicBridge)),
      ])

  return fields


def _GetInstDiskUsage(ctx, inst):
  """Get disk usage for an instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  usage = ctx.disk_usage[inst.name]

  if usage is None:
    usage = 0

  return (constants.QRFS_NORMAL, usage)


def _GetInstanceDiskFields():
  """Get instance fields involving disks.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
  fields = [
    (_MakeField("disk_usage", "DiskUsage", constants.QFT_UNIT), IQ_DISKUSAGE,
     _GetInstDiskUsage),
    (_MakeField("sda_size", "LegacyDisk/0", constants.QFT_UNIT), IQ_CONFIG,
     _GetInstDiskSize(0)),
    (_MakeField("sdb_size", "LegacyDisk/1", constants.QFT_UNIT), IQ_CONFIG,
     _GetInstDiskSize(1)),
    (_MakeField("disk.count", "Disks", constants.QFT_NUMBER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, len(inst.disks))),
    (_MakeField("disk.sizes", "Disk_sizes", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL,
                        [disk.size for disk in inst.disks])),
    ]

  # Disks by number
  fields.extend([
    (_MakeField("disk.size/%s" % i, "Disk/%s" % i, constants.QFT_UNIT),
     IQ_CONFIG, _GetInstDiskSize(i))
    for i in range(constants.MAX_DISKS)
    ])

  return fields


def _GetInstanceParameterFields():
  """Get instance fields involving parameters.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
  # TODO: Consider moving titles closer to constants
  be_title = {
    constants.BE_AUTO_BALANCE: "Auto_balance",
    constants.BE_MEMORY: "Configured_memory",
    constants.BE_VCPUS: "VCPUs",
    }

  hv_title = {
    constants.HV_ACPI: "ACPI",
    constants.HV_BOOT_ORDER: "Boot_order",
    constants.HV_CDROM_IMAGE_PATH: "CDROM_image_path",
    constants.HV_DISK_TYPE: "Disk_type",
    constants.HV_INITRD_PATH: "Initrd_path",
    constants.HV_KERNEL_PATH: "Kernel_path",
    constants.HV_NIC_TYPE: "NIC_type",
    constants.HV_PAE: "PAE",
    constants.HV_VNC_BIND_ADDRESS: "VNC_bind_address",
    }

  fields = [
    # Filled parameters
    (_MakeField("hvparams", "HypervisorParameters", constants.QFT_OTHER),
     IQ_CONFIG, lambda ctx, _: (constants.QRFS_NORMAL, ctx.inst_hvparams)),
    (_MakeField("beparams", "BackendParameters", constants.QFT_OTHER),
     IQ_CONFIG, lambda ctx, _: (constants.QRFS_NORMAL, ctx.inst_beparams)),
    (_MakeField("vcpus", "LegacyVCPUs", constants.QFT_NUMBER), IQ_CONFIG,
     lambda ctx, _: (constants.QRFS_NORMAL,
                     ctx.inst_beparams[constants.BE_VCPUS])),

    # Unfilled parameters
    (_MakeField("custom_hvparams", "CustomHypervisorParameters",
                constants.QFT_OTHER),
     IQ_CONFIG, lambda ctx, inst: (constants.QRFS_NORMAL, inst.hvparams)),
    (_MakeField("custom_beparams", "CustomBackendParameters",
                constants.QFT_OTHER),
     IQ_CONFIG, lambda ctx, inst: (constants.QRFS_NORMAL, inst.beparams)),
    (_MakeField("custom_nicparams", "CustomNicParameters",
                constants.QFT_OTHER),
     IQ_CONFIG, lambda ctx, inst: (constants.QRFS_NORMAL,
                                   [nic.nicparams for nic in inst.nics])),
    ]

  # HV params
  def _GetInstHvParam(name):
    return lambda ctx, _: (constants.QRFS_NORMAL,
                           ctx.inst_hvparams.get(name, None))

  fields.extend([
    # For now all hypervisor parameters are exported as QFT_OTHER
    (_MakeField("hv/%s" % name, hv_title.get(name, "hv/%s" % name),
                constants.QFT_OTHER),
     IQ_CONFIG, _GetInstHvParam(name))
    for name in constants.HVS_PARAMETERS
    if name not in constants.HVC_GLOBALS
    ])

  # BE params
  def _GetInstBeParam(name):
    return lambda ctx, _: (constants.QRFS_NORMAL,
                           ctx.inst_beparams.get(name, None))

  fields.extend([
    # For now all backend parameters are exported as QFT_OTHER
    (_MakeField("be/%s" % name, be_title.get(name, "be/%s" % name),
                constants.QFT_OTHER),
     IQ_CONFIG, _GetInstBeParam(name))
    for name in constants.BES_PARAMETERS
    ])

  return fields


_INST_SIMPLE_FIELDS = {
  "disk_template": ("Disk_template", constants.QFT_TEXT),
  "hypervisor": ("Hypervisor", constants.QFT_TEXT),
  "name": ("Node", constants.QFT_TEXT),
  # Depending on the hypervisor, the port can be None
  "network_port": ("Network_port", constants.QFT_OTHER),
  "os": ("OS", constants.QFT_TEXT),
  "serial_no": ("SerialNo", constants.QFT_NUMBER),
  "uuid": ("UUID", constants.QFT_TEXT),
  }


def _BuildInstanceFields():
  """Builds list of fields for instance queries.

  """
  fields = [
    (_MakeField("pnode", "Primary_node", constants.QFT_TEXT), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, inst.primary_node)),
    (_MakeField("snodes", "Secondary_Nodes", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, list(inst.secondary_nodes))),
    (_MakeField("admin_state", "Autostart", constants.QFT_BOOL), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, inst.admin_up)),
    (_MakeField("tags", "Tags", constants.QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: (constants.QRFS_NORMAL, list(inst.GetTags()))),
    ]

  # Add simple fields
  fields.extend([(_MakeField(name, title, kind), IQ_CONFIG, _GetItemAttr(name))
                 for (name, (title, kind)) in _INST_SIMPLE_FIELDS.items()])

  # Fields requiring talking to the node
  fields.extend([
    (_MakeField("oper_state", "Running", constants.QFT_BOOL), IQ_LIVE,
     _GetInstOperState),
    (_MakeField("oper_ram", "RuntimeMemory", constants.QFT_UNIT), IQ_LIVE,
     _GetInstLiveData("memory")),
    (_MakeField("oper_vcpus", "RuntimeVCPUs", constants.QFT_NUMBER), IQ_LIVE,
     _GetInstLiveData("vcpus")),
    (_MakeField("status", "Status", constants.QFT_TEXT), IQ_LIVE,
     _GetInstStatus),
    ])

  fields.extend(_GetInstanceParameterFields())
  fields.extend(_GetInstanceDiskFields())
  fields.extend(_GetInstanceNetworkFields())
  fields.extend(_GetItemTimestampFields(IQ_CONFIG))

  return _PrepareFieldList(fields)


class LockQueryData:
  """Data container for lock data queries.

  """
  def __init__(self, lockdata):
    """Initializes this class.

    """
    self.lockdata = lockdata

  def __iter__(self):
    """Iterate over all locks.

    """
    return iter(self.lockdata)


def _GetLockOwners(_, data):
  """Returns a sorted list of a lock's current owners.

  """
  (_, _, owners, _) = data

  if owners:
    owners = utils.NiceSort(owners)

  return (constants.QRFS_NORMAL, owners)


def _GetLockPending(_, data):
  """Returns a sorted list of a lock's pending acquires.

  """
  (_, _, _, pending) = data

  if pending:
    pending = [(mode, utils.NiceSort(names))
               for (mode, names) in pending]

  return (constants.QRFS_NORMAL, pending)


def _BuildLockFields():
  """Builds list of fields for lock queries.

  """
  return _PrepareFieldList([
    (_MakeField("name", "Name", constants.QFT_TEXT), None,
     lambda ctx, (name, mode, owners, pending): (constants.QRFS_NORMAL, name)),
    (_MakeField("mode", "Mode", constants.QFT_OTHER), LQ_MODE,
     lambda ctx, (name, mode, owners, pending): (constants.QRFS_NORMAL, mode)),
    (_MakeField("owner", "Owner", constants.QFT_OTHER), LQ_OWNER,
     _GetLockOwners),
    (_MakeField("pending", "Pending", constants.QFT_OTHER), LQ_PENDING,
     _GetLockPending),
    ])


#: Fields available for node queries
NODE_FIELDS = _BuildNodeFields()

#: Fields available for instance queries
INSTANCE_FIELDS = _BuildInstanceFields()

#: Fields available for lock queries
LOCK_FIELDS = _BuildLockFields()
