#!/usr/bin/python3
#

# Copyright (C) 2012 Google Inc.
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
import mock


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
    except EnvironmentError as err:
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
    self._tmpdir = tempfile.mkdtemp()
    self.ssdir = utils.PathJoin(self._tmpdir, "files")
    lockfile = utils.PathJoin(self._tmpdir, "lock")

    os.mkdir(self.ssdir)

    self.sstore = ssconf.SimpleStore(cfg_location=self.ssdir,
                                     _lockfile=lockfile)

  def tearDown(self):
    shutil.rmtree(self._tmpdir)

  def _ReadSsFile(self, filename):
    return utils.ReadFile(utils.PathJoin(self.ssdir, "ssconf_%s" % filename))

  def testInvalidKey(self):
    self.assertRaises(errors.ProgrammerError, self.sstore.KeyToFilename,
                      "not a valid key")
    self.assertRaises(errors.ProgrammerError, self.sstore._ReadFile,
                      "not a valid key")

  def testKeyToFilename(self):
    for key in ssconf._VALID_KEYS:
      result = self.sstore.KeyToFilename(key)
      self.assertTrue(utils.IsBelowDir(self.ssdir, result))
      self.assertTrue(os.path.basename(result).startswith("ssconf_"))

  def testReadFileNonExistingFile(self):
    filename = self.sstore.KeyToFilename(constants.SS_CLUSTER_NAME)

    self.assertFalse(os.path.exists(filename))
    try:
      self.sstore._ReadFile(constants.SS_CLUSTER_NAME)
    except errors.ConfigurationError as err:
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

  def testReadAllNoFiles(self):
    self.assertEqual(self.sstore.ReadAll(), {})

  def testReadAllSingleFile(self):
    utils.WriteFile(self.sstore.KeyToFilename(constants.SS_CLUSTER_NAME),
                    data="cluster.example.com")
    self.assertEqual(self.sstore.ReadAll(), {
      constants.SS_CLUSTER_NAME: "cluster.example.com",
      })

  def testWriteFiles(self):
    values = {
      constants.SS_CLUSTER_NAME: "cluster.example.com",
      constants.SS_CLUSTER_TAGS: "value\nwith\nnewlines\n",
      constants.SS_INSTANCE_LIST: "",
      }

    self.sstore.WriteFiles(values)

    self.assertEqual(sorted(os.listdir(self.ssdir)), sorted([
      "ssconf_cluster_name",
      "ssconf_cluster_tags",
      "ssconf_instance_list",
      ]))

    self.assertEqual(self._ReadSsFile(constants.SS_CLUSTER_NAME),
                     "cluster.example.com\n")
    self.assertEqual(self._ReadSsFile(constants.SS_CLUSTER_TAGS),
                     "value\nwith\nnewlines\n")
    self.assertEqual(self._ReadSsFile(constants.SS_INSTANCE_LIST), "")

  def testWriteFilesUnknownKey(self):
    values = {
      "unknown key": "value",
      }

    self.assertRaises(errors.ProgrammerError, self.sstore.WriteFiles,
                      values, dry_run=True)

    self.assertEqual(os.listdir(self.ssdir), [])

  def testWriteFilesDryRun(self):
    values = {
      constants.SS_CLUSTER_NAME: "cluster.example.com",
      }

    self.sstore.WriteFiles(values, dry_run=True)

    self.assertEqual(os.listdir(self.ssdir), [])

  def testWriteFilesNoValues(self):
    for dry_run in [False, True]:
      self.sstore.WriteFiles({}, dry_run=dry_run)

      self.assertEqual(os.listdir(self.ssdir), [])

  def testWriteFilesTooLong(self):
    values = {
      constants.SS_INSTANCE_LIST: "A" * ssconf._MAX_SIZE,
      }

    for dry_run in [False, True]:
      try:
        self.sstore.WriteFiles(values, dry_run=dry_run)
      except errors.ConfigurationError as err:
        self.assertTrue(str(err).startswith("Value 'instance_list' has"))
      else:
        self.fail("Exception was not raised")

      self.assertEqual(os.listdir(self.ssdir), [])

  def testEnabledUserShutdown(self):
    self.sstore._ReadFile = mock.Mock(return_value="True")
    result = self.sstore.GetEnabledUserShutdown()
    self.assertTrue(isinstance(result, bool))
    self.assertEqual(result, True)

    self.sstore._ReadFile = mock.Mock(return_value="False")
    result = self.sstore.GetEnabledUserShutdown()
    self.assertTrue(isinstance(result, bool))
    self.assertEqual(result, False)

  def testGetNodesVmCapable(self):
    def _ToBool(x):
      return x == "True"

    vm_capable = [("node1.example.com", "True"), ("node2.example.com", "False")]
    ssconf_file_content = '\n'.join("%s=%s" % (key, value) for (key, value)
                                    in vm_capable)
    self.sstore._ReadFile = mock.Mock(return_value=ssconf_file_content)
    result = self.sstore.GetNodesVmCapable()
    for (key, value) in vm_capable:
      self.assertTrue(isinstance(key, str))
      self.assertTrue(key in result)
      self.assertTrue(isinstance(result[key], bool))
      self.assertEqual(_ToBool(value), result[key])

  def testGetHvparamsForHypervisor(self):
    hvparams = [("a", "A"), ("b", "B"), ("c", "C")]
    ssconf_file_content = '\n'.join("%s=%s" % (key, value) for (key, value)
                                    in hvparams)
    self.sstore._ReadFile = mock.Mock(return_value=ssconf_file_content)
    result = self.sstore.GetHvparamsForHypervisor("foo")
    for (key, value) in hvparams:
      self.assertTrue(key in result)
      self.assertEqual(value, result[key])


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


class TestVerifyKeys(unittest.TestCase):
  def testNoKeys(self):
    ssconf.VerifyKeys({})

  def testValidKeys(self):
    ssconf.VerifyKeys(ssconf._VALID_KEYS)

    for key in ssconf._VALID_KEYS:
      ssconf.VerifyKeys([key])

  def testInvalidKeys(self):
    for key in ["", ".", " ", "foo", "bar", "HelloWorld"]:
      self.assertRaises(errors.GenericError, ssconf.VerifyKeys, [key])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
