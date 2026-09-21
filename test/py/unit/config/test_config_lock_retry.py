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

"""Pytest tests for the config-lock retry behaviour (issue #1978 / PR #1972).

ConfigWriter's WConfd lock acquisition must use exponential backoff with a
bounded budget instead of a tight poll loop, so that contended locks do not
add load to wconfd exactly when it is slowest, and so that a permanently
unavailable lock produces a diagnosable error rather than an infinite spin.
"""

import unittest.mock as mock

import pytest

from ganeti import config as gconfig
from ganeti import objects
from ganeti import utils


class _StubWConfd(object):
  """wconfd client stub whose lock/update calls fail N times, then pass."""

  def __init__(self, fails=0):
    self.fails = fails
    self.lock_calls = 0
    self.update_calls = 0

  def LockConfig(self, _context, _shared):
    self.lock_calls += 1
    if self.lock_calls <= self.fails:
      return None
    return {"stub": True}

  def UpdateInstance(self, _instance):
    self.update_calls += 1
    if self.update_calls <= self.fails:
      return None
    return (42, 100.0)


class _VirtualClock(object):
  """Advances virtual time on sleep() instead of blocking."""

  def __init__(self):
    self.now = 1000.0
    self.slept = []

  def time(self):
    return self.now

  def sleep(self, seconds):
    self.slept.append(seconds)
    self.now += seconds


def _make_config_writer(stub):
  cw = object.__new__(gconfig.ConfigWriter)
  cw.write_count = 0
  cw._SetConfigData(None)
  cw._offline = False
  cw._wconfdcontext = ("test", "/dev/null", 0)
  cw._wconfd = stub
  cw._lock_count = 0
  cw._lock_current_shared = None
  cw._lock_forced = False
  return cw


def _with_virtual_clock(clock):
  """Patch utils.Retry (as used by ganeti.config) to use a virtual clock."""
  real_retry = utils.Retry

  def fast_retry(fn, delay, timeout, **kwargs):
    return real_retry(fn, delay, timeout,
                      wait_fn=clock.sleep, _time_fn=clock.time,
                      **kwargs)

  return mock.patch.object(gconfig.utils, "Retry", fast_retry)


class TestOpenConfigLockRetry(object):
  """ConfigWriter._OpenConfig polls the config lock with backoff."""

  def test_lock_acquire_retries_with_backoff(self):
    """LockConfig is retried with increasing delays until it succeeds."""
    stub = _StubWConfd(fails=5)
    cw = _make_config_writer(stub)
    clock = _VirtualClock()
    with _with_virtual_clock(clock), \
         mock.patch.object(gconfig.objects.ConfigData, "FromDict",
                           return_value="cfg"), \
         mock.patch.object(cw, "_UpgradeConfig"):
      cw._OpenConfig(shared=False)
    assert stub.lock_calls == 6
    # backoff is applied: delays grow and are capped at the tuple limit
    assert clock.slept[0] == pytest.approx(0.1)
    assert all(later >= earlier
               for earlier, later in zip(clock.slept, clock.slept[1:]))
    assert max(clock.slept) <= gconfig._CONFIG_LOCK_RETRY_DELAY[2]

  def test_lock_acquire_timeout_is_bounded(self):
    """An unavailable lock raises RetryTimeout within the retry budget.

    The old behaviour was an unbounded while-True spin; the budget must
    now be finite and respected.
    """
    stub = _StubWConfd(fails=10**6)
    cw = _make_config_writer(stub)
    clock = _VirtualClock()
    with _with_virtual_clock(clock):
      with pytest.raises(utils.RetryTimeout):
        cw._OpenConfig(shared=False)
    # bounded: virtual time advanced by at most the budget plus one poll
    assert clock.now - 1000.0 <= gconfig._CONFIG_LOCK_RETRY_TIMEOUT + 2.0


class TestUpdateLockRetry(object):
  """ConfigWriter.Update retries lock-dependent updates with backoff."""

  def test_update_succeeds_after_transient_failures(self):
    """A transiently unavailable lock is retried, then the update lands."""
    stub = _StubWConfd(fails=3)
    cw = _make_config_writer(stub)
    clock = _VirtualClock()
    inst = objects.Instance(name="inst1.example.com", uuid="uuid-1",
                            serial_no=1)
    with _with_virtual_clock(clock), \
         mock.patch.object(cw, "VerifyConfigAndLog"):
      cw.Update(inst, None)
    assert stub.update_calls == 4
    assert inst.serial_no == 42
    assert inst.mtime == pytest.approx(100.0)

  def test_update_reports_budget_timeout(self):
    """Exhausting the budget raises with the diagnosable PR #1972 message."""
    stub = _StubWConfd(fails=10**6)
    cw = _make_config_writer(stub)
    clock = _VirtualClock()
    inst = objects.Instance(name="inst1.example.com", uuid="uuid-1",
                            serial_no=1)
    with _with_virtual_clock(clock):
      with pytest.raises(utils.RetryTimeout) as excinfo:
        cw.Update(inst, None)
    msg = str(excinfo.value)
    assert "WConfd config-lock timeout" in msg
    assert "UpdateInstance" in msg
    assert "uuid-1" in msg
    assert "retry budget" in msg
    # backoff: far fewer polls than the old fixed 0.1s loop would make
    assert stub.update_calls < 300
