#!/usr/bin/python
#

# Copyright (C) 2010, 2013 Google Inc.
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
