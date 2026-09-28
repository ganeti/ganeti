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

"""The firmware disk must be exempt from the disk-size/count/type ipolicy."""

from unittest import mock

from ganeti import constants
from ganeti import objects
from ganeti.cmdlib import common


def _disk(size, role=constants.DR_ROLE_DATA, dev_type=constants.DT_PLAIN):
  return objects.Disk(dev_type=dev_type, size=size, role=role)


def _fake_cfg(disks):
  cluster = mock.Mock()
  cluster.FillBE.return_value = {
    constants.BE_MAXMEM: 4096,
    constants.BE_VCPUS: 2,
    constants.BE_SPINDLE_USE: 1,
  }
  cfg = mock.Mock()
  cfg.GetClusterInfo.return_value = cluster
  cfg.GetInstanceNodes.return_value = ["node-uuid"]
  cfg.GetInstanceDisks.return_value = disks
  return cfg


def test_firmware_disk_excluded_from_ipolicy_spec():
  instance = objects.Instance(name="i1", uuid="i1-uuid", nics=[])
  # one normal data disk plus a 32 MiB firmware disk
  disks = [_disk(1024),
           _disk(constants.OVMF_FIRMWARE_DISK_SIZE,
                 role=constants.DR_ROLE_FIRMWARE)]
  cfg = _fake_cfg(disks)

  captured = {}

  def _capture(_ipolicy, _mem, _cpu, disk_count, _nic, disk_sizes,
               _spindle, disk_types):
    captured["disk_count"] = disk_count
    captured["disk_sizes"] = disk_sizes
    captured["disk_types"] = disk_types
    return []

  with mock.patch.object(common.rpc, "GetExclusiveStorageForNodes",
                         return_value={"node-uuid": False}):
    common.ComputeIPolicyInstanceViolation({}, instance, cfg,
                                           _compute_fn=_capture)

  # The 32 MiB firmware disk is not part of the policy spec.
  assert captured["disk_count"] == 1
  assert captured["disk_sizes"] == [1024]
  assert captured["disk_types"] == [constants.DT_PLAIN]
