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

"""Unit tests for firmware-disk handling in disk-template conversion."""

from ganeti import constants
from ganeti import objects
from ganeti.cmdlib.instance_set_params import LUInstanceSetParams


def _disk(dev_type, role=constants.DR_ROLE_DATA):
  return objects.Disk(dev_type=dev_type, size=10, role=role)


class TestPreserveDiskRoles:
  """The firmware role (and any non-data role) must survive a template
  conversion so the firmware disk is never silently dropped / demoted."""

  def test_firmware_role_is_carried_over(self):
    # Conversion regenerates disks as plain data disks; the firmware disk is
    # positionally last in both lists (as on a freshly created instance).
    old = [_disk(constants.DT_PLAIN),
           _disk(constants.DT_PLAIN, constants.DR_ROLE_FIRMWARE)]
    new = [_disk(constants.DT_DRBD8),
           _disk(constants.DT_DRBD8)]  # regenerated => role defaults to data

    LUInstanceSetParams._PreserveDiskRoles(old, new)

    assert new[0].role == constants.DR_ROLE_DATA
    assert new[1].role == constants.DR_ROLE_FIRMWARE
    # firmware disk is forced to local (kernelspace) access
    assert new[1].params[constants.LDP_ACCESS] == constants.DISK_KERNELSPACE

  def test_firmware_role_is_carried_over_when_not_last(self):
    # Adding data disks after switching to UEFI leaves the firmware disk in the
    # middle of the array. The role must still land on the correct disk, since
    # the two lists are aligned positionally (not by a tail assumption).
    old = [_disk(constants.DT_PLAIN),
           _disk(constants.DT_PLAIN, constants.DR_ROLE_FIRMWARE),
           _disk(constants.DT_PLAIN)]
    new = [_disk(constants.DT_DRBD8),
           _disk(constants.DT_DRBD8),
           _disk(constants.DT_DRBD8)]  # regenerated => role defaults to data

    LUInstanceSetParams._PreserveDiskRoles(old, new)

    assert new[0].role == constants.DR_ROLE_DATA
    assert new[1].role == constants.DR_ROLE_FIRMWARE
    assert new[2].role == constants.DR_ROLE_DATA
    # only the firmware disk is forced to local (kernelspace) access
    assert new[1].params[constants.LDP_ACCESS] == constants.DISK_KERNELSPACE
    assert not new[0].params or constants.LDP_ACCESS not in new[0].params
    assert not new[2].params or constants.LDP_ACCESS not in new[2].params

  def test_data_only_instance_is_untouched(self):
    old = [_disk(constants.DT_PLAIN), _disk(constants.DT_PLAIN)]
    new = [_disk(constants.DT_DRBD8), _disk(constants.DT_DRBD8)]
    LUInstanceSetParams._PreserveDiskRoles(old, new)
    assert all(d.role == constants.DR_ROLE_DATA for d in new)
    # no access param forced on plain data disks
    assert all(not d.params or constants.LDP_ACCESS not in d.params
               for d in new)
