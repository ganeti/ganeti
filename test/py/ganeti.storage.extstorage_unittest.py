#!/usr/bin/python
#

# Copyright (C) 2016 Google Inc.
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


"""Script for unittesting the extstorage module"""


from ganeti import errors
from ganeti.storage import extstorage

import testutils


class TestExtStorageDevice(testutils.GanetiTestCase):
  """Testing case for extstorage.ExtStorageDevice"""

  def setUp(self):
    """Set up test data"""
    testutils.GanetiTestCase.setUp(self)
    self.name = "testname"
    self.uuid = "testuuid"
    self.test_unique_id = ("testdriver", "testvolumename")

  @testutils.patch_object(extstorage.ExtStorageDevice, "Attach")
  @testutils.patch_object(extstorage, "_ExtStorageAction")
  def testCreate(self, action_mock, attach_mock):
    action_mock.return_value = None
    attach_mock.return_value = True

    expected = extstorage.ExtStorageDevice(self.test_unique_id, [], 123, {}, {},
                                     name=self.name, uuid=self.uuid)
    got = extstorage.ExtStorageDevice.Create(self.test_unique_id, [], 123,
                                             None, {}, False, {},
                                             name=self.name, uuid=self.uuid)

    self.assertEqual(got, expected)

  def testCreateFailure(self):
    self.assertRaises(errors.ProgrammerError,
                      extstorage.ExtStorageDevice.Create,
                      self.test_unique_id, [], 123, None, {},
                      True, {}, name=self.name, uuid=self.uuid)


if __name__ == "__main__":
  testutils.GanetiTestProgram()

