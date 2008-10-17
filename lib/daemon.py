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

from ganeti import utils


class Mainloop(object):
  """Generic mainloop for daemons

  """
  def __init__(self):
    self._io_wait = []
    self._signal_wait = []
    self.sigchld_handler = None
    self.sigterm_handler = None
    self.quit = False

  def Run(self):
    # TODO: Does not yet support adding new event sources while running
    poller = select.poll()
    for (owner, fd, conditions) in self._io_wait:
      poller.register(fd, conditions)

    self.sigchld_handler = utils.SignalHandler([signal.SIGCHLD])
    self.sigterm_handler = utils.SignalHandler([signal.SIGTERM])
    try:
      while not self.quit:
        try:
          io_events = poller.poll(1000)
        except select.error, err:
          # EINTR can happen when signals are sent
          if err.args and err.args[0] in (errno.EINTR,):
            io_events = None
          else:
            raise

        if io_events:
          # Check for I/O events
          for (evfd, evcond) in io_events:
            for (owner, fd, conditions) in self._io_wait:
              if fd == evfd and evcond & conditions:
                owner.OnIO(fd, evcond)

        # Check whether signal was raised
        if self.sigchld_handler.called:
          for owner in self._signal_wait:
            owner.OnSignal(signal.SIGCHLD)
          self.sigchld_handler.Clear()

        if self.sigterm_handler.called:
          self.quit = True
          self.sigterm_handler.Clear()
    finally:
      self.sigchld_handler.Reset()
      self.sigchld_handler = None
      self.sigterm_handler.Reset()
      self.sigterm_handler = None


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
    self._io_wait.append((owner, fd, condition))

  def RegisterSignal(self, owner):
    """Registers a receiver for signal notifications

    The receiver must support a "OnSignal(self, signum)" function.

    @type owner: instance
    @param owner: Receiver

    """
    self._signal_wait.append(owner)
