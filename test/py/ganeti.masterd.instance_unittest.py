#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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


"""Script for testing ganeti.masterd.instance"""

import os
import sys
import unittest

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import masterd

from ganeti.masterd.instance import \
  ImportExportTimeouts, _DiskImportExportBase, \
  ComputeRemoteExportHandshake, CheckRemoteExportHandshake, \
  ComputeRemoteImportDiskInfo, CheckRemoteExportDiskInfo, \
  FormatProgress

import testutils


class TestMisc(unittest.TestCase):
  def testTimeouts(self):
    tmo = ImportExportTimeouts(0)
    self.assertEqual(tmo.connect, 0)
    self.assertEqual(tmo.listen, ImportExportTimeouts.DEFAULT_LISTEN_TIMEOUT)
    self.assertEqual(tmo.ready, ImportExportTimeouts.DEFAULT_READY_TIMEOUT)
    self.assertEqual(tmo.error, ImportExportTimeouts.DEFAULT_ERROR_TIMEOUT)
    self.assertEqual(tmo.progress,
                     ImportExportTimeouts.DEFAULT_PROGRESS_INTERVAL)

    tmo = ImportExportTimeouts(999)
    self.assertEqual(tmo.connect, 999)

    tmo = ImportExportTimeouts(1, listen=2, error=3, ready=4, progress=5)
    self.assertEqual(tmo.connect, 1)
    self.assertEqual(tmo.listen, 2)
    self.assertEqual(tmo.error, 3)
    self.assertEqual(tmo.ready, 4)
    self.assertEqual(tmo.progress, 5)

  def testTimeoutExpired(self):
    self.assert_(utils.TimeoutExpired(100, 300, _time_fn=lambda: 500))
    self.assertFalse(utils.TimeoutExpired(100, 300, _time_fn=lambda: 0))
    self.assertFalse(utils.TimeoutExpired(100, 300, _time_fn=lambda: 100))
    self.assertFalse(utils.TimeoutExpired(100, 300, _time_fn=lambda: 400))

  def testDiskImportExportBaseDirect(self):
    self.assertRaises(AssertionError, _DiskImportExportBase,
                      None, None, None, None, None, None, None)


class TestRieHandshake(unittest.TestCase):
  def test(self):
    cds = "cd-secret"
    hs = ComputeRemoteExportHandshake(cds)
    self.assertEqual(len(hs), 3)
    self.assertEqual(hs[0], constants.RIE_VERSION)

    self.assertEqual(CheckRemoteExportHandshake(cds, hs), None)

  def testCheckErrors(self):
    self.assert_(CheckRemoteExportHandshake(None, None))
    self.assert_(CheckRemoteExportHandshake("", ""))
    self.assert_(CheckRemoteExportHandshake("", ("xyz", "foo")))

  def testCheckWrongHash(self):
    cds = "cd-secret999"
    self.assert_(CheckRemoteExportHandshake(cds, (0, "fakehash", "xyz")))

  def testCheckWrongVersion(self):
    version = 14887
    self.assertNotEqual(version, constants.RIE_VERSION)
    cds = "c28ac99"
    salt = "a19cf8cc06"
    msg = "%s:%s" % (version, constants.RIE_HANDSHAKE)
    hs = (version, utils.Sha1Hmac(cds, msg, salt=salt), salt)
    self.assert_(CheckRemoteExportHandshake(cds, hs))


class TestRieDiskInfo(unittest.TestCase):
  def test(self):
    cds = "bbf46ea9a"
    salt = "ee5ad9"
    di = ComputeRemoteImportDiskInfo(cds, salt, 0, "node1", 1234, "mag111")
    self.assertEqual(CheckRemoteExportDiskInfo(cds, 0, di),
                     ("node1", 1234, "mag111"))

    for i in range(1, 100):
      # Wrong disk index
      self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                        cds, i, di)

  def testInvalidHostPort(self):
    cds = "3ZoJY8KtGJ"
    salt = "drK5oYiHWD"

    for host in [",", "...", "Hello World", "`", "!", "#", "\\"]:
      di = ComputeRemoteImportDiskInfo(cds, salt, 0, host, 1234, "magic")
      self.assertRaises(errors.OpPrereqError,
                        CheckRemoteExportDiskInfo, cds, 0, di)

    for port in [-1, 792825908, "HelloWorld!", "`#", "\\\"", "_?_"]:
      di = ComputeRemoteImportDiskInfo(cds, salt, 0, "localhost", port, "magic")
      self.assertRaises(errors.OpPrereqError,
                        CheckRemoteExportDiskInfo, cds, 0, di)

  def testCheckErrors(self):
    cds = "0776450535a"
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, "")
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ())
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("", 1, 2, 3, 4, 5))

    # No host/port
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("", 1234, "magic", "", ""))
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("host", 0, "magic", "", ""))
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("host", 1234, "", "", ""))

    # Wrong hash
    self.assertRaises(errors.GenericError, CheckRemoteExportDiskInfo,
                      cds, 0, ("nodeX", 123, "magic", "fakehash", "xyz"))


class TestFormatProgress(unittest.TestCase):
  def test(self):
    FormatProgress((0, 0, None, None))
    FormatProgress((100, 3.3, 30, None))
    FormatProgress((100, 3.3, 30, 900))

    self.assertEqual(FormatProgress((1500, 12, 30, None)),
                     "1.5G, 12.0 MiB/s, 30%")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
