#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
