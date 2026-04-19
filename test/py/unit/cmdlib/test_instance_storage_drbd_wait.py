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

"""Pytest tests for the DRBD handshake wait added to AssembleInstanceDisks."""

from unittest import mock

import pytest

from ganeti import constants
from ganeti import errors
from ganeti.cmdlib import instance_storage


PRIMARY = "primary-uuid"
SECONDARY = "secondary-uuid"


def _mk_disk(dev_type):
  disk = mock.Mock()
  disk.dev_type = dev_type
  disk.iv_name = "disk/0"

  def _compute_tree(primary):
    if dev_type == constants.DT_DRBD8:
      return [(PRIMARY, disk), (SECONDARY, disk)]
    return [(PRIMARY, disk)]

  disk.ComputeNodeTree.side_effect = _compute_tree
  return disk


def _mk_rpc_result(fail_msg=None, payload=None, offline=False):
  res = mock.Mock()
  res.fail_msg = fail_msg
  res.payload = payload if payload is not None else ("/dev/drbd0", 0, None)
  res.offline = offline
  return res


def _mk_lu(disk, secondary_nodes):
  lu = mock.Mock()
  instance = mock.Mock()
  instance.uuid = "inst-uuid"
  instance.primary_node = PRIMARY

  lu.cfg.MarkInstanceDisksActive.return_value = instance
  lu.cfg.GetInstanceDisks.return_value = [disk]
  lu.cfg.GetInstanceSecondaryNodes.return_value = secondary_nodes
  lu.cfg.GetNodeName.side_effect = lambda uuid: f"node-{uuid}"

  lu.rpc.call_blockdev_assemble.return_value = _mk_rpc_result()
  # Successful handshake wait: alldone=True, percent=100
  wait_payload = (True, 100)
  lu.rpc.call_drbd_wait_sync.return_value = {
    sec: _mk_rpc_result(payload=wait_payload) for sec in secondary_nodes
  }
  return lu, instance


def test_drbd_with_secondaries_waits_between_passes():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY])

  ok, _, _ = instance_storage.AssembleInstanceDisks(lu, instance)

  assert ok is True
  lu.rpc.call_drbd_wait_sync.assert_called_once_with(
    [SECONDARY], ([disk], instance))

  # Ordering: wait must be called after pass 1 (secondary-mode assemble)
  # and before pass 2 (primary promotion). Check call order on the mocks.
  call_order = [
    c for c in lu.rpc.method_calls
    if c[0] in ("call_blockdev_assemble", "call_drbd_wait_sync")
  ]
  names = [c[0] for c in call_order]
  assert names.count("call_drbd_wait_sync") == 1
  idx = names.index("call_drbd_wait_sync")
  # Pass 1 assemble on secondary + primary = 2 calls before wait
  assert names[:idx] == ["call_blockdev_assemble", "call_blockdev_assemble"]
  # Pass 2 does one more call_blockdev_assemble for the primary
  assert names[idx + 1:] == ["call_blockdev_assemble"]


def test_drbd_without_secondaries_does_not_wait():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [])

  instance_storage.AssembleInstanceDisks(lu, instance)

  lu.rpc.call_drbd_wait_sync.assert_not_called()


@pytest.mark.parametrize("dev_type", [
  constants.DT_PLAIN,
  constants.DT_FILE,
  constants.DT_RBD,
  constants.DT_DISKLESS,
])
def test_non_drbd_templates_do_not_wait(dev_type):
  disk = _mk_disk(dev_type)
  # Non-DRBD templates normally have no secondaries, but even if one were
  # reported the wait must be skipped because the RPC is DRBD-only.
  lu, instance = _mk_lu(disk, [SECONDARY])

  instance_storage.AssembleInstanceDisks(lu, instance)

  lu.rpc.call_drbd_wait_sync.assert_not_called()


TIMEOUT_FAIL = "DRBD device /dev/drbd0 is not in sync: stats=<...>"


def _promote_calls(lu):
  return [c for c in lu.rpc.call_blockdev_assemble.call_args_list
          if c.args[3] is True]


def test_wait_failure_is_fatal_by_default():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY])
  lu.rpc.call_drbd_wait_sync.return_value = {
    SECONDARY: _mk_rpc_result(fail_msg=TIMEOUT_FAIL),
  }

  with pytest.raises(errors.OpExecError) as excinfo:
    instance_storage.AssembleInstanceDisks(lu, instance)

  msg = str(excinfo.value)
  # Names the secondary by resolved hostname, not UUID.
  assert f"node-{SECONDARY}" in msg
  assert SECONDARY not in msg.replace(f"node-{SECONDARY}", "")
  # Classifies the timeout distinctly from a plain RPC error.
  assert "timeout waiting for handshake" in msg
  # References the guard rationale.
  assert "accepting the data-loss risk" in msg
  # Disks were marked inactive before the raise.
  lu.cfg.MarkInstanceDisksInactive.assert_called_once_with(instance.uuid)
  # Pass 2 must not have run.
  assert _promote_calls(lu) == []


def test_wait_rpc_error_is_fatal_and_classified():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY])
  lu.rpc.call_drbd_wait_sync.return_value = {
    SECONDARY: _mk_rpc_result(fail_msg="connection refused"),
  }

  with pytest.raises(errors.OpExecError) as excinfo:
    instance_storage.AssembleInstanceDisks(lu, instance)

  msg = str(excinfo.value)
  assert "RPC error: connection refused" in msg
  assert "timeout waiting for handshake" not in msg


def test_wait_failure_with_ignore_secondaries_is_warning():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY])
  lu.rpc.call_drbd_wait_sync.return_value = {
    SECONDARY: _mk_rpc_result(fail_msg=TIMEOUT_FAIL),
  }

  ok, _, _ = instance_storage.AssembleInstanceDisks(
    lu, instance, ignore_secondaries=True)

  assert ok is True
  lu.LogWarning.assert_any_call(
    "DRBD handshake wait failed on secondary %s: %s;"
    " proceeding because ignore_secondaries is set",
    f"node-{SECONDARY}", TIMEOUT_FAIL)
  lu.cfg.MarkInstanceDisksInactive.assert_not_called()
  assert len(_promote_calls(lu)) == 1


def test_wait_failure_on_offline_secondary_is_warning():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY])
  lu.rpc.call_drbd_wait_sync.return_value = {
    SECONDARY: _mk_rpc_result(fail_msg="node down", offline=True),
  }

  ok, _, _ = instance_storage.AssembleInstanceDisks(lu, instance)

  assert ok is True
  lu.LogWarning.assert_any_call(
    "DRBD handshake wait skipped on secondary %s:"
    " node is administratively offline",
    f"node-{SECONDARY}")
  lu.cfg.MarkInstanceDisksInactive.assert_not_called()
  assert len(_promote_calls(lu)) == 1


def test_mixed_offline_and_timeout_is_fatal_but_mentions_offline():
  other_secondary = "secondary2-uuid"
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY, other_secondary])
  lu.rpc.call_drbd_wait_sync.return_value = {
    SECONDARY: _mk_rpc_result(fail_msg=TIMEOUT_FAIL),
    other_secondary: _mk_rpc_result(fail_msg="node down", offline=True),
  }

  with pytest.raises(errors.OpExecError) as excinfo:
    instance_storage.AssembleInstanceDisks(lu, instance)

  msg = str(excinfo.value)
  assert f"node-{SECONDARY}" in msg
  assert "timeout waiting for handshake" in msg
  # Offline node is reported but does not itself cause the fatal.
  assert f"node-{other_secondary}" in msg
  assert "Skipped as offline" in msg
  lu.cfg.MarkInstanceDisksInactive.assert_called_once_with(instance.uuid)


def test_error_message_has_remediation_hint():
  disk = _mk_disk(constants.DT_DRBD8)
  lu, instance = _mk_lu(disk, [SECONDARY])
  lu.rpc.call_drbd_wait_sync.return_value = {
    SECONDARY: _mk_rpc_result(fail_msg=TIMEOUT_FAIL),
  }

  with pytest.raises(errors.OpExecError) as excinfo:
    instance_storage.AssembleInstanceDisks(lu, instance)

  msg = str(excinfo.value)
  # All three documented escape hatches must be named.
  assert "gnt-instance startup --force" in msg
  assert "--ignore-secondaries" in msg
  assert "gnt-node modify --offline" in msg
