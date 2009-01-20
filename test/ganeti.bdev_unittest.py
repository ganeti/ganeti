#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Script for unittesting the bdev module"""


import os
import unittest

import testutils
from ganeti import bdev
from ganeti import errors


class TestDRBD8Runner(testutils.GanetiTestCase):
  """Testing case for DRBD8"""

  @staticmethod
  def _has_disk(data, dname, mname):
    """Check local disk corectness"""
    retval = (
      "local_dev" in data and
      data["local_dev"] == dname and
      "meta_dev" in data and
      data["meta_dev"] == mname and
      "meta_index" in data and
      data["meta_index"] == 0
      )
    return retval

  @staticmethod
  def _has_net(data, local, remote):
    """Check network connection parameters"""
    retval = (
      "local_addr" in data and
      data["local_addr"] == local and
      "remote_addr" in data and
      data["remote_addr"] == remote
      )
    return retval

  def testParserCreation(self):
    """Test drbdsetup show parser creation"""
    bdev.DRBD8._GetShowParser()

  def testParserBoth(self):
    """Test drbdsetup show parser for disk and network"""
    data = self._ReadTestData("bdev-both.txt")
    result = bdev.DRBD8._GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(self._has_net(result, ("192.168.1.1", 11000),
                                  ("192.168.1.2", 11000)),
                    "Wrong network info")

  def testParserNet(self):
    """Test drbdsetup show parser for disk and network"""
    data = self._ReadTestData("bdev-net.txt")
    result = bdev.DRBD8._GetDevInfo(data)
    self.failUnless(("local_dev" not in result and
                     "meta_dev" not in result and
                     "meta_index" not in result),
                    "Should not find local disk info")
    self.failUnless(self._has_net(result, ("192.168.1.1", 11002),
                                  ("192.168.1.2", 11002)),
                    "Wrong network info")

  def testParserDisk(self):
    """Test drbdsetup show parser for disk and network"""
    data = self._ReadTestData("bdev-disk.txt")
    result = bdev.DRBD8._GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(("local_addr" not in result and
                     "remote_addr" not in result),
                    "Should not find network info")


class TestDRBD8Status(testutils.GanetiTestCase):
  """Testing case for DRBD8 /proc status"""

  def setUp(self):
    """Read in txt data"""
    testutils.GanetiTestCase.setUp(self)
    proc_data = self._TestDataFilename("proc_drbd8.txt")
    self.proc_data = bdev.DRBD8._GetProcData(filename=proc_data)
    self.mass_data = bdev.DRBD8._MassageProcData(self.proc_data)

  def testMinorNotFound(self):
    """Test not-found-minor in /proc"""
    self.failUnless(9 not in self.mass_data)

  def testLineNotMatch(self):
    """Test wrong line passed to DRBD8Status"""
    self.assertRaises(errors.BlockDeviceError, bdev.DRBD8Status, "foo")

  def testMinor0(self):
    """Test connected, primary device"""
    stats = bdev.DRBD8Status(self.mass_data[0])
    self.failUnless(stats.is_connected and stats.is_primary and
                    stats.peer_secondary and stats.is_disk_uptodate)

  def testMinor1(self):
    """Test connected, secondary device"""
    stats = bdev.DRBD8Status(self.mass_data[1])
    self.failUnless(stats.is_connected and stats.is_secondary and
                    stats.peer_primary and stats.is_disk_uptodate)

  def testMinor4(self):
    """Test WFconn device"""
    stats = bdev.DRBD8Status(self.mass_data[4])
    self.failUnless(stats.is_wfconn and stats.is_primary and
                    stats.rrole == 'Unknown' and
                    stats.is_disk_uptodate)

  def testMinor6(self):
    """Test diskless device"""
    stats = bdev.DRBD8Status(self.mass_data[6])
    self.failUnless(stats.is_connected and stats.is_secondary and
                    stats.peer_primary and stats.is_diskless)

  def testMinor8(self):
    """Test standalone device"""
    stats = bdev.DRBD8Status(self.mass_data[8])
    self.failUnless(stats.is_standalone and
                    stats.rrole == 'Unknown' and
                    stats.is_disk_uptodate)

if __name__ == '__main__':
  unittest.main()
