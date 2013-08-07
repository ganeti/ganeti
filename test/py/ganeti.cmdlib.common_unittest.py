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


"""Script for unittesting the cmdlib module 'common'"""


import unittest

from ganeti.cmdlib import common
from ganeti import constants
from ganeti import errors

import testutils


class TestCheckIpolicy(unittest.TestCase):

  def testAllTemplatesEnabled(self):
    allowed_disk_templates = [constants.DT_PLAIN]
    ipolicy = {constants.IPOLICY_DTS: allowed_disk_templates}
    enabled_disk_templates = [constants.DT_PLAIN, constants.DT_DRBD8]
    common.CheckIpolicyVsDiskTemplates(
        ipolicy, enabled_disk_templates)

  def testSomeTemplatesUnenabled(self):
    allowed_disk_templates = [constants.DT_PLAIN, constants.DT_DISKLESS]
    ipolicy = {constants.IPOLICY_DTS: allowed_disk_templates}
    enabled_disk_templates = [constants.DT_PLAIN, constants.DT_DRBD8]
    self.assertRaises(
        errors.OpPrereqError,
        common.CheckIpolicyVsDiskTemplates,
        ipolicy, enabled_disk_templates)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
