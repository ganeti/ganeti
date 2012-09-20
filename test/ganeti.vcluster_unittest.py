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


"""Script for testing ganeti.vcluster"""

import os
import unittest

from ganeti import utils
from ganeti import compat
from ganeti import vcluster

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
    self.assertRaises(RuntimeError, vcluster._MakeNodeRoot, "/tmp", "/")

    for i in ["/tmp", "/tmp/", "/tmp///"]:
      self.assertEqual(vcluster._MakeNodeRoot(i, "other.example.com"),
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


class TestVirtualPathPrefix(unittest.TestCase):
  def test(self):
    self.assertTrue(os.path.isabs(vcluster._VIRT_PATH_PREFIX))
    self.assertEqual(os.path.normcase(vcluster._VIRT_PATH_PREFIX),
                     vcluster._VIRT_PATH_PREFIX)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
