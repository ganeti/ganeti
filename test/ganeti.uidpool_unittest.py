#!/usr/bin/python
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


"""Script for unittesting the uidpool module"""


import os
import tempfile
import unittest

from ganeti import constants
from ganeti import uidpool
from ganeti import errors

import testutils


class TestUidPool(testutils.GanetiTestCase):
  """Uid-pool tests"""

  def setUp(self):
    self.old_uid_min = constants.UIDPOOL_UID_MIN
    self.old_uid_max = constants.UIDPOOL_UID_MAX
    constants.UIDPOOL_UID_MIN = 1
    constants.UIDPOOL_UID_MAX = 10
    constants.UIDPOOL_LOCKDIR = tempfile.mkdtemp()

  def tearDown(self):
    constants.UIDPOOL_UID_MIN = self.old_uid_min
    constants.UIDPOOL_UID_MAX = self.old_uid_max
    for name in os.listdir(constants.UIDPOOL_LOCKDIR):
      os.unlink(os.path.join(constants.UIDPOOL_LOCKDIR, name))
    os.rmdir(constants.UIDPOOL_LOCKDIR)

  def testParseUidPool(self):
    self.assertEqualValues(
        uidpool.ParseUidPool("1-100,200,"),
        [(1, 100), (200, 200)])
    self.assertEqualValues(
        uidpool.ParseUidPool("1000:2000-2500", separator=":"),
        [(1000, 1000), (2000, 2500)])
    self.assertEqualValues(
        uidpool.ParseUidPool("1000\n2000-2500", separator="\n"),
        [(1000, 1000), (2000, 2500)])

  def testCheckUidPool(self):
    # UID < UIDPOOL_UID_MIN
    self.assertRaises(errors.OpPrereqError,
                      uidpool.CheckUidPool,
                      [(0, 0)])
    # UID > UIDPOOL_UID_MAX
    self.assertRaises(errors.OpPrereqError,
                      uidpool.CheckUidPool,
                      [(11, 11)])
    # lower boundary > higher boundary
    self.assertRaises(errors.OpPrereqError,
                      uidpool.CheckUidPool,
                      [(2, 1)])

  def testFormatUidPool(self):
    self.assertEqualValues(
        uidpool.FormatUidPool([(1, 100), (200, 200)]),
        "1-100, 200")
    self.assertEqualValues(
        uidpool.FormatUidPool([(1, 100), (200, 200)], separator=":"),
        "1-100:200")
    self.assertEqualValues(
        uidpool.FormatUidPool([(1, 100), (200, 200)], separator="\n"),
        "1-100\n200")

  def testRequestUnusedUid(self):
    # Check with known used user-ids
    #
    # Test with user-id "0" and with our own user-id, both
    # of which are guaranteed to be used user-ids
    for uid in 0, os.getuid():
      self.assertRaises(errors.LockError,
                        uidpool.RequestUnusedUid,
                        set([uid]))

    # Check with a single, known unused user-id
    #
    # We use "-1" here, which is not a valid user-id, so it's
    # guaranteed that it's unused.
    uid = uidpool.RequestUnusedUid(set([-1]))
    self.assertEqualValues(uid.GetUid(), -1)

    # Check uid-pool exhaustion
    #
    # uid "-1" is locked now, so RequestUnusedUid is expected to fail
    self.assertRaises(errors.LockError,
                      uidpool.RequestUnusedUid,
                      set([-1]))

    # Check unlocking
    uid.Unlock()
    # After unlocking, "-1" should be available again
    uid = uidpool.RequestUnusedUid(set([-1]))
    self.assertEqualValues(uid.GetUid(), -1)


if __name__ == '__main__':
  testutils.GanetiTestProgram()
