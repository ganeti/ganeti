#!/usr/bin/python3
#

# Copyright (C) 2018 Google Inc.
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


"""Script for testing utils.LiveLock

"""

import os
import unittest

from ganeti.utils.livelock import LiveLock
from ganeti import pathutils

import testutils


class TestLiveLock(unittest.TestCase):
  """Whether LiveLock() works

  """
  @testutils.patch_object(pathutils, 'LIVELOCK_DIR', '/tmp')
  def test(self):
    lock = LiveLock()
    lock_path = lock.GetPath()
    self.assertTrue(os.path.exists(lock_path))
    self.assertTrue(lock_path.startswith('/tmp/pid'))
    lock.close()
    self.assertFalse(os.path.exists(lock_path))

  @testutils.patch_object(pathutils, 'LIVELOCK_DIR', '/tmp')
  def testName(self):
    lock = LiveLock('unittest.lock')
    lock_path = lock.GetPath()
    self.assertTrue(os.path.exists(lock_path))
    self.assertTrue(lock_path.startswith('/tmp/unittest.lock_'))
    lock.close()
    self.assertFalse(os.path.exists(lock_path))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
