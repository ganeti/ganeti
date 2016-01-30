#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2012, 2013 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Script for unittesting the drbd module"""


import os

from ganeti import constants
from ganeti import errors
from ganeti import serializer
from ganeti.storage import drbd
from ganeti.storage import drbd_info
from ganeti.storage import drbd_cmdgen

import testutils


class TestDRBD8(testutils.GanetiTestCase):
  def testGetVersion(self):
    data = [
      "version: 8.0.0 (api:76/proto:80)",
      "version: 8.0.12 (api:76/proto:86-91)",
      "version: 8.2.7 (api:88/proto:0-100)",
      "version: 8.3.7.49 (api:188/proto:13-191)",
      "version: 8.4.7-1 (api:1/proto:86-101)",
    ]
    result = [
      {
        "k_major": 8,
        "k_minor": 0,
        "k_point": 0,
        "api": 76,
        "proto": 80,
      },
      {
        "k_major": 8,
        "k_minor": 0,
        "k_point": 12,
        "api": 76,
        "proto": 86,
        "proto2": "91",
      },
      {
        "k_major": 8,
        "k_minor": 2,
        "k_point": 7,
        "api": 88,
        "proto": 0,
        "proto2": "100",
      },
      {
        "k_major": 8,
        "k_minor": 3,
        "k_point": 7,
        "k_fix": "49",
        "api": 188,
        "proto": 13,
        "proto2": "191",
      },
      {
        "k_major": 8,
        "k_minor": 4,
        "k_point": 7,
        "k_release": "1",
        "api": 1,
        "proto": 86,
        "proto2": "101",
      }
    ]
    for d, r in zip(data, result):
      info = drbd.DRBD8Info.CreateFromLines([d])
      self.assertEqual(info.GetVersion(), r)
      self.assertEqual(info.GetVersionString(), d.replace("version: ", ""))


class TestDRBD8Runner(testutils.GanetiTestCase):
  """Testing case for drbd.DRBD8Dev"""

  @staticmethod
  def _has_disk(data, dname, mname, meta_index=0):
    """Check local disk corectness"""
    retval = (
      "local_dev" in data and
      data["local_dev"] == dname and
      "meta_dev" in data and
      data["meta_dev"] == mname and
      ((meta_index is None and
        "meta_index" not in data) or
       ("meta_index" in data and
        data["meta_index"] == meta_index)
      )
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

  def testParser83Creation(self):
    """Test drbdsetup show parser creation"""
    drbd_info.DRBD83ShowInfo._GetShowParser()

  def testParser84Creation(self):
    """Test drbdsetup show parser creation"""
    drbd_info.DRBD84ShowInfo._GetShowParser()

  def testParser80(self):
    """Test drbdsetup show parser for disk and network version 8.0"""
    data = testutils.ReadTestData("bdev-drbd-8.0.txt")
    result = drbd_info.DRBD83ShowInfo.GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(self._has_net(result, ("192.0.2.1", 11000),
                                  ("192.0.2.2", 11000)),
                    "Wrong network info (8.0.x)")

  def testParser83(self):
    """Test drbdsetup show parser for disk and network version 8.3"""
    data = testutils.ReadTestData("bdev-drbd-8.3.txt")
    result = drbd_info.DRBD83ShowInfo.GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(self._has_net(result, ("192.0.2.1", 11000),
                                  ("192.0.2.2", 11000)),
                    "Wrong network info (8.3.x)")

  def testParser84(self):
    """Test drbdsetup show parser for disk and network version 8.4"""
    data = testutils.ReadTestData("bdev-drbd-8.4.txt")
    result = drbd_info.DRBD84ShowInfo.GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(self._has_net(result, ("192.0.2.1", 11000),
                                  ("192.0.2.2", 11000)),
                    "Wrong network info (8.4.x)")

  def testParser84NoDiskParams(self):
    """Test drbdsetup show parser for 8.4 without disk params

    The missing disk parameters occur after re-attaching a local disk but
    before setting the disk params.

    """
    data = testutils.ReadTestData("bdev-drbd-8.4-no-disk-params.txt")
    result = drbd_info.DRBD84ShowInfo.GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta", meta_index=None),
                    "Wrong local disk info")
    self.failUnless(self._has_net(result, ("192.0.2.1", 11000),
                                  ("192.0.2.2", 11000)),
                    "Wrong network info (8.4.x)")

  def testParserNetIP4(self):
    """Test drbdsetup show parser for IPv4 network"""
    data = testutils.ReadTestData("bdev-drbd-net-ip4.txt")
    result = drbd_info.DRBD83ShowInfo.GetDevInfo(data)
    self.failUnless(("local_dev" not in result and
                     "meta_dev" not in result and
                     "meta_index" not in result),
                    "Should not find local disk info")
    self.failUnless(self._has_net(result, ("192.0.2.1", 11002),
                                  ("192.0.2.2", 11002)),
                    "Wrong network info (IPv4)")

  def testParserNetIP6(self):
    """Test drbdsetup show parser for IPv6 network"""
    data = testutils.ReadTestData("bdev-drbd-net-ip6.txt")
    result = drbd_info.DRBD83ShowInfo.GetDevInfo(data)
    self.failUnless(("local_dev" not in result and
                     "meta_dev" not in result and
                     "meta_index" not in result),
                    "Should not find local disk info")
    self.failUnless(self._has_net(result, ("2001:db8:65::1", 11048),
                                  ("2001:db8:66::1", 11048)),
                    "Wrong network info (IPv6)")

  def testParserDisk(self):
    """Test drbdsetup show parser for disk"""
    data = testutils.ReadTestData("bdev-drbd-disk.txt")
    result = drbd_info.DRBD83ShowInfo.GetDevInfo(data)
    self.failUnless(self._has_disk(result, "/dev/xenvg/test.data",
                                   "/dev/xenvg/test.meta"),
                    "Wrong local disk info")
    self.failUnless(("local_addr" not in result and
                     "remote_addr" not in result),
                    "Should not find network info")

  def testBarriersOptions(self):
    """Test class method that generates drbdsetup options for disk barriers"""
    # Tests that should fail because of wrong version/options combinations
    should_fail = [
      (8, 0, 12, "bfd", True),
      (8, 0, 12, "fd", False),
      (8, 0, 12, "b", True),
      (8, 2, 7, "bfd", True),
      (8, 2, 7, "b", True)
    ]

    for vmaj, vmin, vrel, opts, meta in should_fail:
      self.assertRaises(errors.BlockDeviceError,
                        drbd_cmdgen.DRBD83CmdGenerator._ComputeDiskBarrierArgs,
                        vmaj, vmin, vrel, opts, meta)

    # get the valid options from the frozenset(frozenset()) in constants.
    valid_options = [list(x)[0] for x in constants.DRBD_VALID_BARRIER_OPT]

    # Versions that do not support anything
    for vmaj, vmin, vrel in ((8, 0, 0), (8, 0, 11), (8, 2, 6)):
      for opts in valid_options:
        self.assertRaises(
          errors.BlockDeviceError,
          drbd_cmdgen.DRBD83CmdGenerator._ComputeDiskBarrierArgs,
          vmaj, vmin, vrel, opts, True)

    # Versions with partial support (testing only options that are supported)
    tests = [
      (8, 0, 12, "n", False, []),
      (8, 0, 12, "n", True, ["--no-md-flushes"]),
      (8, 2, 7, "n", False, []),
      (8, 2, 7, "fd", False, ["--no-disk-flushes", "--no-disk-drain"]),
      (8, 0, 12, "n", True, ["--no-md-flushes"]),
      ]

    # Versions that support everything
    for vmaj, vmin, vrel in ((8, 3, 0), (8, 3, 12)):
      tests.append((vmaj, vmin, vrel, "bfd", True,
                    ["--no-disk-barrier", "--no-disk-drain",
                     "--no-disk-flushes", "--no-md-flushes"]))
      tests.append((vmaj, vmin, vrel, "n", False, []))
      tests.append((vmaj, vmin, vrel, "b", True,
                    ["--no-disk-barrier", "--no-md-flushes"]))
      tests.append((vmaj, vmin, vrel, "fd", False,
                    ["--no-disk-flushes", "--no-disk-drain"]))
      tests.append((vmaj, vmin, vrel, "n", True, ["--no-md-flushes"]))

    # Test execution
    for test in tests:
      vmaj, vmin, vrel, disabled_barriers, disable_meta_flush, expected = test
      args = \
        drbd_cmdgen.DRBD83CmdGenerator._ComputeDiskBarrierArgs(
          vmaj, vmin, vrel,
          disabled_barriers,
          disable_meta_flush)
      self.failUnless(set(args) == set(expected),
                      "For test %s, got wrong results %s" % (test, args))

    # Unsupported or invalid versions
    for vmaj, vmin, vrel in ((0, 7, 25), (9, 0, 0), (7, 0, 0), (8, 4, 0)):
      self.assertRaises(errors.BlockDeviceError,
                        drbd_cmdgen.DRBD83CmdGenerator._ComputeDiskBarrierArgs,
                        vmaj, vmin, vrel, "n", True)

    # Invalid options
    for option in ("", "c", "whatever", "nbdfc", "nf"):
      self.assertRaises(errors.BlockDeviceError,
                        drbd_cmdgen.DRBD83CmdGenerator._ComputeDiskBarrierArgs,
                        8, 3, 11, option, True)


class TestDRBD8Status(testutils.GanetiTestCase):
  """Testing case for DRBD8Dev /proc status"""

  def setUp(self):
    """Read in txt data"""
    testutils.GanetiTestCase.setUp(self)
    proc_data = testutils.TestDataFilename("proc_drbd8.txt")
    proc80e_data = testutils.TestDataFilename("proc_drbd80-emptyline.txt")
    proc83_data = testutils.TestDataFilename("proc_drbd83.txt")
    proc83_sync_data = testutils.TestDataFilename("proc_drbd83_sync.txt")
    proc83_sync_krnl_data = \
      testutils.TestDataFilename("proc_drbd83_sync_krnl2.6.39.txt")
    proc84_data = testutils.TestDataFilename("proc_drbd84.txt")
    proc84_sync_data = testutils.TestDataFilename("proc_drbd84_sync.txt")
    proc84_emptyfirst_data = \
      testutils.TestDataFilename("proc_drbd84_emptyfirst.txt")

    self.proc80ev_data = \
      testutils.TestDataFilename("proc_drbd80-emptyversion.txt")

    self.drbd_info = drbd.DRBD8Info.CreateFromFile(filename=proc_data)
    self.drbd_info80e = drbd.DRBD8Info.CreateFromFile(filename=proc80e_data)
    self.drbd_info83 = drbd.DRBD8Info.CreateFromFile(filename=proc83_data)
    self.drbd_info83_sync = \
      drbd.DRBD8Info.CreateFromFile(filename=proc83_sync_data)
    self.drbd_info83_sync_krnl = \
      drbd.DRBD8Info.CreateFromFile(filename=proc83_sync_krnl_data)
    self.drbd_info84 = drbd.DRBD8Info.CreateFromFile(filename=proc84_data)
    self.drbd_info84_sync = \
      drbd.DRBD8Info.CreateFromFile(filename=proc84_sync_data)
    self.drbd_info84_emptyfirst = \
      drbd.DRBD8Info.CreateFromFile(filename=proc84_emptyfirst_data)

  def testIOErrors(self):
    """Test handling of errors while reading the proc file."""
    temp_file = self._CreateTempFile()
    os.unlink(temp_file)
    self.failUnlessRaises(errors.BlockDeviceError,
                          drbd.DRBD8Info.CreateFromFile, filename=temp_file)

  def testHelper(self):
    """Test reading usermode_helper in /sys."""
    sys_drbd_helper = testutils.TestDataFilename("sys_drbd_usermode_helper.txt")
    drbd_helper = drbd.DRBD8.GetUsermodeHelper(filename=sys_drbd_helper)
    self.failUnlessEqual(drbd_helper, "/bin/true")

  def testHelperIOErrors(self):
    """Test handling of errors while reading usermode_helper in /sys."""
    temp_file = self._CreateTempFile()
    os.unlink(temp_file)
    self.failUnlessRaises(errors.BlockDeviceError,
                          drbd.DRBD8.GetUsermodeHelper, filename=temp_file)

  def testMinorNotFound(self):
    """Test not-found-minor in /proc"""
    self.failUnless(not self.drbd_info.HasMinorStatus(9))
    self.failUnless(not self.drbd_info83.HasMinorStatus(9))
    self.failUnless(not self.drbd_info80e.HasMinorStatus(3))
    self.failUnless(not self.drbd_info84_emptyfirst.HasMinorStatus(0))

  def testLineNotMatch(self):
    """Test wrong line passed to drbd_info.DRBD8Status"""
    self.assertRaises(errors.BlockDeviceError, drbd_info.DRBD8Status, "foo")

  def testMinor0(self):
    """Test connected, primary device"""
    for info in [self.drbd_info, self.drbd_info83, self.drbd_info84]:
      stats = info.GetMinorStatus(0)
      self.failUnless(stats.is_in_use)
      self.failUnless(stats.is_connected and stats.is_primary and
                      stats.peer_secondary and stats.is_disk_uptodate)

  def testMinor1(self):
    """Test connected, secondary device"""
    for info in [self.drbd_info, self.drbd_info83, self.drbd_info84,
                 self.drbd_info84_emptyfirst]:
      stats = info.GetMinorStatus(1)
      self.failUnless(stats.is_in_use)
      self.failUnless(stats.is_connected and stats.is_secondary and
                      stats.peer_primary and stats.is_disk_uptodate)

  def testMinor2(self):
    """Test unconfigured device"""
    for info in [self.drbd_info, self.drbd_info83,
                 self.drbd_info80e, self.drbd_info84,
                 self.drbd_info84_emptyfirst]:
      stats = info.GetMinorStatus(2)
      self.failIf(stats.is_in_use)

  def testMinor4(self):
    """Test WFconn device"""
    for info in [self.drbd_info, self.drbd_info83,
                 self.drbd_info84, self.drbd_info84_emptyfirst]:
      stats = info.GetMinorStatus(4)
      self.failUnless(stats.is_in_use)
      self.failUnless(stats.is_wfconn and stats.is_primary and
                      stats.rrole == "Unknown" and
                      stats.is_disk_uptodate)

  def testMinor6(self):
    """Test diskless device"""
    for info in [self.drbd_info, self.drbd_info83,
                 self.drbd_info84, self.drbd_info84_emptyfirst]:
      stats = info.GetMinorStatus(6)
      self.failUnless(stats.is_in_use)
      self.failUnless(stats.is_connected and stats.is_secondary and
                      stats.peer_primary and stats.is_diskless)

  def testMinor8(self):
    """Test standalone device"""
    for info in [self.drbd_info, self.drbd_info83, self.drbd_info84]:
      stats = info.GetMinorStatus(8)
      self.failUnless(stats.is_in_use)
      self.failUnless(stats.is_standalone and
                      stats.rrole == "Unknown" and
                      stats.is_disk_uptodate)

  def testDRBD83SyncFine(self):
    stats = self.drbd_info83_sync.GetMinorStatus(3)
    self.failUnless(stats.is_in_resync)
    self.assertAlmostEqual(stats.sync_percent, 34.9)

  def testDRBD83SyncBroken(self):
    stats = self.drbd_info83_sync_krnl.GetMinorStatus(3)
    self.failUnless(stats.is_in_resync)
    self.assertAlmostEqual(stats.sync_percent, 2.4)

  def testDRBD84Sync(self):
    stats = self.drbd_info84_sync.GetMinorStatus(5)
    self.failUnless(stats.is_in_resync)
    self.assertAlmostEqual(stats.sync_percent, 68.5)

  def testDRBDEmptyVersion(self):
    self.assertRaises(errors.BlockDeviceError,
                      drbd.DRBD8Info.CreateFromFile,
                      filename=self.proc80ev_data)


class TestDRBD8Construction(testutils.GanetiTestCase):
  def setUp(self):
    """Read in txt data"""
    testutils.GanetiTestCase.setUp(self)
    self.proc80_info = \
      drbd_info.DRBD8Info.CreateFromFile(
        filename=testutils.TestDataFilename("proc_drbd8.txt"))
    self.proc83_info = \
      drbd_info.DRBD8Info.CreateFromFile(
        filename=testutils.TestDataFilename("proc_drbd83.txt"))
    self.proc84_info = \
      drbd_info.DRBD8Info.CreateFromFile(
        filename=testutils.TestDataFilename("proc_drbd84.txt"))

    self.test_unique_id = ("hosta.com", 123, "host2.com", 123, 0,
                           serializer.Private("secret"))
    self.test_dyn_params = {
      constants.DDP_LOCAL_IP: "192.0.2.1",
      constants.DDP_LOCAL_MINOR: 0,
      constants.DDP_REMOTE_IP: "192.0.2.2",
      constants.DDP_REMOTE_MINOR: 0,
    }

  @testutils.patch_object(drbd.DRBD8, "GetProcInfo")
  def testConstructionWith80Data(self, mock_create_from_file):
    mock_create_from_file.return_value = self.proc80_info

    inst = drbd.DRBD8Dev(self.test_unique_id, [], 123, {}, self.test_dyn_params)
    self.assertEqual(inst._show_info_cls, drbd_info.DRBD83ShowInfo)
    self.assertTrue(isinstance(inst._cmd_gen, drbd_cmdgen.DRBD83CmdGenerator))

  @testutils.patch_object(drbd.DRBD8, "GetProcInfo")
  def testConstructionWith83Data(self, mock_create_from_file):
    mock_create_from_file.return_value = self.proc83_info

    inst = drbd.DRBD8Dev(self.test_unique_id, [], 123, {}, self.test_dyn_params)
    self.assertEqual(inst._show_info_cls, drbd_info.DRBD83ShowInfo)
    self.assertTrue(isinstance(inst._cmd_gen, drbd_cmdgen.DRBD83CmdGenerator))

  @testutils.patch_object(drbd.DRBD8, "GetProcInfo")
  def testConstructionWith84Data(self, mock_create_from_file):
    mock_create_from_file.return_value = self.proc84_info

    inst = drbd.DRBD8Dev(self.test_unique_id, [], 123, {}, self.test_dyn_params)
    self.assertEqual(inst._show_info_cls, drbd_info.DRBD84ShowInfo)
    self.assertTrue(isinstance(inst._cmd_gen, drbd_cmdgen.DRBD84CmdGenerator))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
