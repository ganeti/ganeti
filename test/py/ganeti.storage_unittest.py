#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.storage"""

import re
import unittest
import random

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti import storage

import testutils


class TestVGReduce(testutils.GanetiTestCase):
  VGNAME = "xenvg"
  LIST_CMD = storage.LvmVgStorage.LIST_COMMAND
  VGREDUCE_CMD = storage.LvmVgStorage.VGREDUCE_COMMAND

  def _runCmd(self, cmd, **kwargs):
    if not self.run_history:
      self.fail("Empty run results")
    exp_cmd, result = self.run_history.pop(0)
    self.assertEqual(cmd, exp_cmd)
    return result

  def testOldVersion(self):
    lvmvg = storage.LvmVgStorage()
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
    lvmvg = storage.LvmVgStorage()
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
