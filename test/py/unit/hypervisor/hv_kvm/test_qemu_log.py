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

import os
import re
from unittest import mock

import pytest

from ganeti.hypervisor import hv_kvm


@pytest.fixture
def qemu_log_dir(tmp_path, monkeypatch):
    """Temporary directory used as LOG_KVM_DIR for QEMU log tests.

    Patches :data:`pathutils.LOG_KVM_DIR` to point to this directory.
    """
    monkeypatch.setattr("ganeti.pathutils.LOG_KVM_DIR",
                        os.path.normpath(str(tmp_path)))
    return tmp_path


def _make_hv_mock():
    hv = mock.Mock(spec=hv_kvm.KVMHypervisor)
    hv._GenerateQemuLogPath = \
        hv_kvm.KVMHypervisor._GenerateQemuLogPath.__get__(hv)
    hv._CleanupOldQemuLogs = \
        hv_kvm.KVMHypervisor._CleanupOldQemuLogs.__get__(hv)
    return hv


class TestGenerateQemuLogPath:

  def test_returns_path_with_timestamp(self, qemu_log_dir):
    """Log path contains VM name, ISO-8601 timestamp and .log suffix."""
    hv = _make_hv_mock()
    instance = mock.Mock(spec=["name"], name="myvm")

    result = hv._GenerateQemuLogPath(instance)

    assert result.startswith(os.path.normpath(str(qemu_log_dir)) + "/")
    assert "myvm." in result
    assert result.endswith(".log")
    # check iso-8601-timestamp format with UTC offset and optional microseconds
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00",
                     result)


class TestCleanupOldQemuLogs:

  def test_removes_files_over_limit(self, qemu_log_dir):
    """When 5 files exist with keep=3, exactly 2 are removed (3 remain)."""
    dates = [
      "2026-01-01T00:00:00+00:00",
      "2026-01-02T00:00:00+00:00",
      "2026-01-03T00:00:00+00:00",
      "2026-01-04T00:00:00+00:00",
      "2026-01-05T00:00:00+00:00",
    ]
    for d in dates:
      (qemu_log_dir / ("vm1.%s.log" % d)).touch()

    files = list(qemu_log_dir.glob("vm1.*.log"))
    assert len(files) == 5

    hv = _make_hv_mock()
    hv._CleanupOldQemuLogs("vm1", keep=3)

    remaining = list(qemu_log_dir.glob("vm1.*.log"))
    assert len(remaining) == 3

  def test_noop_under_limit(self, qemu_log_dir):
    """When files <= keep, nothing is deleted."""
    for i in range(3):
      (qemu_log_dir / ("vm2.2026-01-0%sT00:00:00+00:00.log" % i)).touch()

    hv = _make_hv_mock()
    hv._CleanupOldQemuLogs("vm2", keep=3)

    remaining = list(qemu_log_dir.glob("vm2.*.log"))
    assert len(remaining) == 3

  def test_empty_dir_no_error(self, qemu_log_dir):
    """No log files exist — should not raise."""
    hv = _make_hv_mock()
    hv._CleanupOldQemuLogs("vm3", keep=3)

  def test_oldest_removed_first(self, qemu_log_dir):
    """Files are removed in sorted (chronological) order."""
    dates = [
      "2026-01-01T00:00:00+00:00",
      "2026-01-02T00:00:00+00:00",
      "2026-01-03T00:00:00+00:00",
      "2026-01-04T00:00:00+00:00",
      "2026-01-05T00:00:00+00:00",
    ]
    for d in dates:
      (qemu_log_dir / ("vm4.%s.log" % d)).touch()

    hv = _make_hv_mock()
    hv._CleanupOldQemuLogs("vm4", keep=3)

    remaining_names = {f.name for f in qemu_log_dir.glob("vm4.*.log")}
    assert remaining_names == {
      "vm4.2026-01-03T00:00:00+00:00.log",
      "vm4.2026-01-04T00:00:00+00:00.log",
      "vm4.2026-01-05T00:00:00+00:00.log",
    }

  def test_similar_prefix_vms(self, qemu_log_dir):
    """Cleanup for ``vm01`` must not touch ``vm01.dev``'s log files."""
    # vm01.dev logs (different VM, similar name prefix)
    (qemu_log_dir / "vm01.dev.2026-01-01T00:00:00+00:00.log").touch()
    (qemu_log_dir / "vm01.dev.2026-01-02T00:00:00+00:00.log").touch()

    # vm01 logs
    (qemu_log_dir / "vm01.2026-01-03T00:00:00+00:00.log").touch()

    hv = _make_hv_mock()
    hv._CleanupOldQemuLogs("vm01", keep=2)

    # vm01.dev files must survive — they belong to a different instance
    remaining = {f.name for f in qemu_log_dir.glob("*.log")}
    assert "vm01.dev.2026-01-01T00:00:00+00:00.log" in remaining
    assert "vm01.dev.2026-01-02T00:00:00+00:00.log" in remaining
    assert len(remaining) == 3

  def test_legacy_removed_with_excess_files(self, qemu_log_dir):
    """Legacy removed plus oldest ISO files when over keep limit."""
    # Create legacy log (no timestamp)
    (qemu_log_dir / "vm5.log").touch()

    # Create 3 ISO timestamp log files with UTC offset
    dates = [
      "2026-01-01T00:00:00+00:00",
      "2026-01-02T00:00:00+00:00",
      "2026-01-03T00:00:00+00:00",
    ]
    for d in dates:
      (qemu_log_dir / ("vm5.%s.log" % d)).touch()

    hv = _make_hv_mock()
    hv._CleanupOldQemuLogs("vm5", keep=2)

    remaining = {f.name for f in qemu_log_dir.glob("vm5.*.log")}
    # Legacy file must be gone; all 3 ISO files are within keep limit
    assert "vm5.log" not in remaining
    assert remaining == {
      "vm5.2026-01-02T00:00:00+00:00.log",
      "vm5.2026-01-03T00:00:00+00:00.log",
    }
