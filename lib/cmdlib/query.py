#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Logical units for queries."""

from ganeti import constants
from ganeti import errors
from ganeti import query
from ganeti.cmdlib.base import NoHooksLU
from ganeti.cmdlib.cluster import ClusterQuery
from ganeti.cmdlib.misc import ExtStorageQuery
from ganeti.cmdlib.operating_system import OsQuery


#: Query type implementations
_QUERY_IMPL = {
  constants.QR_CLUSTER: ClusterQuery,
  constants.QR_OS: OsQuery,
  constants.QR_EXTSTORAGE: ExtStorageQuery,
  }

assert set(_QUERY_IMPL.keys()) == constants.QR_VIA_OP


def _GetQueryImplementation(name):
  """Returns the implementation for a query type.

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
  REQ_BGL = False

  def CheckArguments(self):
    self.qcls = _GetQueryImplementation(self.op.what)

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    return query.QueryFields(self.qcls.FIELDS, self.op.fields)
