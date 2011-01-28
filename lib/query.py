#
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Module for query operations

How it works:

  - Add field definitions
    - See how L{NODE_FIELDS} is built
    - Each field gets:
      - Query field definition (L{objects.QueryFieldDefinition}, use
        L{_MakeField} for creating), containing:
          - Name, must be lowercase and match L{FIELD_NAME_RE}
          - Title for tables, must not contain whitespace and match
            L{TITLE_RE}
          - Value data type, e.g. L{constants.QFT_NUMBER}
      - Data request type, see e.g. C{NQ_*}
      - A retrieval function, see L{Query.__init__} for description
    - Pass list of fields through L{_PrepareFieldList} for preparation and
      checks
  - Instantiate L{Query} with prepared field list definition and selected fields
  - Call L{Query.RequestedData} to determine what data to collect/compute
  - Call L{Query.Query} or L{Query.OldStyleQuery} with collected data and use
    result
      - Data container must support iteration using C{__iter__}
      - Items are passed to retrieval functions and can have any format
  - Call L{Query.GetFields} to get list of definitions for selected fields

@attention: Retrieval functions must be idempotent. They can be called multiple
  times, in any order and any number of times. This is important to keep in
  mind for implementing filters in the future.

"""

import logging
import operator
import re

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import compat
from ganeti import objects
from ganeti import ht

from ganeti.constants import (QFT_UNKNOWN, QFT_TEXT, QFT_BOOL, QFT_NUMBER,
                              QFT_UNIT, QFT_TIMESTAMP, QFT_OTHER,
                              RS_NORMAL, RS_UNKNOWN, RS_NODATA,
                              RS_UNAVAIL, RS_OFFLINE)


# Constants for requesting data from the caller/data provider. Each property
# collected/computed separately by the data provider should have its own to
# only collect the requested data and not more.

(NQ_CONFIG,
 NQ_INST,
 NQ_LIVE,
 NQ_GROUP,
 NQ_OOB) = range(1, 6)

(IQ_CONFIG,
 IQ_LIVE,
 IQ_DISKUSAGE) = range(100, 103)

(LQ_MODE,
 LQ_OWNER,
 LQ_PENDING) = range(10, 13)

(GQ_CONFIG,
 GQ_NODE,
 GQ_INST) = range(200, 203)


FIELD_NAME_RE = re.compile(r"^[a-z0-9/._]+$")
TITLE_RE = re.compile(r"^[^\s]+$")

#: Verification function for each field type
_VERIFY_FN = {
  QFT_UNKNOWN: ht.TNone,
  QFT_TEXT: ht.TString,
  QFT_BOOL: ht.TBool,
  QFT_NUMBER: ht.TInt,
  QFT_UNIT: ht.TInt,
  QFT_TIMESTAMP: ht.TOr(ht.TInt, ht.TFloat),
  QFT_OTHER: lambda _: True,
  }

# Unique objects for special field statuses
_FS_UNKNOWN = object()
_FS_NODATA = object()
_FS_UNAVAIL = object()
_FS_OFFLINE = object()

#: VType to QFT mapping
_VTToQFT = {
  # TODO: fix validation of empty strings
  constants.VTYPE_STRING: QFT_OTHER, # since VTYPE_STRINGs can be empty
  constants.VTYPE_MAYBE_STRING: QFT_OTHER,
  constants.VTYPE_BOOL: QFT_BOOL,
  constants.VTYPE_SIZE: QFT_UNIT,
  constants.VTYPE_INT: QFT_NUMBER,
  }


def _GetUnknownField(ctx, item): # pylint: disable-msg=W0613
  """Gets the contents of an unknown field.

  """
  return _FS_UNKNOWN


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
      fdef = (_MakeField(name, name, QFT_UNKNOWN), None, _GetUnknownField)

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
    result = [[_ProcessResult(fn(ctx, item)) for (_, _, fn) in self._fields]
              for item in ctx]

    # Verify result
    if __debug__:
      for row in result:
        _VerifyResultRow(self._fields, row)

    return result

  def OldStyleQuery(self, ctx):
    """Query with "old" query result format.

    See L{Query.Query} for arguments.

    """
    unknown = set(fdef.name
                  for (fdef, _, _) in self._fields if fdef.kind == QFT_UNKNOWN)
    if unknown:
      raise errors.OpPrereqError("Unknown output fields selected: %s" %
                                 (utils.CommaJoin(unknown), ),
                                 errors.ECODE_INVAL)

    return [[value for (_, value) in row]
            for row in self.Query(ctx)]


def _ProcessResult(value):
  """Converts result values into externally-visible ones.

  """
  if value is _FS_UNKNOWN:
    return (RS_UNKNOWN, None)
  elif value is _FS_NODATA:
    return (RS_NODATA, None)
  elif value is _FS_UNAVAIL:
    return (RS_UNAVAIL, None)
  elif value is _FS_OFFLINE:
    return (RS_OFFLINE, None)
  else:
    return (RS_NORMAL, value)


def _VerifyResultRow(fields, row):
  """Verifies the contents of a query result row.

  @type fields: list
  @param fields: Field definitions for result
  @type row: list of tuples
  @param row: Row data

  """
  assert len(row) == len(fields)
  errs = []
  for ((status, value), (fdef, _, _)) in zip(row, fields):
    if status == RS_NORMAL:
      if not _VERIFY_FN[fdef.kind](value):
        errs.append("normal field %s fails validation (value is %s)" %
                    (fdef.name, value))
    elif value is not None:
      errs.append("abnormal field %s has a non-None value" % fdef.name)
  assert not errs, ("Failed validation: %s in row %s" %
                    (utils.CommaJoin(errors), row))


def _PrepareFieldList(fields, aliases):
  """Prepares field list for use by L{Query}.

  Converts the list to a dictionary and does some verification.

  @type fields: list of tuples; (L{objects.QueryFieldDefinition}, data
      kind, retrieval function)
  @param fields: List of fields, see L{Query.__init__} for a better
      description
  @type aliases: list of tuples; (alias, target)
  @param aliases: list of tuples containing aliases; for each
      alias/target pair, a duplicate will be created in the field list
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

  for alias, target in aliases:
    assert alias not in result, "Alias %s overrides an existing field" % alias
    assert target in result, "Missing target %s for alias %s" % (target, alias)
    (fdef, k, fn) = result[target]
    fdef = fdef.Copy()
    fdef.name = alias
    result[alias] = (fdef, k, fn)

  assert len(result) == len(fields) + len(aliases)
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
  return lambda _, item: getter(item)


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
      return _FS_UNAVAIL
    else:
      return timestamp

  return fn


def _GetItemTimestampFields(datatype):
  """Returns common timestamp fields.

  @param datatype: Field data type for use by L{Query.RequestedData}

  """
  return [
    (_MakeField("ctime", "CTime", QFT_TIMESTAMP), datatype,
     _GetItemTimestamp(operator.attrgetter("ctime"))),
    (_MakeField("mtime", "MTime", QFT_TIMESTAMP), datatype,
     _GetItemTimestamp(operator.attrgetter("mtime"))),
    ]


class NodeQueryData:
  """Data container for node data queries.

  """
  def __init__(self, nodes, live_data, master_name, node_to_primary,
               node_to_secondary, groups, oob_support, cluster):
    """Initializes this class.

    """
    self.nodes = nodes
    self.live_data = live_data
    self.master_name = master_name
    self.node_to_primary = node_to_primary
    self.node_to_secondary = node_to_secondary
    self.groups = groups
    self.oob_support = oob_support
    self.cluster = cluster

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
  "drained": ("Drained", QFT_BOOL),
  "master_candidate": ("MasterC", QFT_BOOL),
  "master_capable": ("MasterCapable", QFT_BOOL),
  "name": ("Node", QFT_TEXT),
  "offline": ("Offline", QFT_BOOL),
  "serial_no": ("SerialNo", QFT_NUMBER),
  "uuid": ("UUID", QFT_TEXT),
  "vm_capable": ("VMCapable", QFT_BOOL),
  }


#: Fields requiring talking to the node
_NODE_LIVE_FIELDS = {
  "bootid": ("BootID", QFT_TEXT, "bootid"),
  "cnodes": ("CNodes", QFT_NUMBER, "cpu_nodes"),
  "csockets": ("CSockets", QFT_NUMBER, "cpu_sockets"),
  "ctotal": ("CTotal", QFT_NUMBER, "cpu_total"),
  "dfree": ("DFree", QFT_UNIT, "vg_free"),
  "dtotal": ("DTotal", QFT_UNIT, "vg_size"),
  "mfree": ("MFree", QFT_UNIT, "memory_free"),
  "mnode": ("MNode", QFT_UNIT, "memory_dom0"),
  "mtotal": ("MTotal", QFT_UNIT, "memory_total"),
  }


def _GetGroup(cb):
  """Build function for calling another function with an node group.

  @param cb: The callback to be called with the nodegroup

  """
  def fn(ctx, node):
    """Get group data for a node.

    @type ctx: L{NodeQueryData}
    @type inst: L{objects.Node}
    @param inst: Node object

    """
    ng = ctx.groups.get(node.group, None)
    if ng is None:
      # Nodes always have a group, or the configuration is corrupt
      return _FS_UNAVAIL

    return cb(ctx, node, ng)

  return fn


def _GetNodeGroup(ctx, node, ng): # pylint: disable-msg=W0613
  """Returns the name of a node's group.

  @type ctx: L{NodeQueryData}
  @type node: L{objects.Node}
  @param node: Node object
  @type ng: L{objects.NodeGroup}
  @param ng: The node group this node belongs to

  """
  return ng.name


def _GetNodePower(ctx, node):
  """Returns the node powered state

  @type ctx: L{NodeQueryData}
  @type node: L{objects.Node}
  @param node: Node object

  """
  if ctx.oob_support[node.name]:
    return node.powered

  return _FS_UNAVAIL


def _GetNdParams(ctx, node, ng):
  """Returns the ndparams for this node.

  @type ctx: L{NodeQueryData}
  @type node: L{objects.Node}
  @param node: Node object
  @type ng: L{objects.NodeGroup}
  @param ng: The node group this node belongs to

  """
  return ctx.cluster.SimpleFillND(ng.FillND(node))


def _GetLiveNodeField(field, kind, ctx, node):
  """Gets the value of a "live" field from L{NodeQueryData}.

  @param field: Live field name
  @param kind: Data kind, one of L{constants.QFT_ALL}
  @type ctx: L{NodeQueryData}
  @type node: L{objects.Node}
  @param node: Node object

  """
  if node.offline:
    return _FS_OFFLINE

  if not ctx.curlive_data:
    return _FS_NODATA

  try:
    value = ctx.curlive_data[field]
  except KeyError:
    return _FS_UNAVAIL

  if kind == QFT_TEXT:
    return value

  assert kind in (QFT_NUMBER, QFT_UNIT)

  # Try to convert into number
  try:
    return int(value)
  except (ValueError, TypeError):
    logging.exception("Failed to convert node field '%s' (value %r) to int",
                      value, field)
    return _FS_UNAVAIL


def _BuildNodeFields():
  """Builds list of fields for node queries.

  """
  fields = [
    (_MakeField("pip", "PrimaryIP", QFT_TEXT), NQ_CONFIG,
     _GetItemAttr("primary_ip")),
    (_MakeField("sip", "SecondaryIP", QFT_TEXT), NQ_CONFIG,
     _GetItemAttr("secondary_ip")),
    (_MakeField("tags", "Tags", QFT_OTHER), NQ_CONFIG,
     lambda ctx, node: list(node.GetTags())),
    (_MakeField("master", "IsMaster", QFT_BOOL), NQ_CONFIG,
     lambda ctx, node: node.name == ctx.master_name),
    (_MakeField("role", "Role", QFT_TEXT), NQ_CONFIG,
     lambda ctx, node: _GetNodeRole(node, ctx.master_name)),
    (_MakeField("group", "Group", QFT_TEXT), NQ_GROUP,
     _GetGroup(_GetNodeGroup)),
    (_MakeField("group.uuid", "GroupUUID", QFT_TEXT),
     NQ_CONFIG, _GetItemAttr("group")),
    (_MakeField("powered", "Powered", QFT_BOOL), NQ_OOB, _GetNodePower),
    (_MakeField("ndparams", "NodeParameters", QFT_OTHER), NQ_GROUP,
      _GetGroup(_GetNdParams)),
    (_MakeField("custom_ndparams", "CustomNodeParameters", QFT_OTHER),
      NQ_GROUP, _GetItemAttr("ndparams")),
    ]

  def _GetLength(getter):
    return lambda ctx, node: len(getter(ctx)[node.name])

  def _GetList(getter):
    return lambda ctx, node: list(getter(ctx)[node.name])

  # Add fields operating on instance lists
  for prefix, titleprefix, getter in \
      [("p", "Pri", operator.attrgetter("node_to_primary")),
       ("s", "Sec", operator.attrgetter("node_to_secondary"))]:
    fields.extend([
      (_MakeField("%sinst_cnt" % prefix, "%sinst" % prefix.upper(), QFT_NUMBER),
       NQ_INST, _GetLength(getter)),
      (_MakeField("%sinst_list" % prefix, "%sInstances" % titleprefix,
                  QFT_OTHER),
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

  return _PrepareFieldList(fields, [])


class InstanceQueryData:
  """Data container for instance data queries.

  """
  def __init__(self, instances, cluster, disk_usage, offline_nodes, bad_nodes,
               live_data, wrongnode_inst):
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
    @type wrongnode_inst: set
    @param wrongnode_inst: Set of instances running on wrong node(s)

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
    self.wrongnode_inst = wrongnode_inst

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
  # Can't use RS_OFFLINE here as it would describe the instance to
  # be offline when we actually don't know due to missing data
  if inst.primary_node in ctx.bad_nodes:
    return _FS_NODATA
  else:
    return bool(ctx.live_data.get(inst.name))


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
      # Can't use RS_OFFLINE here as it would describe the instance to be
      # offline when we actually don't know due to missing data
      return _FS_NODATA

    if inst.name in ctx.live_data:
      data = ctx.live_data[inst.name]
      if name in data:
        return data[name]

    return _FS_UNAVAIL

  return fn


def _GetInstStatus(ctx, inst):
  """Get instance status.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  if inst.primary_node in ctx.offline_nodes:
    return "ERROR_nodeoffline"

  if inst.primary_node in ctx.bad_nodes:
    return "ERROR_nodedown"

  if bool(ctx.live_data.get(inst.name)):
    if inst.name in ctx.wrongnode_inst:
      return "ERROR_wrongnode"
    elif inst.admin_up:
      return "running"
    else:
      return "ERROR_up"

  if inst.admin_up:
    return "ERROR_down"

  return "ADMIN_down"


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
      return inst.disks[index].size
    except IndexError:
      return _FS_UNAVAIL

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
      return _FS_UNAVAIL

    return cb(ctx, index, nic)

  return fn


def _GetInstNicIp(ctx, _, nic): # pylint: disable-msg=W0613
  """Get a NIC's IP address.

  @type ctx: L{InstanceQueryData}
  @type nic: L{objects.NIC}
  @param nic: NIC object

  """
  if nic.ip is None:
    return _FS_UNAVAIL
  else:
    return nic.ip


def _GetInstNicBridge(ctx, index, _):
  """Get a NIC's bridge.

  @type ctx: L{InstanceQueryData}
  @type index: int
  @param index: NIC index

  """
  assert len(ctx.inst_nicparams) >= index

  nicparams = ctx.inst_nicparams[index]

  if nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
    return nicparams[constants.NIC_LINK]
  else:
    return _FS_UNAVAIL


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

  return result


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
    return ctx.inst_nicparams[index][name]

  return fn


def _GetInstanceNetworkFields():
  """Get instance fields involving network interfaces.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
  nic_mac_fn = lambda ctx, _, nic: nic.mac
  nic_mode_fn = _GetInstNicParam(constants.NIC_MODE)
  nic_link_fn = _GetInstNicParam(constants.NIC_LINK)

  fields = [
    # First NIC (legacy)
    (_MakeField("ip", "IP_address", QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, _GetInstNicIp)),
    (_MakeField("mac", "MAC_address", QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, nic_mac_fn)),
    (_MakeField("bridge", "Bridge", QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, _GetInstNicBridge)),
    (_MakeField("nic_mode", "NIC_Mode", QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, nic_mode_fn)),
    (_MakeField("nic_link", "NIC_Link", QFT_TEXT), IQ_CONFIG,
     _GetInstNic(0, nic_link_fn)),

    # All NICs
    (_MakeField("nic.count", "NICs", QFT_NUMBER), IQ_CONFIG,
     lambda ctx, inst: len(inst.nics)),
    (_MakeField("nic.macs", "NIC_MACs", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: [nic.mac for nic in inst.nics]),
    (_MakeField("nic.ips", "NIC_IPs", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: [nic.ip for nic in inst.nics]),
    (_MakeField("nic.modes", "NIC_modes", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: [nicp[constants.NIC_MODE]
                        for nicp in ctx.inst_nicparams]),
    (_MakeField("nic.links", "NIC_links", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: [nicp[constants.NIC_LINK]
                        for nicp in ctx.inst_nicparams]),
    (_MakeField("nic.bridges", "NIC_bridges", QFT_OTHER), IQ_CONFIG,
     _GetInstAllNicBridges),
    ]

  # NICs by number
  for i in range(constants.MAX_NICS):
    fields.extend([
      (_MakeField("nic.ip/%s" % i, "NicIP/%s" % i, QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, _GetInstNicIp)),
      (_MakeField("nic.mac/%s" % i, "NicMAC/%s" % i, QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, nic_mac_fn)),
      (_MakeField("nic.mode/%s" % i, "NicMode/%s" % i, QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, nic_mode_fn)),
      (_MakeField("nic.link/%s" % i, "NicLink/%s" % i, QFT_TEXT),
       IQ_CONFIG, _GetInstNic(i, nic_link_fn)),
      (_MakeField("nic.bridge/%s" % i, "NicBridge/%s" % i, QFT_TEXT),
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

  return usage


def _GetInstanceDiskFields():
  """Get instance fields involving disks.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
  fields = [
    (_MakeField("disk_usage", "DiskUsage", QFT_UNIT), IQ_DISKUSAGE,
     _GetInstDiskUsage),
    (_MakeField("disk.count", "Disks", QFT_NUMBER), IQ_CONFIG,
     lambda ctx, inst: len(inst.disks)),
    (_MakeField("disk.sizes", "Disk_sizes", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: [disk.size for disk in inst.disks]),
    ]

  # Disks by number
  fields.extend([
    (_MakeField("disk.size/%s" % i, "Disk/%s" % i, QFT_UNIT),
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
    constants.BE_MEMORY: "ConfigMemory",
    constants.BE_VCPUS: "ConfigVCPUs",
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
    (_MakeField("hvparams", "HypervisorParameters", QFT_OTHER),
     IQ_CONFIG, lambda ctx, _: ctx.inst_hvparams),
    (_MakeField("beparams", "BackendParameters", QFT_OTHER),
     IQ_CONFIG, lambda ctx, _: ctx.inst_beparams),

    # Unfilled parameters
    (_MakeField("custom_hvparams", "CustomHypervisorParameters", QFT_OTHER),
     IQ_CONFIG, _GetItemAttr("hvparams")),
    (_MakeField("custom_beparams", "CustomBackendParameters", QFT_OTHER),
     IQ_CONFIG, _GetItemAttr("beparams")),
    (_MakeField("custom_nicparams", "CustomNicParameters", QFT_OTHER),
     IQ_CONFIG, lambda ctx, inst: [nic.nicparams for nic in inst.nics]),
    ]

  # HV params
  def _GetInstHvParam(name):
    return lambda ctx, _: ctx.inst_hvparams.get(name, _FS_UNAVAIL)

  fields.extend([
    (_MakeField("hv/%s" % name, hv_title.get(name, "hv/%s" % name),
                _VTToQFT[kind]),
     IQ_CONFIG, _GetInstHvParam(name))
    for name, kind in constants.HVS_PARAMETER_TYPES.items()
    if name not in constants.HVC_GLOBALS
    ])

  # BE params
  def _GetInstBeParam(name):
    return lambda ctx, _: ctx.inst_beparams.get(name, None)

  fields.extend([
    (_MakeField("be/%s" % name, be_title.get(name, "be/%s" % name),
                _VTToQFT[kind]), IQ_CONFIG,
     _GetInstBeParam(name))
    for name, kind in constants.BES_PARAMETER_TYPES.items()
    ])

  return fields


_INST_SIMPLE_FIELDS = {
  "disk_template": ("Disk_template", QFT_TEXT),
  "hypervisor": ("Hypervisor", QFT_TEXT),
  "name": ("Node", QFT_TEXT),
  # Depending on the hypervisor, the port can be None
  "network_port": ("Network_port", QFT_OTHER),
  "os": ("OS", QFT_TEXT),
  "serial_no": ("SerialNo", QFT_NUMBER),
  "uuid": ("UUID", QFT_TEXT),
  }


def _BuildInstanceFields():
  """Builds list of fields for instance queries.

  """
  fields = [
    (_MakeField("pnode", "Primary_node", QFT_TEXT), IQ_CONFIG,
     _GetItemAttr("primary_node")),
    (_MakeField("snodes", "Secondary_Nodes", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: list(inst.secondary_nodes)),
    (_MakeField("admin_state", "Autostart", QFT_BOOL), IQ_CONFIG,
     _GetItemAttr("admin_up")),
    (_MakeField("tags", "Tags", QFT_OTHER), IQ_CONFIG,
     lambda ctx, inst: list(inst.GetTags())),
    ]

  # Add simple fields
  fields.extend([(_MakeField(name, title, kind), IQ_CONFIG, _GetItemAttr(name))
                 for (name, (title, kind)) in _INST_SIMPLE_FIELDS.items()])

  # Fields requiring talking to the node
  fields.extend([
    (_MakeField("oper_state", "Running", QFT_BOOL), IQ_LIVE,
     _GetInstOperState),
    (_MakeField("oper_ram", "Memory", QFT_UNIT), IQ_LIVE,
     _GetInstLiveData("memory")),
    (_MakeField("oper_vcpus", "VCPUs", QFT_NUMBER), IQ_LIVE,
     _GetInstLiveData("vcpus")),
    (_MakeField("status", "Status", QFT_TEXT), IQ_LIVE, _GetInstStatus),
    ])

  fields.extend(_GetInstanceParameterFields())
  fields.extend(_GetInstanceDiskFields())
  fields.extend(_GetInstanceNetworkFields())
  fields.extend(_GetItemTimestampFields(IQ_CONFIG))

  aliases = [
    ("vcpus", "be/vcpus"),
    ("sda_size", "disk.size/0"),
    ("sdb_size", "disk.size/1"),
    ]

  return _PrepareFieldList(fields, aliases)


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

  return owners


def _GetLockPending(_, data):
  """Returns a sorted list of a lock's pending acquires.

  """
  (_, _, _, pending) = data

  if pending:
    pending = [(mode, utils.NiceSort(names))
               for (mode, names) in pending]

  return pending


def _BuildLockFields():
  """Builds list of fields for lock queries.

  """
  return _PrepareFieldList([
    (_MakeField("name", "Name", QFT_TEXT), None,
     lambda ctx, (name, mode, owners, pending): name),
    (_MakeField("mode", "Mode", QFT_OTHER), LQ_MODE,
     lambda ctx, (name, mode, owners, pending): mode),
    (_MakeField("owner", "Owner", QFT_OTHER), LQ_OWNER, _GetLockOwners),
    (_MakeField("pending", "Pending", QFT_OTHER), LQ_PENDING, _GetLockPending),
    ], [])


class GroupQueryData:
  """Data container for node group data queries.

  """
  def __init__(self, groups, group_to_nodes, group_to_instances):
    """Initializes this class.

    @param groups: List of node group objects
    @type group_to_nodes: dict; group UUID as key
    @param group_to_nodes: Per-group list of nodes
    @type group_to_instances: dict; group UUID as key
    @param group_to_instances: Per-group list of (primary) instances

    """
    self.groups = groups
    self.group_to_nodes = group_to_nodes
    self.group_to_instances = group_to_instances

  def __iter__(self):
    """Iterate over all node groups.

    """
    return iter(self.groups)


_GROUP_SIMPLE_FIELDS = {
  "alloc_policy": ("AllocPolicy", QFT_TEXT),
  "name": ("Group", QFT_TEXT),
  "serial_no": ("SerialNo", QFT_NUMBER),
  "uuid": ("UUID", QFT_TEXT),
  "ndparams": ("NDParams", QFT_OTHER),
  }


def _BuildGroupFields():
  """Builds list of fields for node group queries.

  """
  # Add simple fields
  fields = [(_MakeField(name, title, kind), GQ_CONFIG, _GetItemAttr(name))
            for (name, (title, kind)) in _GROUP_SIMPLE_FIELDS.items()]

  def _GetLength(getter):
    return lambda ctx, group: len(getter(ctx)[group.uuid])

  def _GetSortedList(getter):
    return lambda ctx, group: utils.NiceSort(getter(ctx)[group.uuid])

  group_to_nodes = operator.attrgetter("group_to_nodes")
  group_to_instances = operator.attrgetter("group_to_instances")

  # Add fields for nodes
  fields.extend([
    (_MakeField("node_cnt", "Nodes", QFT_NUMBER),
     GQ_NODE, _GetLength(group_to_nodes)),
    (_MakeField("node_list", "NodeList", QFT_OTHER),
     GQ_NODE, _GetSortedList(group_to_nodes)),
    ])

  # Add fields for instances
  fields.extend([
    (_MakeField("pinst_cnt", "Instances", QFT_NUMBER),
     GQ_INST, _GetLength(group_to_instances)),
    (_MakeField("pinst_list", "InstanceList", QFT_OTHER),
     GQ_INST, _GetSortedList(group_to_instances)),
    ])

  fields.extend(_GetItemTimestampFields(GQ_CONFIG))

  return _PrepareFieldList(fields, [])


#: Fields available for node queries
NODE_FIELDS = _BuildNodeFields()

#: Fields available for instance queries
INSTANCE_FIELDS = _BuildInstanceFields()

#: Fields available for lock queries
LOCK_FIELDS = _BuildLockFields()

#: Fields available for node group queries
GROUP_FIELDS = _BuildGroupFields()

#: All available field lists
ALL_FIELD_LISTS = [NODE_FIELDS, INSTANCE_FIELDS, LOCK_FIELDS, GROUP_FIELDS]
