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

from ganeti import bdev


class TestDRBD8Runner(unittest.TestCase):
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
  def _get_contents(name):
    """Returns the contents of a file"""

    prefix = os.environ.get("srcdir", None)
    if prefix:
      name = prefix + "/" + name
    fh = open(name, "r")
    try:
      data = fh.read()
    finally:
      fh.close()
    return data


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
    data = self._get_contents("data/bdev-both.txt")
    result = bdev.DRBD8._GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(self._has_net(result, ("192.168.1.1", 11000),
                                  ("192.168.1.2", 11000)),
                    "Wrong network info")

  def testParserNet(self):
    """Test drbdsetup show parser for disk and network"""
    data = self._get_contents("data/bdev-net.txt")
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
    data = self._get_contents("data/bdev-disk.txt")
    result = bdev.DRBD8._GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(("local_addr" not in result and
                     "remote_addr" not in result),
                    "Should not find network info")

if __name__ == '__main__':
  unittest.main()
