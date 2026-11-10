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

import pytest

from ganeti import constants
from ganeti import objects
from ganeti.hypervisor import hv_kvm

_TEST_UUID = "c2140463-d768-404d-b840-178cd24f5751"


class TestSetDiskSerialUUID:

  def _make_disk(self, uuid_val):
    disk = objects.Disk()
    disk.uuid = uuid_val
    return disk

  @pytest.mark.parametrize("hv_disk_type,expected_serial", [
      (constants.HT_DISK_PARAVIRTUAL, _TEST_UUID[:20]),
      (constants.HT_DISK_SCSI_HD, _TEST_UUID[:20]),
      (constants.HT_DISK_SCSI_BLOCK, None),
      (constants.HT_DISK_IDE, None),
      (constants.HT_DISK_PFLASH, None),
      (constants.HT_DISK_MTD, None),
      (None, None),
  ])
  def test_disk_sets_serial(self, hv_disk_type, expected_serial):
    expected = _TEST_UUID[:20]  # first 20 characters of UUID
    disk = self._make_disk(_TEST_UUID)
    hvinfo = {}
    hv_kvm._SetDiskSerialUUID(hvinfo, constants.HOTPLUG_TARGET_DISK,
                              disk, hv_disk_type)

    if expected_serial is None:
      assert "serial" not in hvinfo
    else:
      assert hvinfo["serial"] == expected_serial

  def test_nic_no_serial(self):
    nic = objects.NIC()
    nic.uuid = _TEST_UUID
    hvinfo = {}
    hv_kvm._SetDiskSerialUUID(hvinfo, constants.HOTPLUG_TARGET_NIC, nic,
                              constants.HT_NIC_PARAVIRTUAL)
    assert "serial" not in hvinfo
