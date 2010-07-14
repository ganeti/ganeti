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


"""Script for testing the hypervisor.hv_kvm module"""

import unittest

from ganeti import constants
from ganeti import compat
from ganeti import objects
from ganeti import errors

from ganeti.hypervisor import hv_kvm

import testutils


class TestWriteNetScript(unittest.TestCase):
  def testBridged(self):
    inst = objects.Instance(name="inst1.example.com", tags=[])
    nic = objects.NIC(mac="01:23:45:67:89:0A",
                      nicparams={
                        constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
                        constants.NIC_LINK: "",
                        })

    script = hv_kvm._WriteNetScript(inst, nic, 0)
    self.assert_(isinstance(script, basestring))

  def testBridgedWithTags(self):
    inst = objects.Instance(name="inst1.example.com", tags=["Hello", "World"])
    nic = objects.NIC(mac="01:23:45:67:89:0A",
                      nicparams={
                        constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
                        constants.NIC_LINK: "",
                        })

    script = hv_kvm._WriteNetScript(inst, nic, 0)
    self.assert_(isinstance(script, basestring))

  def testRouted(self):
    inst = objects.Instance(name="inst2.example.com", tags=[])
    nic = objects.NIC(mac="A0:98:76:54:32:10",
                      ip="192.0.2.4",
                      nicparams={
                        constants.NIC_MODE: constants.NIC_MODE_ROUTED,
                        constants.NIC_LINK: "eth0",
                        })

    script = hv_kvm._WriteNetScript(inst, nic, 4)
    self.assert_(isinstance(script, basestring))

  def testRoutedNoIpAddress(self):
    inst = objects.Instance(name="eiphei1e.example.com", tags=[])
    nic = objects.NIC(mac="93:28:76:54:32:10",
                      nicparams={
                        constants.NIC_MODE: constants.NIC_MODE_ROUTED,
                        constants.NIC_LINK: "",
                        })

    self.assertRaises(errors.HypervisorError, hv_kvm._WriteNetScript,
                      inst, nic, 2)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
