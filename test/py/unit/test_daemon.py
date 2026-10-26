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

"""Pytest tests for ganeti.daemon module."""

import logging
import os
import signal
import threading

import pytest

from ganeti import daemon


def _send_signal_delayed(signum, delay=0.05):
  """Send a signal to the current process after a short delay.

  Used to deliver signals while Mainloop.Run() is executing, after it
  has installed its own signal handlers.

  """
  pid = os.getpid()

  def _send():
    os.kill(pid, signum)

  t = threading.Timer(delay, _send)
  t.daemon = True
  t.start()
  return t


class TestHandleSigHup:
  """Tests for the _HandleSigHup signal handler."""

  def test_calls_reopen_callbacks(self):
    """Test that log reopen callbacks are called."""
    called = []
    reopen_fn = [lambda: called.append("reopen")]
    reload_fn = []

    daemon._HandleSigHup(reopen_fn, reload_fn, signal.SIGHUP, None)

    assert called == ["reopen"]

  def test_calls_reload_callbacks(self):
    """Test that reload callbacks are called."""
    called = []
    reopen_fn = []
    reload_fn = [lambda: called.append("reload")]

    daemon._HandleSigHup(reopen_fn, reload_fn, signal.SIGHUP, None)

    assert called == ["reload"]

  def test_calls_both_reopen_and_reload(self):
    """Test that both reopen and reload callbacks are called in order."""
    called = []
    reopen_fn = [lambda: called.append("reopen")]
    reload_fn = [lambda: called.append("reload")]

    daemon._HandleSigHup(reopen_fn, reload_fn, signal.SIGHUP, None)

    assert called == ["reopen", "reload"]

  def test_skips_none_entries(self):
    """Test that None entries in callback lists are skipped."""
    called = []
    reopen_fn = [None, lambda: called.append("reopen")]
    reload_fn = [None, lambda: called.append("reload")]

    daemon._HandleSigHup(reopen_fn, reload_fn, signal.SIGHUP, None)

    assert called == ["reopen", "reload"]

  def test_reload_error_does_not_prevent_other_callbacks(self, caplog):
    """Test that an error in one reload callback does not block others."""
    called = []

    def failing_reload():
      raise RuntimeError("reload failed")

    reopen_fn = []
    reload_fn = [failing_reload, lambda: called.append("second")]

    with caplog.at_level(logging.ERROR):
      daemon._HandleSigHup(reopen_fn, reload_fn, signal.SIGHUP, None)

    assert called == ["second"]
    assert "Error in SIGHUP reload callback" in caplog.text

  def test_multiple_reload_callbacks(self):
    """Test that multiple reload callbacks are all called."""
    called = []
    reopen_fn = []
    reload_fn = [
      lambda: called.append("first"),
      lambda: called.append("second"),
      lambda: called.append("third"),
    ]

    daemon._HandleSigHup(reopen_fn, reload_fn, signal.SIGHUP, None)

    assert called == ["first", "second", "third"]

  def test_empty_callback_lists(self):
    """Test that empty callback lists are handled gracefully."""
    daemon._HandleSigHup([], [], signal.SIGHUP, None)


class TestMainloop:
  """Tests for the Mainloop class construction and resource management."""

  @pytest.fixture
  def mainloop(self):
    ml = daemon.Mainloop()
    yield ml
    ml.close()

  def test_creates_socketpair(self, mainloop):
    """Test that the socketpair file descriptors are valid."""
    assert mainloop._awaker_in.fileno() >= 0
    assert mainloop._awaker_out.fileno() >= 0

  def test_awaker_in_is_nonblocking(self, mainloop):
    """Test that the read side of the socketpair is non-blocking."""
    assert mainloop._awaker_in.getblocking() is False

  def test_selector_registered(self, mainloop):
    """Test that the awaker socket is registered with the selector."""
    key = mainloop._sel.get_key(mainloop._awaker_in)
    assert key is not None

  def test_close_releases_resources(self):
    """Test that close() shuts down selector and sockets."""
    ml = daemon.Mainloop()
    in_fd = ml._awaker_in.fileno()
    out_fd = ml._awaker_out.fileno()
    ml.close()

    # File descriptors should be closed
    assert not _fd_is_open(in_fd)
    assert not _fd_is_open(out_fd)

  def test_wakeup_makes_selector_ready(self, mainloop):
    """Test that _wakeup() makes the selector return immediately."""
    mainloop._wakeup()
    events = mainloop._sel.select(timeout=0)
    assert len(events) == 1

  def test_wakeup_coalescing(self, mainloop):
    """Test that multiple _wakeup() calls before drain are coalesced."""
    mainloop._wakeup()
    # Force need_signal back to True to simulate a race
    mainloop._need_signal = True
    mainloop._wakeup()

    events = mainloop._sel.select(timeout=0)
    assert len(events) == 1

    # Drain the socketpair
    mainloop._awaker_in.recv(4096)
    mainloop._need_signal = True

    # No more data pending
    events = mainloop._sel.select(timeout=0)
    assert len(events) == 0

  def test_no_pending_data_initially(self, mainloop):
    """Test that no data is pending on the socketpair initially."""
    events = mainloop._sel.select(timeout=0)
    assert len(events) == 0


class TestMainloopRun:
  """Tests for Mainloop.Run() signal-driven shutdown."""

  @pytest.fixture
  def mainloop(self):
    ml = daemon.Mainloop()
    yield ml
    ml.close()

  def test_sigterm_triggers_shutdown(self, mainloop):
    """Test that SIGTERM causes Run() to exit."""
    _send_signal_delayed(signal.SIGTERM)
    mainloop.Run()

  def test_sigint_triggers_shutdown(self, mainloop):
    """Test that SIGINT causes Run() to exit."""
    _send_signal_delayed(signal.SIGINT)
    mainloop.Run()

  def test_shutdown_wait_fn_defers_exit(self, mainloop):
    """Test that shutdown_wait_fn can defer shutdown."""
    call_count = [0]

    def wait_fn():
      call_count[0] += 1
      if call_count[0] < 2:
        # First call: defer for 0 seconds (will re-check next iteration)
        return 0
      # Second call: allow shutdown
      return None

    _send_signal_delayed(signal.SIGTERM)

    mainloop.Run(shutdown_wait_fn=wait_fn)
    assert call_count[0] == 2


class TestMainloopSighupCallbacks:
  """Tests for Mainloop.RegisterSighupCallback."""

  @pytest.fixture
  def mainloop(self):
    ml = daemon.Mainloop()
    yield ml
    ml.close()

  def test_register_callback(self, mainloop):
    """Test registering a single callback."""
    def my_callback():
      pass

    mainloop.RegisterSighupCallback(my_callback)

    assert my_callback in mainloop.sighup_callbacks

  def test_register_multiple_callbacks(self, mainloop):
    """Test registering multiple callbacks."""
    callbacks = [lambda: None, lambda: None, lambda: None]

    for cb in callbacks:
      mainloop.RegisterSighupCallback(cb)

    assert len(mainloop.sighup_callbacks) == 3

  def test_callbacks_shared_with_signal_handler(self):
    """Test that registered callbacks are visible to _HandleSigHup.

    This tests the integration between RegisterSighupCallback and
    _HandleSigHup: both share the same mutable list, so callbacks
    registered after the signal handler is set up are still invoked.

    """
    called = []
    reload_callbacks = []

    # Simulate what GenericMain does: create the list, then pass it
    # to the signal handler
    mainloop = daemon.Mainloop()
    mainloop.sighup_callbacks = reload_callbacks

    # Register a callback after the list was passed to the handler
    mainloop.RegisterSighupCallback(lambda: called.append("late"))

    # Simulate SIGHUP
    daemon._HandleSigHup([], reload_callbacks, signal.SIGHUP, None)

    mainloop.close()

    assert called == ["late"]


def _fd_is_open(fd):
  """Check whether a file descriptor is still open."""
  try:
    os.fstat(fd)
    return True
  except OSError:
    return False
