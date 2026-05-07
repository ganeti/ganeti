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

"""Pytest tests for the post-resize resync wait in DRBD8Dev.Grow."""

from unittest import mock

import pytest

from ganeti import errors
from ganeti.storage import drbd


def _mk_dev(grow_resync_timeout=0.3):
  """Build a minimally-initialised DRBD8Dev for Grow testing.

  The full constructor needs unique_id / dyn_params / children plumbing that
  is irrelevant to the wait logic, so bypass __init__ and set just the
  attributes Grow touches.
  """
  dev = drbd.DRBD8Dev.__new__(drbd.DRBD8Dev)
  dev.minor = 0
  dev._aminor = 0
  dev.size = 1024
  dev._children = [mock.Mock(), mock.Mock()]
  dev._cmd_gen = mock.Mock()
  dev._cmd_gen.GenResizeCmd.return_value = ["drbdsetup", "resize", "0",
                                            "--size", "1044m"]
  dev._GROW_RESYNC_TIMEOUT = grow_resync_timeout
  return dev


def _proc_status(is_in_resync):
  stats = mock.Mock()
  stats.is_in_resync = is_in_resync
  return stats


def test_grow_waits_until_resync_starts():
  """Grow polls GetProcStatus until is_in_resync flips True."""
  dev = _mk_dev()

  with mock.patch.object(drbd.utils, "RunCmd") as run_cmd, \
       mock.patch.object(drbd.DRBD8Dev, "GetProcStatus") as get_status:
    run_cmd.return_value = mock.Mock(failed=False, output="")
    # First two probes: not yet in resync. Third: resync visible.
    get_status.side_effect = [
      _proc_status(False),
      _proc_status(False),
      _proc_status(True),
    ]

    dev.Grow(20, False, False, False)

    # drbdsetup resize was issued exactly once...
    assert run_cmd.call_count == 1
    # ...and we kept polling proc status until resync was observable.
    assert get_status.call_count == 3


def test_grow_returns_after_timeout_when_no_resync():
  """If DRBD never enters resync the wait times out cleanly (no error)."""
  dev = _mk_dev(grow_resync_timeout=0.2)

  with mock.patch.object(drbd.utils, "RunCmd") as run_cmd, \
       mock.patch.object(drbd.DRBD8Dev, "GetProcStatus") as get_status:
    run_cmd.return_value = mock.Mock(failed=False, output="")
    get_status.return_value = _proc_status(False)

    # Must not raise: a missing resync is treated as "no resync needed".
    dev.Grow(20, False, False, False)

    assert run_cmd.call_count == 1
    assert get_status.call_count >= 1


def test_grow_resize_failure_still_raises():
  """A failed `drbdsetup resize` propagates as before; no wait happens."""
  dev = _mk_dev()

  with mock.patch.object(drbd.utils, "RunCmd") as run_cmd, \
       mock.patch.object(drbd.DRBD8Dev, "GetProcStatus") as get_status:
    run_cmd.return_value = mock.Mock(failed=True,
                                     output="(130) Resize not allowed"
                                            " during resync.")

    with pytest.raises(errors.BlockDeviceError):
      dev.Grow(20, False, False, False)

    # We never start polling proc status if the resize itself failed.
    get_status.assert_not_called()


@pytest.mark.parametrize("dryrun,backingstore", [(True, False), (False, True)])
def test_grow_dryrun_or_backingstore_skips_drbd_resize(dryrun, backingstore):
  """In dry-run / backing-store mode Grow must not touch DRBD at all."""
  dev = _mk_dev()

  with mock.patch.object(drbd.utils, "RunCmd") as run_cmd, \
       mock.patch.object(drbd.DRBD8Dev, "GetProcStatus") as get_status:
    dev.Grow(20, dryrun, backingstore, False)

    # The backing child's Grow was called, but no drbdsetup resize and no
    # resync wait happened.
    dev._children[0].Grow.assert_called_once_with(20, dryrun, backingstore,
                                                  False)
    run_cmd.assert_not_called()
    get_status.assert_not_called()
