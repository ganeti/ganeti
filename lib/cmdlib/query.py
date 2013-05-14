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


"""Logical units for queries."""

from ganeti import constants
from ganeti import errors
from ganeti import query
from ganeti.cmdlib.backup import _ExportQuery
from ganeti.cmdlib.base import NoHooksLU
from ganeti.cmdlib.cluster import _ClusterQuery
from ganeti.cmdlib.group import _GroupQuery
from ganeti.cmdlib.instance_query import _InstanceQuery
from ganeti.cmdlib.misc import _ExtStorageQuery
from ganeti.cmdlib.network import _NetworkQuery
from ganeti.cmdlib.node import _NodeQuery
from ganeti.cmdlib.operating_system import _OsQuery


#: Query type implementations
_QUERY_IMPL = {
  constants.QR_CLUSTER: _ClusterQuery,
  constants.QR_INSTANCE: _InstanceQuery,
  constants.QR_NODE: _NodeQuery,
  constants.QR_GROUP: _GroupQuery,
  constants.QR_NETWORK: _NetworkQuery,
  constants.QR_OS: _OsQuery,
  constants.QR_EXTSTORAGE: _ExtStorageQuery,
  constants.QR_EXPORT: _ExportQuery,
  }

assert set(_QUERY_IMPL.keys()) == constants.QR_VIA_OP


def _GetQueryImplementation(name):
  """Returns the implemtnation for a query type.

  @param name: Query type, must be one of L{constants.QR_VIA_OP}

  """
  try:
    return _QUERY_IMPL[name]
  except KeyError:
    raise errors.OpPrereqError("Unknown query resource '%s'" % name,
                               errors.ECODE_INVAL)


class LUQuery(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    qcls = _GetQueryImplementation(self.op.what)

    self.impl = qcls(self.op.qfilter, self.op.fields, self.op.use_locking)

  def ExpandNames(self):
    self.impl.ExpandNames(self)

  def DeclareLocks(self, level):
    self.impl.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.impl.NewStyleQuery(self)


class LUQueryFields(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.qcls = _GetQueryImplementation(self.op.what)

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    return query.QueryFields(self.qcls.FIELDS, self.op.fields)
