#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.ssconf"""

import os
import unittest
import tempfile
import shutil
import errno

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import ssconf

import testutils


class TestReadSsconfFile(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testReadDirectory(self):
    self.assertRaises(EnvironmentError, ssconf.ReadSsconfFile, self.tmpdir)

  def testNonExistantFile(self):
    testfile = utils.PathJoin(self.tmpdir, "does.not.exist")

    self.assertFalse(os.path.exists(testfile))

    try:
      ssconf.ReadSsconfFile(testfile)
    except EnvironmentError, err:
      self.assertEqual(err.errno, errno.ENOENT)
    else:
      self.fail("Exception was not raised")

  def testEmptyFile(self):
    testfile = utils.PathJoin(self.tmpdir, "empty")

    utils.WriteFile(testfile, data="")

    self.assertEqual(ssconf.ReadSsconfFile(testfile), "")

  def testSingleLine(self):
    testfile = utils.PathJoin(self.tmpdir, "data")

    for nl in range(0, 10):
      utils.WriteFile(testfile, data="Hello World" + ("\n" * nl))

      self.assertEqual(ssconf.ReadSsconfFile(testfile),
                       "Hello World")

  def testExactlyMaxSize(self):
    testfile = utils.PathJoin(self.tmpdir, "data")

    data = "A" * ssconf._MAX_SIZE
    utils.WriteFile(testfile, data=data)

    self.assertEqual(os.path.getsize(testfile), ssconf._MAX_SIZE)

    self.assertEqual(ssconf.ReadSsconfFile(testfile),
                     data)

  def testLargeFile(self):
    testfile = utils.PathJoin(self.tmpdir, "data")

    for size in [ssconf._MAX_SIZE + 1, ssconf._MAX_SIZE * 2]:
      utils.WriteFile(testfile, data="A" * size)
      self.assertTrue(os.path.getsize(testfile) > ssconf._MAX_SIZE)
      self.assertRaises(RuntimeError, ssconf.ReadSsconfFile, testfile)


class TestSimpleStore(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.sstore = ssconf.SimpleStore(cfg_location=self.tmpdir)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testInvalidKey(self):
    self.assertRaises(errors.ProgrammerError, self.sstore.KeyToFilename,
                      "not a valid key")
    self.assertRaises(errors.ProgrammerError, self.sstore._ReadFile,
                      "not a valid key")

  def testKeyToFilename(self):
    for key in ssconf._VALID_KEYS:
      result = self.sstore.KeyToFilename(key)
      self.assertTrue(utils.IsBelowDir(self.tmpdir, result))
      self.assertTrue(os.path.basename(result).startswith("ssconf_"))

  def testReadFileNonExistingFile(self):
    filename = self.sstore.KeyToFilename(constants.SS_CLUSTER_NAME)

    self.assertFalse(os.path.exists(filename))
    try:
      self.sstore._ReadFile(constants.SS_CLUSTER_NAME)
    except errors.ConfigurationError, err:
      self.assertTrue(str(err).startswith("Can't read ssconf file"))
    else:
      self.fail("Exception was not raised")

    for default in ["", "Hello World", 0, 100]:
      self.assertFalse(os.path.exists(filename))
      result = self.sstore._ReadFile(constants.SS_CLUSTER_NAME, default=default)
      self.assertEqual(result, default)

  def testReadFile(self):
    utils.WriteFile(self.sstore.KeyToFilename(constants.SS_CLUSTER_NAME),
                    data="cluster.example.com")

    self.assertEqual(self.sstore._ReadFile(constants.SS_CLUSTER_NAME),
                     "cluster.example.com")

    self.assertEqual(self.sstore._ReadFile(constants.SS_CLUSTER_NAME,
                                           default="something.example.com"),
                     "cluster.example.com")


class TestVerifyClusterName(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testMissingFile(self):
    tmploc = utils.PathJoin(self.tmpdir, "does-not-exist")
    ssconf.VerifyClusterName(NotImplemented, _cfg_location=tmploc)

  def testMatchingName(self):
    tmpfile = utils.PathJoin(self.tmpdir, "ssconf_cluster_name")

    for content in ["cluster.example.com", "cluster.example.com\n\n"]:
      utils.WriteFile(tmpfile, data=content)
      ssconf.VerifyClusterName("cluster.example.com",
                               _cfg_location=self.tmpdir)

  def testNameMismatch(self):
    tmpfile = utils.PathJoin(self.tmpdir, "ssconf_cluster_name")

    for content in ["something.example.com", "foobar\n\ncluster.example.com"]:
      utils.WriteFile(tmpfile, data=content)
      self.assertRaises(errors.GenericError, ssconf.VerifyClusterName,
                        "cluster.example.com", _cfg_location=self.tmpdir)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
