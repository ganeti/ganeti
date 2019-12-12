#!/usr/bin/python3
#

# Copyright (C) 2010, 2013 Google Inc.
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


"""Script for testing hypervisor functionality"""

import unittest

from ganeti import constants
from ganeti import compat
from ganeti import objects
from ganeti import errors
from ganeti import hypervisor
from ganeti.hypervisor import hv_base

import testutils


class TestParameters(unittest.TestCase):
  def test(self):
    for hv, const_params in constants.HVC_DEFAULTS.items():
      hyp = hypervisor.GetHypervisorClass(hv)
      for pname in const_params:
        self.assertTrue(pname in hyp.PARAMETERS,
                        "Hypervisor %s: parameter %s defined in constants"
                        " but not in the permitted hypervisor parameters" %
                        (hv, pname))
      for pname in hyp.PARAMETERS:
        self.assertTrue(pname in const_params,
                        "Hypervisor %s: parameter %s defined in the hypervisor"
                        " but missing a default value" %
                        (hv, pname))


class TestBase(unittest.TestCase):
  def testVerifyResults(self):
    fn = hv_base.BaseHypervisor._FormatVerifyResults
    # FIXME: use assertIsNone when py 2.7 is minimum supported version
    self.assertEqual(fn([]), None)
    self.assertEqual(fn(["a"]), "a")
    self.assertEqual(fn(["a", "b"]), "a; b")

  def testGetLinuxNodeInfo(self):
    meminfo = testutils.TestDataFilename("proc_meminfo.txt")
    cpuinfo = testutils.TestDataFilename("proc_cpuinfo.txt")
    result = hv_base.BaseHypervisor.GetLinuxNodeInfo(meminfo, cpuinfo)

    self.assertEqual(result["memory_total"], 7686)
    self.assertEqual(result["memory_free"], 6272)
    self.assertEqual(result["memory_dom0"], 2722)
    self.assertEqual(result["cpu_total"], 4)
    self.assertEqual(result["cpu_nodes"], 1)
    self.assertEqual(result["cpu_sockets"], 1)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
