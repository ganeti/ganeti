#
#

# Copyright (C) 2026 the Ganeti project
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

"""Unit tests for the Disk.role field and boot_type config upgrades."""

from ganeti import constants
from ganeti import objects


class TestDiskRole:
  def test_role_roundtrips_through_dict(self):
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=32,
                        role=constants.DR_ROLE_FIRMWARE)
    restored = objects.Disk.FromDict(disk.ToDict())
    assert restored.role == constants.DR_ROLE_FIRMWARE

  def test_default_role_is_data(self):
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=32)
    disk.UpgradeConfig()
    assert disk.role == constants.DR_ROLE_DATA

  def test_pre_3_2_disk_without_role_upgrades_to_data(self):
    # A disk dict predating the boot_type feature carries no 'role' key.
    disk = objects.Disk.FromDict({"dev_type": constants.DT_PLAIN, "size": 1})
    disk.UpgradeConfig()
    assert disk.role == constants.DR_ROLE_DATA
