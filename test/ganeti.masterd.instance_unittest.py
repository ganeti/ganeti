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


"""Script for testing ganeti.masterd.instance"""

import os
import sys
import unittest

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import masterd

from ganeti.masterd.instance import \
  ImportExportTimeouts, _TimeoutExpired, _DiskImportExportBase, \
  ComputeRemoteExportHandshake, CheckRemoteExportHandshake, \
  ComputeRemoteImportDiskInfo, CheckRemoteExportDiskInfo

import testutils


class TestMisc(unittest.TestCase):
  def testTimeouts(self):
    tmo = ImportExportTimeouts(0)
    self.assertEqual(tmo.connect, 0)
    self.assertEqual(tmo.listen, ImportExportTimeouts.DEFAULT_LISTEN_TIMEOUT)
    self.assertEqual(tmo.ready, ImportExportTimeouts.DEFAULT_READY_TIMEOUT)
    self.assertEqual(tmo.error, ImportExportTimeouts.DEFAULT_ERROR_TIMEOUT)

    tmo = ImportExportTimeouts(999)
    self.assertEqual(tmo.connect, 999)

  def testTimeoutExpired(self):
    self.assert_(_TimeoutExpired(100, 300, _time_fn=lambda: 500))
    self.assertFalse(_TimeoutExpired(100, 300, _time_fn=lambda: 0))
    self.assertFalse(_TimeoutExpired(100, 300, _time_fn=lambda: 100))
    self.assertFalse(_TimeoutExpired(100, 300, _time_fn=lambda: 400))

  def testDiskImportExportBaseDirect(self):
    self.assertRaises(AssertionError, _DiskImportExportBase,
                      None, None, None, None, None, None, None)


class TestRieHandshake(unittest.TestCase):
  def test(self):
    cds = "cd-secret"
    hs = ComputeRemoteExportHandshake(cds)
    self.assertEqual(len(hs), 3)
    self.assertEqual(hs[0], constants.RIE_VERSION)

    self.assertEqual(CheckRemoteExportHandshake(cds, hs), None)

  def testCheckErrors(self):
    self.assert_(CheckRemoteExportHandshake(None, None))
    self.assert_(CheckRemoteExportHandshake("", ""))
    self.assert_(CheckRemoteExportHandshake("", ("xyz", "foo")))

  def testCheckWrongHash(self):
    cds = "cd-secret999"
    self.assert_(CheckRemoteExportHandshake(cds, (0, "fakehash", "xyz")))

  def testCheckWrongVersion(self):
    version = 14887
    self.assertNotEqual(version, constants.RIE_VERSION)
    cds = "c28ac99"
    salt = "a19cf8cc06"
    msg = "%s:%s" % (version, constants.RIE_HANDSHAKE)
    hs = (version, utils.Sha1Hmac(cds, msg, salt=salt), salt)
    self.assert_(CheckRemoteExportHandshake(cds, hs))


class TestRieDiskInfo(unittest.TestCase):
  def test(self):
    cds = "bbf46ea9a"
    salt = "ee5ad9"
    di = ComputeRemoteImportDiskInfo(cds, salt, 0, "node1", 1234)
    self.assertEqual(CheckRemoteExportDiskInfo(cds, 0, di),
                     ("node1", 1234))

    for i in range(1, 100):
      # Wrong disk index
      self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                        cds, i, di)

  def testCheckErrors(self):
    cds = "0776450535a"
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, "")
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ())
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("", 1, 2, 3, 4, 5))

    # No host/port
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("", 0, "", ""))

    # Wrong hash
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("nodeX", 123, "fakehash", "xyz"))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
