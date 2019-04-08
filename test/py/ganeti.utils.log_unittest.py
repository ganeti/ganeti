#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.utils.log"""

import os
import unittest
import logging
import tempfile
import shutil
import threading
from io import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import compat
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


class TestSetupToolLogging(unittest.TestCase):
  def test(self):
    error_name = logging.getLevelName(logging.ERROR)
    warn_name = logging.getLevelName(logging.WARNING)
    info_name = logging.getLevelName(logging.INFO)
    debug_name = logging.getLevelName(logging.DEBUG)

    for debug in [False, True]:
      for verbose in [False, True]:
        logger = logging.Logger("TestLogger")
        buf = StringIO()

        utils.SetupToolLogging(debug, verbose, _root_logger=logger, _stream=buf)

        logger.error("level=error")
        logger.warning("level=warning")
        logger.info("level=info")
        logger.debug("level=debug")

        lines = buf.getvalue().splitlines()

        self.assertTrue(compat.all(line.count(":") == 3 for line in lines))

        messages = [line.split(":", 3)[-1].strip() for line in lines]

        if debug:
          self.assertEqual(messages, [
            "%s level=error" % error_name,
            "%s level=warning" % warn_name,
            "%s level=info" % info_name,
            "%s level=debug" % debug_name,
            ])
        elif verbose:
          self.assertEqual(messages, [
            "%s level=error" % error_name,
            "%s level=warning" % warn_name,
            "%s level=info" % info_name,
            ])
        else:
          self.assertEqual(messages, [
            "level=error",
            "level=warning",
            ])

  def testThreadName(self):
    thread_name = threading.currentThread().getName()

    for enable_threadname in [False, True]:
      logger = logging.Logger("TestLogger")
      buf = StringIO()

      utils.SetupToolLogging(True, True, threadname=enable_threadname,
                             _root_logger=logger, _stream=buf)

      logger.debug("test134042376")

      lines = buf.getvalue().splitlines()
      self.assertEqual(len(lines), 1)

      if enable_threadname:
        self.assertTrue((" %s " % thread_name) in lines[0])
      else:
        self.assertTrue(thread_name not in lines[0])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
