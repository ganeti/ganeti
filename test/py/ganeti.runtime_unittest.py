#!/usr/bin/python3
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

"""Script for testing ganeti.runtime"""

from ganeti import constants
from ganeti import errors
from ganeti import runtime
from ganeti import ht

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
    constants.LUXID_USER: _EntStub(uid=4),
    constants.WCONFD_USER: _EntStub(uid=5),
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
    constants.LUXID_GROUP: _EntStub(gid=6),
    constants.WCONFD_GROUP: _EntStub(gid=7),
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
    self.assertEqual(self.resolver.wconfd_uid,
                     _StubGetpwnam(constants.WCONFD_USER).pw_uid)
    self.assertEqual(self.resolver.wconfd_gid,
                     _StubGetgrnam(constants.WCONFD_GROUP).gr_gid)
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


class TestArchInfo(unittest.TestCase):
  EXP_TYPES = \
    ht.TAnd(ht.TIsLength(2),
            ht.TItems([
              ht.TNonEmptyString,
              ht.TNonEmptyString,
              ]))

  def setUp(self):
    self.assertTrue(runtime._arch is None)

  def tearDown(self):
    runtime._arch = None

  def testNotInitialized(self):
    self.assertRaises(errors.ProgrammerError, runtime.GetArchInfo)

  def testInitializeMultiple(self):
    runtime.InitArchInfo()

    self.assertRaises(errors.ProgrammerError, runtime.InitArchInfo)

  def testNormal(self):
    runtime.InitArchInfo()

    info = runtime.GetArchInfo()

    self.assertTrue(self.EXP_TYPES(info),
                    msg=("Doesn't match expected type description: %s" %
                         self.EXP_TYPES))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
