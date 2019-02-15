#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Script for testing the hypervisor.hv_kvm module"""

import threading
import tempfile
import unittest
import socket
import os
import struct
import re

from ganeti import serializer
from ganeti import constants
from ganeti import compat
from ganeti import objects
from ganeti import errors
from ganeti import utils
from ganeti import pathutils

from ganeti.hypervisor import hv_kvm
import ganeti.hypervisor.hv_kvm.netdev as netdev
import ganeti.hypervisor.hv_kvm.monitor as monitor

import mock
import testutils

from testutils.config_mock import ConfigMock


class QmpStub(threading.Thread):
  """Stub for a QMP endpoint for a KVM instance

  """
  _QMP_BANNER_DATA = {
    "QMP": {
      "version": {
        "package": "",
        "qemu": {
          "micro": 50,
          "minor": 13,
          "major": 0,
          },
        "capabilities": [],
        },
      }
    }
  _EMPTY_RESPONSE = {
    "return": [],
    }
  _SUPPORTED_COMMANDS = {
    "return": [
      {"name": "command"},
      {"name": "query-kvm"},
      {"name": "eject"},
      {"name": "query-status"},
      {"name": "query-name"},
    ]
  }

  def __init__(self, socket_filename, server_responses):
    """Creates a QMP stub

    @type socket_filename: string
    @param socket_filename: filename of the UNIX socket that will be created
                            this class and used for the communication
    @type server_responses: list
    @param server_responses: list of responses that the server sends in response
                             to whatever it receives
    """
    threading.Thread.__init__(self)
    self.socket_filename = socket_filename
    self.script = server_responses[:]

    self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.socket.bind(self.socket_filename)
    self.socket.listen(1)

  def run(self):
    # Hypothesis: the messages we receive contain only a complete QMP message
    # encoded in JSON.
    conn, addr = self.socket.accept()

    # Send the banner as the first thing
    conn.send(self.encode_string(self._QMP_BANNER_DATA))

    # Expect qmp_capabilities and return an empty response
    conn.recv(4096)
    conn.send(self.encode_string(self._EMPTY_RESPONSE))

    # Expect query-commands and return the list of supported commands
    conn.recv(4096)
    conn.send(self.encode_string(self._SUPPORTED_COMMANDS))

    while True:
      # We ignore the expected message, as the purpose of this object is not
      # to verify the correctness of the communication but to act as a
      # partner for the SUT (System Under Test, that is QmpConnection)
      msg = conn.recv(4096)
      if not msg:
        break

      if not self.script:
        break
      response = self.script.pop(0)
      if isinstance(response, str):
        conn.send(response)
      elif isinstance(response, list):
        for chunk in response:
          conn.send(chunk)
      else:
        raise errors.ProgrammerError("Unknown response type for %s" % response)

    conn.close()

  def encode_string(self, message):
    return (serializer.DumpJson(message) +
            hv_kvm.QmpConnection._MESSAGE_END_TOKEN)


class TestQmpMessage(testutils.GanetiTestCase):
  def testSerialization(self):
    test_data = {
      "execute": "command",
      "arguments": ["a", "b", "c"],
      }
    message = hv_kvm.QmpMessage(test_data)

    for k, v in test_data.items():
      self.assertEqual(message[k], v)

    serialized = str(message)
    self.assertEqual(len(serialized.splitlines()), 1,
                     msg="Got multi-line message")

    rebuilt_message = hv_kvm.QmpMessage.BuildFromJsonString(serialized)
    self.assertEqual(rebuilt_message, message)
    self.assertEqual(len(rebuilt_message), len(test_data))

  def testDelete(self):
    toDelete = "execute"
    test_data = {
      toDelete: "command",
      "arguments": ["a", "b", "c"],
      }
    message = hv_kvm.QmpMessage(test_data)

    oldLen = len(message)
    del message[toDelete]
    newLen = len(message)
    self.assertEqual(oldLen - 1, newLen)


class TestQmp(testutils.GanetiTestCase):
  REQUESTS = [
    {"execute": "query-kvm", "arguments": []},
    {"execute": "eject", "arguments": {"device": "ide1-cd0"}},
    {"execute": "query-status", "arguments": []},
    {"execute": "query-name", "arguments": []},
    ]

  SERVER_RESPONSES = [
    # One message, one send()
    '{"return": {"enabled": true, "present": true}}\r\n',

    # Message sent using multiple send()
    ['{"retur', 'n": {}}\r\n'],

    # Multiple messages sent using one send()
    '{"return": [{"name": "quit"}, {"name": "eject"}]}\r\n'
    '{"return": {"running": true, "singlestep": false}}\r\n',
    ]

  EXPECTED_RESPONSES = [
    {"enabled": True, "present": True},
    {},
    [{"name": "quit"}, {"name": "eject"}],
    {"running": True, "singlestep": False},
    ]

  def testQmp(self):
    # Set up the stub
    socket_file = tempfile.NamedTemporaryFile()
    os.remove(socket_file.name)
    qmp_stub = QmpStub(socket_file.name, self.SERVER_RESPONSES)
    qmp_stub.start()

    # Set up the QMP connection
    qmp_connection = hv_kvm.QmpConnection(socket_file.name)
    qmp_connection.connect()

    # Format the script
    for request, expected_response in zip(self.REQUESTS,
                                          self.EXPECTED_RESPONSES):
      response = qmp_connection.Execute(request["execute"],
                                        request["arguments"])
      self.assertEqual(response, expected_response)
      msg = hv_kvm.QmpMessage({"return": expected_response})
      self.assertEqual(len(str(msg).splitlines()), 1,
                       msg="Got multi-line message")

    self.assertRaises(monitor.QmpCommandNotSupported,
                      qmp_connection.Execute,
                      "unsupported-command")

  def testQmpContextManager(self):
    # Set up the stub
    socket_file = tempfile.NamedTemporaryFile()
    os.remove(socket_file.name)
    qmp_stub = QmpStub(socket_file.name, self.SERVER_RESPONSES)
    qmp_stub.start()

    # Test the context manager functionality
    with hv_kvm.QmpConnection(socket_file.name) as qmp:
      for request, expected_response in zip(self.REQUESTS,
                                            self.EXPECTED_RESPONSES):
        response = qmp.Execute(request["execute"], request["arguments"])
        self.assertEqual(response, expected_response)


class TestConsole(unittest.TestCase):
  def MakeConsole(self, instance, node, group, hvparams):
    cons = hv_kvm.KVMHypervisor.GetInstanceConsole(instance, node, group,
                                                   hvparams, {})
    self.assertEqual(cons.Validate(), None)
    return cons

  def testSerial(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node6017-uuid")
    node = objects.Node(name="node6017", uuid="node6017-uuid",
                        ndparams={})
    group = objects.NodeGroup(name="group6134", ndparams={})
    hvparams = {
      constants.HV_SERIAL_CONSOLE: True,
      constants.HV_VNC_BIND_ADDRESS: None,
      constants.HV_KVM_SPICE_BIND: None,
      }
    cons = self.MakeConsole(instance, node, group, hvparams)
    self.assertEqual(cons.kind, constants.CONS_SSH)
    self.assertEqual(cons.host, node.name)
    self.assertEqual(cons.command[0], pathutils.KVM_CONSOLE_WRAPPER)
    self.assertEqual(cons.command[1], constants.SOCAT_PATH)

  def testVnc(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node7235-uuid",
                                network_port=constants.VNC_BASE_PORT + 10)
    node = objects.Node(name="node7235", uuid="node7235-uuid",
                        ndparams={})
    group = objects.NodeGroup(name="group3632", ndparams={})
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: "192.0.2.1",
      constants.HV_KVM_SPICE_BIND: None,
      }
    cons = self.MakeConsole(instance, node, group, hvparams)
    self.assertEqual(cons.kind, constants.CONS_VNC)
    self.assertEqual(cons.host, "192.0.2.1")
    self.assertEqual(cons.port, constants.VNC_BASE_PORT + 10)
    self.assertEqual(cons.display, 10)

  def testSpice(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node7235",
                                network_port=11000)
    node = objects.Node(name="node7235", uuid="node7235-uuid",
                        ndparams={})
    group = objects.NodeGroup(name="group0132", ndparams={})
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: None,
      constants.HV_KVM_SPICE_BIND: "192.0.2.1",
      }
    cons = self.MakeConsole(instance, node, group, hvparams)
    self.assertEqual(cons.kind, constants.CONS_SPICE)
    self.assertEqual(cons.host, "192.0.2.1")
    self.assertEqual(cons.port, 11000)

  def testNoConsole(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node24325",
                                network_port=0)
    node = objects.Node(name="node24325", uuid="node24325-uuid",
                        ndparams={})
    group = objects.NodeGroup(name="group9184", ndparams={})
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: None,
      constants.HV_KVM_SPICE_BIND: None,
      }
    cons = self.MakeConsole(instance, node, group, hvparams)
    self.assertEqual(cons.kind, constants.CONS_MESSAGE)


class TestVersionChecking(testutils.GanetiTestCase):
  @staticmethod
  def ParseTestData(name):
    help = testutils.ReadTestData(name)
    return hv_kvm.KVMHypervisor._ParseKVMVersion(help)

  def testParseVersion112(self):
    self.assertEqual(
        self.ParseTestData("kvm_1.1.2_help.txt"), ("1.1.2", 1, 1, 2))

  def testParseVersion10(self):
    self.assertEqual(self.ParseTestData("kvm_1.0_help.txt"), ("1.0", 1, 0, 0))

  def testParseVersion01590(self):
    self.assertEqual(
        self.ParseTestData("kvm_0.15.90_help.txt"), ("0.15.90", 0, 15, 90))

  def testParseVersion0125(self):
    self.assertEqual(
        self.ParseTestData("kvm_0.12.5_help.txt"), ("0.12.5", 0, 12, 5))

  def testParseVersion091(self):
    self.assertEqual(
        self.ParseTestData("kvm_0.9.1_help.txt"), ("0.9.1", 0, 9, 1))


class TestSpiceParameterList(unittest.TestCase):
  def setUp(self):
    self.defaults = constants.HVC_DEFAULTS[constants.HT_KVM]

  def testAudioCompressionDefaultOn(self):
    self.assertTrue(self.defaults[constants.HV_KVM_SPICE_AUDIO_COMPR])

  def testVdAgentDefaultOn(self):
    self.assertTrue(self.defaults[constants.HV_KVM_SPICE_USE_VDAGENT])

  def testTlsCiphersDefaultOn(self):
    self.assertTrue(self.defaults[constants.HV_KVM_SPICE_TLS_CIPHERS])

  def testBindDefaultOff(self):
    self.assertFalse(self.defaults[constants.HV_KVM_SPICE_BIND])

  def testAdditionalParams(self):
    params = compat.UniqueFrozenset(
        getattr(constants, name)
        for name in dir(constants)
        if name.startswith("HV_KVM_SPICE_"))
    fixed = set([
        constants.HV_KVM_SPICE_BIND, constants.HV_KVM_SPICE_TLS_CIPHERS,
        constants.HV_KVM_SPICE_USE_VDAGENT, constants.HV_KVM_SPICE_AUDIO_COMPR])
    self.assertEqual(hv_kvm._SPICE_ADDITIONAL_PARAMS, params - fixed)


class TestHelpRegexps(testutils.GanetiTestCase):
  """Check _BOOT_RE

  It has to match -drive.*boot=on|off except if there is another dash-option
  at the beginning of the line.

  """

  @staticmethod
  def SearchTestData(name):
    boot_re = hv_kvm.KVMHypervisor._BOOT_RE
    help = testutils.ReadTestData(name)
    return boot_re.search(help)

  def testBootRe112(self):
    self.assertFalse(self.SearchTestData("kvm_1.1.2_help.txt"))

  def testBootRe10(self):
    self.assertFalse(self.SearchTestData("kvm_1.0_help.txt"))

  def testBootRe01590(self):
    self.assertFalse(self.SearchTestData("kvm_0.15.90_help.txt"))

  def testBootRe0125(self):
    self.assertTrue(self.SearchTestData("kvm_0.12.5_help.txt"))

  def testBootRe091(self):
    self.assertTrue(self.SearchTestData("kvm_0.9.1_help.txt"))

  def testBootRe091_fake(self):
    self.assertFalse(self.SearchTestData("kvm_0.9.1_help_boot_test.txt"))


class TestGetTunFeatures(unittest.TestCase):
  def testWrongIoctl(self):
    tmpfile = tempfile.NamedTemporaryFile()
    # A file does not have the right ioctls, so this must always fail
    result = netdev._GetTunFeatures(tmpfile.fileno())
    self.assertTrue(result is None)

  def _FakeIoctl(self, features, fd, request, buf):
    self.assertEqual(request, netdev.TUNGETFEATURES)

    (reqno, ) = struct.unpack("I", buf)
    self.assertEqual(reqno, 0)

    return struct.pack("I", features)

  def test(self):
    tmpfile = tempfile.NamedTemporaryFile()
    fd = tmpfile.fileno()

    for features in [0, netdev.IFF_VNET_HDR]:
      fn = compat.partial(self._FakeIoctl, features)
      result = netdev._GetTunFeatures(fd, _ioctl=fn)
      self.assertEqual(result, features)


class TestProbeTapVnetHdr(unittest.TestCase):
  def _FakeTunFeatures(self, expected_fd, flags, fd):
    self.assertEqual(fd, expected_fd)
    return flags

  def test(self):
    tmpfile = tempfile.NamedTemporaryFile()
    fd = tmpfile.fileno()

    for flags in [0, netdev.IFF_VNET_HDR]:
      fn = compat.partial(self._FakeTunFeatures, fd, flags)

      result = netdev._ProbeTapVnetHdr(fd, _features_fn=fn)
      if flags == 0:
        self.assertFalse(result)
      else:
        self.assertTrue(result)

  def testUnsupported(self):
    tmpfile = tempfile.NamedTemporaryFile()
    fd = tmpfile.fileno()

    self.assertFalse(netdev._ProbeTapVnetHdr(fd, _features_fn=lambda _: None))


class TestGenerateDeviceKVMId(unittest.TestCase):
  def test(self):
    device = objects.NIC()
    target = constants.HOTPLUG_TARGET_NIC
    fn = hv_kvm._GenerateDeviceKVMId
    device.uuid = "003fc157-66a8-4e6d-8b7e-ec4f69751396"
    self.assertTrue(re.match("nic-003fc157-66a8-4e6d", fn(target, device)))


class TestGenerateDeviceHVInfo(testutils.GanetiTestCase):
  def testPCI(self):
    """Test the placement of the first PCI device during startup."""
    self.MockOut(mock.patch('ganeti.utils.EnsureDirs'))
    hypervisor = hv_kvm.KVMHypervisor()
    dev_type = constants.HOTPLUG_TARGET_NIC
    kvm_devid = "nic-9e7c85f6-b6e5-4243"
    hv_dev_type = constants.HT_NIC_PARAVIRTUAL
    bus_slots = hypervisor._GetBusSlots()
    hvinfo = hv_kvm._GenerateDeviceHVInfo(dev_type,
                                          kvm_devid,
                                          hv_dev_type,
                                          bus_slots)
    # NOTE: The PCI slot is zero-based, i.e. 13th slot has addr hex(12)
    expected_hvinfo = {
      "driver": "virtio-net-pci",
      "id": kvm_devid,
      "bus": "pci.0",
      "addr": hex(constants.QEMU_DEFAULT_PCI_RESERVATIONS),
      }

    self.assertTrue(hvinfo == expected_hvinfo)

  def testSCSI(self):
    """Test the placement of the first SCSI device during startup."""
    self.MockOut(mock.patch('ganeti.utils.EnsureDirs'))
    hypervisor = hv_kvm.KVMHypervisor()
    dev_type = constants.HOTPLUG_TARGET_DISK
    kvm_devid = "disk-932df160-7a22-4067"
    hv_dev_type = constants.HT_DISK_SCSI_BLOCK
    bus_slots = hypervisor._GetBusSlots()
    hvinfo = hv_kvm._GenerateDeviceHVInfo(dev_type,
                                          kvm_devid,
                                          hv_dev_type,
                                          bus_slots)
    expected_hvinfo = {
      "driver": "scsi-block",
      "id": kvm_devid,
      "bus": "scsi.0",
      "channel": 0,
      "scsi-id": 0,
      "lun": 0,
      }

    self.assertTrue(hvinfo == expected_hvinfo)


class TestGetRuntimeInfo(unittest.TestCase):
  @classmethod
  def _GetRuntime(cls):
    data = testutils.ReadTestData("kvm_runtime.json")
    return hv_kvm._AnalyzeSerializedRuntime(data)

  def _fail(self, target, device, runtime):
    device.uuid = "aaaaaaaa-66a8-4e6d-8b7e-ec4f69751396"
    self.assertRaises(errors.HotplugError,
                      hv_kvm._GetExistingDeviceInfo,
                      target, device, runtime)

  def testNIC(self):
    device = objects.NIC()
    target = constants.HOTPLUG_TARGET_NIC
    runtime = self._GetRuntime()

    self._fail(target, device, runtime)

    device.uuid = "003fc157-66a8-4e6d-8b7e-ec4f69751396"
    devinfo = hv_kvm._GetExistingDeviceInfo(target, device, runtime)
    self.assertTrue(devinfo.hvinfo["addr"] == "0x8")

  def testDisk(self):
    device = objects.Disk()
    target = constants.HOTPLUG_TARGET_DISK
    runtime = self._GetRuntime()

    self._fail(target, device, runtime)

    device.uuid = "9f5c5bd4-6f60-480b-acdc-9bb1a4b7df79"
    (devinfo, _, __) = hv_kvm._GetExistingDeviceInfo(target, device, runtime)
    self.assertTrue(devinfo.hvinfo["addr"] == "0xa")


class PostfixMatcher(object):
  def __init__(self, string):
    self.string = string

  def __eq__(self, other):
    return other.endswith(self.string)

  def __repr__(self):
    return "<Postfix %s>" % self.string

class TestKvmRuntime(testutils.GanetiTestCase):
  """The _ExecuteKvmRuntime is at the core of all KVM operations."""

  def setUp(self):
    super(TestKvmRuntime, self).setUp()
    kvm_class = 'ganeti.hypervisor.hv_kvm.KVMHypervisor'
    self.MockOut('qmp', mock.patch('ganeti.hypervisor.hv_kvm.QmpConnection'))
    self.MockOut('run_cmd', mock.patch('ganeti.utils.RunCmd'))
    self.MockOut('ensure_dirs', mock.patch('ganeti.utils.EnsureDirs'))
    self.MockOut('write_file', mock.patch('ganeti.utils.WriteFile'))
    self.MockOut(mock.patch(kvm_class + '.ValidateParameters'))
    self.MockOut(mock.patch('ganeti.hypervisor.hv_kvm.OpenTap',
                            return_value=('test_nic', [], [])))
    self.MockOut(mock.patch(kvm_class + '._ConfigureNIC'))
    self.MockOut('pid_alive', mock.patch(kvm_class + '._InstancePidAlive',
                                         return_value=('file', -1, False)))
    self.MockOut(mock.patch(kvm_class + '._ExecuteCpuAffinity'))
    self.MockOut(mock.patch(kvm_class + '._CallMonitorCommand'))

    self.cfg = ConfigMock()
    params = constants.HVC_DEFAULTS[constants.HT_KVM].copy()
    beparams = constants.BEC_DEFAULTS.copy()
    self.instance = self.cfg.AddNewInstance(name='name.example.com',
                                            hypervisor='kvm',
                                            hvparams=params,
                                            beparams=beparams)

  def testDirectoriesCreated(self):
    hypervisor = hv_kvm.KVMHypervisor()
    self.mocks['ensure_dirs'].assert_called_with([
        (PostfixMatcher('/run/ganeti/kvm-hypervisor'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/pid'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/uid'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/ctrl'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/conf'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/nic'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/chroot'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/chroot-quarantine'), 0775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/keymap'), 0775)])

  def testStartInstance(self):
    hypervisor = hv_kvm.KVMHypervisor()
    def RunCmd(cmd, **kwargs):
      if '--help' in cmd:
        return mock.Mock(
            failed=False, output=testutils.ReadTestData("kvm_1.1.2_help.txt"))
      if '-S' in cmd:
        self.mocks['pid_alive'].return_value = ('file', -1, True)
        return mock.Mock(failed=False)
      elif '-M' in cmd:
        return mock.Mock(failed=False, output='')
      elif '-device' in cmd:
        return mock.Mock(failed=False, output='name "virtio-blk-pci"')
      else:
        raise errors.ProgrammerError('Unexpected command: %s' % cmd)
    self.mocks['run_cmd'].side_effect = RunCmd
    hypervisor.StartInstance(self.instance, [], False)

if __name__ == "__main__":
  testutils.GanetiTestProgram()
