#!/usr/bin/python
#

# Copyright (C) 2011, 2013 Google Inc.
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

import string # pylint: disable=W0402
import unittest
import tempfile
import shutil
import random
import os

from ganeti import constants
from ganeti import objects
from ganeti import hypervisor
from ganeti import utils
from ganeti import errors
from ganeti import compat

from ganeti.hypervisor import hv_xen

import testutils


# Map from hypervisor class to hypervisor name
HVCLASS_TO_HVNAME = utils.InvertDict(hypervisor._HYPERVISOR_MAP)


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


class TestCreateConfigCpus(unittest.TestCase):
  def testEmpty(self):
    for cpu_mask in [None, ""]:
      self.assertEqual(hv_xen._CreateConfigCpus(cpu_mask),
                       "cpus = [  ]")

  def testAll(self):
    self.assertEqual(hv_xen._CreateConfigCpus(constants.CPU_PINNING_ALL),
                     None)

  def testOne(self):
    self.assertEqual(hv_xen._CreateConfigCpus("9"), "cpu = \"9\"")

  def testMultiple(self):
    self.assertEqual(hv_xen._CreateConfigCpus("0-2,4,5-5:3:all"),
                     ("cpus = [ \"0,1,2,4,5\", \"3\", \"%s\" ]" %
                      constants.CPU_PINNING_ALL_XEN))


class TestParseXmList(testutils.GanetiTestCase):
  def test(self):
    data = testutils.ReadTestData("xen-xm-list-4.0.1-dom0-only.txt")

    # Exclude node
    self.assertEqual(hv_xen._ParseXmList(data.splitlines(), False), [])

    # Include node
    result = hv_xen._ParseXmList(data.splitlines(), True)
    self.assertEqual(len(result), 1)
    self.assertEqual(len(result[0]), 6)

    # Name
    self.assertEqual(result[0][0], hv_xen._DOM0_NAME)

    # ID
    self.assertEqual(result[0][1], 0)

    # Memory
    self.assertEqual(result[0][2], 1023)

    # VCPUs
    self.assertEqual(result[0][3], 1)

    # State
    self.assertEqual(result[0][4], "r-----")

    # Time
    self.assertAlmostEqual(result[0][5], 121152.6)

  def testWrongLineFormat(self):
    tests = [
      ["three fields only"],
      ["name InvalidID 128 1 r----- 12345"],
      ]

    for lines in tests:
      try:
        hv_xen._ParseXmList(["Header would be here"] + lines, False)
      except errors.HypervisorError, err:
        self.assertTrue("Can't parse output of xm list" in str(err))
      else:
        self.fail("Exception was not raised")


class TestGetXmList(testutils.GanetiTestCase):
  def _Fail(self):
    return utils.RunResult(constants.EXIT_FAILURE, None,
                           "stdout", "stderr", None,
                           NotImplemented, NotImplemented)

  def testTimeout(self):
    fn = testutils.CallCounter(self._Fail)
    try:
      hv_xen._GetXmList(fn, False, _timeout=0.1)
    except errors.HypervisorError, err:
      self.assertTrue("timeout exceeded" in str(err))
    else:
      self.fail("Exception was not raised")

    self.assertTrue(fn.Count() < 10,
                    msg="'xm list' was called too many times")

  def _Success(self, stdout):
    return utils.RunResult(constants.EXIT_SUCCESS, None, stdout, "", None,
                           NotImplemented, NotImplemented)

  def testSuccess(self):
    data = testutils.ReadTestData("xen-xm-list-4.0.1-four-instances.txt")

    fn = testutils.CallCounter(compat.partial(self._Success, data))

    result = hv_xen._GetXmList(fn, True, _timeout=0.1)

    self.assertEqual(len(result), 4)

    self.assertEqual(map(compat.fst, result), [
      "Domain-0",
      "server01.example.com",
      "web3106215069.example.com",
      "testinstance.example.com",
      ])

    self.assertEqual(fn.Count(), 1)


class TestParseNodeInfo(testutils.GanetiTestCase):
  def testEmpty(self):
    self.assertEqual(hv_xen._ParseNodeInfo(""), {})

  def testUnknownInput(self):
    data = "\n".join([
      "foo bar",
      "something else goes",
      "here",
      ])
    self.assertEqual(hv_xen._ParseNodeInfo(data), {})

  def testBasicInfo(self):
    data = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    result = hv_xen._ParseNodeInfo(data)
    self.assertEqual(result, {
      "cpu_nodes": 1,
      "cpu_sockets": 2,
      "cpu_total": 4,
      "hv_version": (4, 0),
      "memory_free": 8004,
      "memory_total": 16378,
      })


class TestMergeInstanceInfo(testutils.GanetiTestCase):
  def testEmpty(self):
    self.assertEqual(hv_xen._MergeInstanceInfo({}, lambda _: []), {})

  def _FakeXmList(self, include_node):
    self.assertTrue(include_node)
    return [
      (hv_xen._DOM0_NAME, NotImplemented, 4096, 7, NotImplemented,
       NotImplemented),
      ("inst1.example.com", NotImplemented, 2048, 4, NotImplemented,
       NotImplemented),
      ]

  def testMissingNodeInfo(self):
    result = hv_xen._MergeInstanceInfo({}, self._FakeXmList)
    self.assertEqual(result, {
      "memory_dom0": 4096,
      "dom0_cpus": 7,
      })

  def testWithNodeInfo(self):
    info = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    result = hv_xen._GetNodeInfo(info, self._FakeXmList)
    self.assertEqual(result, {
      "cpu_nodes": 1,
      "cpu_sockets": 2,
      "cpu_total": 4,
      "dom0_cpus": 7,
      "hv_version": (4, 0),
      "memory_dom0": 4096,
      "memory_free": 8004,
      "memory_hv": 2230,
      "memory_total": 16378,
      })


class TestGetConfigFileDiskData(unittest.TestCase):
  def testLetterCount(self):
    self.assertEqual(len(hv_xen._DISK_LETTERS), 26)

  def testNoDisks(self):
    self.assertEqual(hv_xen._GetConfigFileDiskData([], "hd"), [])

  def testManyDisks(self):
    for offset in [0, 1, 10]:
      disks = [(objects.Disk(dev_type=constants.LD_LV), "/tmp/disk/%s" % idx)
               for idx in range(len(hv_xen._DISK_LETTERS) + offset)]

      if offset == 0:
        result = hv_xen._GetConfigFileDiskData(disks, "hd")
        self.assertEqual(result, [
          "'phy:/tmp/disk/%s,hd%s,r'" % (idx, string.ascii_lowercase[idx])
          for idx in range(len(hv_xen._DISK_LETTERS) + offset)
          ])
      else:
        try:
          hv_xen._GetConfigFileDiskData(disks, "hd")
        except errors.HypervisorError, err:
          self.assertEqual(str(err), "Too many disks")
        else:
          self.fail("Exception was not raised")

  def testTwoLvDisksWithMode(self):
    disks = [
      (objects.Disk(dev_type=constants.LD_LV, mode=constants.DISK_RDWR),
       "/tmp/diskFirst"),
      (objects.Disk(dev_type=constants.LD_LV, mode=constants.DISK_RDONLY),
       "/tmp/diskLast"),
      ]

    result = hv_xen._GetConfigFileDiskData(disks, "hd")
    self.assertEqual(result, [
      "'phy:/tmp/diskFirst,hda,w'",
      "'phy:/tmp/diskLast,hdb,r'",
      ])

  def testFileDisks(self):
    disks = [
      (objects.Disk(dev_type=constants.LD_FILE, mode=constants.DISK_RDWR,
                    physical_id=[constants.FD_LOOP]),
       "/tmp/diskFirst"),
      (objects.Disk(dev_type=constants.LD_FILE, mode=constants.DISK_RDONLY,
                    physical_id=[constants.FD_BLKTAP]),
       "/tmp/diskTwo"),
      (objects.Disk(dev_type=constants.LD_FILE, mode=constants.DISK_RDWR,
                    physical_id=[constants.FD_LOOP]),
       "/tmp/diskThree"),
      (objects.Disk(dev_type=constants.LD_FILE, mode=constants.DISK_RDWR,
                    physical_id=[constants.FD_BLKTAP]),
       "/tmp/diskLast"),
      ]

    result = hv_xen._GetConfigFileDiskData(disks, "sd")
    self.assertEqual(result, [
      "'file:/tmp/diskFirst,sda,w'",
      "'tap:aio:/tmp/diskTwo,sdb,r'",
      "'file:/tmp/diskThree,sdc,w'",
      "'tap:aio:/tmp/diskLast,sdd,w'",
      ])

  def testInvalidFileDisk(self):
    disks = [
      (objects.Disk(dev_type=constants.LD_FILE, mode=constants.DISK_RDWR,
                    physical_id=["#unknown#"]),
       "/tmp/diskinvalid"),
      ]

    self.assertRaises(KeyError, hv_xen._GetConfigFileDiskData, disks, "sd")


class TestXenHypervisorUnknownCommand(unittest.TestCase):
  def test(self):
    cmd = "#unknown command#"
    self.assertFalse(cmd in constants.KNOWN_XEN_COMMANDS)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=NotImplemented,
                              _cmd=cmd)
    self.assertRaises(errors.ProgrammerError, hv._RunXen, [])


class TestXenHypervisorWriteConfigFile(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testWriteError(self):
    cfgdir = utils.PathJoin(self.tmpdir, "foobar")

    hv = hv_xen.XenHypervisor(_cfgdir=cfgdir,
                              _run_cmd_fn=NotImplemented,
                              _cmd=NotImplemented)

    self.assertFalse(os.path.exists(cfgdir))

    try:
      hv._WriteConfigFile("name", "data")
    except errors.HypervisorError, err:
      self.assertTrue(str(err).startswith("Cannot write Xen instance"))
    else:
      self.fail("Exception was not raised")


class _TestXenHypervisor(object):
  TARGET = NotImplemented
  CMD = NotImplemented
  HVNAME = NotImplemented

  def setUp(self):
    super(_TestXenHypervisor, self).setUp()

    self.tmpdir = tempfile.mkdtemp()

    self.vncpw = "".join(random.sample(string.ascii_letters, 10))

    self.vncpw_path = utils.PathJoin(self.tmpdir, "vncpw")
    utils.WriteFile(self.vncpw_path, data=self.vncpw)

  def tearDown(self):
    super(_TestXenHypervisor, self).tearDown()

    shutil.rmtree(self.tmpdir)

  def _GetHv(self, run_cmd=NotImplemented):
    return self.TARGET(_cfgdir=self.tmpdir, _run_cmd_fn=run_cmd, _cmd=self.CMD)

  def _SuccessCommand(self, stdout, cmd):
    self.assertEqual(cmd[0], self.CMD)

    return utils.RunResult(constants.EXIT_SUCCESS, None, stdout, "", None,
                           NotImplemented, NotImplemented)

  def _FailingCommand(self, cmd):
    self.assertEqual(cmd[0], self.CMD)

    return utils.RunResult(constants.EXIT_FAILURE, None,
                           "", "This command failed", None,
                           NotImplemented, NotImplemented)

  def testReadingNonExistentConfigFile(self):
    hv = self._GetHv()

    try:
      hv._ReadConfigFile("inst15780.example.com")
    except errors.HypervisorError, err:
      self.assertTrue(str(err).startswith("Failed to load Xen config file:"))
    else:
      self.fail("Exception was not raised")

  def testRemovingAutoConfigFile(self):
    name = "inst8206.example.com"
    cfgfile = utils.PathJoin(self.tmpdir, name)
    autodir = utils.PathJoin(self.tmpdir, "auto")
    autocfgfile = utils.PathJoin(autodir, name)

    os.mkdir(autodir)

    utils.WriteFile(autocfgfile, data="")

    hv = self._GetHv()

    self.assertTrue(os.path.isfile(autocfgfile))
    hv._WriteConfigFile(name, "content")
    self.assertFalse(os.path.exists(autocfgfile))
    self.assertEqual(utils.ReadFile(cfgfile), "content")

  def testVerify(self):
    output = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    hv = self._GetHv(run_cmd=compat.partial(self._SuccessCommand,
                                            output))
    self.assertTrue(hv.Verify() is None)

  def testVerifyFailing(self):
    hv = self._GetHv(run_cmd=self._FailingCommand)
    self.assertTrue("failed:" in hv.Verify())

  def _StartInstanceCommand(self, inst, paused, failcreate, cmd):
    if cmd == [self.CMD, "info"]:
      output = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    elif cmd == [self.CMD, "list"]:
      output = testutils.ReadTestData("xen-xm-list-4.0.1-dom0-only.txt")
    elif cmd[:2] == [self.CMD, "create"]:
      args = cmd[2:]
      cfgfile = utils.PathJoin(self.tmpdir, inst.name)

      if paused:
        self.assertEqual(args, ["-p", cfgfile])
      else:
        self.assertEqual(args, [cfgfile])

      if failcreate:
        return self._FailingCommand(cmd)

      output = ""
    else:
      self.fail("Unhandled command: %s" % (cmd, ))

    return self._SuccessCommand(output, cmd)
    #return self._FailingCommand(cmd)

  def _MakeInstance(self):
    # Copy default parameters
    bep = objects.FillDict(constants.BEC_DEFAULTS, {})
    hvp = objects.FillDict(constants.HVC_DEFAULTS[self.HVNAME], {})

    # Override default VNC password file path
    if constants.HV_VNC_PASSWORD_FILE in hvp:
      hvp[constants.HV_VNC_PASSWORD_FILE] = self.vncpw_path

    disks = [
      (objects.Disk(dev_type=constants.LD_LV, mode=constants.DISK_RDWR),
       utils.PathJoin(self.tmpdir, "disk0")),
      (objects.Disk(dev_type=constants.LD_LV, mode=constants.DISK_RDONLY),
       utils.PathJoin(self.tmpdir, "disk1")),
      ]

    inst = objects.Instance(name="server01.example.com",
                            hvparams=hvp, beparams=bep,
                            osparams={}, nics=[], os="deb1",
                            disks=map(compat.fst, disks))
    inst.UpgradeConfig()

    return (inst, disks)

  def testStartInstance(self):
    (inst, disks) = self._MakeInstance()

    for failcreate in [False, True]:
      for paused in [False, True]:
        run_cmd = compat.partial(self._StartInstanceCommand,
                                 inst, paused, failcreate)

        hv = self._GetHv(run_cmd=run_cmd)

        # Ensure instance is not listed
        self.assertTrue(inst.name not in hv.ListInstances())

        # Remove configuration
        cfgfile = utils.PathJoin(self.tmpdir, inst.name)
        utils.RemoveFile(cfgfile)

        if failcreate:
          self.assertRaises(errors.HypervisorError, hv.StartInstance,
                            inst, disks, paused)
        else:
          hv.StartInstance(inst, disks, paused)

        # Check if configuration was updated
        lines = utils.ReadFile(cfgfile).splitlines()

        if constants.HV_VNC_PASSWORD_FILE in inst.hvparams:
          self.assertTrue(("vncpasswd = '%s'" % self.vncpw) in lines)
        else:
          extra = inst.hvparams[constants.HV_KERNEL_ARGS]
          self.assertTrue(("extra = '%s'" % extra) in lines)

  def _StopInstanceCommand(self, instance_name, force, fail, cmd):
    if ((force and cmd[:2] == [self.CMD, "destroy"]) or
        (not force and cmd[:2] == [self.CMD, "shutdown"])):
      self.assertEqual(cmd[2:], [instance_name])
      output = ""
    else:
      self.fail("Unhandled command: %s" % (cmd, ))

    if fail:
      # Simulate a failing command
      return self._FailingCommand(cmd)
    else:
      return self._SuccessCommand(output, cmd)

  def testStopInstance(self):
    name = "inst4284.example.com"
    cfgfile = utils.PathJoin(self.tmpdir, name)
    cfgdata = "config file content\n"

    for force in [False, True]:
      for fail in [False, True]:
        utils.WriteFile(cfgfile, data=cfgdata)

        run_cmd = compat.partial(self._StopInstanceCommand, name, force, fail)

        hv = self._GetHv(run_cmd=run_cmd)

        self.assertTrue(os.path.isfile(cfgfile))

        if fail:
          try:
            hv._StopInstance(name, force)
          except errors.HypervisorError, err:
            self.assertTrue(str(err).startswith("Failed to stop instance"))
          else:
            self.fail("Exception was not raised")
          self.assertEqual(utils.ReadFile(cfgfile), cfgdata,
                           msg=("Configuration was removed when stopping"
                                " instance failed"))
        else:
          hv._StopInstance(name, force)
          self.assertFalse(os.path.exists(cfgfile))


def _MakeTestClass(cls, cmd):
  """Makes a class for testing.

  The returned class has structure as shown in the following pseudo code:

    class Test{cls.__name__}{cmd}(_TestXenHypervisor, unittest.TestCase):
      TARGET = {cls}
      CMD = {cmd}
      HVNAME = {Hypervisor name retrieved using class}

  @type cls: class
  @param cls: Hypervisor class to be tested
  @type cmd: string
  @param cmd: Hypervisor command
  @rtype: tuple
  @return: Class name and class object (not instance)

  """
  name = "Test%sCmd%s" % (cls.__name__, cmd.title())
  bases = (_TestXenHypervisor, unittest.TestCase)
  hvname = HVCLASS_TO_HVNAME[cls]

  return (name, type(name, bases, dict(TARGET=cls, CMD=cmd, HVNAME=hvname)))


# Create test classes programmatically instead of manually to reduce the risk
# of forgetting some combinations
for cls in [hv_xen.XenPvmHypervisor, hv_xen.XenHvmHypervisor]:
  for cmd in constants.KNOWN_XEN_COMMANDS:
    (name, testcls) = _MakeTestClass(cls, cmd)

    assert name not in locals()

    locals()[name] = testcls


if __name__ == "__main__":
  testutils.GanetiTestProgram()
