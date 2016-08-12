#
#

# Copyright (C) 2010, 2011, 2012, 2013 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


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
from ganeti import runtime
from ganeti import qlang
from ganeti import jstore
from ganeti.hypervisor import hv_base

from ganeti.constants import (QFT_UNKNOWN, QFT_TEXT, QFT_BOOL, QFT_NUMBER,
                              QFT_NUMBER_FLOAT, QFT_UNIT, QFT_TIMESTAMP,
                              QFT_OTHER, RS_NORMAL, RS_UNKNOWN, RS_NODATA,
                              RS_UNAVAIL, RS_OFFLINE)

(NETQ_CONFIG,
 NETQ_GROUP,
 NETQ_STATS,
 NETQ_INST) = range(300, 304)

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
 IQ_NODES,
 IQ_NETWORKS) = range(100, 106)

(LQ_MODE,
 LQ_OWNER,
 LQ_PENDING) = range(10, 13)

(GQ_CONFIG,
 GQ_NODE,
 GQ_INST,
 GQ_DISKPARAMS) = range(200, 204)

(CQ_CONFIG,
 CQ_QUEUE_DRAINED,
 CQ_WATCHER_PAUSE) = range(300, 303)

(JQ_ARCHIVED, ) = range(400, 401)

# Query field flags
QFF_HOSTNAME = 0x01
QFF_IP_ADDRESS = 0x02
QFF_JOB_ID = 0x04
QFF_SPLIT_TIMESTAMP = 0x08
# Next values: 0x10, 0x20, 0x40, 0x80, 0x100, 0x200
QFF_ALL = (QFF_HOSTNAME | QFF_IP_ADDRESS | QFF_JOB_ID | QFF_SPLIT_TIMESTAMP)

FIELD_NAME_RE = re.compile(r"^[a-z0-9/._]+$")
TITLE_RE = re.compile(r"^[^\s]+$")
DOC_RE = re.compile(r"^[A-Z].*[^.,?!]$")

#: Verification function for each field type
_VERIFY_FN = {
  QFT_UNKNOWN: ht.TNone,
  QFT_TEXT: ht.TString,
  QFT_BOOL: ht.TBool,
  QFT_NUMBER: ht.TInt,
  QFT_NUMBER_FLOAT: ht.TFloat,
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
_FS_ALL = compat.UniqueFrozenset([
  _FS_UNKNOWN,
  _FS_NODATA,
  _FS_UNAVAIL,
  _FS_OFFLINE,
  ])

#: VType to QFT mapping
_VTToQFT = {
  # TODO: fix validation of empty strings
  constants.VTYPE_STRING: QFT_OTHER, # since VTYPE_STRINGs can be empty
  constants.VTYPE_MAYBE_STRING: QFT_OTHER,
  constants.VTYPE_BOOL: QFT_BOOL,
  constants.VTYPE_SIZE: QFT_UNIT,
  constants.VTYPE_INT: QFT_NUMBER,
  constants.VTYPE_FLOAT: QFT_NUMBER_FLOAT,
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


class _FilterHints(object):
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

  def NoteUnaryOp(self, op, datakind): # pylint: disable=W0613
    """Called when handling an unary operation.

    @type op: string
    @param op: Operator

    """
    if datakind is not None:
      self._datakinds.add(datakind)

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
    EQ_OPS = [qlang.OP_EQUAL, qlang.OP_EQUAL_LEGACY]
    if op in EQ_OPS and name == self._namefield:
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


def _PrepareSplitTimestamp(value):
  """Prepares a value for comparison by L{_MakeSplitTimestampComparison}.

  """
  if ht.TNumber(value):
    return value
  else:
    return utils.MergeTime(value)


def _MakeSplitTimestampComparison(fn):
  """Compares split timestamp values after converting to float.

  """
  return lambda lhs, rhs: fn(utils.MergeTime(lhs), rhs)


def _MakeComparisonChecks(fn):
  """Prepares flag-specific comparisons using a comparison function.

  """
  return [
    (QFF_SPLIT_TIMESTAMP, _MakeSplitTimestampComparison(fn),
     _PrepareSplitTimestamp),
    (QFF_JOB_ID, lambda lhs, rhs: fn(jstore.ParseJobId(lhs), rhs),
     jstore.ParseJobId),
    (None, fn, None),
    ]


class _FilterCompilerHelper(object):
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
  (e.g. L{QFF_HOSTNAME} or L{QFF_SPLIT_TIMESTAMP}).

  Order matters. The first item with flags will be used. Flags are checked
  using binary AND.

  """
  _EQUALITY_CHECKS = [
    (QFF_HOSTNAME,
     lambda lhs, rhs: utils.MatchNameComponent(rhs, [lhs],
                                               case_sensitive=False),
     None),
    (QFF_SPLIT_TIMESTAMP, _MakeSplitTimestampComparison(operator.eq),
     _PrepareSplitTimestamp),
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
    qlang.OP_EQUAL_LEGACY: (_OPTYPE_BINARY, _EQUALITY_CHECKS),
    qlang.OP_NOT_EQUAL:
      (_OPTYPE_BINARY, [(flags, compat.partial(_WrapNot, fn), valprepfn)
                        for (flags, fn, valprepfn) in _EQUALITY_CHECKS]),
    qlang.OP_LT: (_OPTYPE_BINARY, _MakeComparisonChecks(operator.lt)),
    qlang.OP_LE: (_OPTYPE_BINARY, _MakeComparisonChecks(operator.le)),
    qlang.OP_GT: (_OPTYPE_BINARY, _MakeComparisonChecks(operator.gt)),
    qlang.OP_GE: (_OPTYPE_BINARY, _MakeComparisonChecks(operator.ge)),
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

    if len(operands) != 1:
      raise errors.ParameterError("Unary operator '%s' expects exactly one"
                                  " operand" % op)

    if op == qlang.OP_TRUE:
      (_, datakind, _, retrieval_fn) = self._LookupField(operands[0])

      if hints_fn:
        hints_fn(op, datakind)

      op_fn = operator.truth
      arg = retrieval_fn
    elif op == qlang.OP_NOT:
      if hints_fn:
        hints_fn(op, None)

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


class Query(object):
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
        # Answer: if the name field is non-string...
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


def _StaticValueInner(value, ctx, _): # pylint: disable=W0613
  """Returns a static value.

  """
  return value


def _StaticValue(value):
  """Prepares a function to return a static value.

  """
  return compat.partial(_StaticValueInner, value)


def _GetNodeRole(node, master_uuid):
  """Determine node role.

  @type node: L{objects.Node}
  @param node: Node object
  @type master_uuid: string
  @param master_uuid: Master node UUID

  """
  if node.uuid == master_uuid:
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


def _GetItemMaybeAttr(attr):
  """Returns a field function to return a not-None attribute of the item.

  If the value is None, then C{_FS_UNAVAIL} will be returned instead.

  @param attr: Attribute name

  """
  def _helper(_, obj):
    val = getattr(obj, attr)
    if val is None:
      return _FS_UNAVAIL
    else:
      return val
  return _helper


def _GetNDParam(name):
  """Return a field function to return an ND parameter out of the context.

  """
  def _helper(ctx, _):
    if ctx.ndparams is None:
      return _FS_UNAVAIL
    else:
      return ctx.ndparams.get(name, None)
  return _helper


def _BuildNDFields(is_group):
  """Builds all the ndparam fields.

  @param is_group: whether this is called at group or node level

  """
  if is_group:
    field_kind = GQ_CONFIG
  else:
    field_kind = NQ_GROUP
  return [(_MakeField("ndp/%s" % name,
                      constants.NDS_PARAMETER_TITLES.get(name,
                                                         "ndp/%s" % name),
                      _VTToQFT[kind], "The \"%s\" node parameter" % name),
           field_kind, 0, _GetNDParam(name))
          for name, kind in constants.NDS_PARAMETER_TYPES.items()]


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


class NodeQueryData(object):
  """Data container for node data queries.

  """
  def __init__(self, nodes, live_data, master_uuid, node_to_primary,
               node_to_secondary, inst_uuid_to_inst_name, groups, oob_support,
               cluster):
    """Initializes this class.

    """
    self.nodes = nodes
    self.live_data = live_data
    self.master_uuid = master_uuid
    self.node_to_primary = node_to_primary
    self.node_to_secondary = node_to_secondary
    self.inst_uuid_to_inst_name = inst_uuid_to_inst_name
    self.groups = groups
    self.oob_support = oob_support
    self.cluster = cluster

    # Used for individual rows
    self.curlive_data = None
    self.ndparams = None

  def __iter__(self):
    """Iterate over all nodes.

    This function has side-effects and only one instance of the resulting
    generator should be used at a time.

    """
    for node in self.nodes:
      group = self.groups.get(node.group, None)
      if group is None:
        self.ndparams = None
      else:
        self.ndparams = self.cluster.FillND(node, group)
      if self.live_data:
        self.curlive_data = self.live_data.get(node.uuid, None)
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
  "cnos": ("CNOs", QFT_NUMBER, "cpu_dom0",
            "Number of logical processors used by the node OS (dom0 for Xen)"),
  "csockets": ("CSockets", QFT_NUMBER, "cpu_sockets",
               "Number of physical CPU sockets (if exported by hypervisor)"),
  "ctotal": ("CTotal", QFT_NUMBER, "cpu_total", "Number of logical processors"),
  "dfree": ("DFree", QFT_UNIT, "storage_free",
            "Available storage space in storage unit"),
  "dtotal": ("DTotal", QFT_UNIT, "storage_size",
             "Total storage space in storage unit used for instance disk"
             " allocation"),
  "spfree": ("SpFree", QFT_NUMBER, "spindles_free",
             "Available spindles in volume group (exclusive storage only)"),
  "sptotal": ("SpTotal", QFT_NUMBER, "spindles_total",
              "Total spindles in volume group (exclusive storage only)"),
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
  if ctx.oob_support[node.uuid]:
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

  return _GetStatsField(field, kind, ctx.curlive_data)


def _GetStatsField(field, kind, data):
  """Gets a value from live statistics.

  If the value is not found, L{_FS_UNAVAIL} is returned. If the field kind is
  numeric a conversion to integer is attempted. If that fails, L{_FS_UNAVAIL}
  is returned.

  @param field: Live field name
  @param kind: Data kind, one of L{constants.QFT_ALL}
  @type data: dict
  @param data: Statistics

  """
  try:
    value = data[field]
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
                      field, value)
    return _FS_UNAVAIL


def _GetNodeHvState(_, node):
  """Converts node's hypervisor state for query result.

  """
  hv_state = node.hv_state

  if hv_state is None:
    return _FS_UNAVAIL

  return dict((name, value.ToDict()) for (name, value) in hv_state.items())


def _GetNodeDiskState(_, node):
  """Converts node's disk state for query result.

  """
  disk_state = node.disk_state

  if disk_state is None:
    return _FS_UNAVAIL

  return dict((disk_kind, dict((name, value.ToDict())
                               for (name, value) in kind_state.items()))
              for (disk_kind, kind_state) in disk_state.items())


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
     NQ_CONFIG, 0, lambda ctx, node: node.uuid == ctx.master_uuid),
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
    (_MakeField("hv_state", "HypervisorState", QFT_OTHER, "Hypervisor state"),
     NQ_CONFIG, 0, _GetNodeHvState),
    (_MakeField("disk_state", "DiskState", QFT_OTHER, "Disk state"),
     NQ_CONFIG, 0, _GetNodeDiskState),
    ]

  fields.extend(_BuildNDFields(False))

  # Node role
  role_values = (constants.NR_MASTER, constants.NR_MCANDIDATE,
                 constants.NR_REGULAR, constants.NR_DRAINED,
                 constants.NR_OFFLINE)
  role_doc = ("Node role; \"%s\" for master, \"%s\" for master candidate,"
              " \"%s\" for regular, \"%s\" for drained, \"%s\" for offline" %
              role_values)
  fields.append((_MakeField("role", "Role", QFT_TEXT, role_doc), NQ_CONFIG, 0,
                 lambda ctx, node: _GetNodeRole(node, ctx.master_uuid)))
  assert set(role_values) == constants.NR_ALL

  def _GetLength(getter):
    return lambda ctx, node: len(getter(ctx)[node.uuid])

  def _GetList(getter):
    return lambda ctx, node: utils.NiceSort(
                               [ctx.inst_uuid_to_inst_name[uuid]
                                for uuid in getter(ctx)[node.uuid]])

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
    for (name, (title, kind, flags, doc)) in _NODE_SIMPLE_FIELDS.items()])

  # Add fields requiring live data
  fields.extend([
    (_MakeField(name, title, kind, doc), NQ_LIVE, 0,
     compat.partial(_GetLiveNodeField, nfield, kind))
    for (name, (title, kind, nfield, doc)) in _NODE_LIVE_FIELDS.items()])

  # Add timestamps
  fields.extend(_GetItemTimestampFields(NQ_CONFIG))

  return _PrepareFieldList(fields, [])


class InstanceQueryData(object):
  """Data container for instance data queries.

  """
  def __init__(self, instances, cluster, disk_usage, offline_node_uuids,
               bad_node_uuids, live_data, wrongnode_inst, console, nodes,
               groups, networks):
    """Initializes this class.

    @param instances: List of instance objects
    @param cluster: Cluster object
    @type disk_usage: dict; instance UUID as key
    @param disk_usage: Per-instance disk usage
    @type offline_node_uuids: list of strings
    @param offline_node_uuids: List of offline nodes
    @type bad_node_uuids: list of strings
    @param bad_node_uuids: List of faulty nodes
    @type live_data: dict; instance UUID as key
    @param live_data: Per-instance live data
    @type wrongnode_inst: set
    @param wrongnode_inst: Set of instances running on wrong node(s)
    @type console: dict; instance UUID as key
    @param console: Per-instance console information
    @type nodes: dict; node UUID as key
    @param nodes: Node objects
    @type networks: dict; net_uuid as key
    @param networks: Network objects

    """
    assert len(set(bad_node_uuids) & set(offline_node_uuids)) == \
           len(offline_node_uuids), \
           "Offline nodes not included in bad nodes"
    assert not (set(live_data.keys()) & set(bad_node_uuids)), \
           "Found live data for bad or offline nodes"

    self.instances = instances
    self.cluster = cluster
    self.disk_usage = disk_usage
    self.offline_nodes = offline_node_uuids
    self.bad_nodes = bad_node_uuids
    self.live_data = live_data
    self.wrongnode_inst = wrongnode_inst
    self.console = console
    self.nodes = nodes
    self.groups = groups
    self.networks = networks

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
    return bool(ctx.live_data.get(inst.uuid))


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

    if inst.uuid in ctx.live_data:
      data = ctx.live_data[inst.uuid]
      if name in data:
        return data[name]

    return _FS_UNAVAIL

  return fn


def _GetLiveInstStatus(ctx, instance, instance_state):
  hvparams = ctx.cluster.FillHV(instance, skip_globals=True)

  allow_userdown = \
      ctx.cluster.enabled_user_shutdown and \
      (instance.hypervisor != constants.HT_KVM or
       hvparams[constants.HV_KVM_USER_SHUTDOWN])

  if instance.uuid in ctx.wrongnode_inst:
    return constants.INSTST_WRONGNODE
  else:
    if hv_base.HvInstanceState.IsShutdown(instance_state):
      if instance.admin_state == constants.ADMINST_UP and allow_userdown:
        return constants.INSTST_USERDOWN
      elif instance.admin_state == constants.ADMINST_UP:
        return constants.INSTST_ERRORDOWN
      else:
        return constants.INSTST_ADMINDOWN
    else:
      if instance.admin_state == constants.ADMINST_UP:
        return constants.INSTST_RUNNING
      else:
        return constants.INSTST_ERRORUP


def _GetDeadInstStatus(inst):
  if inst.admin_state == constants.ADMINST_UP:
    return constants.INSTST_ERRORDOWN
  elif inst.admin_state == constants.ADMINST_DOWN:
    if inst.admin_state_source == constants.USER_SOURCE:
      return constants.INSTST_USERDOWN
    else:
      return constants.INSTST_ADMINDOWN
  else:
    return constants.INSTST_ADMINOFFLINE


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

  instance_live_data = ctx.live_data.get(inst.uuid)

  if bool(instance_live_data):
    return _GetLiveInstStatus(ctx, inst, instance_live_data["state"])
  else:
    return _GetDeadInstStatus(inst)


def _GetInstDisk(index, cb):
  """Build function for calling another function with an instance Disk.

  @type index: int
  @param index: Disk index
  @type cb: callable
  @param cb: Callback

  """
  def fn(ctx, inst):
    """Call helper function with instance Disk.

    @type ctx: L{InstanceQueryData}
    @type inst: L{objects.Instance}
    @param inst: Instance object

    """
    try:
      nic = inst.disks[index]
    except IndexError:
      return _FS_UNAVAIL

    return cb(ctx, index, nic)

  return fn


def _GetInstDiskSize(ctx, _, disk): # pylint: disable=W0613
  """Get a Disk's size.

  @type ctx: L{InstanceQueryData}
  @type disk: L{objects.Disk}
  @param disk: The Disk object

  """
  if disk.size is None:
    return _FS_UNAVAIL
  else:
    return disk.size


def _GetInstDiskSpindles(ctx, _, disk): # pylint: disable=W0613
  """Get a Disk's spindles.

  @type disk: L{objects.Disk}
  @param disk: The Disk object

  """
  if disk.spindles is None:
    return _FS_UNAVAIL
  else:
    return disk.spindles


def _GetInstDeviceName(ctx, _, device): # pylint: disable=W0613
  """Get a Device's Name.

  @type ctx: L{InstanceQueryData}
  @type device: L{objects.NIC} or L{objects.Disk}
  @param device: The NIC or Disk object

  """
  if device.name is None:
    return _FS_UNAVAIL
  else:
    return device.name


def _GetInstDeviceUUID(ctx, _, device): # pylint: disable=W0613
  """Get a Device's UUID.

  @type ctx: L{InstanceQueryData}
  @type device: L{objects.NIC} or L{objects.Disk}
  @param device: The NIC or Disk object

  """
  if device.uuid is None:
    return _FS_UNAVAIL
  else:
    return device.uuid


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


def _GetInstNicNetworkName(ctx, _, nic): # pylint: disable=W0613
  """Get a NIC's Network.

  @type ctx: L{InstanceQueryData}
  @type nic: L{objects.NIC}
  @param nic: NIC object

  """
  if nic.network is None:
    return _FS_UNAVAIL
  else:
    return ctx.networks[nic.network].name


def _GetInstNicNetwork(ctx, _, nic): # pylint: disable=W0613
  """Get a NIC's Network.

  @type ctx: L{InstanceQueryData}
  @type nic: L{objects.NIC}
  @param nic: NIC object

  """
  if nic.network is None:
    return _FS_UNAVAIL
  else:
    return nic.network


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


def _GetInstNicVLan(ctx, index, _):
  """Get a NIC's VLAN.

  @type ctx: L{InstanceQueryData}
  @type index: int
  @param index: NIC index

  """
  assert len(ctx.inst_nicparams) >= index

  nicparams = ctx.inst_nicparams[index]

  if nicparams[constants.NIC_MODE] == constants.NIC_MODE_OVS:
    return nicparams[constants.NIC_VLAN]
  else:
    return _FS_UNAVAIL


def _GetInstAllNicNetworkNames(ctx, inst):
  """Get all network names for an instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  result = []

  for nic in inst.nics:
    name = None
    if nic.network:
      name = ctx.networks[nic.network].name
    result.append(name)

  assert len(result) == len(inst.nics)

  return result


def _GetInstAllNicVlans(ctx, inst):
  """Get all network VLANs for an instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  assert len(ctx.inst_nicparams) == len(inst.nics)

  result = []

  for nicp in ctx.inst_nicparams:
    if nicp[constants.NIC_MODE] in \
          [constants.NIC_MODE_BRIDGED, constants.NIC_MODE_OVS]:
      result.append(nicp[constants.NIC_VLAN])
    else:
      result.append(None)

  assert len(result) == len(inst.nics)

  return result


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
    (_MakeField("nic.names", "NIC_Names", QFT_OTHER,
                "List containing each network interface's name"),
     IQ_CONFIG, 0, lambda ctx, inst: [nic.name for nic in inst.nics]),
    (_MakeField("nic.uuids", "NIC_UUIDs", QFT_OTHER,
                "List containing each network interface's UUID"),
     IQ_CONFIG, 0, lambda ctx, inst: [nic.uuid for nic in inst.nics]),
    (_MakeField("nic.modes", "NIC_modes", QFT_OTHER,
                "List containing each network interface's mode"), IQ_CONFIG, 0,
     lambda ctx, inst: [nicp[constants.NIC_MODE]
                        for nicp in ctx.inst_nicparams]),
    (_MakeField("nic.links", "NIC_links", QFT_OTHER,
                "List containing each network interface's link"), IQ_CONFIG, 0,
     lambda ctx, inst: [nicp[constants.NIC_LINK]
                        for nicp in ctx.inst_nicparams]),
    (_MakeField("nic.vlans", "NIC_VLANs", QFT_OTHER,
                "List containing each network interface's VLAN"),
     IQ_CONFIG, 0, _GetInstAllNicVlans),
    (_MakeField("nic.bridges", "NIC_bridges", QFT_OTHER,
                "List containing each network interface's bridge"),
     IQ_CONFIG, 0, _GetInstAllNicBridges),
    (_MakeField("nic.networks", "NIC_networks", QFT_OTHER,
                "List containing each interface's network"), IQ_CONFIG, 0,
     lambda ctx, inst: [nic.network for nic in inst.nics]),
    (_MakeField("nic.networks.names", "NIC_networks_names", QFT_OTHER,
                "List containing each interface's network"),
     IQ_NETWORKS, 0, _GetInstAllNicNetworkNames)
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
      (_MakeField("nic.name/%s" % i, "NicName/%s" % i, QFT_TEXT,
                  "Name address of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstDeviceName)),
      (_MakeField("nic.uuid/%s" % i, "NicUUID/%s" % i, QFT_TEXT,
                  "UUID address of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstDeviceUUID)),
      (_MakeField("nic.mode/%s" % i, "NicMode/%s" % i, QFT_TEXT,
                  "Mode of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, nic_mode_fn)),
      (_MakeField("nic.link/%s" % i, "NicLink/%s" % i, QFT_TEXT,
                  "Link of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, nic_link_fn)),
      (_MakeField("nic.bridge/%s" % i, "NicBridge/%s" % i, QFT_TEXT,
                  "Bridge of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstNicBridge)),
      (_MakeField("nic.vlan/%s" % i, "NicVLAN/%s" % i, QFT_TEXT,
                  "VLAN of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstNicVLan)),
      (_MakeField("nic.network/%s" % i, "NicNetwork/%s" % i, QFT_TEXT,
                  "Network of %s network interface" % numtext),
       IQ_CONFIG, 0, _GetInstNic(i, _GetInstNicNetwork)),
      (_MakeField("nic.network.name/%s" % i, "NicNetworkName/%s" % i, QFT_TEXT,
                  "Network name of %s network interface" % numtext),
       IQ_NETWORKS, 0, _GetInstNic(i, _GetInstNicNetworkName)),
      ])

  aliases = [
    # Legacy fields for first NIC
    ("ip", "nic.ip/0"),
    ("mac", "nic.mac/0"),
    ("bridge", "nic.bridge/0"),
    ("nic_mode", "nic.mode/0"),
    ("nic_link", "nic.link/0"),
    ("nic_network", "nic.network/0"),
    ]

  return (fields, aliases)


def _GetInstDiskUsage(ctx, inst):
  """Get disk usage for an instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  usage = ctx.disk_usage[inst.uuid]

  if usage is None:
    usage = 0

  return usage


def _GetInstanceConsole(ctx, inst):
  """Get console information for instance.

  @type ctx: L{InstanceQueryData}
  @type inst: L{objects.Instance}
  @param inst: Instance object

  """
  consinfo = ctx.console[inst.uuid]

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
    (_MakeField("disk.spindles", "Disk_spindles", QFT_OTHER,
                "List of disk spindles"),
     IQ_CONFIG, 0, lambda ctx, inst: [disk.spindles for disk in inst.disks]),
    (_MakeField("disk.names", "Disk_names", QFT_OTHER, "List of disk names"),
     IQ_CONFIG, 0, lambda ctx, inst: [disk.name for disk in inst.disks]),
    (_MakeField("disk.uuids", "Disk_UUIDs", QFT_OTHER, "List of disk UUIDs"),
     IQ_CONFIG, 0, lambda ctx, inst: [disk.uuid for disk in inst.disks]),
    ]

  # Disks by number
  for i in range(constants.MAX_DISKS):
    numtext = utils.FormatOrdinal(i + 1)
    fields.extend([
        (_MakeField("disk.size/%s" % i, "Disk/%s" % i, QFT_UNIT,
                    "Disk size of %s disk" % numtext),
         IQ_CONFIG, 0, _GetInstDisk(i, _GetInstDiskSize)),
        (_MakeField("disk.spindles/%s" % i, "DiskSpindles/%s" % i, QFT_NUMBER,
                    "Spindles of %s disk" % numtext),
         IQ_CONFIG, 0, _GetInstDisk(i, _GetInstDiskSpindles)),
        (_MakeField("disk.name/%s" % i, "DiskName/%s" % i, QFT_TEXT,
                    "Name of %s disk" % numtext),
         IQ_CONFIG, 0, _GetInstDisk(i, _GetInstDeviceName)),
        (_MakeField("disk.uuid/%s" % i, "DiskUUID/%s" % i, QFT_TEXT,
                    "UUID of %s disk" % numtext),
         IQ_CONFIG, 0, _GetInstDisk(i, _GetInstDeviceUUID))])

  return fields


def _GetInstanceParameterFields():
  """Get instance fields involving parameters.

  @return: List of field definitions used as input for L{_PrepareFieldList}

  """
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
    (_MakeField("hv/%s" % name,
                constants.HVS_PARAMETER_TITLES.get(name, "hv/%s" % name),
                _VTToQFT[kind], "The \"%s\" hypervisor parameter" % name),
     IQ_CONFIG, 0, _GetInstHvParam(name))
    for name, kind in constants.HVS_PARAMETER_TYPES.items()
    if name not in constants.HVC_GLOBALS])

  # BE params
  def _GetInstBeParam(name):
    return lambda ctx, _: ctx.inst_beparams.get(name, None)

  fields.extend([
    (_MakeField("be/%s" % name,
                constants.BES_PARAMETER_TITLES.get(name, "be/%s" % name),
                _VTToQFT[kind], "The \"%s\" backend parameter" % name),
     IQ_CONFIG, 0, _GetInstBeParam(name))
    for name, kind in constants.BES_PARAMETER_TYPES.items()])

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


def _GetNodeName(ctx, default, node_uuid):
  """Gets node name of a node.

  @type ctx: L{InstanceQueryData}
  @param default: Default value
  @type node_uuid: string
  @param node_uuid: Node UUID

  """
  try:
    node = ctx.nodes[node_uuid]
  except KeyError:
    return default
  else:
    return node.name


def _GetInstNodeGroup(ctx, default, node_uuid):
  """Gets group UUID of an instance node.

  @type ctx: L{InstanceQueryData}
  @param default: Default value
  @type node_uuid: string
  @param node_uuid: Node UUID

  """
  try:
    node = ctx.nodes[node_uuid]
  except KeyError:
    return default
  else:
    return node.group


def _GetInstNodeGroupName(ctx, default, node_uuid):
  """Gets group name of an instance node.

  @type ctx: L{InstanceQueryData}
  @param default: Default value
  @type node_uuid: string
  @param node_uuid: Node UUID

  """
  try:
    node = ctx.nodes[node_uuid]
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
     IQ_NODES, QFF_HOSTNAME,
     lambda ctx, inst: _GetNodeName(ctx, None, inst.primary_node)),
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
     IQ_NODES, 0,
     lambda ctx, inst: [
       _GetNodeName(ctx, None, uuid) for uuid in inst.secondary_nodes
     ]),
    (_MakeField("snodes.group", "SecondaryNodesGroups", QFT_OTHER,
                "Node groups of secondary nodes"),
     IQ_NODES, 0,
     lambda ctx, inst: [
       _GetInstNodeGroupName(ctx, None, uuid) for uuid in inst.secondary_nodes
     ]),
    (_MakeField("snodes.group.uuid", "SecondaryNodesGroupsUUID", QFT_OTHER,
                "Node group UUIDs of secondary nodes"),
     IQ_NODES, 0,
     lambda ctx, inst: [
       _GetInstNodeGroup(ctx, None, uuid) for uuid in inst.secondary_nodes
     ]),
    (_MakeField("admin_state", "InstanceState", QFT_TEXT,
                "Desired state of the instance"),
     IQ_CONFIG, 0, _GetItemAttr("admin_state")),
    (_MakeField("admin_up", "Autostart", QFT_BOOL,
                "Desired state of the instance"),
     IQ_CONFIG, 0, lambda ctx, inst: inst.admin_state == constants.ADMINST_UP),
    (_MakeField("admin_state_source", "InstanceStateSource", QFT_TEXT,
                "Who last changed the desired state of the instance"),
     IQ_CONFIG, 0, _GetItemAttr("admin_state_source")),
    (_MakeField("disks_active", "DisksActive", QFT_BOOL,
                "Desired state of the instance disks"),
     IQ_CONFIG, 0, _GetItemAttr("disks_active")),
    (_MakeField("tags", "Tags", QFT_OTHER, "Tags"), IQ_CONFIG, 0,
     lambda ctx, inst: list(inst.GetTags())),
    (_MakeField("console", "Console", QFT_OTHER,
                "Instance console information"), IQ_CONSOLE, 0,
     _GetInstanceConsole),
    (_MakeField("forthcoming", "Forthcoming", QFT_BOOL,
                "Whether the Instance is forthcoming"), IQ_CONFIG, 0,
     lambda _, inst: bool(inst.forthcoming)),
    ]

  # Add simple fields
  fields.extend([
    (_MakeField(name, title, kind, doc), IQ_CONFIG, flags, _GetItemAttr(name))
    for (name, (title, kind, flags, doc)) in _INST_SIMPLE_FIELDS.items()])

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
                   constants.INSTST_NODEOFFLINE, constants.INSTST_ADMINOFFLINE,
                   constants.INSTST_USERDOWN)
  status_doc = ("Instance status; \"%s\" if instance is set to be running"
                " and actually is, \"%s\" if instance is stopped and"
                " is not running, \"%s\" if instance running, but not on its"
                " designated primary node, \"%s\" if instance should be"
                " stopped, but is actually running, \"%s\" if instance should"
                " run, but doesn't, \"%s\" if instance's primary node is down,"
                " \"%s\" if instance's primary node is marked offline,"
                " \"%s\" if instance is offline and does not use dynamic,"
                " \"%s\" if the user shutdown the instance"
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


class LockQueryData(object):
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


class GroupQueryData(object):
  """Data container for node group data queries.

  """
  def __init__(self, cluster, groups, group_to_nodes, group_to_instances,
               want_diskparams):
    """Initializes this class.

    @param cluster: Cluster object
    @param groups: List of node group objects
    @type group_to_nodes: dict; group UUID as key
    @param group_to_nodes: Per-group list of nodes
    @type group_to_instances: dict; group UUID as key
    @param group_to_instances: Per-group list of (primary) instances
    @type want_diskparams: bool
    @param want_diskparams: Whether diskparamters should be calculated

    """
    self.groups = groups
    self.group_to_nodes = group_to_nodes
    self.group_to_instances = group_to_instances
    self.cluster = cluster
    self.want_diskparams = want_diskparams

    # Used for individual rows
    self.group_ipolicy = None
    self.ndparams = None
    self.group_dp = None

  def __iter__(self):
    """Iterate over all node groups.

    This function has side-effects and only one instance of the resulting
    generator should be used at a time.

    """
    for group in self.groups:
      self.group_ipolicy = self.cluster.SimpleFillIPolicy(group.ipolicy)
      self.ndparams = self.cluster.SimpleFillND(group.ndparams)
      if self.want_diskparams:
        self.group_dp = self.cluster.SimpleFillDP(group.diskparams)
      else:
        self.group_dp = None
      yield group


_GROUP_SIMPLE_FIELDS = {
  "alloc_policy": ("AllocPolicy", QFT_TEXT, "Allocation policy for group"),
  "name": ("Group", QFT_TEXT, "Group name"),
  "serial_no": ("SerialNo", QFT_NUMBER, _SERIAL_NO_DOC % "Group"),
  "uuid": ("UUID", QFT_TEXT, "Group UUID"),
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
    (_MakeField("ipolicy", "InstancePolicy", QFT_OTHER,
                "Instance policy limitations (merged)"),
     GQ_CONFIG, 0, lambda ctx, _: ctx.group_ipolicy),
    (_MakeField("custom_ipolicy", "CustomInstancePolicy", QFT_OTHER,
                "Custom instance policy limitations"),
     GQ_CONFIG, 0, _GetItemAttr("ipolicy")),
    (_MakeField("custom_ndparams", "CustomNDParams", QFT_OTHER,
                "Custom node parameters"),
     GQ_CONFIG, 0, _GetItemAttr("ndparams")),
    (_MakeField("ndparams", "NDParams", QFT_OTHER,
                "Node parameters"),
     GQ_CONFIG, 0, lambda ctx, _: ctx.ndparams),
    (_MakeField("diskparams", "DiskParameters", QFT_OTHER,
                "Disk parameters (merged)"),
     GQ_DISKPARAMS, 0, lambda ctx, _: ctx.group_dp),
    (_MakeField("custom_diskparams", "CustomDiskParameters", QFT_OTHER,
                "Custom disk parameters"),
     GQ_CONFIG, 0, _GetItemAttr("diskparams")),
    ])

  # ND parameters
  fields.extend(_BuildNDFields(True))

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
    "os_hvp",
    "osparams",
    "trusted"
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
    (_MakeField("os_hvp", "OsHypervisorParams", QFT_OTHER,
                "Operating system specific hypervisor parameters"),
     None, 0, _GetItemAttr("os_hvp")),
    (_MakeField("osparams", "OsParameters", QFT_OTHER,
                "Operating system specific parameters"),
     None, 0, _GetItemAttr("osparams")),
    (_MakeField("trusted", "Trusted", QFT_BOOL,
                "Whether this OS is trusted"),
     None, 0, _GetItemAttr("trusted")),
    ]

  return _PrepareFieldList(fields, [])


class ExtStorageInfo(objects.ConfigObject):
  __slots__ = [
    "name",
    "node_status",
    "nodegroup_status",
    "parameters",
    ]


def _BuildExtStorageFields():
  """Builds list of fields for extstorage provider queries.

  """
  fields = [
    (_MakeField("name", "Name", QFT_TEXT, "ExtStorage provider name"),
     None, 0, _GetItemAttr("name")),
    (_MakeField("node_status", "NodeStatus", QFT_OTHER,
                "Status from node"),
     None, 0, _GetItemAttr("node_status")),
    (_MakeField("nodegroup_status", "NodegroupStatus", QFT_OTHER,
                "Overall Nodegroup status"),
     None, 0, _GetItemAttr("nodegroup_status")),
    (_MakeField("parameters", "Parameters", QFT_OTHER,
                "ExtStorage provider parameters"),
     None, 0, _GetItemAttr("parameters")),
    ]

  return _PrepareFieldList(fields, [])


def _JobUnavailInner(fn, ctx, (job_id, job)): # pylint: disable=W0613
  """Return L{_FS_UNAVAIL} if job is None.

  When listing specifc jobs (e.g. "gnt-job list 1 2 3"), a job may not be
  found, in which case this function converts it to L{_FS_UNAVAIL}.

  """
  if job is None:
    return _FS_UNAVAIL
  else:
    return fn(job)


def _JobUnavail(inner):
  """Wrapper for L{_JobUnavailInner}.

  """
  return compat.partial(_JobUnavailInner, inner)


def _PerJobOpInner(fn, job):
  """Executes a function per opcode in a job.

  """
  return map(fn, job.ops)


def _PerJobOp(fn):
  """Wrapper for L{_PerJobOpInner}.

  """
  return _JobUnavail(compat.partial(_PerJobOpInner, fn))


def _JobTimestampInner(fn, job):
  """Converts unavailable timestamp to L{_FS_UNAVAIL}.

  """
  timestamp = fn(job)

  if timestamp is None:
    return _FS_UNAVAIL
  else:
    return timestamp


def _JobTimestamp(fn):
  """Wrapper for L{_JobTimestampInner}.

  """
  return _JobUnavail(compat.partial(_JobTimestampInner, fn))


def _BuildJobFields():
  """Builds list of fields for job queries.

  """
  fields = [
    (_MakeField("id", "ID", QFT_NUMBER, "Job ID"),
     None, QFF_JOB_ID, lambda _, (job_id, job): job_id),
    (_MakeField("status", "Status", QFT_TEXT, "Job status"),
     None, 0, _JobUnavail(lambda job: job.CalcStatus())),
    (_MakeField("priority", "Priority", QFT_NUMBER,
                ("Current job priority (%s to %s)" %
                 (constants.OP_PRIO_LOWEST, constants.OP_PRIO_HIGHEST))),
     None, 0, _JobUnavail(lambda job: job.CalcPriority())),
    (_MakeField("archived", "Archived", QFT_BOOL, "Whether job is archived"),
     JQ_ARCHIVED, 0, lambda _, (job_id, job): job.archived),
    (_MakeField("ops", "OpCodes", QFT_OTHER, "List of all opcodes"),
     None, 0, _PerJobOp(lambda op: op.input.__getstate__())),
    (_MakeField("opresult", "OpCode_result", QFT_OTHER,
                "List of opcodes results"),
     None, 0, _PerJobOp(operator.attrgetter("result"))),
    (_MakeField("opstatus", "OpCode_status", QFT_OTHER,
                "List of opcodes status"),
     None, 0, _PerJobOp(operator.attrgetter("status"))),
    (_MakeField("oplog", "OpCode_log", QFT_OTHER,
                "List of opcode output logs"),
     None, 0, _PerJobOp(operator.attrgetter("log"))),
    (_MakeField("opstart", "OpCode_start", QFT_OTHER,
                "List of opcode start timestamps (before acquiring locks)"),
     None, 0, _PerJobOp(operator.attrgetter("start_timestamp"))),
    (_MakeField("opexec", "OpCode_exec", QFT_OTHER,
                "List of opcode execution start timestamps (after acquiring"
                " locks)"),
     None, 0, _PerJobOp(operator.attrgetter("exec_timestamp"))),
    (_MakeField("opend", "OpCode_end", QFT_OTHER,
                "List of opcode execution end timestamps"),
     None, 0, _PerJobOp(operator.attrgetter("end_timestamp"))),
    (_MakeField("oppriority", "OpCode_prio", QFT_OTHER,
                "List of opcode priorities"),
     None, 0, _PerJobOp(operator.attrgetter("priority"))),
    (_MakeField("summary", "Summary", QFT_OTHER,
                "List of per-opcode summaries"),
     None, 0, _PerJobOp(lambda op: op.input.Summary())),
    ]

  # Timestamp fields
  for (name, attr, title, desc) in [
    ("received_ts", "received_timestamp", "Received",
     "Timestamp of when job was received"),
    ("start_ts", "start_timestamp", "Start", "Timestamp of job start"),
    ("end_ts", "end_timestamp", "End", "Timestamp of job end"),
    ]:
    getter = operator.attrgetter(attr)
    fields.extend([
      (_MakeField(name, title, QFT_OTHER,
                  "%s (tuple containing seconds and microseconds)" % desc),
       None, QFF_SPLIT_TIMESTAMP, _JobTimestamp(getter)),
      ])

  return _PrepareFieldList(fields, [])


def _GetExportName(_, (node_name, expname)): # pylint: disable=W0613
  """Returns an export name if available.

  """
  if expname is None:
    return _FS_NODATA
  else:
    return expname


def _BuildExportFields():
  """Builds list of fields for exports.

  """
  fields = [
    (_MakeField("node", "Node", QFT_TEXT, "Node name"),
     None, QFF_HOSTNAME, lambda _, (node_name, expname): node_name),
    (_MakeField("export", "Export", QFT_TEXT, "Export name"),
     None, 0, _GetExportName),
    ]

  return _PrepareFieldList(fields, [])


_CLUSTER_VERSION_FIELDS = {
  "software_version": ("SoftwareVersion", QFT_TEXT, constants.RELEASE_VERSION,
                       "Software version"),
  "protocol_version": ("ProtocolVersion", QFT_NUMBER,
                       constants.PROTOCOL_VERSION,
                       "RPC protocol version"),
  "config_version": ("ConfigVersion", QFT_NUMBER, constants.CONFIG_VERSION,
                     "Configuration format version"),
  "os_api_version": ("OsApiVersion", QFT_NUMBER, max(constants.OS_API_VERSIONS),
                     "API version for OS template scripts"),
  "export_version": ("ExportVersion", QFT_NUMBER, constants.EXPORT_VERSION,
                     "Import/export file format version"),
  "vcs_version": ("VCSVersion", QFT_TEXT, constants.VCS_VERSION,
                     "VCS version"),
  }


_CLUSTER_SIMPLE_FIELDS = {
  "cluster_name": ("Name", QFT_TEXT, QFF_HOSTNAME, "Cluster name"),
  "volume_group_name": ("VgName", QFT_TEXT, 0, "LVM volume group name"),
  }


class ClusterQueryData(object):
  def __init__(self, cluster, nodes, drain_flag, watcher_pause):
    """Initializes this class.

    @type cluster: L{objects.Cluster}
    @param cluster: Instance of cluster object
    @type nodes: dict; node UUID as key
    @param nodes: Node objects
    @type drain_flag: bool
    @param drain_flag: Whether job queue is drained
    @type watcher_pause: number
    @param watcher_pause: Until when watcher is paused (Unix timestamp)

    """
    self._cluster = cluster
    self.nodes = nodes
    self.drain_flag = drain_flag
    self.watcher_pause = watcher_pause

  def __iter__(self):
    return iter([self._cluster])


def _ClusterWatcherPause(ctx, _):
  """Returns until when watcher is paused (if available).

  """
  if ctx.watcher_pause is None:
    return _FS_UNAVAIL
  else:
    return ctx.watcher_pause


def _BuildClusterFields():
  """Builds list of fields for cluster information.

  """
  fields = [
    (_MakeField("tags", "Tags", QFT_OTHER, "Tags"), CQ_CONFIG, 0,
     lambda ctx, cluster: list(cluster.GetTags())),
    (_MakeField("architecture", "ArchInfo", QFT_OTHER,
                "Architecture information"), None, 0,
     lambda ctx, _: runtime.GetArchInfo()),
    (_MakeField("drain_flag", "QueueDrained", QFT_BOOL,
                "Flag whether job queue is drained"), CQ_QUEUE_DRAINED, 0,
     lambda ctx, _: ctx.drain_flag),
    (_MakeField("watcher_pause", "WatcherPause", QFT_TIMESTAMP,
                "Until when watcher is paused"), CQ_WATCHER_PAUSE, 0,
     _ClusterWatcherPause),
    (_MakeField("master_node", "Master", QFT_TEXT, "Master node name"),
     CQ_CONFIG, QFF_HOSTNAME,
     lambda ctx, cluster: _GetNodeName(ctx, None, cluster.master_node)),
    ]

  # Simple fields
  fields.extend([
    (_MakeField(name, title, kind, doc), CQ_CONFIG, flags, _GetItemAttr(name))
    for (name, (title, kind, flags, doc)) in _CLUSTER_SIMPLE_FIELDS.items()
    ],)

  # Version fields
  fields.extend([
    (_MakeField(name, title, kind, doc), None, 0, _StaticValue(value))
    for (name, (title, kind, value, doc)) in _CLUSTER_VERSION_FIELDS.items()])

  # Add timestamps
  fields.extend(_GetItemTimestampFields(CQ_CONFIG))

  return _PrepareFieldList(fields, [
    ("name", "cluster_name")])


class NetworkQueryData(object):
  """Data container for network data queries.

  """
  def __init__(self, networks, network_to_groups,
               network_to_instances, stats):
    """Initializes this class.

    @param networks: List of network objects
    @type network_to_groups: dict; network UUID as key
    @param network_to_groups: Per-network list of groups
    @type network_to_instances: dict; network UUID as key
    @param network_to_instances: Per-network list of instances
    @type stats: dict; network UUID as key
    @param stats: Per-network usage statistics

    """
    self.networks = networks
    self.network_to_groups = network_to_groups
    self.network_to_instances = network_to_instances
    self.stats = stats

  def __iter__(self):
    """Iterate over all networks.

    """
    for net in self.networks:
      if self.stats:
        self.curstats = self.stats.get(net.uuid, None)
      else:
        self.curstats = None
      yield net


_NETWORK_SIMPLE_FIELDS = {
  "name": ("Network", QFT_TEXT, 0, "Name"),
  "network": ("Subnet", QFT_TEXT, 0, "IPv4 subnet"),
  "gateway": ("Gateway", QFT_OTHER, 0, "IPv4 gateway"),
  "network6": ("IPv6Subnet", QFT_OTHER, 0, "IPv6 subnet"),
  "gateway6": ("IPv6Gateway", QFT_OTHER, 0, "IPv6 gateway"),
  "mac_prefix": ("MacPrefix", QFT_OTHER, 0, "MAC address prefix"),
  "serial_no": ("SerialNo", QFT_NUMBER, 0, _SERIAL_NO_DOC % "Network"),
  "uuid": ("UUID", QFT_TEXT, 0, "Network UUID"),
  }


_NETWORK_STATS_FIELDS = {
  "free_count": ("FreeCount", QFT_NUMBER, 0, "Number of available addresses"),
  "reserved_count":
    ("ReservedCount", QFT_NUMBER, 0, "Number of reserved addresses"),
  "map": ("Map", QFT_TEXT, 0, "Actual mapping"),
  "external_reservations":
    ("ExternalReservations", QFT_TEXT, 0, "External reservations"),
  }


def _GetNetworkStatsField(field, kind, ctx, _):
  """Gets the value of a "stats" field from L{NetworkQueryData}.

  @param field: Field name
  @param kind: Data kind, one of L{constants.QFT_ALL}
  @type ctx: L{NetworkQueryData}

  """
  return _GetStatsField(field, kind, ctx.curstats)


def _BuildNetworkFields():
  """Builds list of fields for network queries.

  """
  fields = [
    (_MakeField("tags", "Tags", QFT_OTHER, "Tags"), IQ_CONFIG, 0,
     lambda ctx, inst: list(inst.GetTags())),
    ]

  # Add simple fields
  fields.extend([
    (_MakeField(name, title, kind, doc),
     NETQ_CONFIG, 0, _GetItemMaybeAttr(name))
     for (name, (title, kind, _, doc)) in _NETWORK_SIMPLE_FIELDS.items()])

  def _GetLength(getter):
    return lambda ctx, network: len(getter(ctx)[network.uuid])

  def _GetSortedList(getter):
    return lambda ctx, network: utils.NiceSort(getter(ctx)[network.uuid])

  network_to_groups = operator.attrgetter("network_to_groups")
  network_to_instances = operator.attrgetter("network_to_instances")

  # Add fields for node groups
  fields.extend([
    (_MakeField("group_cnt", "NodeGroups", QFT_NUMBER, "Number of nodegroups"),
     NETQ_GROUP, 0, _GetLength(network_to_groups)),
    (_MakeField("group_list", "GroupList", QFT_OTHER,
     "List of nodegroups (group name, NIC mode, NIC link)"),
     NETQ_GROUP, 0, lambda ctx, network: network_to_groups(ctx)[network.uuid]),
    ])

  # Add fields for instances
  fields.extend([
    (_MakeField("inst_cnt", "Instances", QFT_NUMBER, "Number of instances"),
     NETQ_INST, 0, _GetLength(network_to_instances)),
    (_MakeField("inst_list", "InstanceList", QFT_OTHER, "List of instances"),
     NETQ_INST, 0, _GetSortedList(network_to_instances)),
    ])

  # Add fields for usage statistics
  fields.extend([
    (_MakeField(name, title, kind, doc), NETQ_STATS, 0,
     compat.partial(_GetNetworkStatsField, name, kind))
    for (name, (title, kind, _, doc)) in _NETWORK_STATS_FIELDS.items()])

  # Add timestamps
  fields.extend(_GetItemTimestampFields(IQ_NETWORKS))

  return _PrepareFieldList(fields, [])


_FILTER_SIMPLE_FIELDS = {
  "watermark": ("Watermark", QFT_NUMBER, 0, "Watermark"),
  "priority": ("Priority", QFT_NUMBER, 0, "Priority"),
  "predicates": ("Predicates", QFT_OTHER, 0, "Predicates"),
  "action": ("Action", QFT_OTHER, 0, "Action"),
  "reason_trail": ("ReasonTrail", QFT_OTHER, 0, "Reason trail"),
  "uuid": ("UUID", QFT_TEXT, 0, "Network UUID"),
  }


def _BuildFilterFields():
  """Builds list of fields for job filter queries.

  """
  fields = [
    (_MakeField(name, title, kind, doc), None, 0, _GetItemMaybeAttr(name))
    for (name, (title, kind, _, doc)) in _FILTER_SIMPLE_FIELDS.items()
    ]

  return _PrepareFieldList(fields, [])

#: Fields for cluster information
CLUSTER_FIELDS = _BuildClusterFields()

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

#: Fields available for extstorage provider queries
EXTSTORAGE_FIELDS = _BuildExtStorageFields()

#: Fields available for job queries
JOB_FIELDS = _BuildJobFields()

#: Fields available for exports
EXPORT_FIELDS = _BuildExportFields()

#: Fields available for network queries
NETWORK_FIELDS = _BuildNetworkFields()

#: Fields available for job filter queries
FILTER_FIELDS = _BuildFilterFields()

#: All available resources
ALL_FIELDS = {
  constants.QR_CLUSTER: CLUSTER_FIELDS,
  constants.QR_INSTANCE: INSTANCE_FIELDS,
  constants.QR_NODE: NODE_FIELDS,
  constants.QR_LOCK: LOCK_FIELDS,
  constants.QR_GROUP: GROUP_FIELDS,
  constants.QR_OS: OS_FIELDS,
  constants.QR_EXTSTORAGE: EXTSTORAGE_FIELDS,
  constants.QR_JOB: JOB_FIELDS,
  constants.QR_EXPORT: EXPORT_FIELDS,
  constants.QR_NETWORK: NETWORK_FIELDS,
  constants.QR_FILTER: FILTER_FIELDS,
  }

#: All available field lists
ALL_FIELD_LISTS = ALL_FIELDS.values()
