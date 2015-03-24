#
#

# Copyright (C) 2014 Google Inc.
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


"""Support for mocking the wconfd calls"""


class MockClient(object):
  """Mock client calls to wconfd.

  """
  def __init__(self, wconfdmock):
    self.wconfdmock = wconfdmock

  def TryUpdateLocks(self, _cid, req):
    # Note that UpdateLocksWaiting in this mock
    # relies on TryUpdateLocks to always succeed.
    for lockrq in req:
      if lockrq[1] == "release":
        if lockrq[0] in self.wconfdmock.mylocks:
          del self.wconfdmock.mylocks[lockrq[0]]
      else:
        self.wconfdmock.mylocks[lockrq[0]] = lockrq[1]
        self.wconfdmock.all_locks[lockrq[0]] = lockrq[1]
    return []

  def UpdateLocksWaiting(self, cid, _prio, req):
    # as our mock TryUpdateLocks always suceeds, we can
    # just use it
    return self.TryUpdateLocks(cid, req)

  def HasPendingRequest(self, _cid):
    return False

  def ListLocks(self, *_):
    result = []
    for lock in self.wconfdmock.mylocks:
      result.append([lock, self.wconfdmock.mylocks[lock]])
    return result

  def FreeLocksLevel(self, _cid, level):
    locks = self.wconfdmock.mylocks.keys()
    for lock in locks:
      if lock.startswith(level + "/"):
        del self.wconfdmock.mylocks[lock]

  def OpportunisticLockUnion(self, _cid, req):
    for lockrq in req:
      self.wconfdmock.mylocks[lockrq[0]] = lockrq[1]
    return [lockrq[0] for lockrq in req]

  def PrepareClusterDestruction(self, _cid):
    pass


class WConfdMock(object):
  """Mock calls to WConfD.

  As at various points, LUs are tested in an integration-test
  fashion, calling it through mcpu, which, in turn, calls wconfd,
  this mock must be able to live under these circumstances. In particular,
  it needs to keep track of locks requested and released, as both,
  mcpu and the individual LUs do consistency checks on the locks they
  own.

  """
  def __init__(self):
    self.mylocks = {}
    self.all_locks = {}

  def Client(self):
    return MockClient(self)
