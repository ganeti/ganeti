#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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
# 0.0510-1301, USA.


"""Script for unittesting the constants module"""


import unittest
import re
import itertools

from ganeti import constants
from ganeti import locking
from ganeti import utils

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

    self.failUnless(constants.BuildVersion(0, 0, 0) == 0)
    self.failUnless(constants.BuildVersion(10, 10, 1010) == 10101010)
    self.failUnless(constants.BuildVersion(12, 34, 5678) == 12345678)
    self.failUnless(constants.BuildVersion(99, 99, 9999) == 99999999)

    self.failUnless(constants.SplitVersion(00000000) == (0, 0, 0))
    self.failUnless(constants.SplitVersion(10101010) == (10, 10, 1010))
    self.failUnless(constants.SplitVersion(12345678) == (12, 34, 5678))
    self.failUnless(constants.SplitVersion(99999999) == (99, 99, 9999))
    self.failUnless(constants.SplitVersion(constants.CONFIG_VERSION) ==
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
    for kind, source in [('hypervisor', constants.HVS_PARAMETER_TYPES),
                         ('backend', constants.BES_PARAMETER_TYPES),
                         ('nic', constants.NICS_PARAMETER_TYPES),
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
    self.failUnlessEqual(len(constants.CONFD_MAGIC_FOURCC), 4,
                         "Invalid fourcc len, should be 4")

  def _IsUniqueSequence(self, sequence):
    seen = set()
    for member in sequence:
      if member in seen:
        return False
      seen.add(member)
    return True

  def testReqs(self):
    self.failUnless(self._IsUniqueSequence(constants.CONFD_REQS),
                    "Duplicated confd request code")

  def testReplStatuses(self):
    self.failUnless(self._IsUniqueSequence(constants.CONFD_REPL_STATUSES),
                    "Duplicated confd reply status code")


if __name__ == '__main__':
  testutils.GanetiTestProgram()
