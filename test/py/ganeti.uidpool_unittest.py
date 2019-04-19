#!/usr/bin/python3
#

# Copyright (C) 2010 Google Inc.
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


"""Script for unittesting the uidpool module"""


import os
import tempfile
import unittest

from ganeti import constants
from ganeti import uidpool
from ganeti import errors
from ganeti import pathutils

import testutils


class TestUidPool(testutils.GanetiTestCase):
  """Uid-pool tests"""

  def setUp(self):
    self.old_uid_min = constants.UIDPOOL_UID_MIN
    self.old_uid_max = constants.UIDPOOL_UID_MAX
    constants.UIDPOOL_UID_MIN = 1
    constants.UIDPOOL_UID_MAX = 10
    pathutils.UIDPOOL_LOCKDIR = tempfile.mkdtemp()

  def tearDown(self):
    constants.UIDPOOL_UID_MIN = self.old_uid_min
    constants.UIDPOOL_UID_MAX = self.old_uid_max
    for name in os.listdir(pathutils.UIDPOOL_LOCKDIR):
      os.unlink(os.path.join(pathutils.UIDPOOL_LOCKDIR, name))
    os.rmdir(pathutils.UIDPOOL_LOCKDIR)

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
    # Test with our own user-id which is guaranteed to be used
    self.assertRaises(errors.LockError,
                      uidpool.RequestUnusedUid,
                      set([os.getuid()]))

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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
