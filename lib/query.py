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
          - Human-readable description, must not end with punctuation or
            contain newlines
      - Data request type, see e.g. C{NQ_*}
      - OR-ed flags, see C{QFF_*}
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
  times, in any order and any number of times.

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
from ganeti import qlang

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
 IQ_DISKUSAGE,
 IQ_CONSOLE,
 IQ_NODES) = range(100, 105)

(LQ_MODE,
 LQ_OWNER,
 LQ_PENDING) = range(10, 13)

(GQ_CONFIG,
 GQ_NODE,
 GQ_INST) = range(200, 203)

# Query field flags
QFF_HOSTNAME = 0x01
QFF_IP_ADDRESS = 0x02
# Next values: 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x100, 0x200
QFF_ALL = (QFF_HOSTNAME | QFF_IP_ADDRESS)

FIELD_NAME_RE = re.compile(r"^[a-z0-9/._]+$")
TITLE_RE = re.compile(r"^[^\s]+$")
DOC_RE = re.compile(r"^[A-Z].*[^.,?!]$")

#: Verification function for each field type
_VERIFY_FN = {
  QFT_UNKNOWN: ht.TNone,
  QFT_TEXT: ht.TString,
  QFT_BOOL: ht.TBool,
  QFT_NUMBER: ht.TInt,
  QFT_UNIT: ht.TInt,
  QFT_TIMESTAMP: ht.TNumber,
  QFT_OTHER: lambda _: True,
  }

# Unique objects for special field statuses
_FS_UNKNOWN = object()
_FS_NODATA = object()
_FS_UNAVAIL = object()
_FS_OFFLINE = object()

#: List of all special status
_FS_ALL = frozenset([_FS_UNKNOWN, _FS_NODATA, _FS_UNAVAIL, _FS_OFFLINE])

#: VType to QFT mapping
_VTToQFT = {
  # TODO: fix validation of empty strings
  constants.VTYPE_STRING: QFT_OTHER, # since VTYPE_STRINGs can be empty
  constants.VTYPE_MAYBE_STRING: QFT_OTHER,
  constants.VTYPE_BOOL: QFT_BOOL,
  constants.VTYPE_SIZE: QFT_UNIT,
  constants.VTYPE_INT: QFT_NUMBER,
  }

_SERIAL_NO_DOC = "%s object serial number, incremented on each modification"


def _GetUnknownField(ctx, item): # pylint: disable=W0613
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
      fdef = (_MakeField(name, name, QFT_UNKNOWN, "Unknown field '%s'" % name),
              None, 0, _GetUnknownField)

    assert len(fdef) == 4

    result.append(fdef)

  return result


def GetAllFields(fielddefs):
  """Extract L{objects.QueryFieldDefinition} from field definitions.

  @rtype: list of L{objects.QueryFieldDefinition}

  """
  return [fdef for (fdef, _, _, _) in fielddefs]


class _FilterHints:
  """Class for filter analytics.

  When filters are used, the user of the L{Query} class usually doesn't know
  exactly which items will be necessary for building the result. It therefore
  has to prepare and compute the input data for potentially returning
  everything.

  There are two ways to optimize this. The first, and simpler, is to assign
  each field a group of data, so that the caller can determine which
  computations are necessary depending on the data groups requested. The list
  of referenced groups must also be computed for fields referenced in the
  filter.

  The second is restricting the items based on a primary key. The primary key
  is usually a unique name (e.g. a node name). This class extracts all
  referenced names from a filter. If it encounters any filter condition which
  disallows such a list to be determined (e.g. a non-equality filter), all
  names will be requested.

  The end-effect is that any operation other than L{qlang.OP_OR} and
  L{qlang.OP_EQUAL} will make the query more expensive.

  """
  def __init__(self, namefield):
    """Initializes this class.

    @type namefield: string
    @param namefield: Field caller is interested in

    """
    self._namefield = namefield

    #: Whether all names need to be requested (e.g. if a non-equality operator
    #: has been used)
    self._allnames = False

    #: Which names to request
    self._names = None

    #: Data kinds referenced by the filter (used by L{Query.RequestedData})
    self._datakinds = set()

  def RequestedNames(self):
    """Returns all requested values.

    Returns C{None} if list of values can't be determined (e.g. encountered
    non-equality operators).

    @rtype: list

    """
    if self._allnames or self._names is None:
      return None

    return utils.UniqueSequence(self._names)

  def ReferencedData(self):
    """Returns all kinds of data referenced by the filter.

    """
    return frozenset(self._datakinds)

  def _NeedAllNames(self):
    """Changes internal state to request all names.

    """
    self._allnames = True
    self._names = None

  def NoteLogicOp(self, op):
    """Called when handling a logic operation.

    @type op: string
    @param op: Operator

    """
    if op != qlang.OP_OR:
      self._NeedAllNames()

  def NoteUnaryOp(self, op): # pylint: disable=W0613
    """Called when handling an unary operation.

    @type op: string
    @param op: Operator

    """
    self._NeedAllNames()

  def NoteBinaryOp(self, op, datakind, name, value):
    """Called when handling a binary operation.

    @type op: string
    @param op: Operator
    @type name: string
    @param name: Left-hand side of operator (field name)
    @param value: Right-hand side of operator

    """
    if datakind is not None:
      self._datakinds.add(datakind)

    if self._allnames:
      return

    # If any operator other than equality was used, all names need to be
    # retrieved
    if op == qlang.OP_EQUAL and name == self._namefield:
      if self._names is None:
        self._names = []
      self._names.append(value)
    else:
      self._NeedAllNames()


def _WrapLogicOp(op_fn, sentences, ctx, item):
  """Wrapper for logic operator functions.

  """
  return op_fn(fn(ctx, item) for fn in sentences)


def _WrapUnaryOp(op_fn, inner, ctx, item):
  """Wrapper for unary operator functions.

  """
  return op_fn(inner(ctx, item))


def _WrapBinaryOp(op_fn, retrieval_fn, value, ctx, item):
  """Wrapper for binary operator functions.

  """
  return op_fn(retrieval_fn(ctx, item), value)


def _WrapNot(fn, lhs, rhs):
  """Negates the result of a wrapped function.

  """
  return not fn(lhs, rhs)


def _PrepareRegex(pattern):
  """Compiles a regular expression.

  """
  try:
    return re.compile(pattern)
  except re.error, err:
    raise errors.ParameterError("Invalid regex pattern (%s)" % err)


class _FilterCompilerHelper:
  """Converts a query filter to a callable usable for filtering.

  """
  # String statement has no effect, pylint: disable=W0105

  #: How deep filters can be nested
  _LEVELS_MAX = 10

  # Unique identifiers for operator groups
  (_OPTYPE_LOGIC,
   _OPTYPE_UNARY,
   _OPTYPE_BINARY) = range(1, 4)

  """Functions for equality checks depending on field flags.

  List of tuples containing flags and a callable receiving the left- and
  right-hand side of the operator. The flags are an OR-ed value of C{QFF_*}
  (e.g. L{QFF_HOSTNAME}).

  Order matters. The first item with flags will be used. Flags are checked
  using binary AND.

  """
  _EQUALITY_CHECKS = [
    (QFF_HOSTNAME,
     lambda lhs, rhs: utils.MatchNameComponent(rhs, [lhs],
                                               case_sensitive=False),
     None),
    (None, operator.eq, None),
    ]

  """Known operators

  Operator as key (C{qlang.OP_*}), value a tuple of operator group
  (C{_OPTYPE_*}) and a group-specific value:

    - C{_OPTYPE_LOGIC}: Callable taking any number of arguments; used by
      L{_HandleLogicOp}
    - C{_OPTYPE_UNARY}: Always C{None}; details handled by L{_HandleUnaryOp}
    - C{_OPTYPE_BINARY}: Callable taking exactly two parameters, the left- and
      right-hand side of the operator, used by L{_HandleBinaryOp}

  """
  _OPS = {
    # Logic operators
    qlang.OP_OR: (_OPTYPE_LOGIC, compat.any),
    qlang.OP_AND: (_OPTYPE_LOGIC, compat.all),

    # Unary operators
    qlang.OP_NOT: (_OPTYPE_UNARY, None),
    qlang.OP_TRUE: (_OPTYPE_UNARY, None),

    # Binary operators
    qlang.OP_EQUAL: (_OPTYPE_BINARY, _EQUALITY_CHECKS),
    qlang.OP_NOT_EQUAL:
      (_OPTYPE_BINARY, [(flags, compat.partial(_WrapNot, fn), valprepfn)
                        for (flags, fn, valprepfn) in _EQUALITY_CHECKS]),
    qlang.OP_REGEXP: (_OPTYPE_BINARY, [
      (None, lambda lhs, rhs: rhs.search(lhs), _PrepareRegex),
      ]),
    qlang.OP_CONTAINS: (_OPTYPE_BINARY, [
      (None, operator.contains, None),
      ]),
    }

  def __init__(self, fields):
    """Initializes this class.

    @param fields: Field definitions (return value of L{_PrepareFieldList})

    """
    self._fields = fields
    self._hints = None
    self._op_handler = None

  def __call__(self, hints, qfilter):
    """Converts a query filter into a callable function.

    @type hints: L{_FilterHints} or None
    @param hints: Callbacks doing analysis on filter
    @type qfilter: list
    @param qfilter: Filter structure
    @rtype: callable
    @return: Function receiving context and item as parameters, returning
             boolean as to whether item matches filter

    """
    self._op_handler = {
      self._OPTYPE_LOGIC:
        (self._HandleLogicOp, getattr(hints, "NoteLogicOp", None)),
      self._OPTYPE_UNARY:
        (self._HandleUnaryOp, getattr(hints, "NoteUnaryOp", None)),
      self._OPTYPE_BINARY:
        (self._HandleBinaryOp, getattr(hints, "NoteBinaryOp", None)),
      }

    try:
      filter_fn = self._Compile(qfilter, 0)
    finally:
      self._op_handler = None

    return filter_fn

  def _Compile(self, qfilter, level):
    """Inner function for converting filters.

    Calls the correct handler functions for the top-level operator. This
    function is called recursively (e.g. for logic operators).

    """
    if not (isinstance(qfilter, (list, tuple)) and qfilter):
      raise errors.ParameterError("Invalid filter on level %s" % level)

    # Limit recursion
    if level >= self._LEVELS_MAX:
      raise errors.ParameterError("Only up to %s levels are allowed (filter"
                                  " nested too deep)" % self._LEVELS_MAX)

    # Create copy to be modified
    operands = qfilter[:]
    op = operands.pop(0)

    try:
      (kind, op_data) = self._OPS[op]
    except KeyError:
      raise errors.ParameterError("Unknown operator '%s'" % op)

    (handler, hints_cb) = self._op_handler[kind]

    return handler(hints_cb, level, op, op_data, operands)

  def _LookupField(self, name):
    """Returns a field definition by name.

    """
    try:
      return self._fields[name]
    except KeyError:
      raise errors.ParameterError("Unknown field '%s'" % name)

  def _HandleLogicOp(self, hints_fn, level, op, op_fn, operands):
    """Handles logic operators.

    @type hints_fn: callable
    @param hints_fn: Callback doing some analysis on the filter
    @type level: integer
    @param level: Current depth
    @type op: string
    @param op: Operator
    @type op_fn: callable
    @param op_fn: Function implementing operator
    @type operands: list
    @param operands: List of operands

    """
    if hints_fn:
      hints_fn(op)

    return compat.partial(_WrapLogicOp, op_fn,
                          [self._Compile(op, level + 1) for op in operands])

  def _HandleUnaryOp(self, hints_fn, level, op, op_fn, operands):
    """Handles unary operators.

    @type hints_fn: callable
    @param hints_fn: Callback doing some analysis on the filter
    @type level: integer
    @param level: Current depth
    @type op: string
    @param op: Operator
    @type op_fn: callable
    @param op_fn: Function implementing operator
    @type operands: list
    @param operands: List of operands

    """
    assert op_fn is None

    if hints_fn:
      hints_fn(op)

    if len(operands) != 1:
      raise errors.ParameterError("Unary operator '%s' expects exactly one"
                                  " operand" % op)

    if op == qlang.OP_TRUE:
      (_, _, _, retrieval_fn) = self._LookupField(operands[0])

      op_fn = operator.truth
      arg = retrieval_fn
    elif op == qlang.OP_NOT:
      op_fn = operator.not_
      arg = self._Compile(operands[0], level + 1)
    else:
      raise errors.ProgrammerError("Can't handle operator '%s'" % op)

    return compat.partial(_WrapUnaryOp, op_fn, arg)

  def _HandleBinaryOp(self, hints_fn, level, op, op_data, operands):
    """Handles binary operators.

    @type hints_fn: callable
    @param hints_fn: Callback doing some analysis on the filter
    @type level: integer
    @param level: Current depth
    @type op: string
    @param op: Operator
    @param op_data: Functions implementing operators
    @type operands: list
    @param operands: List of operands

    """
    # Unused arguments, pylint: disable=W0613
    try:
      (name, value) = operands
    except (ValueError, TypeError):
      raise errors.ParameterError("Invalid binary operator, expected exactly"
                                  " two operands")

    (fdef, datakind, field_flags, retrieval_fn) = self._LookupField(name)

    assert fdef.kind != QFT_UNKNOWN

    # TODO: Type conversions?

    verify_fn = _VERIFY_FN[fdef.kind]
    if not verify_fn(value):
      raise errors.ParameterError("Unable to compare field '%s' (type '%s')"
                                  " with '%s', expected %s" %
                                  (name, fdef.kind, value.__class__.__name__,
                                   verify_fn))

    if hints_fn:
      hints_fn(op, datakind, name, value)

    for (fn_flags, fn, valprepfn) in op_data:
      if fn_flags is None or fn_flags & field_flags:
        # Prepare value if necessary (e.g. compile regular expression)
        if valprepfn:
          value = valprepfn(value)

        return compat.partial(_WrapBinaryOp, fn, retrieval_fn, value)

    raise errors.ProgrammerError("Unable to find operator implementation"
                                 " (op '%s', flags %s)" % (op, field_flags))


def _CompileFilter(fields, hints, qfilter):
  """Converts a query filter into a callable function.

  See L{_FilterCompilerHelper} for details.

  @rtype: callable

  """
  return _FilterCompilerHelper(fields)(hints, qfilter)


class Query:
  def __init__(self, fieldlist, selected, qfilter=None, namefield=None):
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
    assert namefield is None or namefield in fieldlist

    self._fields = _GetQueryFields(fieldlist, selected)

    self._filter_fn = None
    self._requested_names = None
    self._filter_datakinds = frozenset()

    if qfilter is not None:
      # Collect requested names if wanted
      if namefield:
        hints = _FilterHints(namefield)
      else:
        hints = None

      # Build filter function
      self._filter_fn = _CompileFilter(fieldlist, hints, qfilter)
      if hints:
        self._requested_names = hints.RequestedNames()
        self._filter_datakinds = hints.ReferencedData()

    if namefield is None:
      self._name_fn = None
    else:
      (_, _, _, self._name_fn) = fieldlist[namefield]

  def RequestedNames(self):
    """Returns all names referenced in the filter.

    If there is no filter or operators are preventing determining the exact
    names, C{None} is returned.

    """
    return self._requested_names

  def RequestedData(self):
    """Gets requested kinds of data.

    @rtype: frozenset

    """
    return (self._filter_datakinds |
            frozenset(datakind for (_, datakind, _, _) in self._fields
                      if datakind is not None))

  def GetFields(self):
    """Returns the list of fields for this query.

    Includes unknown fields.

    @rtype: List of L{objects.QueryFieldDefinition}

    """
    return GetAllFields(self._fields)

  def Query(self, ctx, sort_by_name=True):
    """Execute a query.

    @param ctx: Data container passed to field retrieval functions, must
      support iteration using C{__iter__}
    @type sort_by_name: boolean
    @param sort_by_name: Whether to sort by name or keep the input data's
      ordering

    """
    sort = (self._name_fn and sort_by_name)

    result = []

    for idx, item in enumerate(ctx):
      if not (self._filter_fn is None or self._filter_fn(ctx, item)):
        continue

      row = [_ProcessResult(fn(ctx, item)) for (_, _, _, fn) in self._fields]

      # Verify result
      if __debug__:
        _VerifyResultRow(self._fields, row)

      if sort:
        (status, name) = _ProcessResult(self._name_fn(ctx, item))
        assert status == constants.RS_NORMAL
        # TODO: Are there cases where we wouldn't want to use NiceSort?
        result.append((utils.NiceSortKey(name), idx, row))
      else:
        result.append(row)

    if not sort:
      return result

    # TODO: Would "heapq" be more efficient than sorting?

    # Sorting in-place instead of using "sorted()"
    result.sort()

    assert not result or (len(result[0]) == 3 and len(result[-1]) == 3)

    return map(operator.itemgetter(2), result)

  def OldStyleQuery(self, ctx, sort_by_name=True):
    """Query with "old" query result format.

    See L{Query.Query} for arguments.

    """
    unknown = set(fdef.name for (fdef, _, _, _) in self._fields
                  if fdef.kind == QFT_UNKNOWN)
    if unknown:
      raise errors.OpPrereqError("Unknown output fields selected: %s" %
                                 (utils.CommaJoin(unknown), ),
                                 errors.ECODE_INVAL)

    return [[value for (_, value) in row]
            for row in self.Query(ctx, sort_by_name=sort_by_name)]


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
  for ((status, value), (fdef, _, _, _)) in zip(row, fields):
    if status == RS_NORMAL:
      if not _VERIFY_FN[fdef.kind](value):
        errs.append("normal field %s fails validation (value is %s)" %
                    (fdef.name, value))
    elif value is not None:
      errs.append("abnormal field %s has a non-None value" % fdef.name)
  assert not errs, ("Failed validation: %s in row %s" %
                    (utils.CommaJoin(errs), row))


def _FieldDictKey((fdef, _, flags, fn)):
  """Generates key for field dictionary.

  """
  assert fdef.name and fdef.title, "Name and title are required"
  assert FIELD_NAME_RE.match(fdef.name)
  assert TITLE_RE.match(fdef.title)
  assert (DOC_RE.match(fdef.doc) and len(fdef.doc.splitlines()) == 1 and
          fdef.doc.strip() == fdef.doc), \
         "Invalid description for field '%s'" % fdef.name
  assert callable(fn)
  assert (flags & ~QFF_ALL) == 0, "Unknown flags for field '%s'" % fdef.name

  return fdef.name


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
                                      for (fdef, _, _, _) in fields)
    assert not duplicates, "Duplicate title(s) found: %r" % duplicates

  result = utils.SequenceToDict(fields, key=_FieldDictKey)

  for alias, target in aliases:
    assert alias not in result, "Alias %s overrides an existing field" % alias
    assert target in result, "Missing target %s for alias %s" % (target, alias)
    (fdef, k, flags, fn) = result[target]
    fdef = fdef.Copy()
    fdef.name = alias
    result[alias] = (fdef, k, flags, fn)

  assert len(result) == len(fields) + len(aliases)
  assert compat.all(name == fdef.name
                    for (name, (fdef, _, _, _)) in result.items())

  return result


def GetQueryResponse(query, ctx, sort_by_name=True):
  """Prepares the response for a query.

  @type query: L{Query}
  @param ctx: Data container, see L{Query.Query}
  @type sort_by_name: boolean
  @param sort_by_name: Whether to sort by name or keep the input data's
    ordering

  """
  return objects.QueryResponse(data=query.Query(ctx, sort_by_name=sort_by_name),
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


def _MakeField(name, title, kind, doc):
  """Wrapper for creating L{objects.QueryFieldDefinition} instances.

  @param name: Field name as a regular expression
  @param title: Human-readable title
  @param kind: Field type
  @param doc: Human-readable description

  """
  return objects.QueryFieldDefinition(name=name, title=title, kind=kind,
                                      doc=doc)


def _GetNodeRole(node, master_name):
  """Determine node role.

  @type node: L{objects.Node}
  @param node: Node object
  @type master_name: string
  @param master_name: Master node name

  """
  if node.name == master_name:
    return constants.NR_MASTER
  elif node.master_candidate:
    return constants.NR_MCANDIDATE
  elif node.drained:
    return constants.NR_DRAINED
  elif node.offline:
    return constants.NR_OFFLINE
  else:
    return constants.NR_REGULAR


def _GetItemAttr(attr):
  """Returns a field function to return an attribute of the item.

  @param attr: Attribute name

  """
  getter = operator.attrgetter(attr)
  return lambda _, item: getter(item)


def _ConvWrapInner(convert, fn, ctx, item):
  """Wrapper for converting values.

  @param convert: Conversion function receiving value as single parameter
  @param fn: Retrieval function

  """
  value = fn(ctx, item)

  # Is the value an abnormal status?
  if compat.any(value is fs for fs in _FS_ALL):
    # Return right away
    return value

  # TODO: Should conversion function also receive context, item or both?
  return convert(value)


def _ConvWrap(convert, fn):
  """Convenience wrapper for L{_ConvWrapInner}.

  @param convert: Conversion function receiving value as single parameter
  @param fn: Retrieval function

  """
  return compat.partial(_ConvWrapInner, convert, fn)


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
    (_MakeField("ctime", "CTime", QFT_TIMESTAMP, "Creation timestamp"),
     datatype, 0, _GetItemTimestamp(operator.attrgetter("ctime"))),
    (_MakeField("mtime", "MTime", QFT_TIMESTAMP, "Modification timestamp"),
     datatype, 0, _GetItemTimestamp(operator.attrgetter("mtime"))),
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
  "drained": ("Drained", QFT_BOOL, 0, "Whether node is drained"),
  "master_candidate": ("MasterC", QFT_BOOL, 0,
                       "Whether node is a master candidate"),
  "master_capable": ("MasterCapable", QFT_BOOL, 0,
                     "Whether node can become a master candidate"),
  "name": ("Node", QFT_TEXT, QFF_HOSTNAME, "Node name"),
  "offline": ("Offline", QFT_BOOL, 0, "Whether node is marked offline"),
  "serial_no": ("SerialNo", QFT_NUMBER, 0, _SERIAL_NO_DOC % "Node"),
  "uuid": ("UUID", QFT_TEXT, 0, "Node UUID"),
  "vm_capable": ("VMCapable", QFT_BOOL, 0, "Whether node can host instances"),
  }


#: Fields requiring talking to the node
# Note that none of these are available for non-vm_capable nodes
_NODE_LIVE_FIELDS = {
  "bootid": ("BootID", QFT_TEXT, "bootid",
             "Random UUID renewed for each system reboot, can be used"
             " for detecting reboots by tracking changes"),
  "cnodes": ("CNodes", QFT_NUMBER, "cpu_nodes",
             "Number of NUMA domains on node (if exported by hypervisor)"),
  "csockets": ("CSockets", QFT_NUMBER, "cpu_sockets",
               "Number of physical CPU sockets (if exported by hypervisor)"),
  "ctotal": ("CTotal", QFT_NUMBER, "cpu_total", "Number of logical processors"),
  "dfree": ("DFree", QFT_UNIT, "vg_free",
            "Available disk space in volume group"),
  "dtotal": ("DTotal", QFT_UNIT, "vg_size",
             "Total disk space in volume group used for instance disk"
             " allocation"),
  "mfree": ("MFree", QFT_UNIT, "memory_free",
            "Memory available for instance allocations"),
  "mnode": ("MNode", QFT_UNIT, "memory_dom0",
            "Amount of memory used by node (dom0 for Xen)"),
  "mtotal": ("MTotal", QFT_UNIT, "memory_total",
             "Total amount of memory of physical machine"),
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


def _GetNodeGroup(ctx, node, ng): # pylint: disable=W0613
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

  if not node.vm_capable:
    return _FS_UNAVAIL

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
    (_MakeField("pip", "PrimaryIP", QFT_TEXT, "Primary IP address"),
     NQ_CONFIG, 0, _GetItemAttr("primary_ip")),
    (_MakeField("sip", "SecondaryIP", QFT_TEXT, "Secondary IP address"),
     NQ_CONFIG, 0, _GetItemAttr("secondary_ip")),
    (_MakeField("tags", "Tags", QFT_OTHER, "Tags"), NQ_CONFIG, 0,
     lambda ctx, node: list(node.GetTags())),
    (_MakeField("master", "IsMaster", QFT_BOOL, "Whether node is master"),
     NQ_CONFIG, 0, lambda ctx, node: node.name == ctx.master_name),
    (_MakeField("group", "Group", QFT_TEXT, "Node group"), NQ_GROUP, 0,
     _GetGroup(_GetNodeGroup)),
    (_MakeField("group.uuid", "GroupUUID", QFT_TEXT, "UUID of node group"),
     NQ_CONFIG, 0, _GetItemAttr("group")),
    (_MakeField("powered", "Powered", QFT_BOOL,
                "Whether node is thought to be powered on"),
     NQ_OOB, 0, _GetNodePower),
    (_MakeField("ndparams", "NodeParameters", QFT_OTHER,
                "Merged node parameters"),
     NQ_GROUP, 0, _GetGroup(_GetNdParams)),
    (_MakeField("custom_ndparams", "CustomNodeParameters", QFT_OTHER,
                "Custom node parameters"),
      NQ_GROUP, 0, _GetItemAttr("ndparams")),
    ]

  # Node role
  role_values = (constants.NR_MASTER, constants.NR_MCANDIDATE,
                 constants.NR_REGULAR, constants.NR_DRAINED,
                 constants.NR_OFFLINE)
  role_doc = ("Node role; \"%s\" for master, \"%s\" for master candidate,"
              " \"%s\" for regular, \"%s\" for a drained, \"%s\" for offline" %
              role_values)
  fields.append((_MakeField("role", "Role", QFT_TEXT, role_doc), NQ_CONFIG, 0,
                 lambda ctx, node: _GetNodeRole(node, ctx.master_name)))
  assert set(role_values) == constants.NR_ALL

  def _GetLength(getter):
    return lambda ctx, node: len(getter(ctx)[node.name])

  def _GetList(getter):
    return lambda ctx, node: list(getter(ctx)[node.name])

  # Add fields operating on instance lists
  for prefix, titleprefix, docword, getter in \
      [("p", "Pri", "primary", operator.attrgetter("node_to_primary")),
       ("s", "Sec", "secondary", operator.attrgetter("node_to_secondary"))]:
    # TODO: Allow filterting by hostname in list
    fields.extend([
      (_MakeField("%sinst_cnt" % prefix, "%sinst" % prefix.upper(), QFT_NUMBER,
                  "Number of instances with this node as %s" % docword),
       NQ_INST, 0, _GetLength(getter)),
      (_MakeField("%sinst_list" % prefix, "%sInstances" % titleprefix,
                  QFT_OTHER,
                  "List of instances with this node as %s" % docword),
       NQ_INST, 0, _GetList(getter)),
      ])

  # Add simple fields
  fields.extend([
    (_MakeField(name, title, kind, doc), NQ_CONFIG, flags, _GetItemAttr(name))
    for (name, (title, kind, flags, doc)) in _NODE_SIMPLE_FIELDS.items()
    ])

  # Add fields requiring live data
  fields.extend([
    (_MakeField(name, title, kind, doc), NQ_LIVE, 0,
     compat.partial(_GetLiveNodeField, nfield, kind))
    for (name, (title, kind, nfield, doc)) in _NODE_LIVE_FIELDS.items()
    ])

  # Add timestamps
  fields.extend(_GetItemTimestampFields(NQ_CONFIG))

  return _PrepareFieldList(fields, [])


class InstanceQueryData:
  """Data container for instance data queries.

  """
  def __init__(self, instances, cluster, disk_usage, offline_nodes, bad_nodes,
               live_data, wrongnode_inst, console, nodes, groups):
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
    @type console: dict; instance name as key
    @param console: Per-instance console information
    @type nodes: dict; node name as key
    @param nodes: Node objects

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
    self.console = console
    self.nodes = nodes
    self.groups = groups

    # Used for individual rows
    self.inst_hvparams = None
    self.inst_beparams = None
    self.inst_osparams = None
    self.inst_nicparams = None

  def __iter__(self):
    """Iterate over all instances.

    This function has side-effects and only one instance of the resulting
    generator should be used at a time.

    """
    for inst in self.instances:
      self.inst_hvparams = self.cluster.FillHV(inst, skip_globals=True)
      self.inst_beparams = self.cluster.FillBE(inst)
      self.inst_osparams = self.cluster.SimpleFillOS(inst.os, inst.osparams)
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
    return constants.INSTST_NODEOFFLINE

  if inst.primary_node in ctx.bad_nodes:
    return constants.INSTST_NODEDOWN

  if bool(ctx.live_data.get(inst.name)):
    if inst.name in ctx.wrongnode_inst:
      return constants.INSTST_WRONGNODE
    elif inst.admin_state == constants.ADMINST_UP:
      return constants.INSTST_RUNNING
    else:
      return constants.INSTST_ERRORUP

  if inst.admin_state == constants.ADMINST_UP:
    return constants.INSTST_ERRORDOWN
  elif inst.admin_state == constants.ADMINST_DOWN:
    return constants.INSTST_ADMINDOWN

  return constants.INSTST_ADMINOFFLINE


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


def _GetInstNicIp(ctx, _, nic): # pylint: disable=W0613
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

  @return: Tuple containing list of field definitions used as input for
    L{_PrepareFieldList} and a list of aliases

  """
  nic_mac_fn = lambda ctx, _, nic: nic.mac
  nic_mode_fn = _GetInstNicParam(constants.NIC_MODE)
  nic_link_fn = _GetInstNicParam(constants.NIC_LINK)

  fields = [
    # All NICs
    (_MakeField("nic.count", "NICs", QFT_NUMBER,
                "Number of network interfaces"),
     IQ_CONFIG, 0, lambda ctx, inst: len(inst.nics)),
    (_MakeField("nic.macs", "NIC_MACs", QFT_OTHER,
                "List containing each network interface's MAC address"),
     IQ_CONFIG, 0, lambda ctx, inst: [nic.mac for nic in inst.nics]),
    (_MakeField("nic.ips", "NIC_IPs", QFT_OTHER,
                "List containing each network interface's IP address"),
     IQ_CONFIG, 0, lambda ctx, inst: [nic.ip for nic in inst.nics]),
    (_MakeField("nic.modes", "NIC_modes", QFT_OTHER,
                "List containing each network interface's mode"), IQ_CONFIG, 0,
     lambda ctx, inst: [nicp[constants.NIC_MODE]
                        for nicp in ctx.inst_nicparams]),
    (_MakeField("nic.links", "NIC_links", QFT_OTHER,
                "List containing each network interface's link"), IQ_CONFIG, 0,
     lambda ctx, inst: [nicp[constants.NIC_LINK]
                        for nicp in ctx.inst_nicparams]),
    (_MakeField("nic.bridges", "NIC_bridges", QFT_OTHER,
                "List containing each network interface's bridge"),
     IQ_CONFIG, 0, _GetInstAllNicBridges),
    ]

  # NICs by number
  for i in range(constants.MAX_NICS):
    numtext = utils.FormatOrdinal(i + 1)
    fields.extend([
      (_MakeField("nic.ip/%s" % i, "NicIP/%s" % i, QFT_TEXT,
                  "IP address of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstNicIp)),
      (_MakeField("nic.mac/%s" % i, "NicMAC/%s" % i, QFT_TEXT,
                  "MAC address of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, nic_mac_fn)),
      (_MakeField("nic.mode/%s" % i, "NicMode/%s" % i, QFT_TEXT,
                  "Mode of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, nic_mode_fn)),
      (_MakeField("nic.link/%s" % i, "NicLink/%s" % i, QFT_TEXT,
                  "Link of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, nic_link_fn)),
      (_MakeField("nic.bridge/%s" % i, "NicBridge/%s" % i, QFT_TEXT,
                  "Bridge of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstNicBridge)),
      ])

  aliases = [
    # Legacy fields for first NIC
    ("ip", "nic.ip/0"),
    ("mac", "nic.mac/0"),
    ("bridge", "nic.bridge/0"),
    ("nic_mode", "nic.mode/0"),
    ("nic_link", "nic.link/0"),
    ]

  return (fields, aliases)


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


def _GetInstanceConsole(ctx, inst):
  """Get console information for instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  consinfo = ctx.console[inst.name]

  if consinfo is None:
    return _FS_UNAVAIL

  return consinfo


def _GetInstanceDiskFields():
  """Get instance fields involving disks.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
  fields = [
    (_MakeField("disk_usage", "DiskUsage", QFT_UNIT,
                "Total disk space used by instance on each of its nodes;"
                " this is not the disk size visible to the instance, but"
                " the usage on the node"),
     IQ_DISKUSAGE, 0, _GetInstDiskUsage),
    (_MakeField("disk.count", "Disks", QFT_NUMBER, "Number of disks"),
     IQ_CONFIG, 0, lambda ctx, inst: len(inst.disks)),
    (_MakeField("disk.sizes", "Disk_sizes", QFT_OTHER, "List of disk sizes"),
     IQ_CONFIG, 0, lambda ctx, inst: [disk.size for disk in inst.disks]),
    ]

  # Disks by number
  fields.extend([
    (_MakeField("disk.size/%s" % i, "Disk/%s" % i, QFT_UNIT,
                "Disk size of %s disk" % utils.FormatOrdinal(i + 1)),
     IQ_CONFIG, 0, _GetInstDiskSize(i))
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
    constants.BE_MAXMEM: "ConfigMaxMem",
    constants.BE_MINMEM: "ConfigMinMem",
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
    (_MakeField("hvparams", "HypervisorParameters", QFT_OTHER,
                "Hypervisor parameters (merged)"),
     IQ_CONFIG, 0, lambda ctx, _: ctx.inst_hvparams),
    (_MakeField("beparams", "BackendParameters", QFT_OTHER,
                "Backend parameters (merged)"),
     IQ_CONFIG, 0, lambda ctx, _: ctx.inst_beparams),
    (_MakeField("osparams", "OpSysParameters", QFT_OTHER,
                "Operating system parameters (merged)"),
     IQ_CONFIG, 0, lambda ctx, _: ctx.inst_osparams),

    # Unfilled parameters
    (_MakeField("custom_hvparams", "CustomHypervisorParameters", QFT_OTHER,
                "Custom hypervisor parameters"),
     IQ_CONFIG, 0, _GetItemAttr("hvparams")),
    (_MakeField("custom_beparams", "CustomBackendParameters", QFT_OTHER,
                "Custom backend parameters",),
     IQ_CONFIG, 0, _GetItemAttr("beparams")),
    (_MakeField("custom_osparams", "CustomOpSysParameters", QFT_OTHER,
                "Custom operating system parameters",),
     IQ_CONFIG, 0, _GetItemAttr("osparams")),
    (_MakeField("custom_nicparams", "CustomNicParameters", QFT_OTHER,
                "Custom network interface parameters"),
     IQ_CONFIG, 0, lambda ctx, inst: [nic.nicparams for nic in inst.nics]),
    ]

  # HV params
  def _GetInstHvParam(name):
    return lambda ctx, _: ctx.inst_hvparams.get(name, _FS_UNAVAIL)

  fields.extend([
    (_MakeField("hv/%s" % name, hv_title.get(name, "hv/%s" % name),
                _VTToQFT[kind], "The \"%s\" hypervisor parameter" % name),
     IQ_CONFIG, 0, _GetInstHvParam(name))
    for name, kind in constants.HVS_PARAMETER_TYPES.items()
    if name not in constants.HVC_GLOBALS
    ])

  # BE params
  def _GetInstBeParam(name):
    return lambda ctx, _: ctx.inst_beparams.get(name, None)

  fields.extend([
    (_MakeField("be/%s" % name, be_title.get(name, "be/%s" % name),
                _VTToQFT[kind], "The \"%s\" backend parameter" % name),
     IQ_CONFIG, 0, _GetInstBeParam(name))
    for name, kind in constants.BES_PARAMETER_TYPES.items()
    ])

  return fields


_INST_SIMPLE_FIELDS = {
  "disk_template": ("Disk_template", QFT_TEXT, 0, "Instance disk template"),
  "hypervisor": ("Hypervisor", QFT_TEXT, 0, "Hypervisor name"),
  "name": ("Instance", QFT_TEXT, QFF_HOSTNAME, "Instance name"),
  # Depending on the hypervisor, the port can be None
  "network_port": ("Network_port", QFT_OTHER, 0,
                   "Instance network port if available (e.g. for VNC console)"),
  "os": ("OS", QFT_TEXT, 0, "Operating system"),
  "serial_no": ("SerialNo", QFT_NUMBER, 0, _SERIAL_NO_DOC % "Instance"),
  "uuid": ("UUID", QFT_TEXT, 0, "Instance UUID"),
  }


def _GetInstNodeGroup(ctx, default, node_name):
  """Gets group UUID of an instance node.

  @type ctx: L{InstanceQueryData}
  @param default: Default value
  @type node_name: string
  @param node_name: Node name

  """
  try:
    node = ctx.nodes[node_name]
  except KeyError:
    return default
  else:
    return node.group


def _GetInstNodeGroupName(ctx, default, node_name):
  """Gets group name of an instance node.

  @type ctx: L{InstanceQueryData}
  @param default: Default value
  @type node_name: string
  @param node_name: Node name

  """
  try:
    node = ctx.nodes[node_name]
  except KeyError:
    return default

  try:
    group = ctx.groups[node.group]
  except KeyError:
    return default

  return group.name


def _BuildInstanceFields():
  """Builds list of fields for instance queries.

  """
  fields = [
    (_MakeField("pnode", "Primary_node", QFT_TEXT, "Primary node"),
     IQ_CONFIG, QFF_HOSTNAME, _GetItemAttr("primary_node")),
    (_MakeField("pnode.group", "PrimaryNodeGroup", QFT_TEXT,
                "Primary node's group"),
     IQ_NODES, 0,
     lambda ctx, inst: _GetInstNodeGroupName(ctx, _FS_UNAVAIL,
                                             inst.primary_node)),
    (_MakeField("pnode.group.uuid", "PrimaryNodeGroupUUID", QFT_TEXT,
                "Primary node's group UUID"),
     IQ_NODES, 0,
     lambda ctx, inst: _GetInstNodeGroup(ctx, _FS_UNAVAIL, inst.primary_node)),
    # TODO: Allow filtering by secondary node as hostname
    (_MakeField("snodes", "Secondary_Nodes", QFT_OTHER,
                "Secondary nodes; usually this will just be one node"),
     IQ_CONFIG, 0, lambda ctx, inst: list(inst.secondary_nodes)),
    (_MakeField("snodes.group", "SecondaryNodesGroups", QFT_OTHER,
                "Node groups of secondary nodes"),
     IQ_NODES, 0,
     lambda ctx, inst: map(compat.partial(_GetInstNodeGroupName, ctx, None),
                           inst.secondary_nodes)),
    (_MakeField("snodes.group.uuid", "SecondaryNodesGroupsUUID", QFT_OTHER,
                "Node group UUIDs of secondary nodes"),
     IQ_NODES, 0,
     lambda ctx, inst: map(compat.partial(_GetInstNodeGroup, ctx, None),
                           inst.secondary_nodes)),
    (_MakeField("admin_state", "InstanceState", QFT_TEXT,
                "Desired state of instance"),
     IQ_CONFIG, 0, _GetItemAttr("admin_state")),
    (_MakeField("admin_up", "Autostart", QFT_BOOL,
                "Desired state of instance"),
     IQ_CONFIG, 0, lambda ctx, inst: inst.admin_state == constants.ADMINST_UP),
    (_MakeField("tags", "Tags", QFT_OTHER, "Tags"), IQ_CONFIG, 0,
     lambda ctx, inst: list(inst.GetTags())),
    (_MakeField("console", "Console", QFT_OTHER,
                "Instance console information"), IQ_CONSOLE, 0,
     _GetInstanceConsole),
    ]

  # Add simple fields
  fields.extend([
    (_MakeField(name, title, kind, doc), IQ_CONFIG, flags, _GetItemAttr(name))
    for (name, (title, kind, flags, doc)) in _INST_SIMPLE_FIELDS.items()
    ])

  # Fields requiring talking to the node
  fields.extend([
    (_MakeField("oper_state", "Running", QFT_BOOL, "Actual state of instance"),
     IQ_LIVE, 0, _GetInstOperState),
    (_MakeField("oper_ram", "Memory", QFT_UNIT,
                "Actual memory usage as seen by hypervisor"),
     IQ_LIVE, 0, _GetInstLiveData("memory")),
    (_MakeField("oper_vcpus", "VCPUs", QFT_NUMBER,
                "Actual number of VCPUs as seen by hypervisor"),
     IQ_LIVE, 0, _GetInstLiveData("vcpus")),
    ])

  # Status field
  status_values = (constants.INSTST_RUNNING, constants.INSTST_ADMINDOWN,
                   constants.INSTST_WRONGNODE, constants.INSTST_ERRORUP,
                   constants.INSTST_ERRORDOWN, constants.INSTST_NODEDOWN,
                   constants.INSTST_NODEOFFLINE, constants.INSTST_ADMINOFFLINE)
  status_doc = ("Instance status; \"%s\" if instance is set to be running"
                " and actually is, \"%s\" if instance is stopped and"
                " is not running, \"%s\" if instance running, but not on its"
                " designated primary node, \"%s\" if instance should be"
                " stopped, but is actually running, \"%s\" if instance should"
                " run, but doesn't, \"%s\" if instance's primary node is down,"
                " \"%s\" if instance's primary node is marked offline,"
                " \"%s\" if instance is offline and does not use dynamic"
                " resources" % status_values)
  fields.append((_MakeField("status", "Status", QFT_TEXT, status_doc),
                 IQ_LIVE, 0, _GetInstStatus))
  assert set(status_values) == constants.INSTST_ALL, \
         "Status documentation mismatch"

  (network_fields, network_aliases) = _GetInstanceNetworkFields()

  fields.extend(network_fields)
  fields.extend(_GetInstanceParameterFields())
  fields.extend(_GetInstanceDiskFields())
  fields.extend(_GetItemTimestampFields(IQ_CONFIG))

  aliases = [
    ("vcpus", "be/vcpus"),
    ("be/memory", "be/maxmem"),
    ("sda_size", "disk.size/0"),
    ("sdb_size", "disk.size/1"),
    ] + network_aliases

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
    # TODO: Lock names are not always hostnames. Should QFF_HOSTNAME be used?
    (_MakeField("name", "Name", QFT_TEXT, "Lock name"), None, 0,
     lambda ctx, (name, mode, owners, pending): name),
    (_MakeField("mode", "Mode", QFT_OTHER,
                "Mode in which the lock is currently acquired"
                " (exclusive or shared)"),
     LQ_MODE, 0, lambda ctx, (name, mode, owners, pending): mode),
    (_MakeField("owner", "Owner", QFT_OTHER, "Current lock owner(s)"),
     LQ_OWNER, 0, _GetLockOwners),
    (_MakeField("pending", "Pending", QFT_OTHER,
                "Threads waiting for the lock"),
     LQ_PENDING, 0, _GetLockPending),
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
  "alloc_policy": ("AllocPolicy", QFT_TEXT, "Allocation policy for group"),
  "name": ("Group", QFT_TEXT, "Group name"),
  "serial_no": ("SerialNo", QFT_NUMBER, _SERIAL_NO_DOC % "Group"),
  "uuid": ("UUID", QFT_TEXT, "Group UUID"),
  "ndparams": ("NDParams", QFT_OTHER, "Node parameters"),
  }


def _BuildGroupFields():
  """Builds list of fields for node group queries.

  """
  # Add simple fields
  fields = [(_MakeField(name, title, kind, doc), GQ_CONFIG, 0,
             _GetItemAttr(name))
            for (name, (title, kind, doc)) in _GROUP_SIMPLE_FIELDS.items()]

  def _GetLength(getter):
    return lambda ctx, group: len(getter(ctx)[group.uuid])

  def _GetSortedList(getter):
    return lambda ctx, group: utils.NiceSort(getter(ctx)[group.uuid])

  group_to_nodes = operator.attrgetter("group_to_nodes")
  group_to_instances = operator.attrgetter("group_to_instances")

  # Add fields for nodes
  fields.extend([
    (_MakeField("node_cnt", "Nodes", QFT_NUMBER, "Number of nodes"),
     GQ_NODE, 0, _GetLength(group_to_nodes)),
    (_MakeField("node_list", "NodeList", QFT_OTHER, "List of nodes"),
     GQ_NODE, 0, _GetSortedList(group_to_nodes)),
    ])

  # Add fields for instances
  fields.extend([
    (_MakeField("pinst_cnt", "Instances", QFT_NUMBER,
                "Number of primary instances"),
     GQ_INST, 0, _GetLength(group_to_instances)),
    (_MakeField("pinst_list", "InstanceList", QFT_OTHER,
                "List of primary instances"),
     GQ_INST, 0, _GetSortedList(group_to_instances)),
    ])

  # Other fields
  fields.extend([
    (_MakeField("tags", "Tags", QFT_OTHER, "Tags"), GQ_CONFIG, 0,
     lambda ctx, group: list(group.GetTags())),
    ])

  fields.extend(_GetItemTimestampFields(GQ_CONFIG))

  return _PrepareFieldList(fields, [])


class OsInfo(objects.ConfigObject):
  __slots__ = [
    "name",
    "valid",
    "hidden",
    "blacklisted",
    "variants",
    "api_versions",
    "parameters",
    "node_status",
    ]


def _BuildOsFields():
  """Builds list of fields for operating system queries.

  """
  fields = [
    (_MakeField("name", "Name", QFT_TEXT, "Operating system name"),
     None, 0, _GetItemAttr("name")),
    (_MakeField("valid", "Valid", QFT_BOOL,
                "Whether operating system definition is valid"),
     None, 0, _GetItemAttr("valid")),
    (_MakeField("hidden", "Hidden", QFT_BOOL,
                "Whether operating system is hidden"),
     None, 0, _GetItemAttr("hidden")),
    (_MakeField("blacklisted", "Blacklisted", QFT_BOOL,
                "Whether operating system is blacklisted"),
     None, 0, _GetItemAttr("blacklisted")),
    (_MakeField("variants", "Variants", QFT_OTHER,
                "Operating system variants"),
     None, 0, _ConvWrap(utils.NiceSort, _GetItemAttr("variants"))),
    (_MakeField("api_versions", "ApiVersions", QFT_OTHER,
                "Operating system API versions"),
     None, 0, _ConvWrap(sorted, _GetItemAttr("api_versions"))),
    (_MakeField("parameters", "Parameters", QFT_OTHER,
                "Operating system parameters"),
     None, 0, _ConvWrap(compat.partial(utils.NiceSort, key=compat.fst),
                        _GetItemAttr("parameters"))),
    (_MakeField("node_status", "NodeStatus", QFT_OTHER,
                "Status from node"),
     None, 0, _GetItemAttr("node_status")),
    ]

  return _PrepareFieldList(fields, [])


#: Fields available for node queries
NODE_FIELDS = _BuildNodeFields()

#: Fields available for instance queries
INSTANCE_FIELDS = _BuildInstanceFields()

#: Fields available for lock queries
LOCK_FIELDS = _BuildLockFields()

#: Fields available for node group queries
GROUP_FIELDS = _BuildGroupFields()

#: Fields available for operating system queries
OS_FIELDS = _BuildOsFields()

#: All available resources
ALL_FIELDS = {
  constants.QR_INSTANCE: INSTANCE_FIELDS,
  constants.QR_NODE: NODE_FIELDS,
  constants.QR_LOCK: LOCK_FIELDS,
  constants.QR_GROUP: GROUP_FIELDS,
  constants.QR_OS: OS_FIELDS,
  }

#: All available field lists
ALL_FIELD_LISTS = ALL_FIELDS.values()
