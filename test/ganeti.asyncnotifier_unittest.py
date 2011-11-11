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
import tempfile
import shutil

try:
  # pylint: disable=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import daemon
from ganeti import utils
from ganeti import errors

import testutils


class _MyErrorLoggingAsyncNotifier(asyncnotifier.ErrorLoggingAsyncNotifier):
  def __init__(self, *args, **kwargs):
    asyncnotifier.ErrorLoggingAsyncNotifier.__init__(self, *args, **kwargs)
    self.error_count = 0

  def handle_error(self):
    self.error_count += 1
    raise


class TestSingleFileEventHandler(testutils.GanetiTestCase):
  """Test daemon.Mainloop"""

  NOTIFIERS = [NOTIFIER_TERM, NOTIFIER_NORM, NOTIFIER_ERR] = range(3)

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    self.chk_files = [self._CreateTempFile() for i in self.NOTIFIERS]
    self.notified = [False for i in self.NOTIFIERS]
    # We need one watch manager per notifier, as those contain the file
    # descriptor which is monitored by asyncore
    self.wms = [pyinotify.WatchManager() for i in self.NOTIFIERS]
    self.cbk = [self.OnInotifyCallback(self, i) for i in self.NOTIFIERS]
    self.ihandler = [asyncnotifier.SingleFileEventHandler(wm, cb, cf)
                     for (wm, cb, cf) in
                     zip(self.wms, self.cbk, self.chk_files)]
    self.notifiers = [_MyErrorLoggingAsyncNotifier(wm, ih)
                      for (wm, ih) in zip(self.wms, self.ihandler)]
    # TERM notifier is enabled by default, as we use it to get out of the loop
    self.ihandler[self.NOTIFIER_TERM].enable()

  class OnInotifyCallback:
    def __init__(self, testobj, i):
      self.testobj = testobj
      self.notified = testobj.notified
      self.i = i

    def __call__(self, enabled):
      self.notified[self.i] = True
      if self.i == self.testobj.NOTIFIER_TERM:
        os.kill(os.getpid(), signal.SIGTERM)
      elif self.i == self.testobj.NOTIFIER_ERR:
        raise errors.GenericError("an error")

  def testReplace(self):
    utils.WriteFile(self.chk_files[self.NOTIFIER_TERM], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[self.NOTIFIER_TERM])
    self.assertFalse(self.notified[self.NOTIFIER_NORM])
    self.assertEquals(self.notifiers[self.NOTIFIER_TERM].error_count, 0)
    self.assertEquals(self.notifiers[self.NOTIFIER_NORM].error_count, 0)

  def testEnableDisable(self):
    self.ihandler[self.NOTIFIER_TERM].enable()
    self.ihandler[self.NOTIFIER_TERM].disable()
    self.ihandler[self.NOTIFIER_TERM].disable()
    self.ihandler[self.NOTIFIER_TERM].enable()
    self.ihandler[self.NOTIFIER_TERM].disable()
    self.ihandler[self.NOTIFIER_TERM].enable()
    utils.WriteFile(self.chk_files[self.NOTIFIER_TERM], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[self.NOTIFIER_TERM])
    self.assertFalse(self.notified[self.NOTIFIER_NORM])
    self.assertEquals(self.notifiers[self.NOTIFIER_TERM].error_count, 0)
    self.assertEquals(self.notifiers[self.NOTIFIER_NORM].error_count, 0)

  def testDoubleEnable(self):
    self.ihandler[self.NOTIFIER_TERM].enable()
    self.ihandler[self.NOTIFIER_TERM].enable()
    utils.WriteFile(self.chk_files[self.NOTIFIER_TERM], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[self.NOTIFIER_TERM])
    self.assertFalse(self.notified[self.NOTIFIER_NORM])
    self.assertEquals(self.notifiers[self.NOTIFIER_TERM].error_count, 0)
    self.assertEquals(self.notifiers[self.NOTIFIER_NORM].error_count, 0)

  def testDefaultDisabled(self):
    utils.WriteFile(self.chk_files[self.NOTIFIER_NORM], data="dummy")
    utils.WriteFile(self.chk_files[self.NOTIFIER_TERM], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[self.NOTIFIER_TERM])
    # NORM notifier is disabled by default
    self.assertFalse(self.notified[self.NOTIFIER_NORM])
    self.assertEquals(self.notifiers[self.NOTIFIER_TERM].error_count, 0)
    self.assertEquals(self.notifiers[self.NOTIFIER_NORM].error_count, 0)

  def testBothEnabled(self):
    self.ihandler[self.NOTIFIER_NORM].enable()
    utils.WriteFile(self.chk_files[self.NOTIFIER_NORM], data="dummy")
    utils.WriteFile(self.chk_files[self.NOTIFIER_TERM], data="dummy")
    self.mainloop.Run()
    self.assert_(self.notified[self.NOTIFIER_TERM])
    self.assert_(self.notified[self.NOTIFIER_NORM])
    self.assertEquals(self.notifiers[self.NOTIFIER_TERM].error_count, 0)
    self.assertEquals(self.notifiers[self.NOTIFIER_NORM].error_count, 0)

  def testError(self):
    self.ihandler[self.NOTIFIER_ERR].enable()
    utils.WriteFile(self.chk_files[self.NOTIFIER_ERR], data="dummy")
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assert_(self.notified[self.NOTIFIER_ERR])
    self.assertEquals(self.notifiers[self.NOTIFIER_ERR].error_count, 1)
    self.assertEquals(self.notifiers[self.NOTIFIER_NORM].error_count, 0)
    self.assertEquals(self.notifiers[self.NOTIFIER_TERM].error_count, 0)


class TestSingleFileEventHandlerError(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def test(self):
    wm = pyinotify.WatchManager()
    handler = asyncnotifier.SingleFileEventHandler(wm, None,
                                                   utils.PathJoin(self.tmpdir,
                                                                  "nonexist"))
    self.assertRaises(errors.InotifyError, handler.enable)
    self.assertRaises(errors.InotifyError, handler.enable)
    handler.disable()
    self.assertRaises(errors.InotifyError, handler.enable)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
