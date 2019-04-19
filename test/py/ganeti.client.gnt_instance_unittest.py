#!/usr/bin/python3
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.client.gnt_instance"""

import unittest

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import objects
from ganeti.client import gnt_instance

import testutils


class TestConsole(unittest.TestCase):
  def setUp(self):
    self._output = []
    self._cmds = []
    self._next_cmd_exitcode = 0

  def _Test(self, console, show_command, cluster_name):
    return gnt_instance._DoConsole(console, show_command, cluster_name,
                                   feedback_fn=self._Feedback,
                                   _runcmd_fn=self._FakeRunCmd)

  def _Feedback(self, msg, *args):
    if args:
      msg = msg % args
    self._output.append(msg)

  def _FakeRunCmd(self, cmd, interactive=None):
    self.assertTrue(interactive)
    self.assertTrue(isinstance(cmd, list))
    self._cmds.append(cmd)
    return utils.RunResult(self._next_cmd_exitcode, None, "", "", "cmd",
                           utils.process._TIMEOUT_NONE, 5)

  def testMessage(self):
    cons = objects.InstanceConsole(instance="inst98.example.com",
                                   kind=constants.CONS_MESSAGE,
                                   message="Hello World")
    self.assertEqual(self._Test(cons, False, "cluster.example.com"),
                     constants.EXIT_SUCCESS)
    self.assertEqual(len(self._cmds), 0)
    self.assertEqual(self._output, ["Hello World"])

  def testVnc(self):
    cons = objects.InstanceConsole(instance="inst1.example.com",
                                   kind=constants.CONS_VNC,
                                   host="node1.example.com",
                                   port=5901,
                                   display=1)
    self.assertEqual(self._Test(cons, False, "cluster.example.com"),
                     constants.EXIT_SUCCESS)
    self.assertEqual(len(self._cmds), 0)
    self.assertEqual(len(self._output), 1)
    self.assertTrue(" inst1.example.com " in self._output[0])
    self.assertTrue(" node1.example.com:5901 " in self._output[0])
    self.assertTrue("vnc://node1.example.com:5901/" in self._output[0])

  def testSshShow(self):
    cons = objects.InstanceConsole(instance="inst31.example.com",
                                   kind=constants.CONS_SSH,
                                   host="node93.example.com",
                                   user="user_abc",
                                   command="xm console x.y.z")
    self.assertEqual(self._Test(cons, True, "cluster.example.com"),
                     constants.EXIT_SUCCESS)
    self.assertEqual(len(self._cmds), 0)
    self.assertEqual(len(self._output), 1)
    self.assertTrue(" user_abc@node93.example.com " in self._output[0])
    self.assertTrue("'xm console x.y.z'" in self._output[0])

  def testSshRun(self):
    cons = objects.InstanceConsole(instance="inst31.example.com",
                                   kind=constants.CONS_SSH,
                                   host="node93.example.com",
                                   user="user_abc",
                                   command=["xm", "console", "x.y.z"])
    self.assertEqual(self._Test(cons, False, "cluster.example.com"),
                     constants.EXIT_SUCCESS)
    self.assertEqual(len(self._cmds), 1)
    self.assertEqual(len(self._output), 0)

    # This is very important to prevent escapes from the console
    self.assertTrue("-oEscapeChar=none" in self._cmds[0])

  def testSshRunFail(self):
    cons = objects.InstanceConsole(instance="inst31.example.com",
                                   kind=constants.CONS_SSH,
                                   host="node93.example.com",
                                   user="user_abc",
                                   command=["xm", "console", "x.y.z"])

    self._next_cmd_exitcode = 100
    self.assertRaises(errors.OpExecError, self._Test,
                      cons, False, "cluster.example.com")
    self.assertEqual(len(self._cmds), 1)
    self.assertEqual(len(self._output), 0)


class TestConvertNicDiskModifications(unittest.TestCase):
  def testErrorMods(self):
    fn = gnt_instance._ConvertNicDiskModifications

    self.assertEqual(fn([]), [])

    # Error cases
    self.assertRaises(errors.OpPrereqError, fn, [
      (constants.DDM_REMOVE, {"param": "value", }),
      ])
    self.assertRaises(errors.OpPrereqError, fn, [
      (0, {constants.DDM_REMOVE: True, "param": "value", }),
      ])
    self.assertRaises(errors.OpPrereqError, fn, [
      (constants.DDM_DETACH, {"param": "value", }),
      ])
    self.assertRaises(errors.OpPrereqError, fn, [
      (0, {constants.DDM_DETACH: True, "param": "value", }),
      ])

    self.assertRaises(errors.OpPrereqError, fn, [
      (0, {
        constants.DDM_REMOVE: True,
        constants.DDM_ADD: True,
        }),
      ])
    self.assertRaises(errors.OpPrereqError, fn, [
      (0, {
        constants.DDM_DETACH: True,
        constants.DDM_MODIFY: True,
        }),
      ])

  def testLegacyCalls(self):
    fn = gnt_instance._ConvertNicDiskModifications

    for action in constants.DDMS_VALUES:
      self.assertEqual(fn([
        (action, {}),
        ]), [
        (action, -1, {}),
        ])
      self.assertRaises(errors.OpPrereqError, fn, [
        (0, {
          action: True,
          constants.DDM_MODIFY: True,
          }),
        ])

    self.assertEqual(fn([
      (constants.DDM_ADD, {
        constants.IDISK_SIZE: 1024,
        }),
      ]), [
      (constants.DDM_ADD, -1, {
        constants.IDISK_SIZE: 1024,
        }),
      ])

  def testNewStyleCalls(self):
    fn = gnt_instance._ConvertNicDiskModifications

    self.assertEqual(fn([
      (2, {
        constants.IDISK_MODE: constants.DISK_RDWR,
        }),
      ]), [
      (constants.DDM_MODIFY, 2, {
        constants.IDISK_MODE: constants.DISK_RDWR,
        }),
      ])

    self.assertEqual(fn([
      (0, {
        constants.DDM_ADD: True,
        constants.IDISK_SIZE: 4096,
        }),
      ]), [
      (constants.DDM_ADD, 0, {
        constants.IDISK_SIZE: 4096,
        }),
      ])

    self.assertEqual(fn([
      (-1, {
        constants.DDM_REMOVE: True,
        }),
      ]), [
      (constants.DDM_REMOVE, -1, {}),
      ])

    self.assertEqual(fn([
      (-1, {
        constants.DDM_MODIFY: True,
        constants.IDISK_SIZE: 1024,
        }),
      ]), [
      (constants.DDM_MODIFY, -1, {
        constants.IDISK_SIZE: 1024,
        }),
      ])

  def testNamesUUIDs(self):
    fn = gnt_instance._ConvertNicDiskModifications

    self.assertEqual(fn([
      ('name', {
        constants.IDISK_MODE: constants.DISK_RDWR,
        constants.IDISK_NAME: "rename",
        }),
      ]), [
      (constants.DDM_MODIFY, 'name', {
        constants.IDISK_MODE: constants.DISK_RDWR,
        constants.IDISK_NAME: "rename",
        }),
      ])
    self.assertEqual(fn([
      ('024ef14d-4879-400e-8767-d61c051950bf', {
        constants.DDM_MODIFY: True,
        constants.IDISK_SIZE: 1024,
        constants.IDISK_NAME: "name",
        }),
      ]), [
      (constants.DDM_MODIFY, '024ef14d-4879-400e-8767-d61c051950bf', {
        constants.IDISK_SIZE: 1024,
        constants.IDISK_NAME: "name",
        }),
      ])
    self.assertEqual(fn([
      ('name', {
        constants.DDM_REMOVE: True,
        }),
      ]), [
      (constants.DDM_REMOVE, 'name', {}),
      ])


class TestParseDiskSizes(unittest.TestCase):
  def test(self):
    fn = gnt_instance._ParseDiskSizes

    self.assertEqual(fn([]), [])

    # Missing size parameter
    self.assertRaises(errors.OpPrereqError, fn, [
      (constants.DDM_ADD, 0, {}),
      ])

    # Converting disk size
    self.assertEqual(fn([
      (constants.DDM_ADD, 11, {
        constants.IDISK_SIZE: "9G",
        }),
      ]), [
        (constants.DDM_ADD, 11, {
          constants.IDISK_SIZE: 9216,
          }),
        ])

    # No size parameter
    self.assertEqual(fn([
      (constants.DDM_REMOVE, 11, {
        "other": "24M",
        }),
      ]), [
        (constants.DDM_REMOVE, 11, {
          "other": "24M",
          }),
        ])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
