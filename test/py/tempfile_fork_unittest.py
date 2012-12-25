#!/usr/bin/python
#

# Copyright (C) 2010, 2012 Google Inc.
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


"""Script for testing utils.ResetTempfileModule"""

import os
import sys
import errno
import shutil
import tempfile
import unittest
import logging

from ganeti import utils

import testutils


# This constant is usually at a much higher value. Setting it lower for test
# purposes.
tempfile.TMP_MAX = 3


class TestResetTempfileModule(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNoReset(self):
    if ((sys.hexversion >= 0x020703F0 and sys.hexversion < 0x03000000) or
        sys.hexversion >= 0x030203F0):
      # We can't test the no_reset case on Python 2.7+
      return
    # evil Debian sid...
    if (hasattr(tempfile._RandomNameSequence, "rng") and
        type(tempfile._RandomNameSequence.rng) == property):
      return
    self._Test(False)

  def testReset(self):
    self._Test(True)

  def _Test(self, reset):
    self.failIf(tempfile.TMP_MAX > 10)

    # Initialize tempfile module
    (fd, _) = tempfile.mkstemp(dir=self.tmpdir, prefix="init.", suffix="")
    os.close(fd)

    (notify_read, notify_write) = os.pipe()

    pid = os.fork()
    if pid == 0:
      # Child
      try:
        try:
          if reset:
            utils.ResetTempfileModule()

          os.close(notify_write)

          # Wait for parent to close pipe
          os.read(notify_read, 1)

          try:
            # This is a short-lived process, not caring about closing file
            # descriptors
            (_, path) = tempfile.mkstemp(dir=self.tmpdir,
                                         prefix="test.", suffix="")
          except EnvironmentError, err:
            if err.errno == errno.EEXIST:
              # Couldnt' create temporary file (e.g. because we run out of
              # retries)
              os._exit(2)
            raise

          logging.debug("Child created %s", path)

          os._exit(0)
        except Exception:
          logging.exception("Unhandled error")
      finally:
        os._exit(1)

    # Parent
    os.close(notify_read)

    # Create parent's temporary files
    for _ in range(tempfile.TMP_MAX):
      (fd, path) = tempfile.mkstemp(dir=self.tmpdir,
                                    prefix="test.", suffix="")
      os.close(fd)
      logging.debug("Parent created %s", path)

    # Notify child by closing pipe
    os.close(notify_write)

    (_, status) = os.waitpid(pid, 0)

    self.failIf(os.WIFSIGNALED(status))

    if reset:
      # If the tempfile module was reset, it should not fail to create
      # temporary files
      expected = 0
    else:
      expected = 2

    self.assertEqual(os.WEXITSTATUS(status), expected)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
