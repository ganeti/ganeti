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
                (self._fields, idx, row))

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
  assert len(set(fdef.title.lower()
                 for (fdef, _, _) in fields)) == len(fields), \
         "Duplicate title found"

  result = {}

  for field in fields:
    (fdef, _, fn) = field

    assert fdef.name and fdef.title, "Name and title are required"
    assert FIELD_NAME_RE.match(fdef.name)
    assert TITLE_RE.match(fdef.title)
    assert callable(fn)
    assert fdef.name not in result, "Duplicate field name found"

    result[fdef.name] = field

  assert len(result) == len(fields)
  assert compat.all(name == fdef.name
                    for (name, (fdef, _, _)) in result.items())

  return result


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
  "ctime": ("CTime", constants.QFT_TIMESTAMP),
  "drained": ("Drained", constants.QFT_BOOL),
  "master_candidate": ("MasterC", constants.QFT_BOOL),
  "master_capable": ("MasterCapable", constants.QFT_BOOL),
  "mtime": ("MTime", constants.QFT_TIMESTAMP),
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


def _GetLiveNodeField(field, kind, ctx, _):
  """Gets the value of a "live" field from L{NodeQueryData}.

  @param field: Live field name
  @param kind: Data kind, one of L{constants.QFT_ALL}
  @type ctx: L{NodeQueryData}

  """
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

  return _PrepareFieldList(fields)


#: Fields available for node queries
NODE_FIELDS = _BuildNodeFields()
