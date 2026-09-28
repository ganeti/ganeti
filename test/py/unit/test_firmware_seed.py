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

"""Unit tests for backend.BlockdevSeedFirmware (node-side firmware seeding)."""

import os
from unittest import mock

import pytest

from ganeti import backend
from ganeti.hypervisor.hv_kvm import firmware


_CODE = b"CODE" * 100000   # 400000 bytes (sector multiple)
_VARS = b"VARS" * 20000    # 80000 bytes (sector multiple)


@pytest.fixture
def seeded(tmp_path):
  """Seed a firmware 'device' file and return (path, layout)."""
  code_path = tmp_path / "OVMF_CODE.fd"
  vars_path = tmp_path / "OVMF_VARS.fd"
  dev_path = tmp_path / "fw.img"
  code_path.write_bytes(_CODE)
  vars_path.write_bytes(_VARS)
  with open(dev_path, "wb") as fh:
    fh.truncate(32 * 1024 * 1024)

  rdev = mock.Mock(dev_path=str(dev_path), size=32)  # size in MiB
  disk = mock.Mock(iv_name="disk/2")
  with mock.patch.object(backend, "_RecursiveFindBD", return_value=rdev):
    backend.BlockdevSeedFirmware(disk, str(code_path), str(vars_path))
  return str(dev_path)


def test_seed_writes_superblock_and_regions(seeded):
  with open(seeded, "rb") as fh:
    layout = firmware.UnpackSuperblock(fh.read(firmware.SECTOR_SIZE))
    code_off, code_size = layout[firmware.REGION_CODE]
    vars_off, vars_size = layout[firmware.REGION_VARS]
    assert (code_size, vars_size) == (len(_CODE), len(_VARS))
    fh.seek(code_off)
    assert fh.read(code_size) == _CODE
    fh.seek(vars_off)
    assert fh.read(vars_size) == _VARS


def test_missing_template_fails(tmp_path):
  vars_path = tmp_path / "OVMF_VARS.fd"
  vars_path.write_bytes(_VARS)
  disk = mock.Mock(iv_name="disk/2")
  with pytest.raises(backend.RPCFail):
    backend.BlockdevSeedFirmware(disk, str(tmp_path / "missing.fd"),
                                 str(vars_path))


def test_device_too_small_fails(tmp_path):
  code_path = tmp_path / "OVMF_CODE.fd"
  vars_path = tmp_path / "OVMF_VARS.fd"
  dev_path = tmp_path / "fw.img"
  code_path.write_bytes(_CODE)
  vars_path.write_bytes(_VARS)
  with open(dev_path, "wb") as fh:
    fh.truncate(1024 * 1024)  # 1 MiB - too small for the layout

  rdev = mock.Mock(dev_path=str(dev_path), size=1)
  disk = mock.Mock(iv_name="disk/2")
  with mock.patch.object(backend, "_RecursiveFindBD", return_value=rdev):
    with pytest.raises(backend.RPCFail):
      backend.BlockdevSeedFirmware(disk, str(code_path), str(vars_path))
