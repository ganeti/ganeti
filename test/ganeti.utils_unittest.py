#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Script for unittesting the utils module"""

import errno
import fcntl
import glob
import os
import os.path
import re
import shutil
import signal
import socket
import stat
import tempfile
import time
import unittest
import warnings
import random
import operator

import testutils
from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import errors
from ganeti.utils import RunCmd, \
     FirstFree, \
     RunParts


class TestParseCpuMask(unittest.TestCase):
  """Test case for the ParseCpuMask function."""

  def testWellFormed(self):
    self.assertEqual(utils.ParseCpuMask(""), [])
    self.assertEqual(utils.ParseCpuMask("1"), [1])
    self.assertEqual(utils.ParseCpuMask("0-2,4,5-5"), [0,1,2,4,5])

  def testInvalidInput(self):
    for data in ["garbage", "0,", "0-1-2", "2-1", "1-a"]:
      self.assertRaises(errors.ParseError, utils.ParseCpuMask, data)


class TestGetMounts(unittest.TestCase):
  """Test case for GetMounts()."""

  TESTDATA = (
    "rootfs /     rootfs rw 0 0\n"
    "none   /sys  sysfs  rw,nosuid,nodev,noexec,relatime 0 0\n"
    "none   /proc proc   rw,nosuid,nodev,noexec,relatime 0 0\n")

  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    utils.WriteFile(self.tmpfile.name, data=self.TESTDATA)

  def testGetMounts(self):
    self.assertEqual(utils.GetMounts(filename=self.tmpfile.name),
      [
        ("rootfs", "/", "rootfs", "rw"),
        ("none", "/sys", "sysfs", "rw,nosuid,nodev,noexec,relatime"),
        ("none", "/proc", "proc", "rw,nosuid,nodev,noexec,relatime"),
      ])


class TestFirstFree(unittest.TestCase):
  """Test case for the FirstFree function"""

  def test(self):
    """Test FirstFree"""
    self.failUnlessEqual(FirstFree([0, 1, 3]), 2)
    self.failUnlessEqual(FirstFree([]), None)
    self.failUnlessEqual(FirstFree([3, 4, 6]), 0)
    self.failUnlessEqual(FirstFree([3, 4, 6], base=3), 5)
    self.failUnlessRaises(AssertionError, FirstFree, [0, 3, 4, 6], base=3)


class TestTimeFunctions(unittest.TestCase):
  """Test case for time functions"""

  def runTest(self):
    self.assertEqual(utils.SplitTime(1), (1, 0))
    self.assertEqual(utils.SplitTime(1.5), (1, 500000))
    self.assertEqual(utils.SplitTime(1218448917.4809151), (1218448917, 480915))
    self.assertEqual(utils.SplitTime(123.48012), (123, 480120))
    self.assertEqual(utils.SplitTime(123.9996), (123, 999600))
    self.assertEqual(utils.SplitTime(123.9995), (123, 999500))
    self.assertEqual(utils.SplitTime(123.9994), (123, 999400))
    self.assertEqual(utils.SplitTime(123.999999999), (123, 999999))

    self.assertRaises(AssertionError, utils.SplitTime, -1)

    self.assertEqual(utils.MergeTime((1, 0)), 1.0)
    self.assertEqual(utils.MergeTime((1, 500000)), 1.5)
    self.assertEqual(utils.MergeTime((1218448917, 500000)), 1218448917.5)

    self.assertEqual(round(utils.MergeTime((1218448917, 481000)), 3),
                     1218448917.481)
    self.assertEqual(round(utils.MergeTime((1, 801000)), 3), 1.801)

    self.assertRaises(AssertionError, utils.MergeTime, (0, -1))
    self.assertRaises(AssertionError, utils.MergeTime, (0, 1000000))
    self.assertRaises(AssertionError, utils.MergeTime, (0, 9999999))
    self.assertRaises(AssertionError, utils.MergeTime, (-1, 0))
    self.assertRaises(AssertionError, utils.MergeTime, (-9999, 0))


class FieldSetTestCase(unittest.TestCase):
  """Test case for FieldSets"""

  def testSimpleMatch(self):
    f = utils.FieldSet("a", "b", "c", "def")
    self.failUnless(f.Matches("a"))
    self.failIf(f.Matches("d"), "Substring matched")
    self.failIf(f.Matches("defghi"), "Prefix string matched")
    self.failIf(f.NonMatching(["b", "c"]))
    self.failIf(f.NonMatching(["a", "b", "c", "def"]))
    self.failUnless(f.NonMatching(["a", "d"]))

  def testRegexMatch(self):
    f = utils.FieldSet("a", "b([0-9]+)", "c")
    self.failUnless(f.Matches("b1"))
    self.failUnless(f.Matches("b99"))
    self.failIf(f.Matches("b/1"))
    self.failIf(f.NonMatching(["b12", "c"]))
    self.failUnless(f.NonMatching(["a", "1"]))

class TestForceDictType(unittest.TestCase):
  """Test case for ForceDictType"""
  KEY_TYPES = {
    "a": constants.VTYPE_INT,
    "b": constants.VTYPE_BOOL,
    "c": constants.VTYPE_STRING,
    "d": constants.VTYPE_SIZE,
    "e": constants.VTYPE_MAYBE_STRING,
    }

  def _fdt(self, dict, allowed_values=None):
    if allowed_values is None:
      utils.ForceDictType(dict, self.KEY_TYPES)
    else:
      utils.ForceDictType(dict, self.KEY_TYPES, allowed_values=allowed_values)

    return dict

  def testSimpleDict(self):
    self.assertEqual(self._fdt({}), {})
    self.assertEqual(self._fdt({'a': 1}), {'a': 1})
    self.assertEqual(self._fdt({'a': '1'}), {'a': 1})
    self.assertEqual(self._fdt({'a': 1, 'b': 1}), {'a':1, 'b': True})
    self.assertEqual(self._fdt({'b': 1, 'c': 'foo'}), {'b': True, 'c': 'foo'})
    self.assertEqual(self._fdt({'b': 1, 'c': False}), {'b': True, 'c': ''})
    self.assertEqual(self._fdt({'b': 'false'}), {'b': False})
    self.assertEqual(self._fdt({'b': 'False'}), {'b': False})
    self.assertEqual(self._fdt({'b': False}), {'b': False})
    self.assertEqual(self._fdt({'b': 'true'}), {'b': True})
    self.assertEqual(self._fdt({'b': 'True'}), {'b': True})
    self.assertEqual(self._fdt({'d': '4'}), {'d': 4})
    self.assertEqual(self._fdt({'d': '4M'}), {'d': 4})
    self.assertEqual(self._fdt({"e": None, }), {"e": None, })
    self.assertEqual(self._fdt({"e": "Hello World", }), {"e": "Hello World", })
    self.assertEqual(self._fdt({"e": False, }), {"e": '', })
    self.assertEqual(self._fdt({"b": "hello", }, ["hello"]), {"b": "hello"})

  def testErrors(self):
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'a': 'astring'})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"b": "hello"})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'c': True})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'d': 'astring'})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'d': '4 L'})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"e": object(), })
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"e": [], })
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"x": None, })
    self.assertRaises(errors.TypeEnforcementError, self._fdt, [])
    self.assertRaises(errors.ProgrammerError, utils.ForceDictType,
                      {"b": "hello"}, {"b": "no-such-type"})


class TestValidateServiceName(unittest.TestCase):
  def testValid(self):
    testnames = [
      0, 1, 2, 3, 1024, 65000, 65534, 65535,
      "ganeti",
      "gnt-masterd",
      "HELLO_WORLD_SVC",
      "hello.world.1",
      "0", "80", "1111", "65535",
      ]

    for name in testnames:
      self.assertEqual(utils.ValidateServiceName(name), name)

  def testInvalid(self):
    testnames = [
      -15756, -1, 65536, 133428083,
      "", "Hello World!", "!", "'", "\"", "\t", "\n", "`",
      "-8546", "-1", "65536",
      (129 * "A"),
      ]

    for name in testnames:
      self.assertRaises(errors.OpPrereqError, utils.ValidateServiceName, name)


class TestReadLockedPidFile(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExistent(self):
    path = utils.PathJoin(self.tmpdir, "nonexist")
    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testUnlocked(self):
    path = utils.PathJoin(self.tmpdir, "pid")
    utils.WriteFile(path, data="123")
    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testLocked(self):
    path = utils.PathJoin(self.tmpdir, "pid")
    utils.WriteFile(path, data="123")

    fl = utils.FileLock.Open(path)
    try:
      fl.Exclusive(blocking=True)

      self.assertEqual(utils.ReadLockedPidFile(path), 123)
    finally:
      fl.Close()

    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testError(self):
    path = utils.PathJoin(self.tmpdir, "foobar", "pid")
    utils.WriteFile(utils.PathJoin(self.tmpdir, "foobar"), data="")
    # open(2) should return ENOTDIR
    self.assertRaises(EnvironmentError, utils.ReadLockedPidFile, path)


class TestFindMatch(unittest.TestCase):
  def test(self):
    data = {
      "aaaa": "Four A",
      "bb": {"Two B": True},
      re.compile(r"^x(foo|bar|bazX)([0-9]+)$"): (1, 2, 3),
      }

    self.assertEqual(utils.FindMatch(data, "aaaa"), ("Four A", []))
    self.assertEqual(utils.FindMatch(data, "bb"), ({"Two B": True}, []))

    for i in ["foo", "bar", "bazX"]:
      for j in range(1, 100, 7):
        self.assertEqual(utils.FindMatch(data, "x%s%s" % (i, j)),
                         ((1, 2, 3), [i, str(j)]))

  def testNoMatch(self):
    self.assert_(utils.FindMatch({}, "") is None)
    self.assert_(utils.FindMatch({}, "foo") is None)
    self.assert_(utils.FindMatch({}, 1234) is None)

    data = {
      "X": "Hello World",
      re.compile("^(something)$"): "Hello World",
      }

    self.assert_(utils.FindMatch(data, "") is None)
    self.assert_(utils.FindMatch(data, "Hello World") is None)


class TestTryConvert(unittest.TestCase):
  def test(self):
    for src, fn, result in [
      ("1", int, 1),
      ("a", int, "a"),
      ("", bool, False),
      ("a", bool, True),
      ]:
      self.assertEqual(utils.TryConvert(fn, src), result)


if __name__ == '__main__':
  testutils.GanetiTestProgram()
