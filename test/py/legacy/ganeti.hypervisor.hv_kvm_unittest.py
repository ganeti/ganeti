#!/usr/bin/python3
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
from unittest import mock

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
import ganeti.hypervisor.hv_kvm.validation as validation

import testutils
from lib.hypervisor.hv_kvm.kvm_runtime import KVMRuntime

from testutils.config_mock import ConfigMock


class TestParameterCheck(testutils.GanetiTestCase):
  def testInvalidVncParameters(self):
    invalid_data = {
      constants.HV_VNC_X509_VERIFY: True,
      constants.HV_VNC_X509: None
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_vnc_parameters, invalid_data)

  def testValidVncParameters(self):
    valid_data = {
      constants.HV_VNC_X509_VERIFY: True,
      constants.HV_VNC_X509: "mycert.pem"
    }

    self.assertTrue(validation.check_vnc_parameters(valid_data))

  def testInvalidSecurityModel(self):
    invalid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_USER,
      constants.HV_SECURITY_DOMAIN: None
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_security_model, invalid_data)

    invalid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_NONE,
      constants.HV_SECURITY_DOMAIN: "secure_user"
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_security_model, invalid_data)

    invalid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_POOL,
      constants.HV_SECURITY_DOMAIN: "secure_user"
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_security_model, invalid_data)

  def testValidSecurityModel(self):
    valid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_USER,
      constants.HV_SECURITY_DOMAIN: "secure_user"
    }

    self.assertTrue(validation.check_security_model(valid_data))

    valid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_POOL,
      constants.HV_SECURITY_DOMAIN: None
    }

    self.assertTrue(validation.check_security_model(valid_data))

    valid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_NONE,
      constants.HV_SECURITY_DOMAIN: None
    }

    self.assertTrue(validation.check_security_model(valid_data))

  def testInvalidBootParameters(self):
    invalid_data = {
      constants.HV_BOOT_ORDER: constants.HT_BO_CDROM,
      constants.HV_CDROM_IMAGE_PATH: None,
      constants.HV_KERNEL_PATH: "/some/path",
      constants.HV_ROOT_PATH: "/"
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_boot_parameters, invalid_data)

    invalid_data = {
      constants.HV_BOOT_ORDER: constants.HT_BO_CDROM,
      constants.HV_CDROM_IMAGE_PATH: "/cd.iso",
      constants.HV_KERNEL_PATH: "/some/path",
      constants.HV_ROOT_PATH: None
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_boot_parameters, invalid_data)

  def testValidBootParameters(self):
    valid_data = {
      constants.HV_BOOT_ORDER: constants.HT_BO_CDROM,
      constants.HV_CDROM_IMAGE_PATH: "/cd.iso",
      constants.HV_KERNEL_PATH: "/some/path",
      constants.HV_ROOT_PATH: "/"
    }

    self.assertTrue(validation.check_boot_parameters(valid_data))

    valid_data = {
      constants.HV_BOOT_ORDER: constants.HT_BO_DISK,
      constants.HV_CDROM_IMAGE_PATH: None,
      constants.HV_KERNEL_PATH: "/some/path",
      constants.HV_ROOT_PATH: "/"
    }

    self.assertTrue(validation.check_boot_parameters(valid_data))

    valid_data = {
      constants.HV_BOOT_ORDER: constants.HT_BO_DISK,
      constants.HV_CDROM_IMAGE_PATH: None,
      constants.HV_KERNEL_PATH: None,
      constants.HV_ROOT_PATH: None
    }

    self.assertTrue(validation.check_boot_parameters(valid_data))

  def testInvalidConsoleParameters(self):
    invalid_data = {
      constants.HV_SERIAL_CONSOLE: True,
      constants.HV_SERIAL_SPEED: None,
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_console_parameters, invalid_data)

    invalid_data = {
      constants.HV_SERIAL_CONSOLE: True,
      constants.HV_SERIAL_SPEED: 1,
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_console_parameters, invalid_data)

  def testValidConsoleParameters(self):
    valid_data = {
      constants.HV_SERIAL_CONSOLE: False
    }

    self.assertTrue(validation.check_console_parameters(valid_data))

    for speed in constants.VALID_SERIAL_SPEEDS:
      valid_data = {
        constants.HV_SERIAL_CONSOLE: True,
        constants.HV_SERIAL_SPEED: speed
      }

      self.assertTrue(validation.check_console_parameters(valid_data),
                      "Testing serial console speed %d" % speed)

  def testInvalidSpiceParameters(self):
    invalid_data = {
      constants.HV_KVM_SPICE_BIND: "0.0.0.0",
      constants.HV_KVM_SPICE_IP_VERSION: constants.IP6_VERSION
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_spice_parameters, invalid_data)

    invalid_data = {
      constants.HV_KVM_SPICE_BIND: "::",
      constants.HV_KVM_SPICE_IP_VERSION: constants.IP4_VERSION
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_spice_parameters, invalid_data)

    invalid_data = {
      constants.HV_KVM_SPICE_BIND: None,
      constants.HV_KVM_SPICE_IP_VERSION: None,
      constants.HV_KVM_SPICE_PASSWORD_FILE: "password.txt",
      constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR: None,
      constants.HV_KVM_SPICE_JPEG_IMG_COMPR: None,
      constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR: None,
      constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION: None,
      constants.HV_KVM_SPICE_USE_TLS: True
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_spice_parameters, invalid_data)

  def testValidSpiceParameters(self):
    valid_data = {
      constants.HV_KVM_SPICE_BIND: None,
      constants.HV_KVM_SPICE_IP_VERSION: None,
      constants.HV_KVM_SPICE_PASSWORD_FILE: None,
      constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR: None,
      constants.HV_KVM_SPICE_JPEG_IMG_COMPR: None,
      constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR: None,
      constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION: None,
      constants.HV_KVM_SPICE_USE_TLS: None
    }

    self.assertTrue(validation.check_spice_parameters(valid_data))

    valid_data = {
      constants.HV_KVM_SPICE_BIND: "0.0.0.0",
      constants.HV_KVM_SPICE_IP_VERSION: constants.IP4_VERSION,
      constants.HV_KVM_SPICE_PASSWORD_FILE: "password.txt",
      constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR: "glz",
      constants.HV_KVM_SPICE_JPEG_IMG_COMPR: "never",
      constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR: "never",
      constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION: "off",
      constants.HV_KVM_SPICE_USE_TLS: True
    }

    self.assertTrue(validation.check_spice_parameters(valid_data))

    valid_data = {
      constants.HV_KVM_SPICE_BIND: "::",
      constants.HV_KVM_SPICE_IP_VERSION: constants.IP6_VERSION,
      constants.HV_KVM_SPICE_PASSWORD_FILE: "password.txt",
      constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR: "glz",
      constants.HV_KVM_SPICE_JPEG_IMG_COMPR: "never",
      constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR: "never",
      constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION: "off",
      constants.HV_KVM_SPICE_USE_TLS: True
    }

    self.assertTrue(validation.check_spice_parameters(valid_data))

  def testInvalidDiskCacheParameters(self):
    invalid_data = {
      constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_NATIVE,
      constants.HV_DISK_CACHE: constants.HT_CACHE_WBACK
    }

    self.assertRaises(errors.HypervisorError,
                      validation.check_disk_cache_parameters, invalid_data)

  def testValidDiskCacheParameters(self):
    valid_data = {
      constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_THREADS,
      constants.HV_DISK_CACHE: constants.HT_CACHE_WBACK
    }

    self.assertTrue(validation.check_disk_cache_parameters(valid_data))

    valid_data = {
      constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_THREADS,
      constants.HV_DISK_CACHE: constants.HT_CACHE_DEFAULT
    }

    self.assertTrue(validation.check_disk_cache_parameters(valid_data))

    valid_data = {
      constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_THREADS,
      constants.HV_DISK_CACHE: constants.HT_CACHE_WTHROUGH
    }

    self.assertTrue(validation.check_disk_cache_parameters(valid_data))

    valid_data = {
      constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_NATIVE,
      constants.HV_DISK_CACHE: constants.HT_CACHE_NONE
    }

    self.assertTrue(validation.check_disk_cache_parameters(valid_data))


class TestParameterValidation(testutils.GanetiTestCase):
  def testInvalidVncParameters(self):
    # invalid IPv4 address
    invalid_data = {
      constants.HV_VNC_BIND_ADDRESS: "192.0.2.5.5",
    }

    self.assertRaises(errors.HypervisorError,
                      validation.validate_vnc_parameters, invalid_data)

    # invalid network interface
    invalid_data = {
      constants.HV_VNC_BIND_ADDRESS: "doesnotexist0",
    }

    self.assertRaises(errors.HypervisorError,
                      validation.validate_vnc_parameters, invalid_data)

  def testValidVncParameters(self):
    valid_data = {
      constants.HV_VNC_BIND_ADDRESS: "127.0.0.1"
    }

    self.assertTrue(validation.validate_vnc_parameters(valid_data))

    valid_data = {
      constants.HV_VNC_BIND_ADDRESS: "lo"
    }

    self.assertTrue(validation.validate_vnc_parameters(valid_data))

  def testInvalidSecurityModelParameters(self):
    invalid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_USER,
      constants.HV_SECURITY_DOMAIN: "really-non-existing-user"
    }

    self.assertRaises(errors.HypervisorError,
                      validation.validate_security_model, invalid_data)

  def testValidSecurityModelParameters(self):
    valid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_NONE
    }

    self.assertTrue(validation.validate_security_model(valid_data))

    valid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_POOL
    }

    self.assertTrue(validation.validate_security_model(valid_data))

    valid_data = {
      constants.HV_SECURITY_MODEL: constants.HT_SM_USER,
      constants.HV_SECURITY_DOMAIN: "root"
    }

    self.assertTrue(validation.validate_security_model(valid_data))

  def testInvalidMachineVersion(self):
    kvm_machine_output = testutils.ReadTestData("kvm_6.0.0_machine.txt")
    invalid_data = {
      constants.HV_KVM_MACHINE_VERSION: "some-invalid-machine-type"
    }
    self.assertRaises(errors.HypervisorError,
                      validation.validate_machine_version, invalid_data,
                      kvm_machine_output)

  def testValidMachineVersion(self):
    kvm_machine_output = testutils.ReadTestData("kvm_6.0.0_machine.txt")
    valid_data = {
      constants.HV_KVM_MACHINE_VERSION: "pc-i440fx-6.0"
    }
    self.assertTrue(validation.validate_machine_version(valid_data,
                                                        kvm_machine_output))

  def testInvalidSpiceParameters(self):
    kvm_help_too_old = testutils.ReadTestData("kvm_0.9.1_help.txt")
    kvm_help_working = testutils.ReadTestData("kvm_1.1.2_help.txt")

    invalid_data = {
      constants.HV_KVM_SPICE_BIND: "0.0.0.0",
      constants.HV_VNC_BIND_ADDRESS: "0.0.0.0"
    }

    self.assertRaises(errors.HypervisorError,
                      validation.validate_spice_parameters, invalid_data,
                      kvm_help_working)

    invalid_data = {
      constants.HV_KVM_SPICE_BIND: "0.0.0.0",
      constants.HV_VNC_BIND_ADDRESS: None
    }

    self.assertRaises(errors.HypervisorError,
                      validation.validate_spice_parameters, invalid_data,
                      kvm_help_too_old)

    invalid_data = {
      constants.HV_KVM_SPICE_BIND: "invalid-interface0",
      constants.HV_VNC_BIND_ADDRESS: None
    }

    self.assertRaises(errors.HypervisorError,
                      validation.validate_spice_parameters, invalid_data,
                      kvm_help_working)

  def testValidSpiceParameters(self):
    kvm_help_working = testutils.ReadTestData("kvm_1.1.2_help.txt")

    valid_data = {
      constants.HV_KVM_SPICE_BIND: "0.0.0.0",
      constants.HV_VNC_BIND_ADDRESS: None
    }

    self.assertTrue(validation.validate_spice_parameters(valid_data,
                                                         kvm_help_working))

    valid_data = {
      constants.HV_KVM_SPICE_BIND: "::",
      constants.HV_VNC_BIND_ADDRESS: None
    }

    self.assertTrue(validation.validate_spice_parameters(valid_data,
                                                         kvm_help_working))

    valid_data = {
      constants.HV_KVM_SPICE_BIND: "lo",
      constants.HV_VNC_BIND_ADDRESS: None
    }

    self.assertTrue(validation.validate_spice_parameters(valid_data,
                                                         kvm_help_working))


class TestQmpMessage(testutils.GanetiTestCase):
  def testSerialization(self):
    test_data = {
      "execute": "command",
      "arguments": ["a", "b", "c"],
      }
    message = hv_kvm.QmpMessage(test_data)

    for k, v in test_data.items():
      self.assertEqual(message[k], v)

    serialized = message.to_bytes()
    self.assertEqual(len(serialized.splitlines()), 1,
                     msg="Got multi-line message")

    rebuilt_message = hv_kvm.QmpMessage.build_from_json_string(serialized)
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
    self.assertEqual(hv_kvm.validation._SPICE_ADDITIONAL_PARAMS, params - fixed)


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
    return KVMRuntime.from_serialized(data)

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


class TestDictToQemuStringNotation(unittest.TestCase):
  def test(self):
    tests = [
      {
        "blockdev": {
          'driver': 'raw',
          'node-name': 'disk-3edc32a2-8127-4b9d',
          'discard': 'ignore',
          'cache': {
            'direct': True,
            'no-flush': False
          },
          'file': {
            'driver': 'rbd',
            'pool': 'ganeti',
            'image': '32eb97b3-ec20-401d-b48c-a1f24c0385a2.rbd.disk0'
          },
          'auto-read-only': False
        },
        "result": "driver=raw,node-name=disk-3edc32a2-8127-4b9d,"
                  "discard=ignore,cache.direct=on,cache.no-flush=off,"
                  "file.driver=rbd,file.pool=ganeti,"
                  "file.image=32eb97b3-ec20-401d-b48c-a1f24c0385a2.rbd.disk0,"
                  "auto-read-only=off"
      },
      {
          "blockdev": {
            'driver': 'raw',
            'node-name': 'disk-c44790ad-e9e2-46a3',
            'discard': 'ignore',
            'cache': {
              'direct': True,
              'no-flush': False
            },
            'file': {
              'driver': 'host_device',
              'filename': '/path/to/disk',
              'aio': 'native'
            },
            'auto-read-only': False
          },
          "result": "driver=raw,node-name=disk-c44790ad-e9e2-46a3,"
                    "discard=ignore,cache.direct=on,cache.no-flush=off,"
                    "file.driver=host_device,"
                    "file.filename=/path/to/disk,file.aio=native,"
                    "auto-read-only=off"
      }
    ]

    for test in tests:
      self.assertEqual(test["result"],
                       hv_kvm.kvm_utils.DictToQemuStringNotation(
                         test["blockdev"]))


class TestParseStorageUriToBlockdevParam(unittest.TestCase):
  def testRbd(self):
    uri = "rbd:cephpool/image-1234-xyz"

    expected_data = {
        "driver": "rbd",
        "pool": "cephpool",
        "image": "image-1234-xyz"
    }

    blockdev_driver = hv_kvm.kvm_utils.ParseStorageUriToBlockdevParam(uri)

    self.assertDictEqual(expected_data, blockdev_driver)

  def testGluster(self):
    uri = "gluster://server:1234/gluster-volume/path"

    expected_data = {
      "driver": "gluster",
      "server": [
        {
          "type": "inet",
          "host": "server",
          "port": "1234",
        }
      ],
      "volume": "gluster-volume",
      "path": "path"
    }

    blockdev_driver = hv_kvm.kvm_utils.ParseStorageUriToBlockdevParam(uri)

    self.assertDictEqual(expected_data, blockdev_driver)

  def testBadURI(self):
    uri = "gopher://storage/file"

    self.assertRaises(errors.HypervisorError,
                      hv_kvm.kvm_utils.ParseStorageUriToBlockdevParam, uri)


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
        (PostfixMatcher('/run/ganeti/kvm-hypervisor'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/pid'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/uid'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/ctrl'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/conf'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/nic'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/chroot'), 0o775),
        (PostfixMatcher('/run/ganeti/kvm-hypervisor/chroot-quarantine'), 0o775)
        ])

  def testStartInstance(self):
    hypervisor = hv_kvm.KVMHypervisor()
    def RunCmd(cmd, **kwargs):
      if '--help' in cmd:
        return mock.Mock(
            failed=False, output=testutils.ReadTestData("kvm_current_help.txt"))
      if '-S' in cmd:
        self.mocks['pid_alive'].return_value = ('file', -1, True)
        return mock.Mock(failed=False)
      elif '-machine' in cmd:
        return mock.Mock(failed=False, output='')
      elif '-device' in cmd:
        return mock.Mock(failed=False, output='name "virtio-blk-pci"')
      else:
        raise errors.ProgrammerError('Unexpected command: %s' % cmd)
    self.mocks['run_cmd'].side_effect = RunCmd
    hypervisor.StartInstance(self.instance, [], False)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
