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

import operator
import re

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import compat
from ganeti import objects
from ganeti import ht


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
