#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2012, 2013, 2016 Google Inc.
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


"""Script for unittesting the bdev module"""


import os
import random
import unittest

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import utils
from ganeti.storage import bdev

import testutils

def _FakeRunCmd(success, stdout, cmd):
  if success:
    exit_code = 0
  else:
    exit_code = 1
  return utils.RunResult(exit_code, None, stdout, "", cmd,
                         utils.process._TIMEOUT_NONE, 5)


class FakeStatResult(object):
  def __init__(self, st_mode):
    self.st_mode = st_mode
    self.st_rdev = 0


class TestRADOSBlockDevice(testutils.GanetiTestCase):
  """Tests for bdev.RADOSBlockDevice volumes

  """

  def setUp(self):
    """Set up input data"""
    testutils.GanetiTestCase.setUp(self)

    self.plain_output_old_ok = \
      testutils.ReadTestData("bdev-rbd/plain_output_old_ok.txt")
    self.plain_output_old_no_matches = \
      testutils.ReadTestData("bdev-rbd/plain_output_old_no_matches.txt")
    self.plain_output_old_extra_matches = \
      testutils.ReadTestData("bdev-rbd/plain_output_old_extra_matches.txt")
    self.plain_output_old_empty = \
      testutils.ReadTestData("bdev-rbd/plain_output_old_empty.txt")
    self.plain_output_new_ok = \
      testutils.ReadTestData("bdev-rbd/plain_output_new_ok.txt")
    self.plain_output_new_no_matches = \
      testutils.ReadTestData("bdev-rbd/plain_output_new_no_matches.txt")
    self.plain_output_new_extra_matches = \
      testutils.ReadTestData("bdev-rbd/plain_output_new_extra_matches.txt")
    # This file is completely empty, and as such it's not shipped.
    self.plain_output_new_empty = ""
    self.json_output_ok = testutils.ReadTestData("bdev-rbd/json_output_ok.txt")
    self.json_output_no_matches = \
      testutils.ReadTestData("bdev-rbd/json_output_no_matches.txt")
    self.json_output_extra_matches = \
      testutils.ReadTestData("bdev-rbd/json_output_extra_matches.txt")
    self.json_output_empty = \
      testutils.ReadTestData("bdev-rbd/json_output_empty.txt")
    self.output_invalid = testutils.ReadTestData("bdev-rbd/output_invalid.txt")

    self.volume_name = "d7ab910a-4933-4ffe-88d0-faf2ce31390a.rbd.disk0"
    self.pool_name = "rbd"
    self.test_unique_id = ("rbd", self.volume_name)
    self.test_params = {
      constants.LDP_POOL: "fake_pool"
      }

  def testParseRbdShowmappedJson(self):
    parse_function = bdev.RADOSBlockDevice._ParseRbdShowmappedJson

    self.assertEqual(parse_function(self.json_output_ok, self.pool_name,
                     self.volume_name), "/dev/rbd3")
    self.assertEqual(parse_function(self.json_output_ok, "fake_pool",
                     self.volume_name), None)
    self.assertEqual(parse_function(self.json_output_empty, self.pool_name,
                     self.volume_name), None)
    self.assertEqual(parse_function(self.json_output_no_matches, self.pool_name,
                     self.volume_name), None)
    self.assertRaises(errors.BlockDeviceError, parse_function,
                      self.json_output_extra_matches, self.pool_name,
                      self.volume_name)
    self.assertRaises(errors.BlockDeviceError, parse_function,
                      self.output_invalid, self.pool_name, self.volume_name)

  def testParseRbdShowmappedPlain(self):
    parse_function = bdev.RADOSBlockDevice._ParseRbdShowmappedPlain

    self.assertEqual(parse_function(self.plain_output_new_ok,
                     self.volume_name), "/dev/rbd3")
    self.assertEqual(parse_function(self.plain_output_old_ok,
                     self.volume_name), "/dev/rbd3")
    self.assertEqual(parse_function(self.plain_output_new_empty,
                     self.volume_name), None)
    self.assertEqual(parse_function(self.plain_output_old_empty,
                     self.volume_name), None)
    self.assertEqual(parse_function(self.plain_output_new_no_matches,
                     self.volume_name), None)
    self.assertEqual(parse_function(self.plain_output_old_no_matches,
                     self.volume_name), None)
    self.assertRaises(errors.BlockDeviceError, parse_function,
                      self.plain_output_new_extra_matches, self.volume_name)
    self.assertRaises(errors.BlockDeviceError, parse_function,
                      self.plain_output_old_extra_matches, self.volume_name)
    self.assertRaises(errors.BlockDeviceError, parse_function,
                      self.output_invalid, self.volume_name)

  @testutils.patch_object(utils, "RunCmd")
  @testutils.patch_object(bdev.RADOSBlockDevice, "_UnmapVolumeFromBlockdev")
  @testutils.patch_object(bdev.RADOSBlockDevice, "Attach")
  def testRADOSBlockDeviceImport(self, attach_mock, unmap_mock, run_cmd_mock):
    """Test for bdev.RADOSBlockDevice.Import()"""
    # Set up the mock objects return values
    attach_mock.return_value = True
    run_cmd_mock.return_value = _FakeRunCmd(True, "", "")

    # Create a fake rbd volume
    inst = bdev.RADOSBlockDevice(self.test_unique_id, [], 1024,
                                 self.test_params, {})
    # Desired output command
    import_cmd = [constants.RBD_CMD, "import",
                  "-p", inst.rbd_pool,
                  "-", inst.rbd_name]

    self.assertEqual(inst.Import(), import_cmd)

  @testutils.patch_object(bdev.RADOSBlockDevice, "Attach")
  def testRADOSBlockDeviceExport(self, attach_mock):
    """Test for bdev.RADOSBlockDevice.Export()"""
    # Set up the mock object return value
    attach_mock.return_value = True

    # Create a fake rbd volume
    inst = bdev.RADOSBlockDevice(self.test_unique_id, [], 1024,
                                 self.test_params, {})
    # Desired output command
    export_cmd = [constants.RBD_CMD, "export",
                  "-p", inst.rbd_pool,
                  inst.rbd_name, "-"]

    self.assertEqual(inst.Export(), export_cmd)

  @testutils.patch_object(utils, "RunCmd")
  @testutils.patch_object(bdev.RADOSBlockDevice, "Attach")
  def testRADOSBlockDeviceCreate(self, attach_mock, run_cmd_mock):
    """Test for bdev.RADOSBlockDevice.Create() success"""
    attach_mock.return_value = True
    # This returns a successful RunCmd result
    run_cmd_mock.return_value = _FakeRunCmd(True, "", "")

    expect = bdev.RADOSBlockDevice(self.test_unique_id, [], 1024,
                                   self.test_params, {})
    got = bdev.RADOSBlockDevice.Create(self.test_unique_id, [], 1024, None,
                                       self.test_params, False, {},
                                       test_kwarg="test")

    self.assertEqual(expect, got)

  @testutils.patch_object(bdev.RADOSBlockDevice, "Attach")
  def testRADOSBlockDeviceCreateFailure(self, attach_mock):
    """Test for bdev.RADOSBlockDevice.Create() failure with exclusive_storage
    enabled

    """
    attach_mock.return_value = True

    self.assertRaises(errors.ProgrammerError, bdev.RADOSBlockDevice.Create,
                      self.test_unique_id, [], 1024, None, self.test_params,
                      True, {})

  @testutils.patch_object(bdev.RADOSBlockDevice, "_MapVolumeToBlockdev")
  @testutils.patch_object(os, "stat")
  def testAttach(self, stat_mock, map_mock):
    """Test for bdev.RADOSBlockDevice.Attach()"""
    stat_mock.return_value = FakeStatResult(0x6000) # bitmask for S_ISBLK
    map_mock.return_value = "/fake/path"
    dev = bdev.RADOSBlockDevice.__new__(bdev.RADOSBlockDevice)
    dev.unique_id = self.test_unique_id

    self.assertEqual(dev.Attach(), True)

  @testutils.patch_object(bdev.RADOSBlockDevice, "_MapVolumeToBlockdev")
  @testutils.patch_object(os, "stat")
  def testAttachFailureNotBlockdev(self, stat_mock, map_mock):
    """Test for bdev.RADOSBlockDevice.Attach() failure, not a blockdev"""
    stat_mock.return_value = FakeStatResult(0x0)
    map_mock.return_value = "/fake/path"
    dev = bdev.RADOSBlockDevice.__new__(bdev.RADOSBlockDevice)
    dev.unique_id = self.test_unique_id

    self.assertEqual(dev.Attach(), False)

  @testutils.patch_object(bdev.RADOSBlockDevice, "_MapVolumeToBlockdev")
  @testutils.patch_object(os, "stat")
  def testAttachFailureNoDevice(self, stat_mock, map_mock):
    """Test for bdev.RADOSBlockDevice.Attach() failure, no device found"""
    stat_mock.side_effect = OSError("No device found")
    map_mock.return_value = "/fake/path"
    dev = bdev.RADOSBlockDevice.__new__(bdev.RADOSBlockDevice)
    dev.unique_id = self.test_unique_id

    self.assertEqual(dev.Attach(), False)


class TestExclusiveStoragePvs(unittest.TestCase):
  """Test cases for functions dealing with LVM PV and exclusive storage"""
  # Allowance for rounding
  _EPS = 1e-4
  _MARGIN = constants.PART_MARGIN + constants.PART_RESERVED + _EPS

  @staticmethod
  def _GenerateRandomPvInfo(rnd, name, vg):
    # Granularity is .01 MiB
    size = rnd.randint(1024 * 100, 10 * 1024 * 1024 * 100)
    if rnd.choice([False, True]):
      free = float(rnd.randint(0, size)) / 100.0
    else:
      free = float(size) / 100.0
    size = float(size) / 100.0
    attr = "a-"
    return objects.LvmPvInfo(name=name, vg_name=vg, size=size, free=free,
                             attributes=attr)

  def testGetStdPvSize(self):
    """Test cases for bdev.LogicalVolume._GetStdPvSize()"""
    rnd = random.Random(9517)
    for _ in range(0, 50):
      # Identical volumes
      pvi = self._GenerateRandomPvInfo(rnd, "disk", "myvg")
      onesize = bdev.LogicalVolume._GetStdPvSize([pvi])
      self.assertTrue(onesize <= pvi.size)
      self.assertTrue(onesize > pvi.size * (1 - self._MARGIN))
      for length in range(2, 10):
        n_size = bdev.LogicalVolume._GetStdPvSize([pvi] * length)
        self.assertEqual(onesize, n_size)

      # Mixed volumes
      for length in range(1, 10):
        pvlist = [self._GenerateRandomPvInfo(rnd, "disk", "myvg")
                  for _ in range(0, length)]
        std_size = bdev.LogicalVolume._GetStdPvSize(pvlist)
        self.assertTrue(compat.all(std_size <= pvi.size for pvi in pvlist))
        self.assertTrue(compat.any(std_size > pvi.size * (1 - self._MARGIN)
                                   for pvi in pvlist))
        pvlist.append(pvlist[0])
        p1_size = bdev.LogicalVolume._GetStdPvSize(pvlist)
        self.assertEqual(std_size, p1_size)

  def testComputeNumPvs(self):
    """Test cases for bdev.LogicalVolume._ComputeNumPvs()"""
    rnd = random.Random(8067)
    for _ in range(0, 1000):
      pvlist = [self._GenerateRandomPvInfo(rnd, "disk", "myvg")]
      lv_size = float(rnd.randint(10 * 100, 1024 * 1024 * 100)) / 100.0
      num_pv = bdev.LogicalVolume._ComputeNumPvs(lv_size, pvlist)
      std_size = bdev.LogicalVolume._GetStdPvSize(pvlist)
      self.assertTrue(num_pv >= 1)
      self.assertTrue(num_pv * std_size >= lv_size)
      self.assertTrue((num_pv - 1) * std_size < lv_size * (1 + self._EPS))

  def testGetEmptyPvNames(self):
    """Test cases for bdev.LogicalVolume._GetEmptyPvNames()"""
    rnd = random.Random(21126)
    for _ in range(0, 100):
      num_pvs = rnd.randint(1, 20)
      pvlist = [self._GenerateRandomPvInfo(rnd, "disk%d" % n, "myvg")
                for n in range(0, num_pvs)]
      for num_req in range(1, num_pvs + 2):
        epvs = bdev.LogicalVolume._GetEmptyPvNames(pvlist, num_req)
        epvs_set = compat.UniqueFrozenset(epvs)
        if len(epvs) > 1:
          self.assertEqual(len(epvs), len(epvs_set))
        for pvi in pvlist:
          if pvi.name in epvs_set:
            self.assertEqual(pvi.size, pvi.free)
          else:
            # There should be no remaining empty PV when less than the
            # requeste number of PVs has been returned
            self.assertTrue(len(epvs) == num_req or pvi.free != pvi.size)


class TestLogicalVolume(testutils.GanetiTestCase):
  """Tests for bdev.LogicalVolume."""

  def setUp(self):
    """Set up test data"""
    testutils.GanetiTestCase.setUp(self)

    self.volume_name = "31225655-5775-4356-c212-e8b1e137550a.disk0"
    self.test_unique_id = ("ganeti", self.volume_name)
    self.test_params = {
      constants.LDP_STRIPES: 1
      }
    self.pv_info_return = [objects.LvmPvInfo(name="/dev/sda5", vg_name="xenvg",
                                             size=3500000.00, free=5000000.00,
                                             attributes="wz--n-", lv_list=[])]
    self.pv_info_invalid = [objects.LvmPvInfo(name="/dev/s:da5",
                                              vg_name="xenvg",
                                             size=3500000.00, free=5000000.00,
                                              attributes="wz--n-", lv_list=[])]
    self.pv_info_no_space = [objects.LvmPvInfo(name="/dev/sda5", vg_name="xenvg",
                                               size=3500000.00, free=0.00,
                                               attributes="wz--n-", lv_list=[])]


  def testParseLvInfoLine(self):
    """Tests for LogicalVolume._ParseLvInfoLine."""
    broken_lines = [
      "  toomuch#vg#lv#-wi-ao#253#3#4096.00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3#4096.00#/dev/abc(20)",
      "  vg#lv#-wi-a#253#3#4096.00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#25.3#3#4096.00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#twenty#3#4096.00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3.1#4096.00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#three#4096.00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3#four#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3#4096..00#2#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3#4096.00#2.0#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3#4096.00#two#/dev/abc(20)",
      "  vg#lv#-wi-ao#253#3#4096.00#2#/dev/abc20",
      ]
    for broken in broken_lines:
      self.assertRaises(errors.BlockDeviceError,
                        bdev.LogicalVolume._ParseLvInfoLine, broken, "#")

    # Examples of good lines from "lvs":
    #
    #   /dev/something|-wi-ao|253|3|4096.00|2|/dev/sdb(144),/dev/sdc(0)
    #   /dev/somethingelse|-wi-a-|253|4|4096.00|1|/dev/sdb(208)
    true_out = [
        (("vg", "lv"), ("-wi-ao", 253, 3, 4096.00, 2, ["/dev/abc"])),
        (("vg", "lv"), ("-wi-a-", 253, 7, 4096.00, 4, ["/dev/abc"])),
        (("vg", "lv"), ("-ri-a-", 253, 4, 4.00, 5, ["/dev/abc", "/dev/def"])),
        (("vg", "lv"), ("-wc-ao", 15, 18, 4096.00, 32,
                       ["/dev/abc", "/dev/def", "/dev/ghi0"])),
        # Physical devices might be missing with thin volumes
        (("vg", "lv"), ("twc-ao", 15, 18, 4096.00, 32, [])),
    ]
    for exp in true_out:
      for sep in "#;|":
        # NB We get lvs to return vg_name and lv_name separately, but
        # _ParseLvInfoLine returns a pathname built from these, so we
        # need to do some extra munging to round-trip this properly.
        vg_name, lv_name = exp[0]
        dev = os.environ.get('DM_DEV_DIR', '/dev')
        devpath = os.path.join(dev, vg_name, lv_name)
        lvs = exp[1]
        pvs = ",".join("%s(%s)" % (d, i * 12) for (i, d) in enumerate(lvs[-1]))
        fmt_str = sep.join(("  %s", "%s", "%s", "%d", "%d", "%.2f", "%d", "%s"))
        lvs_line = fmt_str % ((vg_name, lv_name) + lvs[0:-1] + (pvs,))
        parsed = bdev.LogicalVolume._ParseLvInfoLine(lvs_line, sep)
        self.assertEqual(parsed, (devpath,) + exp[1:])


  def testGetLvGlobalInfo(self):
    """Tests for LogicalVolume.GetLvGlobalInfo."""

    good_lines="vg|1|-wi-ao|253|3|4096.00|2|/dev/sda(20)\n" \
        "vg|2|-wi-ao|253|3|4096.00|2|/dev/sda(21)\n"
    expected_output = {"/dev/vg/1": ("-wi-ao", 253, 3, 4096, 2, ["/dev/sda"]),
                       "/dev/vg/2": ("-wi-ao", 253, 3, 4096, 2, ["/dev/sda"])}

    self.assertEqual({},
                     bdev.LogicalVolume.GetLvGlobalInfo(
                         _run_cmd=lambda cmd: _FakeRunCmd(False,
                                                          "Fake error msg",
                                                          cmd)))
    self.assertEqual({},
                     bdev.LogicalVolume.GetLvGlobalInfo(
                         _run_cmd=lambda cmd: _FakeRunCmd(True,
                                                          "",
                                                          cmd)))
    self.assertRaises(errors.BlockDeviceError,
                      bdev.LogicalVolume.GetLvGlobalInfo,
                      _run_cmd=lambda cmd: _FakeRunCmd(True, "BadStdOut", cmd))

    fake_cmd = lambda cmd: _FakeRunCmd(True, good_lines, cmd)
    good_res = bdev.LogicalVolume.GetLvGlobalInfo(_run_cmd=fake_cmd)
    self.assertEqual(expected_output, good_res)

  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testLogicalVolumeImport(self, attach_mock):
    """Tests for bdev.LogicalVolume.Import()"""
    # Set up the mock object return value
    attach_mock.return_value = True

    # Create a fake logical volume
    inst = bdev.LogicalVolume(self.test_unique_id, [], 1024, {}, {})

    # Desired output command
    import_cmd = [constants.DD_CMD,
                  "of=%s" % inst.dev_path,
                  "bs=%s" % constants.DD_BLOCK_SIZE,
                  "oflag=direct", "conv=notrunc"]

    self.assertEqual(inst.Import(), import_cmd)

  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testLogicalVolumeExport(self, attach_mock):
    """Test for bdev.LogicalVolume.Export()"""
    # Set up the mock object return value
    attach_mock.return_value = True

    # Create a fake logical volume
    inst = bdev.LogicalVolume(self.test_unique_id, [], 1024, {}, {})

    # Desired output command
    export_cmd = [constants.DD_CMD,
                  "if=%s" % inst.dev_path,
                  "bs=%s" % constants.DD_BLOCK_SIZE,
                  "count=%s" % inst.size,
                  "iflag=direct"]

    self.assertEqual(inst.Export(), export_cmd)

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(utils, "RunCmd")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreate(self, attach_mock, run_cmd_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() success"""
    attach_mock.return_value = True
    # This returns a successful RunCmd result
    run_cmd_mock.return_value = _FakeRunCmd(True, "", "")
    pv_info_mock.return_value = self.pv_info_return

    expect = bdev.LogicalVolume(self.test_unique_id, [], 1024,
                                self.test_params, {})
    got = bdev.LogicalVolume.Create(self.test_unique_id, [], 1024, None,
                                    self.test_params, False, {},
                                    test_kwarg="test")

    self.assertEqual(expect, got)

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailurePvsInfoExclStor(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when pv_info is empty and
    exclusive storage is enabled

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = []

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, None, {}, True, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailurePvsInfoNoExclStor(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when pv_info is empty and
    exclusive storage is disabled

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = []

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, None, {}, False, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailurePvsInvalid(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when pvs_info output is
    invalid

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = self.pv_info_invalid

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, None, {}, False, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailureNoSpindles(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when there are no spindles

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = self.pv_info_return

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, None,
                      self.test_params,True, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailureNotEnoughSpindles(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when there are not enough
    spindles

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = self.pv_info_return

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, 0,
                      self.test_params, True, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailureNotEnoughEmptyPvs(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when there are not enough
    empty pvs

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = self.pv_info_return

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, 2,
                      self.test_params, True, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailureNoFreeSpace(self, attach_mock, pv_info_mock):
    """Test for bdev.LogicalVolume.Create() failure when there is no free space

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = self.pv_info_no_space

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, None,
                      self.test_params, False, {})

  @testutils.patch_object(utils, "RunCmd")
  @testutils.patch_object(bdev.LogicalVolume, "GetPVInfo")
  @testutils.patch_object(bdev.LogicalVolume, "Attach")
  def testCreateFailureCommand(self, attach_mock, pv_info_mock, run_cmd_mock):
    """Test for bdev.LogicalVolume.Create() failure when the runcmd is incorrect

    """
    attach_mock.return_value = True
    pv_info_mock.return_value = self.pv_info_return
    run_cmd_mock = _FakeRunCmd(False, "", "")

    self.assertRaises(errors.BlockDeviceError, bdev.LogicalVolume.Create,
                      self.test_unique_id, [], 1024, None,
                      self.test_params, False, {})

  @testutils.patch_object(bdev.LogicalVolume, "GetLvGlobalInfo")
  def testAttach(self, info_mock):
    """Test for bdev.LogicalVolume.Attach()"""
    info_mock.return_value = {"/dev/fake/path": ("v", 1, 0, 1024, 0, ["test"])}
    dev = bdev.LogicalVolume.__new__(bdev.LogicalVolume)
    dev.dev_path = "/dev/fake/path"

    self.assertEqual(dev.Attach(), True)

  @testutils.patch_object(bdev.LogicalVolume, "GetLvGlobalInfo")
  def testAttachFalse(self, info_mock):
    """Test for bdev.LogicalVolume.Attach() with missing lv_info"""
    info_mock.return_value = {}
    dev = bdev.LogicalVolume.__new__(bdev.LogicalVolume)
    dev.dev_path = "/dev/fake/path"

    self.assertEqual(dev.Attach(), False)


class TestPersistentBlockDevice(testutils.GanetiTestCase):
  """Tests for bdev.PersistentBlockDevice volumes

  """

  def setUp(self):
    """Set up test data"""
    testutils.GanetiTestCase.setUp(self)
    self.test_unique_id = (constants.BLOCKDEV_DRIVER_MANUAL, "/dev/abc")

  def testPersistentBlockDeviceImport(self):
    """Test case for bdev.PersistentBlockDevice.Import()"""
    # Create a fake block device
    inst = bdev.PersistentBlockDevice(self.test_unique_id, [], 1024, {}, {})

    self.assertRaises(errors.BlockDeviceError,
                      bdev.PersistentBlockDevice.Import, inst)

  @testutils.patch_object(bdev.PersistentBlockDevice, "Attach")
  def testCreate(self, attach_mock):
    """Test for bdev.PersistentBlockDevice.Create()"""
    attach_mock.return_value = True

    expect = bdev.PersistentBlockDevice(self.test_unique_id, [], 0, {}, {})
    got = bdev.PersistentBlockDevice.Create(self.test_unique_id, [], 1024, None,
                                            {}, False, {}, test_kwarg="test")

    self.assertEqual(expect, got)

  def testCreateFailure(self):
    """Test for bdev.PersistentBlockDevice.Create() failure"""

    self.assertRaises(errors.ProgrammerError, bdev.PersistentBlockDevice.Create,
                      self.test_unique_id, [], 1024, None, {}, True, {})

  @testutils.patch_object(os, "stat")
  def testAttach(self, stat_mock):
    """Test for bdev.PersistentBlockDevice.Attach()"""
    stat_mock.return_value = FakeStatResult(0x6000) # bitmask for S_ISBLK
    dev = bdev.PersistentBlockDevice.__new__(bdev.PersistentBlockDevice)
    dev.dev_path = "/dev/fake/path"

    self.assertEqual(dev.Attach(), True)

  @testutils.patch_object(os, "stat")
  def testAttachFailureNotBlockdev(self, stat_mock):
    """Test for bdev.PersistentBlockDevice.Attach() failure, not a blockdev"""
    stat_mock.return_value = FakeStatResult(0x0)
    dev = bdev.PersistentBlockDevice.__new__(bdev.PersistentBlockDevice)
    dev.dev_path = "/dev/fake/path"

    self.assertEqual(dev.Attach(), False)

  @testutils.patch_object(os, "stat")
  def testAttachFailureNoDevice(self, stat_mock):
    """Test for bdev.PersistentBlockDevice.Attach() failure, no device found"""
    stat_mock.side_effect = OSError("No device found")
    dev = bdev.PersistentBlockDevice.__new__(bdev.PersistentBlockDevice)
    dev.dev_path = "/dev/fake/path"

    self.assertEqual(dev.Attach(), False)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
