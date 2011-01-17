#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Script for testing the hypervisor.hv_kvm module"""

import unittest

from ganeti import constants
from ganeti import compat
from ganeti import objects
from ganeti import errors

from ganeti.hypervisor import hv_kvm

import testutils


class TestConsole(unittest.TestCase):
  def _Test(self, instance, hvparams):
    cons = hv_kvm.KVMHypervisor.GetInstanceConsole(instance, hvparams, {})
    self.assertTrue(cons.Validate())
    return cons

  def testSerial(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node6017")
    hvparams = {
      constants.HV_SERIAL_CONSOLE: True,
      constants.HV_VNC_BIND_ADDRESS: None,
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_SSH)
    self.assertEqual(cons.host, instance.primary_node)
    self.assertEqual(cons.command[0], constants.SOCAT_PATH)

  def testVnc(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node7235",
                                network_port=constants.VNC_BASE_PORT + 10)
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: "192.0.2.1",
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_VNC)
    self.assertEqual(cons.host, "192.0.2.1")
    self.assertEqual(cons.port, constants.VNC_BASE_PORT + 10)
    self.assertEqual(cons.display, 10)

  def testNoConsole(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node24325",
                                network_port=0)
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: None,
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_MESSAGE)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
