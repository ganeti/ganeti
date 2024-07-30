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


"""Script for testing ganeti.vcluster"""

import os
import unittest

from ganeti import utils
from ganeti import compat
from ganeti import vcluster
from ganeti import pathutils

import testutils


_ENV_DOES_NOT_EXIST = "GANETI_TEST_DOES_NOT_EXIST"
_ENV_TEST = "GANETI_TESTVAR"


class _EnvVarTest(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    os.environ.pop(_ENV_DOES_NOT_EXIST, None)
    os.environ.pop(_ENV_TEST, None)


class TestGetRootDirectory(_EnvVarTest):
  def test(self):
    assert os.getenv(_ENV_TEST) is None

    self.assertEqual(vcluster._GetRootDirectory(_ENV_DOES_NOT_EXIST), "")
    self.assertEqual(vcluster._GetRootDirectory(_ENV_TEST), "")

    # Absolute path
    os.environ[_ENV_TEST] = "/tmp/xy11"
    self.assertEqual(vcluster._GetRootDirectory(_ENV_TEST), "/tmp/xy11")

    # Relative path
    os.environ[_ENV_TEST] = "foobar"
    self.assertRaises(RuntimeError, vcluster._GetRootDirectory, _ENV_TEST)



class TestGetHostname(_EnvVarTest):
  def test(self):
    assert os.getenv(_ENV_TEST) is None

    self.assertEqual(vcluster._GetRootDirectory(_ENV_DOES_NOT_EXIST), "")
    self.assertEqual(vcluster._GetRootDirectory(_ENV_TEST), "")

    os.environ[_ENV_TEST] = "some.host.example.com"
    self.assertEqual(vcluster._GetHostname(_ENV_TEST), "some.host.example.com")


class TestCheckHostname(_EnvVarTest):
  def test(self):
    for i in ["/", "/tmp"]:
      self.assertRaises(RuntimeError, vcluster._CheckHostname, i)


class TestPreparePaths(_EnvVarTest):
  def testInvalidParameters(self):
    self.assertRaises(RuntimeError, vcluster._PreparePaths,
                      None, "host.example.com")
    self.assertRaises(RuntimeError, vcluster._PreparePaths,
                      "/tmp/", "")

  def testNonNormalizedRootDir(self):
    self.assertRaises(AssertionError, vcluster._PreparePaths,
                      "/tmp////xyz//", "host.example.com")

  def testInvalidHostname(self):
    self.assertRaises(RuntimeError, vcluster._PreparePaths, "/tmp", "/")

  def testPathHostnameMismatch(self):
    self.assertRaises(RuntimeError, vcluster._PreparePaths,
                      "/tmp/host.example.com", "server.example.com")

  def testNoVirtCluster(self):
    for i in ["", None]:
      self.assertEqual(vcluster._PreparePaths(i, i), ("", "", None))

  def testVirtCluster(self):
    self.assertEqual(vcluster._PreparePaths("/tmp/host.example.com",
                                            "host.example.com"),
                     ("/tmp", "/tmp/host.example.com", "host.example.com"))


class TestMakeNodeRoot(unittest.TestCase):
  def test(self):
    self.assertRaises(RuntimeError, vcluster.MakeNodeRoot, "/tmp", "/")

    for i in ["/tmp", "/tmp/", "/tmp///"]:
      self.assertEqual(vcluster.MakeNodeRoot(i, "other.example.com"),
                       "/tmp/other.example.com")


class TestEnvironmentForHost(unittest.TestCase):
  def test(self):
    self.assertEqual(vcluster.EnvironmentForHost("host.example.com",
                                                 _basedir=None),
                     {})
    for i in ["host.example.com", "other.example.com"]:
      self.assertEqual(vcluster.EnvironmentForHost(i, _basedir="/tmp"), {
        vcluster._ROOTDIR_ENVNAME: "/tmp/%s" % i,
        vcluster._HOSTNAME_ENVNAME: i,
        })


class TestExchangeNodeRoot(unittest.TestCase):
  def test(self):
    result = vcluster.ExchangeNodeRoot("node1.example.com", "/tmp/file",
                                       _basedir=None, _noderoot=None)
    self.assertEqual(result, "/tmp/file")

    self.assertRaises(RuntimeError, vcluster.ExchangeNodeRoot,
                      "node1.example.com", "/tmp/node1.example.com",
                      _basedir="/tmp",
                      _noderoot="/tmp/nodeZZ.example.com")

    result = vcluster.ExchangeNodeRoot("node2.example.com",
                                       "/tmp/node1.example.com/file",
                                       _basedir="/tmp",
                                       _noderoot="/tmp/node1.example.com")
    self.assertEqual(result, "/tmp/node2.example.com/file")


class TestAddNodePrefix(unittest.TestCase):
  def testRelativePath(self):
    self.assertRaises(AssertionError, vcluster.AddNodePrefix,
                      "foobar", _noderoot=None)

  def testRelativeNodeRoot(self):
    self.assertRaises(AssertionError, vcluster.AddNodePrefix,
                      "/tmp", _noderoot="foobar")

  def test(self):
    path = vcluster.AddNodePrefix("/file/path",
                                  _noderoot="/tmp/node1.example.com/")
    self.assertEqual(path, "/tmp/node1.example.com/file/path")

    self.assertEqual(vcluster.AddNodePrefix("/file/path", _noderoot=""),
                     "/file/path")


class TestRemoveNodePrefix(unittest.TestCase):
  def testRelativePath(self):
    self.assertRaises(AssertionError, vcluster._RemoveNodePrefix,
                      "foobar", _noderoot=None)

  def testOutsideNodeRoot(self):
    self.assertRaises(RuntimeError, vcluster._RemoveNodePrefix,
                      "/file/path", _noderoot="/tmp/node1.example.com")
    self.assertRaises(RuntimeError, vcluster._RemoveNodePrefix,
                      "/tmp/xyzfile", _noderoot="/tmp/xyz")

  def test(self):
    path = vcluster._RemoveNodePrefix("/tmp/node1.example.com/file/path",
                                      _noderoot="/tmp/node1.example.com")
    self.assertEqual(path, "/file/path")

    path = vcluster._RemoveNodePrefix("/file/path", _noderoot=None)
    self.assertEqual(path, "/file/path")


class TestMakeVirtualPath(unittest.TestCase):
  def testRelativePath(self):
    self.assertRaises(AssertionError, vcluster.MakeVirtualPath,
                      "foobar", _noderoot=None)

  def testOutsideNodeRoot(self):
    self.assertRaises(RuntimeError, vcluster.MakeVirtualPath,
                      "/file/path", _noderoot="/tmp/node1.example.com")

  def testWithNodeRoot(self):
    path = vcluster.MakeVirtualPath("/tmp/node1.example.com/tmp/file",
                                    _noderoot="/tmp/node1.example.com")
    self.assertEqual(path, "%s/tmp/file" % vcluster._VIRT_PATH_PREFIX)

  def testNormal(self):
    self.assertEqual(vcluster.MakeVirtualPath("/tmp/file", _noderoot=None),
                     "/tmp/file")

  def testWhitelisted(self):
    mvp = vcluster.MakeVirtualPath
    for path in vcluster._VPATH_WHITELIST:
      self.assertEqual(mvp(path), path)
      self.assertEqual(mvp(path, _noderoot=None), path)
      self.assertEqual(mvp(path, _noderoot="/tmp"), path)


class TestLocalizeVirtualPath(unittest.TestCase):
  def testWrongPrefix(self):
    self.assertRaises(RuntimeError, vcluster.LocalizeVirtualPath,
                      "/tmp/some/path", _noderoot="/tmp/node1.example.com")

  def testCorrectPrefixRelativePath(self):
    self.assertRaises(AssertionError, vcluster.LocalizeVirtualPath,
                      vcluster._VIRT_PATH_PREFIX + "foobar",
                      _noderoot="/tmp/node1.example.com")

  def testWithNodeRoot(self):
    lvp = vcluster.LocalizeVirtualPath

    virtpath1 = "%s/tmp/file" % vcluster._VIRT_PATH_PREFIX
    virtpath2 = "%s////tmp////file" % vcluster._VIRT_PATH_PREFIX

    for i in [virtpath1, virtpath2]:
      result = lvp(i, _noderoot="/tmp/node1.example.com")
      self.assertEqual(result, "/tmp/node1.example.com/tmp/file")

  def testNormal(self):
    self.assertEqual(vcluster.LocalizeVirtualPath("/tmp/file", _noderoot=None),
                     "/tmp/file")

  def testWhitelisted(self):
    lvp = vcluster.LocalizeVirtualPath
    for path in vcluster._VPATH_WHITELIST:
      self.assertEqual(lvp(path), path)
      self.assertEqual(lvp(path, _noderoot=None), path)
      self.assertEqual(lvp(path, _noderoot="/tmp"), path)


class TestVirtualPathPrefix(unittest.TestCase):
  def test(self):
    self.assertTrue(os.path.isabs(vcluster._VIRT_PATH_PREFIX))
    self.assertEqual(os.path.normcase(vcluster._VIRT_PATH_PREFIX),
                     vcluster._VIRT_PATH_PREFIX)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
