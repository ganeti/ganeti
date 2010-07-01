#!/usr/bin/python
#

# Copyright (C) 2008 Google Inc.
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


"""Script for unittesting the cmdlib module"""


import os
import unittest
import time
import tempfile
import shutil

from ganeti import mcpu
from ganeti import cmdlib
from ganeti import opcodes
from ganeti import errors
from ganeti import utils

import testutils


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    cmdlib._VerifyCertificate(self._TestDataFilename("cert1.pem"))

    nonexist_filename = os.path.join(self.tmpdir, "does-not-exist")

    (errcode, msg) = cmdlib._VerifyCertificate(nonexist_filename)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    # Try to load non-certificate file
    invalid_cert = self._TestDataFilename("bdev-net.txt")
    (errcode, msg) = cmdlib._VerifyCertificate(invalid_cert)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)


class TestOpcodeParams(testutils.GanetiTestCase):
  def testParamsStructures(self):
    for op in sorted(mcpu.Processor.DISPATCH_TABLE):
      lu = mcpu.Processor.DISPATCH_TABLE[op]
      lu_name = lu.__name__
      self.failIf(hasattr(lu, "_OP_REQP"), "LU '%s' has old-style _OP_REQP" %
                  lu_name)
      self.failIf(hasattr(lu, "_OP_DEFS"), "LU '%s' has old-style _OP_DEFS" %
                  lu_name)
      # this needs to remain a list!
      defined_params = [v[0] for v in lu._OP_PARAMS]
      for row in lu._OP_PARAMS:
        # this relies on there being at least one element
        param_name = row[0]
        self.failIf(len(row) != 3, "LU '%s' parameter %s has invalid length" %
                    (lu_name, param_name))
        self.failIf(defined_params.count(param_name) > 1, "LU '%s' parameter"
                    " '%s' is defined multiple times" % (lu_name, param_name))

  def testParamsDefined(self):
    for op in sorted(mcpu.Processor.DISPATCH_TABLE):
      lu = mcpu.Processor.DISPATCH_TABLE[op]
      lu_name = lu.__name__
      # TODO: this doesn't deal with recursive slots definitions
      all_params = set(op.__slots__)
      defined_params = set(v[0] for v in lu._OP_PARAMS)
      missing = all_params.difference(defined_params)
      self.failIf(missing, "Undeclared parameter types for LU '%s': %s" %
                  (lu_name, utils.CommaJoin(missing)))
      extra = defined_params.difference(all_params)
      self.failIf(extra, "Extra parameter types for LU '%s': %s" %
                  (lu_name, utils.CommaJoin(extra)))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
