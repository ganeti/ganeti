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


"""Script for testing ganeti.hypervisor.hv_lxc"""

import unittest

from ganeti import constants
from ganeti import objects
from ganeti import hypervisor

from ganeti.hypervisor import hv_xen

import testutils


class TestConsole(unittest.TestCase):
  def test(self):
    for cls in [hv_xen.XenPvmHypervisor, hv_xen.XenHvmHypervisor]:
      instance = objects.Instance(name="xen.example.com",
                                  primary_node="node24828")
      cons = cls.GetInstanceConsole(instance, {}, {})
      self.assertTrue(cons.Validate())
      self.assertEqual(cons.kind, constants.CONS_SSH)
      self.assertEqual(cons.host, instance.primary_node)
      self.assertEqual(cons.command[-1], instance.name)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
