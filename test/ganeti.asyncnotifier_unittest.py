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


"""Script for unittesting the asyncnotifier module"""

import unittest
import signal
import os

try:
  # pylint: disable-msg=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import daemon
from ganeti import utils

import testutils


class TestSingleFileEventHandler(testutils.GanetiTestCase):
  """Test daemon.Mainloop"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    notifier_count = 2
    self.chk_files = [self._CreateTempFile() for i in range(notifier_count)]
    self.notified = [False for i in range(notifier_count)]
    # We need one watch manager per notifier, as those contain the file
    # descriptor which is monitored by asyncore
    self.wms = [pyinotify.WatchManager() for i in range(notifier_count)]
    self.cbk = [self.OnInotifyCallback(self.notified, i)
                  for i in range(notifier_count)]
    self.ihandler = [asyncnotifier.SingleFileEventHandler(self.wms[i],
                                                          self.cbk[i],
                                                          self.chk_files[i])
                      for i in range(notifier_count)]
    self.notifiers = [asyncnotifier.AsyncNotifier(self.wms[i],
                                                  self.ihandler[i])
                       for i in range(notifier_count)]
    # notifier 0 is enabled by default, as we use it to get out of the loop
    self.ihandler[0].enable()

  class OnInotifyCallback:
    def __init__(self, notified, i):
      self.notified = notified
      self.i = i

    def __call__(self, enabled):
      self.notified[self.i] = True
      # notifier 0 is special as we use it to terminate the mainloop
      if self.i == 0:
        os.kill(os.getpid(), signal.SIGTERM)

  def testReplace(self):
    utils.WriteFile(self.chk_files[0], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[0])
    self.assert_(not self.notified[1])

  def testEnableDisable(self):
    self.ihandler[0].enable()
    self.ihandler[0].disable()
    self.ihandler[0].disable()
    self.ihandler[0].enable()
    self.ihandler[0].disable()
    self.ihandler[0].enable()
    utils.WriteFile(self.chk_files[0], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[0])
    self.assert_(not self.notified[1])

  def testDoubleEnable(self):
    self.ihandler[0].enable()
    self.ihandler[0].enable()
    utils.WriteFile(self.chk_files[0], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[0])
    self.assert_(not self.notified[1])

  def testDefaultDisabled(self):
    utils.WriteFile(self.chk_files[1], data="dummy")
    utils.WriteFile(self.chk_files[0], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[0])
    # notifier 1 is disabled by default
    self.assert_(not self.notified[1])

  def testBothEnabled(self):
    self.ihandler[1].enable()
    utils.WriteFile(self.chk_files[1], data="dummy")
    utils.WriteFile(self.chk_files[0], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[0])
    self.assert_(self.notified[1])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
