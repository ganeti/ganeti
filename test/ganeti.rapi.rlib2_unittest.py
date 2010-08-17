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
        { "ip": "192.0.2.6", "mode": constants.NIC_MODE_ROUTED,
          "mac": "01:23:45:67:68:9A",
        },
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
                  "os": "debootstrap",
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

                  for opdisk, disk in zip(op.disks, disks):
                    for key in constants.IDISK_PARAMS:
                      self.assertEqual(opdisk.get(key), disk.get(key))
                    self.assertFalse("unknown" in opdisk)

                  for opnic, nic in zip(op.nics, nics):
                    for key in constants.INIC_PARAMS:
                      self.assertEqual(opnic.get(key), nic.get(key))
                    self.assertFalse("unknown" in opnic)
                    self.assertFalse("foobar" in opnic)

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
      "disk_template": constants.DT_PLAIN,
      "os": "debootstrap",
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


class TestParseMigrateInstanceRequest(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.Parse = rlib2._ParseMigrateInstanceRequest

  def test(self):
    name = "instYooho6ek"

    for cleanup in [False, True]:
      for mode in constants.HT_MIGRATION_MODES:
        data = {
          "cleanup": cleanup,
          "mode": mode,
          }
        op = self.Parse(name, data)
        self.assert_(isinstance(op, opcodes.OpMigrateInstance))
        self.assertEqual(op.instance_name, name)
        self.assertEqual(op.mode, mode)
        self.assertEqual(op.cleanup, cleanup)

  def testDefaults(self):
    name = "instnohZeex0"

    op = self.Parse(name, {})
    self.assert_(isinstance(op, opcodes.OpMigrateInstance))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.mode, None)
    self.assertFalse(op.cleanup)


class TestParseRenameInstanceRequest(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.Parse = rlib2._ParseRenameInstanceRequest

  def test(self):
    name = "instij0eeph7"

    for new_name in ["ua0aiyoo", "fai3ongi"]:
      for ip_check in [False, True]:
        for name_check in [False, True]:
          data = {
            "new_name": new_name,
            "ip_check": ip_check,
            "name_check": name_check,
            }

          op = self.Parse(name, data)
          self.assert_(isinstance(op, opcodes.OpRenameInstance))
          self.assertEqual(op.instance_name, name)
          self.assertEqual(op.new_name, new_name)
          self.assertEqual(op.ip_check, ip_check)
          self.assertEqual(op.name_check, name_check)

  def testDefaults(self):
    name = "instahchie3t"

    for new_name in ["thag9mek", "quees7oh"]:
      data = {
        "new_name": new_name,
        }

      op = self.Parse(name, data)
      self.assert_(isinstance(op, opcodes.OpRenameInstance))
      self.assertEqual(op.instance_name, name)
      self.assertEqual(op.new_name, new_name)
      self.assert_(op.ip_check)
      self.assert_(op.name_check)


class TestParseModifyInstanceRequest(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.Parse = rlib2._ParseModifyInstanceRequest

  def test(self):
    name = "instush8gah"

    test_disks = [
      [],
      [(1, { constants.IDISK_MODE: constants.DISK_RDWR, })],
      ]

    for osparams in [{}, { "some": "value", "other": "Hello World", }]:
      for hvparams in [{}, { constants.HV_KERNEL_PATH: "/some/kernel", }]:
        for beparams in [{}, { constants.BE_MEMORY: 128, }]:
          for force in [False, True]:
            for nics in [[], [(0, { constants.INIC_IP: "192.0.2.1", })]]:
              for disks in test_disks:
                for disk_template in constants.DISK_TEMPLATES:
                  data = {
                    "osparams": osparams,
                    "hvparams": hvparams,
                    "beparams": beparams,
                    "nics": nics,
                    "disks": disks,
                    "force": force,
                    "disk_template": disk_template,
                    }

                  op = self.Parse(name, data)
                  self.assert_(isinstance(op, opcodes.OpSetInstanceParams))
                  self.assertEqual(op.instance_name, name)
                  self.assertEqual(op.hvparams, hvparams)
                  self.assertEqual(op.beparams, beparams)
                  self.assertEqual(op.osparams, osparams)
                  self.assertEqual(op.force, force)
                  self.assertEqual(op.nics, nics)
                  self.assertEqual(op.disks, disks)
                  self.assertEqual(op.disk_template, disk_template)
                  self.assert_(op.remote_node is None)
                  self.assert_(op.os_name is None)
                  self.assertFalse(op.force_variant)

  def testDefaults(self):
    name = "instir8aish31"

    op = self.Parse(name, {})
    self.assert_(isinstance(op, opcodes.OpSetInstanceParams))
    self.assertEqual(op.instance_name, name)
    self.assertEqual(op.hvparams, {})
    self.assertEqual(op.beparams, {})
    self.assertEqual(op.osparams, {})
    self.assertFalse(op.force)
    self.assertEqual(op.nics, [])
    self.assertEqual(op.disks, [])
    self.assert_(op.disk_template is None)
    self.assert_(op.remote_node is None)
    self.assert_(op.os_name is None)
    self.assertFalse(op.force_variant)


if __name__ == '__main__':
  testutils.GanetiTestProgram()
