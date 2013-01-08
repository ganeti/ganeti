#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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
