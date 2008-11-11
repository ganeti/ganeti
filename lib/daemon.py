#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Module with helper classes and functions for daemons"""


import select
import signal
import errno
import time

from ganeti import utils


class Timer(object):
  def __init__(self, owner, timer_id, start, interval, repeat):
    self.owner = owner
    self.timer_id = timer_id
    self.start = start
    self.interval = interval
    self.repeat = repeat


class Mainloop(object):
  """Generic mainloop for daemons

  """
  def __init__(self):
    """Constructs a new Mainloop instance.

    """
    self._io_wait = {}
    self._io_wait_add = []
    self._io_wait_remove = []
    self._signal_wait = []
    self._timer_id_last = 0
    self._timer = {}
    self._timer_add = []
    self._timer_remove = []

  def Run(self, handle_sigchld=True, handle_sigterm=True, stop_on_empty=False):
    """Runs the mainloop.

    @type handle_sigchld: bool
    @param handle_sigchld: Whether to install handler for SIGCHLD
    @type handle_sigterm: bool
    @param handle_sigterm: Whether to install handler for SIGTERM
    @type stop_on_empty: bool
    @param stop_on_empty: Whether to stop mainloop once all I/O waiters
                          unregistered

    """
    poller = select.poll()

    # Setup signal handlers
    if handle_sigchld:
      sigchld_handler = utils.SignalHandler([signal.SIGCHLD])
    else:
      sigchld_handler = None
    try:
      if handle_sigterm:
        sigterm_handler = utils.SignalHandler([signal.SIGTERM])
      else:
        sigterm_handler = None

      try:
        running = True
        timeout = None
        timeout_needs_update = True

        # Start actual main loop
        while running:
          # Entries could be added again afterwards, hence removing first
          if self._io_wait_remove:
            for fd in self._io_wait_remove:
              try:
                poller.unregister(fd)
              except KeyError:
                pass
              try:
                del self._io_wait[fd]
              except KeyError:
                pass
            self._io_wait_remove = []

          # Add new entries
          if self._io_wait_add:
            for (owner, fd, conditions) in self._io_wait_add:
              self._io_wait[fd] = owner
              poller.register(fd, conditions)
            self._io_wait_add = []

          # Add new timers
          if self._timer_add:
            timeout_needs_update = True
            for timer in self._timer_add:
              self._timer[timer.timer_id] = timer
            del self._timer_add[:]

          # Remove timers
          if self._timer_remove:
            timeout_needs_update = True
            for timer_id in self._timer_remove:
              try:
                del self._timer[timer_id]
              except KeyError:
                pass
            del self._timer_remove[:]

          # Stop if nothing is listening anymore
          if stop_on_empty and not (self._io_wait or self._timer):
            break

          # Calculate timeout again if required
          if timeout_needs_update:
            timeout = self._CalcTimeout(time.time())

          # Wait for I/O events
          try:
            io_events = poller.poll(timeout)
          except select.error, err:
            # EINTR can happen when signals are sent
            if err.args and err.args[0] in (errno.EINTR,):
              io_events = None
            else:
              raise

          after_poll = time.time()

          if io_events:
            # Check for I/O events
            for (evfd, evcond) in io_events:
              owner = self._io_wait.get(evfd, None)
              if owner:
                owner.OnIO(evfd, evcond)

          if self._timer:
            self._CheckTimers(after_poll)

          # Check whether signal was raised
          if sigchld_handler and sigchld_handler.called:
            self._CallSignalWaiters(signal.SIGCHLD)
            sigchld_handler.Clear()

          if sigterm_handler and sigterm_handler.called:
            self._CallSignalWaiters(signal.SIGTERM)
            running = False
            sigterm_handler.Clear()
      finally:
        # Restore signal handlers
        if sigterm_handler:
          sigterm_handler.Reset()
    finally:
      if sigchld_handler:
        sigchld_handler.Reset()

  def _CalcTimeout(self, now):
    if not self._timer:
      return None

    timeout = None

    # TODO: Repeating timers

    min_timeout = 0.001

    for timer in self._timer.itervalues():
      time_left = (timer.start + timer.interval) - now
      if timeout is None or time_left < timeout:
        timeout = time_left
      if timeout < 0:
        timeout = 0
        break
      elif timeout < min_timeout:
        timeout = min_timeout
        break

    return timeout * 1000.0

  def _CheckTimers(self, now):
    # TODO: Repeating timers
    for timer in self._timer.itervalues():
      if now < (timer.start + timer.interval):
        continue

      timer.owner.OnTimer(timer.timer_id)

      # TODO: Repeating timers should not be removed
      self._timer_remove.append(timer.timer_id)

  def _CallSignalWaiters(self, signum):
    """Calls all signal waiters for a certain signal.

    @type signum: int
    @param signum: Signal number

    """
    for owner in self._signal_wait:
      owner.OnSignal(signal.SIGCHLD)

  def RegisterIO(self, owner, fd, condition):
    """Registers a receiver for I/O notifications

    The receiver must support a "OnIO(self, fd, conditions)" function.

    @type owner: instance
    @param owner: Receiver
    @type fd: int
    @param fd: File descriptor
    @type condition: int
    @param condition: ORed field of conditions to be notified
                      (see select module)

    """
    # select.Poller also supports file() like objects, but we don't.
    assert isinstance(fd, (int, long)), \
      "Only integers are supported for file descriptors"

    self._io_wait_add.append((owner, fd, condition))

  def UnregisterIO(self, fd):
    """Unregister a file descriptor.

    It'll be unregistered the next time the mainloop checks for it.

    @type fd: int
    @param fd: File descriptor

    """
    # select.Poller also supports file() like objects, but we don't.
    assert isinstance(fd, (int, long)), \
      "Only integers are supported for file descriptors"

    self._io_wait_remove.append(fd)

  def RegisterSignal(self, owner):
    """Registers a receiver for signal notifications

    The receiver must support a "OnSignal(self, signum)" function.

    @type owner: instance
    @param owner: Receiver

    """
    self._signal_wait.append(owner)

  def AddTimer(self, owner, interval, repeat):
    """Add a new timer.

    The receiver must support a "OnTimer(self, timer_id)" function.

    @type owner: instance
    @param owner: Receiver
    @type interval: int or float
    @param interval: Timer interval in seconds
    @type repeat: bool
    @param repeat: Whether this is a repeating timer or one-off

    """
    # TODO: Implement repeating timers
    assert not repeat, "Repeating timers are not yet supported"

    # Get new ID
    self._timer_id_last += 1

    timer_id = self._timer_id_last

    self._timer_add.append(Timer(owner, timer_id, time.time(),
                                 float(interval), repeat))

    return timer_id

  def RemoveTimer(self, timer_id):
    """Removes a timer.

    @type timer_id: int
    @param timer_id: Timer ID

    """
    self._timer_remove.append(timer_id)
