#!/usr/bin/python
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


"""Script for testing ganeti.tools.node_daemon_setup"""

import unittest

from ganeti import errors
from ganeti import constants
from ganeti.tools import node_daemon_setup

import testutils


_SetupError = node_daemon_setup.SetupError


class TestVerifySsconf(unittest.TestCase):
  def testNoSsconf(self):
    self.assertRaises(_SetupError, node_daemon_setup.VerifySsconf,
                      {}, NotImplemented, _verify_fn=NotImplemented)

    for items in [None, {}]:
      self.assertRaises(_SetupError, node_daemon_setup.VerifySsconf, {
        constants.NDS_SSCONF: items,
        }, NotImplemented, _verify_fn=NotImplemented)

  def _Check(self, names):
    self.assertEqual(frozenset(names), frozenset([
      constants.SS_CLUSTER_NAME,
      constants.SS_INSTANCE_LIST,
      ]))

  def testSuccess(self):
    ssdata = {
      constants.SS_CLUSTER_NAME: "cluster.example.com",
      constants.SS_INSTANCE_LIST: [],
      }

    result = node_daemon_setup.VerifySsconf({
      constants.NDS_SSCONF: ssdata,
      }, "cluster.example.com", _verify_fn=self._Check)

    self.assertEqual(result, ssdata)

    self.assertRaises(_SetupError, node_daemon_setup.VerifySsconf, {
      constants.NDS_SSCONF: ssdata,
      }, "wrong.example.com", _verify_fn=self._Check)

  def testInvalidKey(self):
    self.assertRaises(errors.GenericError, node_daemon_setup.VerifySsconf, {
      constants.NDS_SSCONF: {
        "no-valid-ssconf-key": "value",
        },
      }, NotImplemented)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
