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


"""Script for testing ganeti.server.rapi"""

import re
import unittest
import random
import mimetools
import base64
from cStringIO import StringIO

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti import serializer
from ganeti import rapi
from ganeti import http
from ganeti import objects

import ganeti.rapi.baserlib
import ganeti.rapi.testutils
import ganeti.rapi.rlib2
import ganeti.http.auth

import testutils


class TestRemoteApiHandler(unittest.TestCase):
  @staticmethod
  def _LookupWrongUser(_):
    return None

  def _Test(self, method, path, headers, reqbody,
            user_fn=NotImplemented, luxi_client=NotImplemented):
    rm = rapi.testutils._RapiMock(user_fn, luxi_client)

    (resp_code, resp_headers, resp_body) = \
      rm.FetchResponse(path, method, http.ParseHeaders(StringIO(headers)),
                       reqbody)

    self.assertTrue(resp_headers[http.HTTP_DATE])
    self.assertEqual(resp_headers[http.HTTP_CONNECTION], "close")
    self.assertEqual(resp_headers[http.HTTP_CONTENT_TYPE], http.HTTP_APP_JSON)
    self.assertEqual(resp_headers[http.HTTP_SERVER], http.HTTP_GANETI_VERSION)

    return (resp_code, resp_headers, serializer.LoadJson(resp_body))

  def testRoot(self):
    (code, _, data) = self._Test(http.HTTP_GET, "/", "", None)
    self.assertEqual(code, http.HTTP_OK)
    self.assertTrue(data is None)

  def testVersion(self):
    (code, _, data) = self._Test(http.HTTP_GET, "/version", "", None)
    self.assertEqual(code, http.HTTP_OK)
    self.assertEqual(data, constants.RAPI_VERSION)

  def testSlashTwo(self):
    (code, _, data) = self._Test(http.HTTP_GET, "/2", "", None)
    self.assertEqual(code, http.HTTP_OK)
    self.assertTrue(data is None)

  def testFeatures(self):
    (code, _, data) = self._Test(http.HTTP_GET, "/2/features", "", None)
    self.assertEqual(code, http.HTTP_OK)
    self.assertEqual(set(data), set(rapi.rlib2.ALL_FEATURES))

  def testPutInstances(self):
    (code, _, data) = self._Test(http.HTTP_PUT, "/2/instances", "", None)
    self.assertEqual(code, http.HttpNotImplemented.code)
    self.assertTrue(data["message"].startswith("Method PUT is unsupported"))

  def testPostInstancesNoAuth(self):
    (code, _, _) = self._Test(http.HTTP_POST, "/2/instances", "", None)
    self.assertEqual(code, http.HttpUnauthorized.code)

  def testRequestWithUnsupportedMediaType(self):
    for fn in [lambda s: s, lambda s: s.upper(), lambda s: s.title()]:
      headers = rapi.testutils._FormatHeaders([
        "%s: %s" % (http.HTTP_CONTENT_TYPE, fn("un/supported/media/type")),
        ])
      (code, _, data) = self._Test(http.HTTP_GET, "/", headers, "body")
      self.assertEqual(code, http.HttpUnsupportedMediaType.code)
      self.assertEqual(data["message"], "Unsupported Media Type")

  def testRequestWithInvalidJsonData(self):
    body = "_this/is/no'valid.json"
    self.assertRaises(Exception, serializer.LoadJson, body)

    headers = rapi.testutils._FormatHeaders([
      "%s: %s" % (http.HTTP_CONTENT_TYPE, http.HTTP_APP_JSON),
      ])

    (code, _, data) = self._Test(http.HTTP_GET, "/", headers, body)
    self.assertEqual(code, http.HttpBadRequest.code)
    self.assertEqual(data["message"], "Unable to parse JSON data")

  def testUnsupportedAuthScheme(self):
    headers = rapi.testutils._FormatHeaders([
      "%s: %s" % (http.HTTP_AUTHORIZATION, "Unsupported scheme"),
      ])

    (code, _, _) = self._Test(http.HTTP_POST, "/2/instances", headers, "")
    self.assertEqual(code, http.HttpUnauthorized.code)

  def testIncompleteBasicAuth(self):
    headers = rapi.testutils._FormatHeaders([
      "%s: Basic" % http.HTTP_AUTHORIZATION,
      ])

    (code, _, data) = self._Test(http.HTTP_POST, "/2/instances", headers, "")
    self.assertEqual(code, http.HttpBadRequest.code)
    self.assertEqual(data["message"],
                     "Basic authentication requires credentials")

  def testInvalidBasicAuth(self):
    for auth in ["!invalid=base!64.", base64.b64encode(" "),
                 base64.b64encode("missingcolonchar")]:
      headers = rapi.testutils._FormatHeaders([
        "%s: Basic %s" % (http.HTTP_AUTHORIZATION, auth),
        ])

      (code, _, data) = self._Test(http.HTTP_POST, "/2/instances", headers, "")
      self.assertEqual(code, http.HttpUnauthorized.code)

  @staticmethod
  def _MakeAuthHeaders(username, password, correct_password):
    if correct_password:
      pw = password
    else:
      pw = "wrongpass"

    return rapi.testutils._FormatHeaders([
      "%s: Basic %s" % (http.HTTP_AUTHORIZATION,
                        base64.b64encode("%s:%s" % (username, pw))),
      "%s: %s" % (http.HTTP_CONTENT_TYPE, http.HTTP_APP_JSON),
      ])

  def testQueryAuth(self):
    username = "admin"
    password = "2046920054"

    header_fn = compat.partial(self._MakeAuthHeaders, username, password)

    def _LookupUserNoWrite(name):
      if name == username:
        return http.auth.PasswordFileUser(name, password, [])
      else:
        return None

    for access in [rapi.RAPI_ACCESS_WRITE, rapi.RAPI_ACCESS_READ]:
      def _LookupUserWithWrite(name):
        if name == username:
          return http.auth.PasswordFileUser(name, password, [
            access,
            ])
        else:
          return None

      for qr in constants.QR_VIA_RAPI:
        # The /2/query resource has somewhat special rules for authentication as
        # it can be used to retrieve critical information
        path = "/2/query/%s" % qr

        for method in rapi.baserlib._SUPPORTED_METHODS:
          # No authorization
          (code, _, _) = self._Test(method, path, "", "")

          if method in (http.HTTP_DELETE, http.HTTP_POST):
            self.assertEqual(code, http.HttpNotImplemented.code)
            continue

          self.assertEqual(code, http.HttpUnauthorized.code)

          # Incorrect user
          (code, _, _) = self._Test(method, path, header_fn(True), "",
                                    user_fn=self._LookupWrongUser)
          self.assertEqual(code, http.HttpUnauthorized.code)

          # User has no write access, but the password is correct
          (code, _, _) = self._Test(method, path, header_fn(True), "",
                                    user_fn=_LookupUserNoWrite)
          self.assertEqual(code, http.HttpForbidden.code)

          # Wrong password and no write access
          (code, _, _) = self._Test(method, path, header_fn(False), "",
                                    user_fn=_LookupUserNoWrite)
          self.assertEqual(code, http.HttpUnauthorized.code)

          # Wrong password with write access
          (code, _, _) = self._Test(method, path, header_fn(False), "",
                                    user_fn=_LookupUserWithWrite)
          self.assertEqual(code, http.HttpUnauthorized.code)

          # Prepare request information
          if method == http.HTTP_PUT:
            reqpath = path
            body = serializer.DumpJson({
              "fields": ["name"],
              })
          elif method == http.HTTP_GET:
            reqpath = "%s?fields=name" % path
            body = ""
          else:
            self.fail("Unknown method '%s'" % method)

          # User has write access, password is correct
          (code, _, data) = self._Test(method, reqpath, header_fn(True), body,
                                       user_fn=_LookupUserWithWrite,
                                       luxi_client=_FakeLuxiClientForQuery)
          self.assertEqual(code, http.HTTP_OK)
          self.assertTrue(objects.QueryResponse.FromDict(data))

  def testConsole(self):
    path = "/2/instances/inst1.example.com/console"

    for method in rapi.baserlib._SUPPORTED_METHODS:
      # No authorization
      (code, _, _) = self._Test(method, path, "", "")

      if method == http.HTTP_GET:
        self.assertEqual(code, http.HttpUnauthorized.code)
      else:
        self.assertEqual(code, http.HttpNotImplemented.code)


class _FakeLuxiClientForQuery:
  def __init__(self, *args, **kwargs):
    pass

  def Query(self, *args):
    return objects.QueryResponse(fields=[])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
