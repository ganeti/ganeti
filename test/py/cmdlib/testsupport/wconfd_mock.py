#
#

# Copyright (C) 2014 Google Inc.
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


"""Support for mocking the wconfd calls"""


class MockClient(object):
  """Mock client calls to wconfd.

  """
  def __init__(self, wconfdmock):
    self.wconfdmock = wconfdmock

  def TryUpdateLocks(self, _cid, req):
    for lockrq in req:
      if lockrq[1] == "release":
        if lockrq[0] in self.wconfdmock.mylocks:
          del self.wconfdmock.mylocks[lockrq[0]]
      else:
        self.wconfdmock.mylocks[lockrq[0]] = lockrq[1]
    return []

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

  def Client(self):
    return MockClient(self)
