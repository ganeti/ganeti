#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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

"""Script for unittesting the ganeti.storage.gluster module"""

import os
import shutil
import tempfile
import unittest
import mock

from ganeti import errors
from ganeti.storage import filestorage
from ganeti.storage import gluster
from ganeti import utils

import testutils

class TestGlusterVolume(testutils.GanetiTestCase):

  testAddrIpv = {4: "203.0.113.42",
                 6: "2001:DB8::74:65:28:6:69",
                }

  @staticmethod
  def _MakeVolume(addr=None, port=9001,
                  run_cmd=NotImplemented,
                  vol_name="pinky"):

    addr = addr if addr is not None else TestGlusterVolume.testAddrIpv[4]

    return gluster.GlusterVolume(addr, port, vol_name, _run_cmd=run_cmd,
                                 _mount_point="/invalid")

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    # Create some volumes.
    self.vol_a = TestGlusterVolume._MakeVolume()
    self.vol_a_clone = TestGlusterVolume._MakeVolume()
    self.vol_b = TestGlusterVolume._MakeVolume(vol_name="pinker")

  def testEquality(self):
    self.assertEqual(self.vol_a, self.vol_a_clone)

  def testInequality(self):
    self.assertNotEqual(self.vol_a, self.vol_b)

  def testHostnameResolution(self):
    vol_1 = TestGlusterVolume._MakeVolume(addr="localhost")
    self.assertEqual(vol_1.server_ip, "127.0.0.1")
    self.assertRaises(errors.ResolverError, lambda: \
      TestGlusterVolume._MakeVolume(addr="E_NOENT"))

  def testKVMMountStrings(self):
    # The only source of documentation I can find is:
    #   https://github.com/qemu/qemu/commit/8d6d89c
    # This test gets as close as possible to the examples given there,
    # within the limits of our implementation (no transport specification,
    #                                          no default port version).

    vol_1 = TestGlusterVolume._MakeVolume(addr=TestGlusterVolume.testAddrIpv[4],
                                          port=24007,
                                          vol_name="testvol")
    self.assertEqual(
      vol_1.GetKVMMountString("dir/a.img"),
      "gluster://203.0.113.42:24007/testvol/dir/a.img"
    )

    vol_2 = TestGlusterVolume._MakeVolume(addr=TestGlusterVolume.testAddrIpv[6],
                                          port=24007,
                                          vol_name="testvol")
    self.assertEqual(
      vol_2.GetKVMMountString("dir/a.img"),
      "gluster://[2001:db8:0:74:65:28:6:69]:24007/testvol/dir/a.img"
    )

    vol_3 = TestGlusterVolume._MakeVolume(addr="localhost",
                                          port=9001,
                                          vol_name="testvol")
    self.assertEqual(
      vol_3.GetKVMMountString("dir/a.img"),
      "gluster://127.0.0.1:9001/testvol/dir/a.img"
    )

  def testFUSEMountStrings(self):
    vol_1 = TestGlusterVolume._MakeVolume(addr=TestGlusterVolume.testAddrIpv[4],
                                          port=24007,
                                          vol_name="testvol")
    self.assertEqual(
      vol_1._GetFUSEMountString(),
      "203.0.113.42:24007:testvol"
    )

    vol_2 = TestGlusterVolume._MakeVolume(addr=TestGlusterVolume.testAddrIpv[6],
                                          port=24007,
                                          vol_name="testvol")
    # This _ought_ to work. https://bugzilla.redhat.com/show_bug.cgi?id=764188
    self.assertEqual(
      vol_2._GetFUSEMountString(),
      "2001:db8:0:74:65:28:6:69:24007:testvol"
    )

    vol_3 = TestGlusterVolume._MakeVolume(addr="localhost",
                                          port=9001,
                                          vol_name="testvol")
    self.assertEqual(
      vol_3._GetFUSEMountString(),
      "127.0.0.1:9001:testvol"
    )


if __name__ == "__main__":
  testutils.GanetiTestProgram()
