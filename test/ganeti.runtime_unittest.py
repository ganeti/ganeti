#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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

"""Script for testing ganeti.runtime"""

from ganeti import constants
from ganeti import errors
from ganeti import runtime

import testutils
import unittest


class _EntStub:
  def __init__(self, uid=None, gid=None):
    self.pw_uid = uid
    self.gr_gid = gid


def _StubGetpwnam(user):
  users = {
    constants.MASTERD_USER: _EntStub(uid=0),
    constants.CONFD_USER: _EntStub(uid=1),
    constants.RAPI_USER: _EntStub(uid=2),
    constants.NODED_USER: _EntStub(uid=3),
    }
  return users[user]


def _StubGetgrnam(group):
  groups = {
    constants.MASTERD_GROUP: _EntStub(gid=0),
    constants.CONFD_GROUP: _EntStub(gid=1),
    constants.RAPI_GROUP: _EntStub(gid=2),
    constants.DAEMONS_GROUP: _EntStub(gid=3),
    constants.ADMIN_GROUP: _EntStub(gid=4),
    constants.NODED_GROUP: _EntStub(gid=5),
    }
  return groups[group]


def _RaisingStubGetpwnam(user):
  raise KeyError("user not found")


def _RaisingStubGetgrnam(group):
  raise KeyError("group not found")


class ResolverStubRaising(object):
  def __init__(self):
    raise errors.ConfigurationError("No entries")


class TestErrors(unittest.TestCase):
  def setUp(self):
    self.resolver = runtime.GetentResolver(_getpwnam=_StubGetpwnam,
                                           _getgrnam=_StubGetgrnam)

  def testEverythingSuccessful(self):
    self.assertEqual(self.resolver.masterd_uid,
                     _StubGetpwnam(constants.MASTERD_USER).pw_uid)
    self.assertEqual(self.resolver.masterd_gid,
                     _StubGetgrnam(constants.MASTERD_GROUP).gr_gid)
    self.assertEqual(self.resolver.confd_uid,
                     _StubGetpwnam(constants.CONFD_USER).pw_uid)
    self.assertEqual(self.resolver.confd_gid,
                     _StubGetgrnam(constants.CONFD_GROUP).gr_gid)
    self.assertEqual(self.resolver.rapi_uid,
                     _StubGetpwnam(constants.RAPI_USER).pw_uid)
    self.assertEqual(self.resolver.rapi_gid,
                     _StubGetgrnam(constants.RAPI_GROUP).gr_gid)
    self.assertEqual(self.resolver.noded_uid,
                     _StubGetpwnam(constants.NODED_USER).pw_uid)

    self.assertEqual(self.resolver.daemons_gid,
                     _StubGetgrnam(constants.DAEMONS_GROUP).gr_gid)
    self.assertEqual(self.resolver.admin_gid,
                     _StubGetgrnam(constants.ADMIN_GROUP).gr_gid)

  def testUserNotFound(self):
    self.assertRaises(errors.ConfigurationError, runtime.GetentResolver,
                      _getpwnam=_RaisingStubGetpwnam, _getgrnam=_StubGetgrnam)

  def testGroupNotFound(self):
    self.assertRaises(errors.ConfigurationError, runtime.GetentResolver,
                      _getpwnam=_StubGetpwnam, _getgrnam=_RaisingStubGetgrnam)

  def testUserNotFoundGetEnts(self):
    self.assertRaises(errors.ConfigurationError, runtime.GetEnts,
                      resolver=ResolverStubRaising)

  def testLookupForUser(self):
    master_stub = _StubGetpwnam(constants.MASTERD_USER)
    rapi_stub = _StubGetpwnam(constants.RAPI_USER)
    self.assertEqual(self.resolver.LookupUid(master_stub.pw_uid),
                     constants.MASTERD_USER)
    self.assertEqual(self.resolver.LookupUid(rapi_stub.pw_uid),
                     constants.RAPI_USER)
    self.assertEqual(self.resolver.LookupUser(constants.MASTERD_USER),
                     master_stub.pw_uid)
    self.assertEqual(self.resolver.LookupUser(constants.RAPI_USER),
                     rapi_stub.pw_uid)

  def testLookupForGroup(self):
    master_stub = _StubGetgrnam(constants.MASTERD_GROUP)
    rapi_stub = _StubGetgrnam(constants.RAPI_GROUP)
    self.assertEqual(self.resolver.LookupGid(master_stub.gr_gid),
                     constants.MASTERD_GROUP)
    self.assertEqual(self.resolver.LookupGid(rapi_stub.gr_gid),
                     constants.RAPI_GROUP)

  def testLookupForUserNotFound(self):
    self.assertRaises(errors.ConfigurationError, self.resolver.LookupUid, 9999)
    self.assertRaises(errors.ConfigurationError,
                      self.resolver.LookupUser, "does-not-exist-foo")

  def testLookupForGroupNotFound(self):
    self.assertRaises(errors.ConfigurationError, self.resolver.LookupGid, 9999)
    self.assertRaises(errors.ConfigurationError,
                      self.resolver.LookupGroup, "does-not-exist-foo")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
