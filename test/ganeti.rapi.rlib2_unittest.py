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


"""Script for unittesting the RAPI rlib2 module

"""


import unittest
import tempfile

from ganeti import constants
from ganeti import opcodes
from ganeti import compat
from ganeti import http

from ganeti.rapi import rlib2

import testutils


class TestParseInstanceCreateRequestVersion1(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.Parse = rlib2._ParseInstanceCreateRequestVersion1

  def test(self):
    disk_variants = [
      # No disks
      [],

      # Two disks
      [{"size": 5, }, {"size": 100, }],

      # Disk with mode
      [{"size": 123, "mode": constants.DISK_RDWR, }],

      # With unknown setting
      [{"size": 123, "unknown": 999 }],
      ]

    nic_variants = [
      # No NIC
      [],

      # Three NICs
      [{}, {}, {}],

      # Two NICs
      [
        { "ip": "1.2.3.4", "mode": constants.NIC_MODE_ROUTED, },
        { "mode": constants.NIC_MODE_BRIDGED, "link": "n0", "bridge": "br1", },
      ],

      # Unknown settings
      [{ "unknown": 999, }, { "foobar": "Hello World", }],
      ]

    beparam_variants = [
      None,
      {},
      { constants.BE_VCPUS: 2, },
      { constants.BE_MEMORY: 123, },
      { constants.BE_VCPUS: 2,
        constants.BE_MEMORY: 1024,
        constants.BE_AUTO_BALANCE: True, }
      ]

    hvparam_variants = [
      None,
      { constants.HV_BOOT_ORDER: "anc", },
      { constants.HV_KERNEL_PATH: "/boot/fookernel",
        constants.HV_ROOT_PATH: "/dev/hda1", },
      ]

    for mode in [constants.INSTANCE_CREATE, constants.INSTANCE_IMPORT]:
      for nics in nic_variants:
        for disk_template in constants.DISK_TEMPLATES:
          for disks in disk_variants:
            for beparams in beparam_variants:
              for hvparams in hvparam_variants:
                data = {
                  "name": "inst1.example.com",
                  "hypervisor": constants.HT_FAKE,
                  "disks": disks,
                  "nics": nics,
                  "mode": mode,
                  "disk_template": disk_template,
                  }

                if beparams is not None:
                  data["beparams"] = beparams

                if hvparams is not None:
                  data["hvparams"] = hvparams

                for dry_run in [False, True]:
                  op = self.Parse(data, dry_run)
                  self.assert_(isinstance(op, opcodes.OpCreateInstance))
                  self.assertEqual(op.mode, mode)
                  self.assertEqual(op.disk_template, disk_template)
                  self.assertEqual(op.dry_run, dry_run)
                  self.assertEqual(len(op.disks), len(disks))
                  self.assertEqual(len(op.nics), len(nics))

                  self.assert_(compat.all(opdisk.get("size") ==
                                          disk.get("size") and
                                          opdisk.get("mode") ==
                                          disk.get("mode") and
                                          "unknown" not in opdisk
                                          for opdisk, disk in zip(op.disks,
                                                                  disks)))

                  self.assert_(compat.all(opnic.get("size") ==
                                          nic.get("size") and
                                          opnic.get("mode") ==
                                          nic.get("mode") and
                                          "unknown" not in opnic and
                                          "foobar" not in opnic
                                          for opnic, nic in zip(op.nics, nics)))

                  if beparams is None:
                    self.assertEqualValues(op.beparams, {})
                  else:
                    self.assertEqualValues(op.beparams, beparams)

                  if hvparams is None:
                    self.assertEqualValues(op.hvparams, {})
                  else:
                    self.assertEqualValues(op.hvparams, hvparams)

  def testErrors(self):
    # Test all required fields
    reqfields = {
      "name": "inst1.example.com",
      "disks": [],
      "nics": [],
      "mode": constants.INSTANCE_CREATE,
      "disk_template": constants.DT_PLAIN
      }

    for name in reqfields.keys():
      self.assertRaises(http.HttpBadRequest, self.Parse,
                        dict(i for i in reqfields.iteritems() if i[0] != name),
                        False)

    # Invalid disks and nics
    for field in ["disks", "nics"]:
      invalid_values = [None, 1, "", {}, [1, 2, 3], ["hda1", "hda2"]]

      if field == "disks":
        invalid_values.append([
          # Disks without size
          {},
          { "mode": constants.DISK_RDWR, },
          ])

      for invvalue in invalid_values:
        data = reqfields.copy()
        data[field] = invvalue
        self.assertRaises(http.HttpBadRequest, self.Parse, data, False)


class TestParseExportInstanceRequest(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.Parse = rlib2._ParseExportInstanceRequest

  def test(self):
    name = "instmoo"
    data = {
      "mode": constants.EXPORT_MODE_REMOTE,
      "destination": [(1, 2, 3), (99, 99, 99)],
      "shutdown": True,
      "remove_instance": True,
      "x509_key_name": ("name", "hash"),
      "destination_x509_ca": ("x", "y", "z"),
      }
    op = self.Parse(name, data)
    self.assert_(isinstance(op, opcodes.OpExportInstance))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, constants.EXPORT_MODE_REMOTE)
    self.assertEqual(op.shutdown, True)
    self.assertEqual(op.remove_instance, True)
    self.assertEqualValues(op.x509_key_name, ("name", "hash"))
    self.assertEqualValues(op.destination_x509_ca, ("x", "y", "z"))

  def testDefaults(self):
    name = "inst1"
    data = {
      "destination": "node2",
      "shutdown": False,
      }
    op = self.Parse(name, data)
    self.assert_(isinstance(op, opcodes.OpExportInstance))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, constants.EXPORT_MODE_LOCAL)
    self.assertEqual(op.remove_instance, False)

  def testErrors(self):
    self.assertRaises(http.HttpBadRequest, self.Parse, "err1",
                      { "remove_instance": "True", })
    self.assertRaises(http.HttpBadRequest, self.Parse, "err1",
                      { "remove_instance": "False", })


if __name__ == '__main__':
  testutils.GanetiTestProgram()
