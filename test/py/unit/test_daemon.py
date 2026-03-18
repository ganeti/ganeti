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
import signal

import pytest

from ganeti import daemon


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


class TestMainloopSighupCallbacks:
  """Tests for Mainloop.RegisterSighupCallback."""

  @pytest.fixture
  def mainloop_with_callbacks(self):
    """Create a Mainloop with sighup_callbacks initialized."""
    return daemon.Mainloop()

  def test_register_callback(self, mainloop_with_callbacks):
    """Test registering a single callback."""
    mainloop = mainloop_with_callbacks

    def my_callback():
      pass

    mainloop.RegisterSighupCallback(my_callback)

    assert my_callback in mainloop.sighup_callbacks

  def test_register_multiple_callbacks(self, mainloop_with_callbacks):
    """Test registering multiple callbacks."""
    mainloop = mainloop_with_callbacks
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

    assert called == ["late"]
