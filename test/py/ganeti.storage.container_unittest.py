#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.storage.container"""

import re
import unittest
import random

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti.storage import container

import testutils


class TestVGReduce(testutils.GanetiTestCase):
  VGNAME = "xenvg"
  LIST_CMD = container.LvmVgStorage.LIST_COMMAND
  VGREDUCE_CMD = container.LvmVgStorage.VGREDUCE_COMMAND

  def _runCmd(self, cmd, **kwargs):
    if not self.run_history:
      self.fail("Empty run results")
    exp_cmd, result = self.run_history.pop(0)
    self.assertEqual(cmd, exp_cmd)
    return result

  def testOldVersion(self):
    lvmvg = container.LvmVgStorage()
    stdout = testutils.ReadTestData("vgreduce-removemissing-2.02.02.txt")
    vgs_fail = testutils.ReadTestData("vgs-missing-pvs-2.02.02.txt")
    self.run_history = [
      ([self.VGREDUCE_CMD, "--removemissing", self.VGNAME],
       utils.RunResult(0, None, stdout, "", "", None, None)),
      ([self.LIST_CMD, "--noheadings", "--nosuffix", self.VGNAME],
       utils.RunResult(0, None, "", "", "", None, None)),
      ]
    lvmvg._RemoveMissing(self.VGNAME, _runcmd_fn=self._runCmd)
    self.assertEqual(self.run_history, [])
    for ecode, out in [(1, ""), (0, vgs_fail)]:
      self.run_history = [
        ([self.VGREDUCE_CMD, "--removemissing", self.VGNAME],
         utils.RunResult(0, None, stdout, "", "", None, None)),
        ([self.LIST_CMD, "--noheadings", "--nosuffix", self.VGNAME],
         utils.RunResult(ecode, None, out, "", "", None, None)),
        ]
      self.assertRaises(errors.StorageError, lvmvg._RemoveMissing, self.VGNAME,
                        _runcmd_fn=self._runCmd)
      self.assertEqual(self.run_history, [])

  def testNewVersion(self):
    lvmvg = container.LvmVgStorage()
    stdout1 = testutils.ReadTestData("vgreduce-removemissing-2.02.66-fail.txt")
    stdout2 = testutils.ReadTestData("vgreduce-removemissing-2.02.66-ok.txt")
    vgs_fail = testutils.ReadTestData("vgs-missing-pvs-2.02.66.txt")
    # first: require --fail, check that it's used
    self.run_history = [
      ([self.VGREDUCE_CMD, "--removemissing", self.VGNAME],
       utils.RunResult(0, None, stdout1, "", "", None, None)),
      ([self.VGREDUCE_CMD, "--removemissing", "--force", self.VGNAME],
       utils.RunResult(0, None, stdout2, "", "", None, None)),
      ([self.LIST_CMD, "--noheadings", "--nosuffix", self.VGNAME],
       utils.RunResult(0, None, "", "", "", None, None)),
      ]
    lvmvg._RemoveMissing(self.VGNAME, _runcmd_fn=self._runCmd)
    self.assertEqual(self.run_history, [])
    # second: make sure --fail is not used if not needed
    self.run_history = [
      ([self.VGREDUCE_CMD, "--removemissing", self.VGNAME],
       utils.RunResult(0, None, stdout2, "", "", None, None)),
      ([self.LIST_CMD, "--noheadings", "--nosuffix", self.VGNAME],
       utils.RunResult(0, None, "", "", "", None, None)),
      ]
    lvmvg._RemoveMissing(self.VGNAME, _runcmd_fn=self._runCmd)
    self.assertEqual(self.run_history, [])
    # third: make sure we error out if vgs doesn't find the volume
    for ecode, out in [(1, ""), (0, vgs_fail)]:
      self.run_history = [
        ([self.VGREDUCE_CMD, "--removemissing", self.VGNAME],
         utils.RunResult(0, None, stdout1, "", "", None, None)),
        ([self.VGREDUCE_CMD, "--removemissing", "--force", self.VGNAME],
         utils.RunResult(0, None, stdout2, "", "", None, None)),
        ([self.LIST_CMD, "--noheadings", "--nosuffix", self.VGNAME],
         utils.RunResult(ecode, None, out, "", "", None, None)),
        ]
      self.assertRaises(errors.StorageError, lvmvg._RemoveMissing, self.VGNAME,
                        _runcmd_fn=self._runCmd)
      self.assertEqual(self.run_history, [])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
