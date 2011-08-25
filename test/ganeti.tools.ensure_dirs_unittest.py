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


def _MockStatResult(cb, mode, uid, gid):
  def _fn(path):
    if cb:
      cb()
    return {
      stat.ST_MODE: mode,
      stat.ST_UID: uid,
      stat.ST_GID: gid,
      }
  return _fn


def _RaiseNoEntError():
  raise EnvironmentError(errno.ENOENT, "not found")


def _OtherStatRaise():
  raise EnvironmentError()


class TestEnsureDirsFunctions(unittest.TestCase):
  UID_A = 16024
  UID_B = 25850
  GID_A = 14028
  GID_B = 29801

  def setUp(self):
    self._chown_calls = []
    self._chmod_calls = []
    self._mkdir_calls = []

  def tearDown(self):
    self.assertRaises(IndexError, self._mkdir_calls.pop)
    self.assertRaises(IndexError, self._chmod_calls.pop)
    self.assertRaises(IndexError, self._chown_calls.pop)

  def _FakeMkdir(self, path):
    self._mkdir_calls.append(path)

  def _FakeChown(self, path, uid, gid):
    self._chown_calls.append((path, uid, gid))

  def _ChmodWrapper(self, cb):
    def _fn(path, mode):
      self._chmod_calls.append((path, mode))
      if cb:
        cb()
    return _fn

  def _VerifyEnsure(self, path, mode, uid=-1, gid=-1):
    self.assertEqual(path, "/ganeti-qa-non-test")
    self.assertEqual(mode, 0700)
    self.assertEqual(uid, self.UID_A)
    self.assertEqual(gid, self.GID_A)

  def testEnsureDir(self):
    is_dir_stat = _MockStatResult(None, stat.S_IFDIR, 0, 0)
    ensure_dirs.EnsureDir("/ganeti-qa-non-test", 0700, self.UID_A, self.GID_A,
                          _lstat_fn=is_dir_stat, _ensure_fn=self._VerifyEnsure)

  def testEnsureDirErrors(self):
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsureDir,
                      "/ganeti-qa-non-test", 0700, 0, 0,
                      _lstat_fn=_MockStatResult(None, 0, 0, 0))
    self.assertRaises(IndexError, self._mkdir_calls.pop)

    other_stat_raise = _MockStatResult(_OtherStatRaise, stat.S_IFDIR, 0, 0)
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsureDir,
                      "/ganeti-qa-non-test", 0700, 0, 0,
                      _lstat_fn=other_stat_raise)
    self.assertRaises(IndexError, self._mkdir_calls.pop)

    non_exist_stat = _MockStatResult(_RaiseNoEntError, stat.S_IFDIR, 0, 0)
    ensure_dirs.EnsureDir("/ganeti-qa-non-test", 0700, self.UID_A, self.GID_A,
                          _lstat_fn=non_exist_stat, _mkdir_fn=self._FakeMkdir,
                          _ensure_fn=self._VerifyEnsure)
    self.assertEqual(self._mkdir_calls.pop(0), "/ganeti-qa-non-test")

  def testEnsurePermissionNoEnt(self):
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsurePermission,
                      "/ganeti-qa-non-test", 0600,
                      _chmod_fn=NotImplemented, _chown_fn=NotImplemented,
                      _stat_fn=_MockStatResult(_RaiseNoEntError, 0, 0, 0))

  def testEnsurePermissionNoEntMustNotExist(self):
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0600, must_exist=False,
                                 _chmod_fn=NotImplemented,
                                 _chown_fn=NotImplemented,
                                 _stat_fn=_MockStatResult(_RaiseNoEntError,
                                                          0, 0, 0))

  def testEnsurePermissionOtherErrorMustNotExist(self):
    self.assertRaises(ensure_dirs.EnsureError, ensure_dirs.EnsurePermission,
                      "/ganeti-qa-non-test", 0600, must_exist=False,
                      _chmod_fn=NotImplemented, _chown_fn=NotImplemented,
                      _stat_fn=_MockStatResult(_OtherStatRaise, 0, 0, 0))

  def testEnsurePermissionNoChanges(self):
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0600,
                                 _stat_fn=_MockStatResult(None, 0600, 0, 0),
                                 _chmod_fn=self._ChmodWrapper(None),
                                 _chown_fn=self._FakeChown)

  def testEnsurePermissionChangeMode(self):
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0444,
                                 _stat_fn=_MockStatResult(None, 0600, 0, 0),
                                 _chmod_fn=self._ChmodWrapper(None),
                                 _chown_fn=self._FakeChown)
    self.assertEqual(self._chmod_calls.pop(0), ("/ganeti-qa-non-test", 0444))

  def testEnsurePermissionSetUidGid(self):
    ensure_dirs.EnsurePermission("/ganeti-qa-non-test", 0600,
                                 uid=self.UID_B, gid=self.GID_B,
                                 _stat_fn=_MockStatResult(None, 0600,
                                                          self.UID_A,
                                                          self.GID_A),
                                 _chmod_fn=self._ChmodWrapper(None),
                                 _chown_fn=self._FakeChown)
    self.assertEqual(self._chown_calls.pop(0),
                     ("/ganeti-qa-non-test", self.UID_B, self.GID_B))

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
