#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.utils.log"""

import os
import unittest
import logging
import tempfile
import shutil

from ganeti import constants
from ganeti import errors
from ganeti import utils

import testutils


class TestLogHandler(unittest.TestCase):
  def testNormal(self):
    tmpfile = tempfile.NamedTemporaryFile()

    handler = utils.log._ReopenableLogHandler(tmpfile.name)
    handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))

    logger = logging.Logger("TestLogger")
    logger.addHandler(handler)
    self.assertEqual(len(logger.handlers), 1)

    logger.error("Test message ERROR")
    logger.info("Test message INFO")

    logger.removeHandler(handler)
    self.assertFalse(logger.handlers)
    handler.close()

    self.assertEqual(len(utils.ReadFile(tmpfile.name).splitlines()), 2)

  def testReopen(self):
    tmpfile = tempfile.NamedTemporaryFile()
    tmpfile2 = tempfile.NamedTemporaryFile()

    handler = utils.log._ReopenableLogHandler(tmpfile.name)

    self.assertFalse(utils.ReadFile(tmpfile.name))
    self.assertFalse(utils.ReadFile(tmpfile2.name))

    logger = logging.Logger("TestLoggerReopen")
    logger.addHandler(handler)

    for _ in range(3):
      logger.error("Test message ERROR")
    handler.flush()
    self.assertEqual(len(utils.ReadFile(tmpfile.name).splitlines()), 3)
    before_id = utils.GetFileID(tmpfile.name)

    handler.RequestReopen()
    self.assertTrue(handler._reopen)
    self.assertTrue(utils.VerifyFileID(utils.GetFileID(tmpfile.name),
                                       before_id))

    # Rename only after requesting reopen
    os.rename(tmpfile.name, tmpfile2.name)
    assert not os.path.exists(tmpfile.name)

    # Write another message, should reopen
    for _ in range(4):
      logger.info("Test message INFO")

      # Flag must be reset
      self.assertFalse(handler._reopen)

      self.assertFalse(utils.VerifyFileID(utils.GetFileID(tmpfile.name),
                                          before_id))

    logger.removeHandler(handler)
    self.assertFalse(logger.handlers)
    handler.close()

    self.assertEqual(len(utils.ReadFile(tmpfile.name).splitlines()), 4)
    self.assertEqual(len(utils.ReadFile(tmpfile2.name).splitlines()), 3)

  def testConsole(self):
    for (console, check) in [(None, False),
                             (tempfile.NamedTemporaryFile(), True),
                             (self._FailingFile(os.devnull), False)]:
      # Create a handler which will fail when handling errors
      cls = utils.log._LogErrorsToConsole(self._FailingHandler)

      # Instantiate handler with file which will fail when writing,
      # provoking a write to the console
      handler = cls(console, self._FailingFile(os.devnull))

      logger = logging.Logger("TestLogger")
      logger.addHandler(handler)
      self.assertEqual(len(logger.handlers), 1)

      # Provoke write
      logger.error("Test message ERROR")

      # Take everything apart
      logger.removeHandler(handler)
      self.assertFalse(logger.handlers)
      handler.close()

      if console and check:
        console.flush()

        # Check console output
        consout = utils.ReadFile(console.name)
        self.assertTrue("Cannot log message" in consout)
        self.assertTrue("Test message ERROR" in consout)

  class _FailingFile(file):
    def write(self, _):
      raise Exception

  class _FailingHandler(logging.StreamHandler):
    def handleError(self, _):
      raise Exception


class TestSetupLogging(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testSimple(self):
    logfile = utils.PathJoin(self.tmpdir, "basic.log")
    logger = logging.Logger("TestLogger")
    self.assertTrue(callable(utils.SetupLogging(logfile, "test",
                                                console_logging=False,
                                                syslog=constants.SYSLOG_NO,
                                                stderr_logging=False,
                                                multithreaded=False,
                                                root_logger=logger)))
    self.assertEqual(utils.ReadFile(logfile), "")
    logger.error("This is a test")

    # Ensure SetupLogging used custom logger
    logging.error("This message should not show up in the test log file")

    self.assertTrue(utils.ReadFile(logfile).endswith("This is a test\n"))

  def testReopen(self):
    logfile = utils.PathJoin(self.tmpdir, "reopen.log")
    logfile2 = utils.PathJoin(self.tmpdir, "reopen.log.OLD")
    logger = logging.Logger("TestLogger")
    reopen_fn = utils.SetupLogging(logfile, "test",
                                   console_logging=False,
                                   syslog=constants.SYSLOG_NO,
                                   stderr_logging=False,
                                   multithreaded=False,
                                   root_logger=logger)
    self.assertTrue(callable(reopen_fn))

    self.assertEqual(utils.ReadFile(logfile), "")
    logger.error("This is a test")
    self.assertTrue(utils.ReadFile(logfile).endswith("This is a test\n"))

    os.rename(logfile, logfile2)
    assert not os.path.exists(logfile)

    # Notify logger to reopen on the next message
    reopen_fn()
    assert not os.path.exists(logfile)

    # Provoke actual reopen
    logger.error("First message")

    self.assertTrue(utils.ReadFile(logfile).endswith("First message\n"))
    self.assertTrue(utils.ReadFile(logfile2).endswith("This is a test\n"))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
