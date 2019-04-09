#!/usr/bin/python
#

# Copyright (C) 2011, 2013 Google Inc.
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


"""Script for testing ganeti.hypervisor.hv_xen"""

import string # pylint: disable=W0402
import unittest
import tempfile
import shutil
import random
import os
import mock

from ganeti import constants
from ganeti import objects
from ganeti import pathutils
from ganeti import hypervisor
from ganeti import utils
from ganeti import errors
from ganeti import compat

from ganeti.hypervisor import hv_base
from ganeti.hypervisor import hv_xen

import testutils


# Map from hypervisor class to hypervisor name
HVCLASS_TO_HVNAME = utils.InvertDict(hypervisor._HYPERVISOR_MAP)


class TestConsole(unittest.TestCase):
  def test(self):
    hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    for cls in [hv_xen.XenPvmHypervisor(), hv_xen.XenHvmHypervisor()]:
      instance = objects.Instance(name="xen.example.com",
                                  primary_node="node24828-uuid")
      node = objects.Node(name="node24828", uuid="node24828-uuid",
                          ndparams={})
      group = objects.NodeGroup(name="group52341", ndparams={})
      cons = cls.GetInstanceConsole(instance, node, group, hvparams, {})
      self.assertEqual(cons.Validate(), None)
      self.assertEqual(cons.kind, constants.CONS_SSH)
      self.assertEqual(cons.host, node.name)
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


class TestGetCommand(testutils.GanetiTestCase):
  def testCommandExplicit(self):
    """Test the case when the command is given as class parameter explicitly.

    """
    expected_cmd = "xl"
    hv = hv_xen.XenHypervisor(_cmd=constants.XEN_CMD_XL)
    self.assertEqual(hv._GetCommand(None), expected_cmd)

  def testCommandInvalid(self):
    """Test the case an invalid command is given as class parameter explicitly.

    """
    hv = hv_xen.XenHypervisor(_cmd="invalidcommand")
    self.assertRaises(errors.ProgrammerError, hv._GetCommand, None)

  def testCommandHvparams(self):
    expected_cmd = "xl"
    test_hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    hv = hv_xen.XenHypervisor()
    self.assertEqual(hv._GetCommand(test_hvparams), expected_cmd)

  def testCommandHvparamsInvalid(self):
    test_hvparams = {}
    hv = hv_xen.XenHypervisor()
    self.assertRaises(errors.HypervisorError, hv._GetCommand, test_hvparams)

  def testCommandHvparamsCmdInvalid(self):
    test_hvparams = {constants.HV_XEN_CMD: "invalidcommand"}
    hv = hv_xen.XenHypervisor()
    self.assertRaises(errors.ProgrammerError, hv._GetCommand, test_hvparams)


class TestParseInstanceList(testutils.GanetiTestCase):
  def test(self):
    data = testutils.ReadTestData("xen-xm-list-4.0.1-dom0-only.txt")

    # Exclude node
    self.assertEqual(hv_xen._ParseInstanceList(data.splitlines(), False), [])

    # Include node
    result = hv_xen._ParseInstanceList(data.splitlines(), True)
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
    self.assertEqual(result[0][4], hv_base.HvInstanceState.RUNNING)

    # Time
    self.assertAlmostEqual(result[0][5], 121152.6)

  def testWrongLineFormat(self):
    tests = [
      ["three fields only"],
      ["name InvalidID 128 1 r----- 12345"],
      ]

    for lines in tests:
      try:
        hv_xen._ParseInstanceList(["Header would be here"] + lines, False)
      except errors.HypervisorError as err:
        self.assertTrue("Can't parse instance list" in str(err))
      else:
        self.fail("Exception was not raised")


class TestInstanceStateParsing(unittest.TestCase):
  def testRunningStates(self):
    states = [
      "r-----",
      "r-p---",
      "rb----",
      "rbp---",
      "-b----",
      "-bp---",
      "-----d",
      "--p--d",
      "------",
      "--p---",
      "r--ss-",
      "r-pss-",
      "rb-ss-",
      "rbpss-",
      "-b-ss-",
      "-bpss-",
      "---ss-",
      "r--sr-",
      "r-psr-",
      "rb-sr-",
      "rbpsr-",
      "-b-sr-",
      "-bpsr-",
      "---sr-",
    ]
    for state in states:
      self.assertEqual(hv_xen._XenToHypervisorInstanceState(state),
                       hv_base.HvInstanceState.RUNNING)

  def testShutdownStates(self):
    states = [
      "---s--",
      "--ps--",
      "---s-d",
      "--ps-d",
    ]
    for state in states:
      self.assertEqual(hv_xen._XenToHypervisorInstanceState(state),
                       hv_base.HvInstanceState.SHUTDOWN)

  def testCrashingStates(self):
    states = [
      "--psc-",
      "---sc-",
      "---scd",
      "--p-c-",
      "----c-",
      "----cd",
    ]
    for state in states:
      self.assertRaises(hv_xen._InstanceCrashed,
                        hv_xen._XenToHypervisorInstanceState, state)


class TestGetInstanceList(testutils.GanetiTestCase):
  def _Fail(self):
    return utils.RunResult(constants.EXIT_FAILURE, None,
                           "stdout", "stderr", None,
                           NotImplemented, NotImplemented)

  def testTimeout(self):
    fn = testutils.CallCounter(self._Fail)
    try:
      hv_xen._GetRunningInstanceList(fn, False, delays=(0.02, 1.0, 0.03),
                                     timeout=0.1)
    except errors.HypervisorError as err:
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

    result = hv_xen._GetRunningInstanceList(fn, True, delays=(0.02, 1.0, 0.03),
                                            timeout=0.1)

    self.assertEqual(len(result), 4)

    self.assertEqual([r[0] for r in result], [
      "Domain-0",
      "server01.example.com",
      "web3106215069.example.com",
      "testinstance.example.com",
      ])

    self.assertEqual(fn.Count(), 1)

  def testOmitCrashed(self):
    data = testutils.ReadTestData("xen-xl-list-4.4-crashed-instances.txt")

    fn = testutils.CallCounter(compat.partial(self._Success, data))

    result = hv_xen._GetAllInstanceList(fn, True, delays=(0.02, 1.0, 0.03),
                                        timeout=0.1)

    self.assertEqual(len(result), 2)

    self.assertEqual([r[0] for r in result], [
      "Domain-0",
      "server01.example.com",
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
    self.assertEqual(hv_xen._MergeInstanceInfo({}, []), {})

  def _FakeXmList(self, include_node):
    return [
      (hv_xen._DOM0_NAME, NotImplemented, 4096, 7, NotImplemented,
       NotImplemented),
      ("inst1.example.com", NotImplemented, 2048, 4, NotImplemented,
       NotImplemented),
      ]

  def testMissingNodeInfo(self):
    instance_list = self._FakeXmList(True)
    result = hv_xen._MergeInstanceInfo({}, instance_list)
    self.assertEqual(result, {
      "memory_dom0": 4096,
      "cpu_dom0": 7,
      })

  def testWithNodeInfo(self):
    info = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    instance_list = self._FakeXmList(True)
    result = hv_xen._GetNodeInfo(info, instance_list)
    self.assertEqual(result, {
      "cpu_nodes": 1,
      "cpu_sockets": 2,
      "cpu_total": 4,
      "cpu_dom0": 7,
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
      disks = [(objects.Disk(dev_type=constants.DT_PLAIN),
               "/tmp/disk/%s" % idx,
               NotImplemented)
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
        except errors.HypervisorError as err:
          self.assertEqual(str(err), "Too many disks")
        else:
          self.fail("Exception was not raised")

  def testTwoLvDisksWithMode(self):
    disks = [
      (objects.Disk(dev_type=constants.DT_PLAIN, mode=constants.DISK_RDWR),
       "/tmp/diskFirst",
       NotImplemented),
      (objects.Disk(dev_type=constants.DT_PLAIN, mode=constants.DISK_RDONLY),
       "/tmp/diskLast",
       NotImplemented),
      ]

    result = hv_xen._GetConfigFileDiskData(disks, "hd")
    self.assertEqual(result, [
      "'phy:/tmp/diskFirst,hda,w'",
      "'phy:/tmp/diskLast,hdb,r'",
      ])

  def testFileDisks(self):
    disks = [
      (objects.Disk(dev_type=constants.DT_FILE, mode=constants.DISK_RDWR,
                    logical_id=[constants.FD_LOOP]),
       "/tmp/diskFirst",
       NotImplemented),
      (objects.Disk(dev_type=constants.DT_FILE, mode=constants.DISK_RDONLY,
                    logical_id=[constants.FD_BLKTAP]),
       "/tmp/diskTwo",
       NotImplemented),
      (objects.Disk(dev_type=constants.DT_FILE, mode=constants.DISK_RDWR,
                    logical_id=[constants.FD_LOOP]),
       "/tmp/diskThree",
       NotImplemented),
      (objects.Disk(dev_type=constants.DT_FILE, mode=constants.DISK_RDONLY,
                    logical_id=[constants.FD_BLKTAP2]),
       "/tmp/diskFour",
       NotImplemented),
      (objects.Disk(dev_type=constants.DT_FILE, mode=constants.DISK_RDWR,
                    logical_id=[constants.FD_BLKTAP]),
       "/tmp/diskLast",
       NotImplemented),
      ]

    result = hv_xen._GetConfigFileDiskData(disks, "sd")
    self.assertEqual(result, [
      "'file:/tmp/diskFirst,sda,w'",
      "'tap:aio:/tmp/diskTwo,sdb,r'",
      "'file:/tmp/diskThree,sdc,w'",
      "'tap2:tapdisk:aio:/tmp/diskFour,sdd,r'",
      "'tap:aio:/tmp/diskLast,sde,w'",
      ])

  def testInvalidFileDisk(self):
    disks = [
      (objects.Disk(dev_type=constants.DT_FILE, mode=constants.DISK_RDWR,
                    logical_id=["#unknown#"]),
       "/tmp/diskinvalid",
       NotImplemented),
      ]

    self.assertRaises(KeyError, hv_xen._GetConfigFileDiskData, disks, "sd")


class TestXenHypervisorRunXen(unittest.TestCase):

  XEN_SUB_CMD = "help"

  def testCommandUnknown(self):
    cmd = "#unknown command#"
    self.assertFalse(cmd in constants.KNOWN_XEN_COMMANDS)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=NotImplemented,
                              _cmd=cmd)
    self.assertRaises(errors.ProgrammerError, hv._RunXen, [], None)

  def testCommandNoHvparams(self):
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=NotImplemented)
    hvparams = None
    self.assertRaises(errors.HypervisorError, hv._RunXen, [self.XEN_SUB_CMD],
                      hvparams)

  def testCommandFromHvparams(self):
    expected_xen_cmd = "xl"
    hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    mock_run_cmd = mock.Mock()
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    hv._RunXen([self.XEN_SUB_CMD], hvparams=hvparams)
    mock_run_cmd.assert_called_with([expected_xen_cmd, self.XEN_SUB_CMD])


class TestXenHypervisorGetInstanceList(unittest.TestCase):

  RESULT_OK = utils.RunResult(0, None, "", "", "", None, None)
  XEN_LIST = "list"

  def testNoHvparams(self):
    expected_xen_cmd = "xm"
    mock_run_cmd = mock.Mock(return_value=self.RESULT_OK)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    self.assertRaises(errors.HypervisorError, hv._GetInstanceList, True, None)

  def testFromHvparams(self):
    expected_xen_cmd = "xl"
    hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    mock_run_cmd = mock.Mock(return_value=self.RESULT_OK)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    hv._GetInstanceList(True, hvparams)
    mock_run_cmd.assert_called_with([expected_xen_cmd, self.XEN_LIST])


class TestXenHypervisorListInstances(unittest.TestCase):

  RESULT_OK = utils.RunResult(0, None, "", "", "", None, None)
  XEN_LIST = "list"

  def testNoHvparams(self):
    expected_xen_cmd = "xm"
    mock_run_cmd = mock.Mock(return_value=self.RESULT_OK)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    self.assertRaises(errors.HypervisorError, hv.ListInstances)

  def testHvparamsXl(self):
    expected_xen_cmd = "xl"
    hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    mock_run_cmd = mock.Mock(return_value=self.RESULT_OK)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    hv.ListInstances(hvparams=hvparams)
    mock_run_cmd.assert_called_with([expected_xen_cmd, self.XEN_LIST])


class TestXenHypervisorCheckToolstack(unittest.TestCase):

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.cfg_name = "xen_config"
    self.cfg_path = utils.PathJoin(self.tmpdir, self.cfg_name)
    self.hv = hv_xen.XenHypervisor()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testBinaryNotFound(self):
    RESULT_FAILED = utils.RunResult(1, None, "", "", "", None, None)
    mock_run_cmd = mock.Mock(return_value=RESULT_FAILED)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    result = hv._CheckToolstackBinary("xl")
    self.assertFalse(result)

  def testCheckToolstackXlConfigured(self):
    RESULT_OK = utils.RunResult(0, None, "", "", "", None, None)
    mock_run_cmd = mock.Mock(return_value=RESULT_OK)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    result = hv._CheckToolstackXlConfigured()
    self.assertTrue(result)

  def testCheckToolstackXlNotConfigured(self):
    RESULT_FAILED = utils.RunResult(
        1, None, "",
        "ERROR:  A different toolstack (xm) has been selected!",
        "", None, None)
    mock_run_cmd = mock.Mock(return_value=RESULT_FAILED)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    result = hv._CheckToolstackXlConfigured()
    self.assertFalse(result)

  def testCheckToolstackXlFails(self):
    RESULT_FAILED = utils.RunResult(
        1, None, "",
        "ERROR: The pink bunny hid the binary.",
        "", None, None)
    mock_run_cmd = mock.Mock(return_value=RESULT_FAILED)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    self.assertRaises(errors.HypervisorError, hv._CheckToolstackXlConfigured)


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
    except errors.HypervisorError as err:
      self.assertTrue(str(err).startswith("Cannot write Xen instance"))
    else:
      self.fail("Exception was not raised")


class TestXenHypervisorVerify(unittest.TestCase):

  def setUp(self):
    output = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    self._result_ok = utils.RunResult(0, None, output, "", "", None, None)

  def testVerify(self):
    hvparams = {constants.HV_XEN_CMD : constants.XEN_CMD_XL}
    mock_run_cmd = mock.Mock(return_value=self._result_ok)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    hv._CheckToolstack = mock.Mock(return_value=True)
    result = hv.Verify(hvparams)
    self.assertTrue(result is None)

  def testVerifyToolstackNotOk(self):
    hvparams = {constants.HV_XEN_CMD : constants.XEN_CMD_XL}
    mock_run_cmd = mock.Mock(return_value=self._result_ok)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    hv._CheckToolstack = mock.Mock()
    hv._CheckToolstack.side_effect = errors.HypervisorError("foo")
    result = hv.Verify(hvparams)
    self.assertTrue(result is not None)

  def testVerifyFailing(self):
    result_failed = utils.RunResult(1, None, "", "", "", None, None)
    mock_run_cmd = mock.Mock(return_value=result_failed)
    hv = hv_xen.XenHypervisor(_cfgdir=NotImplemented,
                              _run_cmd_fn=mock_run_cmd)
    hv._CheckToolstack = mock.Mock(return_value=True)
    result = hv.Verify()
    self.assertTrue(result is not None)


class _TestXenHypervisor(object):
  TARGET = NotImplemented
  CMD = NotImplemented
  HVNAME = NotImplemented
  VALID_HVPARAMS = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}

  def setUp(self):
    super(_TestXenHypervisor, self).setUp()

    self.tmpdir = tempfile.mkdtemp()

    self.vncpw = "".join(random.sample(string.ascii_letters, 10))

    self._xen_delay = self.TARGET._INSTANCE_LIST_DELAYS
    self.TARGET._INSTANCE_LIST_DELAYS = (0.01, 1.0, 0.05)

    self._list_timeout = self.TARGET._INSTANCE_LIST_TIMEOUT
    self.TARGET._INSTANCE_LIST_TIMEOUT = 0.1

    self.vncpw_path = utils.PathJoin(self.tmpdir, "vncpw")
    utils.WriteFile(self.vncpw_path, data=self.vncpw)

  def tearDown(self):
    super(_TestXenHypervisor, self).tearDown()

    shutil.rmtree(self.tmpdir)

    self.TARGET._INSTANCE_LIST_DELAYS = self._xen_delay
    self.TARGET._INSTANCE_LIST_TIMEOUT = self._list_timeout

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

  def _FakeTcpPing(self, expected, result, target, port, **kwargs):
    self.assertEqual((target, port), expected)
    return result

  def testReadingNonExistentConfigFile(self):
    hv = self._GetHv()

    try:
      hv._ReadConfigFile("inst15780.example.com")
    except errors.HypervisorError as err:
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

  def _XenList(self, cmd):
    self.assertEqual(cmd, [self.CMD, "list"])

    # TODO: Use actual data from "xl" command
    output = testutils.ReadTestData("xen-xm-list-4.0.1-four-instances.txt")

    return self._SuccessCommand(output, cmd)

  def testGetInstanceInfo(self):
    hv = self._GetHv(run_cmd=self._XenList)

    (name, instid, memory, vcpus, state, runtime) = \
      hv.GetInstanceInfo("server01.example.com")

    self.assertEqual(name, "server01.example.com")
    self.assertEqual(instid, 1)
    self.assertEqual(memory, 1024)
    self.assertEqual(vcpus, 1)
    self.assertEqual(state, hv_base.HvInstanceState.RUNNING)
    self.assertAlmostEqual(runtime, 167643.2)

  def testGetInstanceInfoDom0(self):
    hv = self._GetHv(run_cmd=self._XenList)

    # TODO: Not sure if this is actually used anywhere (can't find it), but the
    # code supports querying for Dom0
    (name, instid, memory, vcpus, state, runtime) = \
      hv.GetInstanceInfo(hv_xen._DOM0_NAME)

    self.assertEqual(name, "Domain-0")
    self.assertEqual(instid, 0)
    self.assertEqual(memory, 1023)
    self.assertEqual(vcpus, 1)
    self.assertEqual(state, hv_base.HvInstanceState.RUNNING)
    self.assertAlmostEqual(runtime, 154706.1)

  def testGetInstanceInfoUnknown(self):
    hv = self._GetHv(run_cmd=self._XenList)

    result = hv.GetInstanceInfo("unknown.example.com")
    self.assertTrue(result is None)

  def testGetAllInstancesInfo(self):
    hv = self._GetHv(run_cmd=self._XenList)

    result = hv.GetAllInstancesInfo()

    self.assertEqual([r[0] for r in result], [
      "server01.example.com",
      "web3106215069.example.com",
      "testinstance.example.com",
      ])

  def testListInstances(self):
    hv = self._GetHv(run_cmd=self._XenList)

    self.assertEqual(hv.ListInstances(), [
      "server01.example.com",
      "web3106215069.example.com",
      "testinstance.example.com",
      ])

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

  def _MakeInstance(self):
    # Copy default parameters
    bep = objects.FillDict(constants.BEC_DEFAULTS, {})
    hvp = objects.FillDict(constants.HVC_DEFAULTS[self.HVNAME], {})

    # Override default VNC password file path
    if constants.HV_VNC_PASSWORD_FILE in hvp:
      hvp[constants.HV_VNC_PASSWORD_FILE] = self.vncpw_path

    disks = [
      (objects.Disk(dev_type=constants.DT_PLAIN, mode=constants.DISK_RDWR),
       utils.PathJoin(self.tmpdir, "disk0"),
       NotImplemented),
      (objects.Disk(dev_type=constants.DT_PLAIN, mode=constants.DISK_RDONLY),
       utils.PathJoin(self.tmpdir, "disk1"),
       NotImplemented),
      ]

    inst = objects.Instance(name="server01.example.com",
                            hvparams=hvp, beparams=bep,
                            osparams={}, nics=[], os="deb1",
                            disks=[d[0] for d in disks])
    inst.UpgradeConfig()

    return (inst, disks)

  def testStartInstance(self):
    (inst, disks) = self._MakeInstance()
    pathutils.LOG_XEN_DIR = self.tmpdir

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
          # Check whether a stale config file is left behind
          self.assertFalse(os.path.exists(cfgfile))
        else:
          hv.StartInstance(inst, disks, paused)
          # Check if configuration was updated
          lines = utils.ReadFile(cfgfile).splitlines()

        if constants.HV_VNC_PASSWORD_FILE in inst.hvparams:
          self.assertTrue(("vncpasswd = '%s'" % self.vncpw) in lines)
        else:
          extra = inst.hvparams[constants.HV_KERNEL_ARGS]
          self.assertTrue(("extra = '%s'" % extra) in lines)

  def _StopInstanceCommand(self, instance_name, force, fail, full_cmd):
    # Remove the timeout (and its number of seconds) if it's there
    if full_cmd[:1][0] == "timeout":
      cmd = full_cmd[2:]
    else:
      cmd = full_cmd

    # Test the actual command
    if (cmd == [self.CMD, "list"]):
      output = "Name  ID  Mem  VCPUs  State  Time(s)\n" \
        "Domain-0  0  1023  1  r-----  142691.0\n" \
        "%s  417  128  1  r-----  3.2\n" % instance_name
    elif cmd[:2] == [self.CMD, "destroy"]:
      self.assertEqual(cmd[2:], [instance_name])
      output = ""
    elif not force and cmd[:3] == [self.CMD, "shutdown", "-w"]:
      self.assertEqual(cmd[3:], [instance_name])
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
            hv._StopInstance(name, force, None,
                             constants.DEFAULT_SHUTDOWN_TIMEOUT)
          except errors.HypervisorError as err:
            self.assertTrue(str(err).startswith("listing instances failed"),
                            msg=str(err))
          else:
            self.fail("Exception was not raised")
          self.assertEqual(utils.ReadFile(cfgfile), cfgdata,
                           msg=("Configuration was removed when stopping"
                                " instance failed"))
        else:
          hv._StopInstance(name, force, None,
                           constants.DEFAULT_SHUTDOWN_TIMEOUT)
          self.assertFalse(os.path.exists(cfgfile))

  def _MigrateNonRunningInstCmd(self, cmd):
    if cmd == [self.CMD, "list"]:
      output = testutils.ReadTestData("xen-xm-list-4.0.1-dom0-only.txt")
    else:
      self.fail("Unhandled command: %s" % (cmd, ))

    return self._SuccessCommand(output, cmd)

  def testMigrateInstanceNotRunning(self):
    name = "nonexistinginstance.example.com"
    target = constants.IP4_ADDRESS_LOCALHOST
    port = 14618

    hv = self._GetHv(run_cmd=self._MigrateNonRunningInstCmd)

    for live in [False, True]:
      try:
        hv._MigrateInstance(name, target, port, live, self.VALID_HVPARAMS,
                            _ping_fn=NotImplemented)
      except errors.HypervisorError as err:
        self.assertEqual(str(err), "Instance not running, cannot migrate")
      else:
        self.fail("Exception was not raised")

  def _MigrateInstTargetUnreachCmd(self, cmd):
    if cmd == [self.CMD, "list"]:
      output = testutils.ReadTestData("xen-xm-list-4.0.1-four-instances.txt")
    else:
      self.fail("Unhandled command: %s" % (cmd, ))

    return self._SuccessCommand(output, cmd)

  def testMigrateTargetUnreachable(self):
    name = "server01.example.com"
    target = constants.IP4_ADDRESS_LOCALHOST
    port = 28349

    hv = self._GetHv(run_cmd=self._MigrateInstTargetUnreachCmd)
    hvparams = {constants.HV_XEN_CMD: self.CMD}

    for live in [False, True]:
      if self.CMD == constants.XEN_CMD_XL:
        # TODO: Detect unreachable targets
        pass
      else:
        try:
          hv._MigrateInstance(name, target, port, live, hvparams,
                              _ping_fn=compat.partial(self._FakeTcpPing,
                                                      (target, port), False))
        except errors.HypervisorError as err:
          wanted = "Remote host %s not" % target
          self.assertTrue(str(err).startswith(wanted))
        else:
          self.fail("Exception was not raised")

  def _MigrateInstanceCmd(self, instance_name, target, port,
                          live, fail, cmd):
    if cmd == [self.CMD, "list"]:
      output = testutils.ReadTestData("xen-xm-list-4.0.1-four-instances.txt")
    elif cmd[:2] == [self.CMD, "migrate"]:
      if self.CMD == constants.XEN_CMD_XM:
        args = ["-p", str(port)]

        if live:
          args.append("-l")

      elif self.CMD == constants.XEN_CMD_XL:
        args = [
          "-s", constants.XL_SOCAT_CMD % (target, port),
          "-C", utils.PathJoin(self.tmpdir, instance_name),
          ]

      else:
        self.fail("Unknown Xen command '%s'" % self.CMD)

      args.extend([instance_name, target])
      self.assertEqual(cmd[2:], args)

      if fail:
        return self._FailingCommand(cmd)

      output = ""
    else:
      self.fail("Unhandled command: %s" % (cmd, ))

    return self._SuccessCommand(output, cmd)

  def testMigrateInstance(self):
    instname = "server01.example.com"
    target = constants.IP4_ADDRESS_LOCALHOST
    port = 22364

    hvparams = {constants.HV_XEN_CMD: self.CMD}

    for live in [False, True]:
      for fail in [False, True]:
        ping_fn = \
          testutils.CallCounter(compat.partial(self._FakeTcpPing,
                                               (target, port), True))

        run_cmd = \
          compat.partial(self._MigrateInstanceCmd,
                         instname, target, port, live, fail)

        hv = self._GetHv(run_cmd=run_cmd)

        if fail:
          try:
            hv._MigrateInstance(instname, target, port, live, hvparams,
                                _ping_fn=ping_fn)
          except errors.HypervisorError as err:
            self.assertTrue(str(err).startswith("Failed to migrate instance"))
          else:
            self.fail("Exception was not raised")
        else:
          hv._MigrateInstance(instname, target, port, live,
                              hvparams, _ping_fn=ping_fn)

        if self.CMD == constants.XEN_CMD_XM:
          expected_pings = 1
        else:
          expected_pings = 0

        self.assertEqual(ping_fn.Count(), expected_pings)

  def _GetNodeInfoCmd(self, fail, cmd):
    if cmd == [self.CMD, "info"]:
      if fail:
        return self._FailingCommand(cmd)
      else:
        output = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    elif cmd == [self.CMD, "list"]:
      if fail:
        self.fail("'xm list' shouldn't be called when 'xm info' failed")
      else:
        output = testutils.ReadTestData("xen-xm-list-4.0.1-four-instances.txt")
    else:
      self.fail("Unhandled command: %s" % (cmd, ))

    return self._SuccessCommand(output, cmd)

  def testGetNodeInfo(self):
    run_cmd = compat.partial(self._GetNodeInfoCmd, False)
    hv = self._GetHv(run_cmd=run_cmd)
    result = hv.GetNodeInfo()

    self.assertEqual(result["hv_version"], (4, 0))
    self.assertEqual(result["memory_free"], 8004)

  def testGetNodeInfoFailing(self):
    run_cmd = compat.partial(self._GetNodeInfoCmd, True)
    hv = self._GetHv(run_cmd=run_cmd)
    self.assertTrue(hv.GetNodeInfo() is None)


class TestXenVersionsSafeForMigration(unittest.TestCase):
  def testHVVersionsLikelySafeForMigration(self):
    hv = hv_xen.XenHypervisor()
    self.assertTrue(hv.VersionsSafeForMigration([4, 0], [4, 1]))
    self.assertFalse(hv.VersionsSafeForMigration([4, 1], [4, 0]))
    self.assertFalse(hv.VersionsSafeForMigration([4, 0], [4, 2]))
    self.assertTrue(hv.VersionsSafeForMigration([4, 2, 7], [4, 2, 9]))
    self.assertTrue(hv.VersionsSafeForMigration([4, 2, 9], [4, 2, 7]))
    self.assertTrue(hv.VersionsSafeForMigration([4], [4]))
    self.assertFalse(hv.VersionsSafeForMigration([4], [5]))


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
