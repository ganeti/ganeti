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


"""Script for testing ganeti.tools.ensure_dirs"""

import errno
import stat
import unittest
import os.path

from ganeti.tools import ensure_dirs

import testutils


class TestEnsureDirsFunctions(unittest.TestCase):
  def _NoopMkdir(self, _):
    self.mkdir_called = True

  @staticmethod
  def _MockStatResult(mode, pre_fn=lambda: 0):
    def _fn(path):
      pre_fn()
      return {stat.ST_MODE: mode}
    return _fn

  def _VerifyEnsure(self, path, mode, uid=-1, gid=-1):
    self.assertEqual(path, "/ganeti-qa-non-test")
    self.assertEqual(mode, 0700)
    self.assertEqual(uid, 0)
    self.assertEqual(gid, 0)

  @staticmethod
  def _RaiseNoEntError():
    noent_error = EnvironmentError()
    noent_error.errno = errno.ENOENT
    raise noent_error

  @staticmethod
  def _OtherStatRaise():
    raise EnvironmentError()

  def _ChmodWrapper(self, pre_fn=lambda: 0):
    def _fn(path, mode):
      self.chmod_called = True
      pre_fn()
    return _fn

  def _NoopChown(self, path, uid, gid):
    self.chown_called = True

  def testEnsureDir(self):
    is_dir_stat = self._MockStatResult(stat.S_IFDIR)
    not_dir_stat = self._MockStatResult(0)
    non_exist_stat = self._MockStatResult(stat.S_IFDIR,
                                          pre_fn=self._RaiseNoEntError)
    other_stat_raise = self._MockStatResult(stat.S_IFDIR,
                                            pre_fn=self._OtherStatRaise)

    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsureDir,
                      "/ganeti-qa-non-test", 0700, 0, 0,
                      _stat_fn=not_dir_stat)
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsureDir,
                      "/ganeti-qa-non-test", 0700, 0, 0,
                      _stat_fn=other_stat_raise)
    self.mkdir_called = False
    ensure_dirs.EnsureDir("/ganeti-qa-non-test", 0700, 0, 0,
                          _stat_fn=non_exist_stat, _mkdir_fn=self._NoopMkdir,
                          _ensure_fn=self._VerifyEnsure)
    self.assertTrue(self.mkdir_called)
    self.mkdir_called = False
    ensure_dirs.EnsureDir("/ganeti-qa-non-test", 0700, 0, 0,
                          _stat_fn=is_dir_stat, _ensure_fn=self._VerifyEnsure)
    self.assertFalse(self.mkdir_called)

  def testEnsurePermission(self):
    noent_chmod_fn = self._ChmodWrapper(pre_fn=self._RaiseNoEntError)
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsurePermission,
                      "/ganeti-qa-non-test", 0600,
                      _chmod_fn=noent_chmod_fn)
    self.chmod_called = False
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0600, must_exist=False,
                                 _chmod_fn=noent_chmod_fn)
    self.assertTrue(self.chmod_called)
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsurePermission,
                      "/ganeti-qa-non-test", 0600, must_exist=False,
                      _chmod_fn=self._ChmodWrapper(pre_fn=self._OtherStatRaise))
    self.chmod_called = False
    self.chown_called = False
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0600,
                                 _chmod_fn=self._ChmodWrapper(),
                                 _chown_fn=self._NoopChown)
    self.assertTrue(self.chmod_called)
    self.assertFalse(self.chown_called)
    self.chmod_called = False
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0600, uid=1, gid=1,
                                 _chmod_fn=self._ChmodWrapper(),
                                 _chown_fn=self._NoopChown)
    self.assertTrue(self.chmod_called)
    self.assertTrue(self.chown_called)

  def testPaths(self):
    paths = [(path[0], path[1]) for path in ensure_dirs.GetPaths()]

    seen = []
    last_dirname = ""
    for path, pathtype in paths:
      self.assertTrue(pathtype in ensure_dirs.ALL_TYPES)
      dirname = os.path.dirname(path)
      if dirname != last_dirname or pathtype == ensure_dirs.DIR:
        if pathtype == ensure_dirs.FILE:
          self.assertFalse(dirname in seen,
                           msg="path %s; dirname %s seen in %s" % (path,
                                                                   dirname,
                                                                   seen))
          last_dirname = dirname
          seen.append(dirname)
        elif pathtype == ensure_dirs.DIR:
          self.assertFalse(path in seen)
          last_dirname = path
          seen.append(path)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
