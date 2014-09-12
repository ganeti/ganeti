#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Script for unittesting the constants module"""


import unittest
import re
import itertools

from ganeti import constants
from ganeti import locking
from ganeti import utils

from ganeti.utils import version

import testutils


class TestConstants(unittest.TestCase):
  """Constants tests"""

  def testConfigVersion(self):
    self.failUnless(constants.CONFIG_MAJOR >= 0 and
                    constants.CONFIG_MAJOR <= 99)
    self.failUnless(constants.CONFIG_MINOR >= 0 and
                    constants.CONFIG_MINOR <= 99)
    self.failUnless(constants.CONFIG_REVISION >= 0 and
                    constants.CONFIG_REVISION <= 9999)
    self.failUnless(constants.CONFIG_VERSION >= 0 and
                    constants.CONFIG_VERSION <= 99999999)

    self.failUnless(version.BuildVersion(0, 0, 0) == 0)
    self.failUnless(version.BuildVersion(10, 10, 1010) == 10101010)
    self.failUnless(version.BuildVersion(12, 34, 5678) == 12345678)
    self.failUnless(version.BuildVersion(99, 99, 9999) == 99999999)

    self.failUnless(version.SplitVersion(00000000) == (0, 0, 0))
    self.failUnless(version.SplitVersion(10101010) == (10, 10, 1010))
    self.failUnless(version.SplitVersion(12345678) == (12, 34, 5678))
    self.failUnless(version.SplitVersion(99999999) == (99, 99, 9999))
    self.failUnless(version.SplitVersion(constants.CONFIG_VERSION) ==
                    (constants.CONFIG_MAJOR, constants.CONFIG_MINOR,
                     constants.CONFIG_REVISION))

  def testDiskStatus(self):
    self.failUnless(constants.LDS_OKAY < constants.LDS_UNKNOWN)
    self.failUnless(constants.LDS_UNKNOWN < constants.LDS_FAULTY)

  def testClockSkew(self):
    self.failUnless(constants.NODE_MAX_CLOCK_SKEW <
                    (0.8 * constants.CONFD_MAX_CLOCK_SKEW))

  def testSslCertExpiration(self):
    self.failUnless(constants.SSL_CERT_EXPIRATION_ERROR <
                    constants.SSL_CERT_EXPIRATION_WARN)

  def testOpCodePriority(self):
    self.failUnless(constants.OP_PRIO_LOWEST > constants.OP_PRIO_LOW)
    self.failUnless(constants.OP_PRIO_LOW > constants.OP_PRIO_NORMAL)
    self.failUnlessEqual(constants.OP_PRIO_NORMAL, locking._DEFAULT_PRIORITY)
    self.failUnlessEqual(constants.OP_PRIO_DEFAULT, locking._DEFAULT_PRIORITY)
    self.failUnless(constants.OP_PRIO_NORMAL > constants.OP_PRIO_HIGH)
    self.failUnless(constants.OP_PRIO_HIGH > constants.OP_PRIO_HIGHEST)

  def testDiskDefaults(self):
    self.failUnless(
        set(constants.DISK_LD_DEFAULTS.keys()) ==
        set(constants.DISK_TEMPLATES) - set([constants.DT_DISKLESS]))
    self.failUnless(set(constants.DISK_DT_DEFAULTS.keys()) ==
                    constants.DISK_TEMPLATES)

  def testJobStatus(self):
    self.assertFalse(constants.JOBS_PENDING & constants.JOBS_FINALIZED)
    self.assertFalse(constants.JOBS_PENDING - constants.JOB_STATUS_ALL)
    self.assertFalse(constants.JOBS_FINALIZED - constants.JOB_STATUS_ALL)

  def testDefaultsForAllHypervisors(self):
    self.assertEqual(frozenset(constants.HVC_DEFAULTS.keys()),
                     constants.HYPER_TYPES)

  def testDefaultHypervisor(self):
    self.assertTrue(constants.DEFAULT_ENABLED_HYPERVISOR in
                    constants.HYPER_TYPES)


class TestExportedNames(unittest.TestCase):
  _VALID_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
  _BUILTIN_NAME_RE = re.compile(r"^__\w+__$")
  _EXCEPTIONS = frozenset([
    "SplitVersion",
    "BuildVersion",
    ])

  def test(self):
    wrong = \
      set(itertools.ifilterfalse(self._BUILTIN_NAME_RE.match,
            itertools.ifilterfalse(self._VALID_NAME_RE.match,
                                   dir(constants))))
    wrong -= self._EXCEPTIONS
    self.assertFalse(wrong,
                     msg=("Invalid names exported from constants module: %s" %
                          utils.CommaJoin(sorted(wrong))))


class TestParameterNames(unittest.TestCase):
  """HV/BE parameter tests"""
  VALID_NAME = re.compile("^[a-zA-Z_][a-zA-Z0-9_]*$")

  def testNoDashes(self):
    for kind, source in [("hypervisor", constants.HVS_PARAMETER_TYPES),
                         ("backend", constants.BES_PARAMETER_TYPES),
                         ("nic", constants.NICS_PARAMETER_TYPES),
                         ("instdisk", constants.IDISK_PARAMS_TYPES),
                         ("instnic", constants.INIC_PARAMS_TYPES),
                        ]:
      for key in source:
        self.failUnless(self.VALID_NAME.match(key),
                        "The %s parameter '%s' contains invalid characters" %
                        (kind, key))


class TestConfdConstants(unittest.TestCase):
  """Test the confd constants"""

  def testFourCc(self):
    self.assertEqual(len(constants.CONFD_MAGIC_FOURCC), 4,
                     msg="Invalid fourcc len, should be 4")

  def testReqs(self):
    self.assertFalse(utils.FindDuplicates(constants.CONFD_REQS),
                     msg="Duplicated confd request code")

  def testReplStatuses(self):
    self.assertFalse(utils.FindDuplicates(constants.CONFD_REPL_STATUSES),
                     msg="Duplicated confd reply status code")

class TestDiskTemplateConstants(unittest.TestCase):

  def testPreference(self):
    self.assertEqual(set(constants.DISK_TEMPLATE_PREFERENCE),
                     set(constants.DISK_TEMPLATES))

  def testMapToStorageTypes(self):
    for disk_template in constants.DISK_TEMPLATES:
      self.assertTrue(
          constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template] is not None)

  def testLvmDiskTemplates(self):
    lvm_by_storage_type = [
        dt for dt in constants.DISK_TEMPLATES
        if constants.ST_LVM_VG == constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[dt]]
    self.assertEqual(set(lvm_by_storage_type), set(constants.DTS_LVM))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
