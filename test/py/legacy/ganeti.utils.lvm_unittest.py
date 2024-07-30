#!/usr/bin/python3
#

# Copyright (C) 2013 Google Inc.
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


"""Script for testing ganeti.utils.lvm"""

import unittest

from ganeti import constants
from ganeti import utils
from ganeti.objects import LvmPvInfo

import testutils


class TestLvmExclusiveCheckNodePvs(unittest.TestCase):
  """Test cases for LvmExclusiveCheckNodePvs()"""
  _VG = "vg"
  _SMALL_PV = LvmPvInfo(name="small", vg_name=_VG, size=100e3, free=40e3,
                        attributes="a-")
  _MED_PV = LvmPvInfo(name="medium", vg_name=_VG, size=400e3, free=40e3,
                      attributes="a-")
  _BIG_PV = LvmPvInfo(name="big", vg_name=_VG, size=1e6, free=400e3,
                      attributes="a-")
  # Allowance for rounding
  _EPS = 1e-4

  def testOnePv(self):
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs([self._MED_PV])
    self.assertFalse(errmsgs)
    self.assertEqual(small, self._MED_PV.size)
    self.assertEqual(big, self._MED_PV.size)

  def testEqualPvs(self):
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [self._MED_PV] * 2)
    self.assertFalse(errmsgs)
    self.assertEqual(small, self._MED_PV.size)
    self.assertEqual(big, self._MED_PV.size)
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [self._SMALL_PV] * 3)
    self.assertFalse(errmsgs)
    self.assertEqual(small, self._SMALL_PV.size)
    self.assertEqual(big, self._SMALL_PV.size)

  def testTooDifferentPvs(self):
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [self._MED_PV, self._BIG_PV])
    self.assertEqual(len(errmsgs), 1)
    self.assertEqual(small, self._MED_PV.size)
    self.assertEqual(big, self._BIG_PV.size)
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [self._MED_PV, self._SMALL_PV])
    self.assertEqual(len(errmsgs), 1)
    self.assertEqual(small, self._SMALL_PV.size)
    self.assertEqual(big, self._MED_PV.size)

  def testBoundarySizeCases(self):
    medpv1 = self._MED_PV.Copy()
    medpv2 = self._MED_PV.Copy()
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [medpv1, medpv2, self._MED_PV])
    self.assertFalse(errmsgs)
    self.assertEqual(small, self._MED_PV.size)
    self.assertEqual(big, self._MED_PV.size)
    # Just within the margins
    medpv1.size = self._MED_PV.size * (1 - constants.PART_MARGIN + self._EPS)
    medpv2.size = self._MED_PV.size * (1 + constants.PART_MARGIN - self._EPS)
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [medpv1, medpv2, self._MED_PV])
    self.assertFalse(errmsgs)
    self.assertEqual(small, medpv1.size)
    self.assertEqual(big, medpv2.size)
    # Just outside the margins
    medpv1.size = self._MED_PV.size * (1 - constants.PART_MARGIN - self._EPS)
    medpv2.size = self._MED_PV.size * (1 + constants.PART_MARGIN)
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [medpv1, medpv2, self._MED_PV])
    self.assertTrue(errmsgs)
    self.assertEqual(small, medpv1.size)
    self.assertEqual(big, medpv2.size)
    medpv1.size = self._MED_PV.size * (1 - constants.PART_MARGIN)
    medpv2.size = self._MED_PV.size * (1 + constants.PART_MARGIN + self._EPS)
    (errmsgs, (small, big)) = utils.LvmExclusiveCheckNodePvs(
      [medpv1, medpv2, self._MED_PV])
    self.assertTrue(errmsgs)
    self.assertEqual(small, medpv1.size)
    self.assertEqual(big, medpv2.size)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
