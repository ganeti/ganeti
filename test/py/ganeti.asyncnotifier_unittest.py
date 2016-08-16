#!/usr/bin/python
#

# Copyright (C) 2010, 2012 Google Inc.
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


"""Script for unittesting the asyncnotifier module"""

import logging
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

  def tearDown(self):
    # disable the inotifiers, before removing the files
    for i in self.ihandler:
      i.disable()
    testutils.GanetiTestCase.tearDown(self)
    # and unregister the fd's being polled
    for n in self.notifiers:
      n.del_channel()

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
    logger = logging.getLogger('pyinotify')
    logger.disabled = True
    try:
      self.assertRaises(errors.InotifyError, handler.enable)
      self.assertRaises(errors.InotifyError, handler.enable)
      handler.disable()
      self.assertRaises(errors.InotifyError, handler.enable)
    finally:
      logger.disabled = False


if __name__ == "__main__":
  testutils.GanetiTestProgram()
