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
    }
  return groups[group]


def _RaisingStubGetpwnam(user):
  raise KeyError("user not found")


def _RaisingStubGetgrnam(group):
  raise KeyError("group not found")


class ResolverStubRaising(object):
  def __init__(self):
    raise errors.ConfigurationError("No entries")


class TestErrors(testutils.GanetiTestCase):
  def testEverythingSuccessful(self):
    resolver = runtime.GetentResolver(_getpwnam=_StubGetpwnam,
                                      _getgrnam=_StubGetgrnam)

    self.assertEqual(resolver.masterd_uid,
                     _StubGetpwnam(constants.MASTERD_USER).pw_uid)
    self.assertEqual(resolver.masterd_gid,
                     _StubGetgrnam(constants.MASTERD_GROUP).gr_gid)
    self.assertEqual(resolver.confd_uid,
                     _StubGetpwnam(constants.CONFD_USER).pw_uid)
    self.assertEqual(resolver.confd_gid,
                     _StubGetgrnam(constants.CONFD_GROUP).gr_gid)
    self.assertEqual(resolver.rapi_uid,
                     _StubGetpwnam(constants.RAPI_USER).pw_uid)
    self.assertEqual(resolver.rapi_gid,
                     _StubGetgrnam(constants.RAPI_GROUP).gr_gid)
    self.assertEqual(resolver.noded_uid,
                     _StubGetpwnam(constants.NODED_USER).pw_uid)

    self.assertEqual(resolver.daemons_gid,
                     _StubGetgrnam(constants.DAEMONS_GROUP).gr_gid)
    self.assertEqual(resolver.admin_gid,
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
