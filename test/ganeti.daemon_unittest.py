#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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


"""Script for unittesting the daemon module"""

import unittest
import signal
import os

from ganeti import daemon

import testutils


class TestMainloop(testutils.GanetiTestCase):
  """Test daemon.Mainloop"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    self.sendsig_events = []
    self.onsignal_events = []

  def _CancelEvent(self, handle):
    self.mainloop.scheduler.cancel(handle)

  def _SendSig(self, sig):
    self.sendsig_events.append(sig)
    os.kill(os.getpid(), sig)

  def OnSignal(self, signum):
    self.onsignal_events.append(signum)

  def testRunAndTermBySched(self):
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run() # terminates by _SendSig being scheduled
    self.assertEquals(self.sendsig_events, [signal.SIGTERM])

  def testSchedulerCancel(self):
    handle = self.mainloop.scheduler.enter(0.1, 1, self._SendSig,
                                           [signal.SIGTERM])
    self.mainloop.scheduler.cancel(handle)
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGCHLD, signal.SIGTERM])

  def testRegisterSignal(self):
    self.mainloop.RegisterSignal(self)
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    handle = self.mainloop.scheduler.enter(0.1, 1, self._SendSig,
                                           [signal.SIGTERM])
    self.mainloop.scheduler.cancel(handle)
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    # ...not delievered because they are scheduled after TERM
    self.mainloop.scheduler.enter(0.4, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.5, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEquals(self.onsignal_events, self.sendsig_events)

  def testDeferredCancel(self):
    self.mainloop.RegisterSignal(self)
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    handle1 = self.mainloop.scheduler.enter(0.3, 2, self._SendSig,
                                           [signal.SIGCHLD])
    handle2 = self.mainloop.scheduler.enter(0.4, 2, self._SendSig,
                                           [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0, 1, self._CancelEvent, [handle1])
    self.mainloop.scheduler.enter(0, 1, self._CancelEvent, [handle2])
    self.mainloop.scheduler.enter(0.5, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGCHLD, signal.SIGTERM])
    self.assertEquals(self.onsignal_events, self.sendsig_events)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
