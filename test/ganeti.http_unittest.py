#!/usr/bin/python
#

# Copyright (C) 2007, 2008 Google Inc.
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


"""Script for unittesting the http module"""


import os
import unittest
import time
import tempfile
from cStringIO import StringIO

from ganeti import http

import ganeti.http.server
import ganeti.http.client
import ganeti.http.auth

import testutils


class TestStartLines(unittest.TestCase):
  """Test cases for start line classes"""

  def testClientToServerStartLine(self):
    """Test client to server start line (HTTP request)"""
    start_line = http.HttpClientToServerStartLine("GET", "/", "HTTP/1.1")
    self.assertEqual(str(start_line), "GET / HTTP/1.1")

  def testServerToClientStartLine(self):
    """Test server to client start line (HTTP response)"""
    start_line = http.HttpServerToClientStartLine("HTTP/1.1", 200, "OK")
    self.assertEqual(str(start_line), "HTTP/1.1 200 OK")


class TestMisc(unittest.TestCase):
  """Miscellaneous tests"""

  def _TestDateTimeHeader(self, gmnow, expected):
    self.assertEqual(http.server._DateTimeHeader(gmnow=gmnow), expected)

  def testDateTimeHeader(self):
    """Test ganeti.http._DateTimeHeader"""
    self._TestDateTimeHeader((2008, 1, 2, 3, 4, 5, 3, 0, 0),
                             "Thu, 02 Jan 2008 03:04:05 GMT")
    self._TestDateTimeHeader((2008, 1, 1, 0, 0, 0, 0, 0, 0),
                             "Mon, 01 Jan 2008 00:00:00 GMT")
    self._TestDateTimeHeader((2008, 12, 31, 0, 0, 0, 0, 0, 0),
                             "Mon, 31 Dec 2008 00:00:00 GMT")
    self._TestDateTimeHeader((2008, 12, 31, 23, 59, 59, 0, 0, 0),
                             "Mon, 31 Dec 2008 23:59:59 GMT")
    self._TestDateTimeHeader((2008, 12, 31, 0, 0, 0, 6, 0, 0),
                             "Sun, 31 Dec 2008 00:00:00 GMT")

  def testHttpServerRequest(self):
    """Test ganeti.http.server._HttpServerRequest"""
    server_request = http.server._HttpServerRequest("GET", "/", None, None)

    # These are expected by users of the HTTP server
    self.assert_(hasattr(server_request, "request_method"))
    self.assert_(hasattr(server_request, "request_path"))
    self.assert_(hasattr(server_request, "request_headers"))
    self.assert_(hasattr(server_request, "request_body"))
    self.assert_(isinstance(server_request.resp_headers, dict))
    self.assert_(hasattr(server_request, "private"))

  def testServerSizeLimits(self):
    """Test HTTP server size limits"""
    message_reader_class = http.server._HttpClientToServerMessageReader
    self.assert_(message_reader_class.START_LINE_LENGTH_MAX > 0)
    self.assert_(message_reader_class.HEADER_LENGTH_MAX > 0)

  def testFormatAuthHeader(self):
    self.assertEqual(http.auth._FormatAuthHeader("Basic", {}),
                     "Basic")
    self.assertEqual(http.auth._FormatAuthHeader("Basic", { "foo": "bar", }),
                     "Basic foo=bar")
    self.assertEqual(http.auth._FormatAuthHeader("Basic", { "foo": "", }),
                     "Basic foo=\"\"")
    self.assertEqual(http.auth._FormatAuthHeader("Basic", { "foo": "x,y", }),
                     "Basic foo=\"x,y\"")
    params = {
      "foo": "x,y",
      "realm": "secure",
      }
    # It's a dict whose order isn't guaranteed, hence checking a list
    self.assert_(http.auth._FormatAuthHeader("Digest", params) in
                 ("Digest foo=\"x,y\" realm=secure",
                  "Digest realm=secure foo=\"x,y\""))


class _FakeRequestAuth(http.auth.HttpServerRequestAuthentication):
  def __init__(self, realm, authreq, authenticate_fn):
    http.auth.HttpServerRequestAuthentication.__init__(self)

    self.realm = realm
    self.authreq = authreq
    self.authenticate_fn = authenticate_fn

  def AuthenticationRequired(self, req):
    return self.authreq

  def GetAuthRealm(self, req):
    return self.realm

  def Authenticate(self, *args):
    if self.authenticate_fn:
      return self.authenticate_fn(*args)
    raise NotImplementedError()


class TestAuth(unittest.TestCase):
  """Authentication tests"""

  hsra = http.auth.HttpServerRequestAuthentication

  def testConstants(self):
    for scheme in [self.hsra._CLEARTEXT_SCHEME, self.hsra._HA1_SCHEME]:
      self.assertEqual(scheme, scheme.upper())
      self.assert_(scheme.startswith("{"))
      self.assert_(scheme.endswith("}"))

  def _testVerifyBasicAuthPassword(self, realm, user, password, expected):
    ra = _FakeRequestAuth(realm, False, None)

    return ra.VerifyBasicAuthPassword(None, user, password, expected)

  def testVerifyBasicAuthPassword(self):
    tvbap = self._testVerifyBasicAuthPassword

    good_pws = ["pw", "pw{", "pw}", "pw{}", "pw{x}y", "}pw",
                "0", "123", "foo...:xyz", "TeST"]

    for pw in good_pws:
      # Try cleartext passwords
      self.assert_(tvbap("abc", "user", pw, pw))
      self.assert_(tvbap("abc", "user", pw, "{cleartext}" + pw))
      self.assert_(tvbap("abc", "user", pw, "{ClearText}" + pw))
      self.assert_(tvbap("abc", "user", pw, "{CLEARTEXT}" + pw))

      # Try with invalid password
      self.failIf(tvbap("abc", "user", pw, "something"))

      # Try with invalid scheme
      self.failIf(tvbap("abc", "user", pw, "{000}" + pw))
      self.failIf(tvbap("abc", "user", pw, "{unk}" + pw))
      self.failIf(tvbap("abc", "user", pw, "{Unk}" + pw))
      self.failIf(tvbap("abc", "user", pw, "{UNK}" + pw))

    # Try with invalid scheme format
    self.failIf(tvbap("abc", "user", "pw", "{something"))

    # Hash is MD5("user:This is only a test:pw")
    self.assert_(tvbap("This is only a test", "user", "pw",
                       "{ha1}92ea58ae804481498c257b2f65561a17"))
    self.assert_(tvbap("This is only a test", "user", "pw",
                       "{HA1}92ea58ae804481498c257b2f65561a17"))

    self.failUnlessRaises(AssertionError, tvbap, None, "user", "pw",
                          "{HA1}92ea58ae804481498c257b2f65561a17")
    self.failIf(tvbap("Admin area", "user", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.failIf(tvbap("This is only a test", "someone", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.failIf(tvbap("This is only a test", "user", "something",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))


class _SimpleAuthenticator:
  def __init__(self, user, password):
    self.user = user
    self.password = password
    self.called = False

  def __call__(self, req, user, password):
    self.called = True
    return self.user == user and self.password == password


class TestHttpServerRequestAuthentication(unittest.TestCase):
  def testNoAuth(self):
    req = http.server._HttpServerRequest("GET", "/", None, None)
    _FakeRequestAuth("area1", False, None).PreHandleRequest(req)

  def testNoRealm(self):
    headers = { http.HTTP_AUTHORIZATION: "", }
    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ra = _FakeRequestAuth(None, False, None)
    self.assertRaises(AssertionError, ra.PreHandleRequest, req)

  def testNoScheme(self):
    headers = { http.HTTP_AUTHORIZATION: "", }
    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testUnknownScheme(self):
    headers = { http.HTTP_AUTHORIZATION: "NewStyleAuth abc", }
    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testInvalidBase64(self):
    headers = { http.HTTP_AUTHORIZATION: "Basic x_=_", }
    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testAuthForPublicResource(self):
    headers = {
      http.HTTP_AUTHORIZATION: "Basic %s" % ("foo".encode("base64").strip(), ),
      }
    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testAuthForPublicResource(self):
    headers = {
      http.HTTP_AUTHORIZATION:
        "Basic %s" % ("foo:bar".encode("base64").strip(), ),
      }
    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ac = _SimpleAuthenticator("foo", "bar")
    ra = _FakeRequestAuth("area1", False, ac)
    ra.PreHandleRequest(req)

    req = http.server._HttpServerRequest("GET", "/", headers, None)
    ac = _SimpleAuthenticator("something", "else")
    ra = _FakeRequestAuth("area1", False, ac)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testInvalidRequestHeader(self):
    checks = {
      http.HttpUnauthorized: ["", "\t", "-", ".", "@", "<", ">", "Digest",
                              "basic %s" % "foobar".encode("base64").strip()],
      http.HttpBadRequest: ["Basic"],
      }

    for exc, headers in checks.items():
      for i in headers:
        headers = { http.HTTP_AUTHORIZATION: i, }
        req = http.server._HttpServerRequest("GET", "/", headers, None)
        ra = _FakeRequestAuth("area1", False, None)
        self.assertRaises(exc, ra.PreHandleRequest, req)

  def testBasicAuth(self):
    for user in ["", "joe", "user name with spaces"]:
      for pw in ["", "-", ":", "foobar", "Foo Bar Baz", "@@@", "###",
                 "foo:bar:baz"]:
        for wrong_pw in [True, False]:
          basic_auth = "%s:%s" % (user, pw)
          if wrong_pw:
            basic_auth += "WRONG"
          headers = {
              http.HTTP_AUTHORIZATION:
                "Basic %s" % (basic_auth.encode("base64").strip(), ),
            }
          req = http.server._HttpServerRequest("GET", "/", headers, None)

          ac = _SimpleAuthenticator(user, pw)
          self.assertFalse(ac.called)
          ra = _FakeRequestAuth("area1", True, ac)
          if wrong_pw:
            try:
              ra.PreHandleRequest(req)
            except http.HttpUnauthorized, err:
              www_auth = err.headers[http.HTTP_WWW_AUTHENTICATE]
              self.assert_(www_auth.startswith(http.auth.HTTP_BASIC_AUTH))
            else:
              self.fail("Didn't raise HttpUnauthorized")
          else:
            ra.PreHandleRequest(req)
          self.assert_(ac.called)


class TestReadPasswordFile(unittest.TestCase):
  def testSimple(self):
    users = http.auth.ParsePasswordFile("user1 password")
    self.assertEqual(len(users), 1)
    self.assertEqual(users["user1"].password, "password")
    self.assertEqual(len(users["user1"].options), 0)

  def testOptions(self):
    buf = StringIO()
    buf.write("# Passwords\n")
    buf.write("user1 password\n")
    buf.write("\n")
    buf.write("# Comment\n")
    buf.write("user2 pw write,read\n")
    buf.write("   \t# Another comment\n")
    buf.write("invalidline\n")

    users = http.auth.ParsePasswordFile(buf.getvalue())
    self.assertEqual(len(users), 2)
    self.assertEqual(users["user1"].password, "password")
    self.assertEqual(len(users["user1"].options), 0)

    self.assertEqual(users["user2"].password, "pw")
    self.assertEqual(users["user2"].options, ["write", "read"])


class TestClientRequest(unittest.TestCase):
  def testRepr(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version",
                                       headers=[], post_data="Hello World")
    self.assert_(repr(cr).startswith("<"))

  def testNoHeaders(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version",
                                       headers=None)
    self.assert_(isinstance(cr.headers, list))
    self.assertEqual(cr.headers, [])
    self.assertEqual(cr.url, "https://localhost:1234/version")

  def testOldStyleHeaders(self):
    headers = {
      "Content-type": "text/plain",
      "Accept": "text/html",
      }
    cr = http.client.HttpClientRequest("localhost", 16481, "GET", "/vg_list",
                                       headers=headers)
    self.assert_(isinstance(cr.headers, list))
    self.assertEqual(sorted(cr.headers), [
      "Accept: text/html",
      "Content-type: text/plain",
      ])
    self.assertEqual(cr.url, "https://localhost:16481/vg_list")

  def testNewStyleHeaders(self):
    headers = [
      "Accept: text/html",
      "Content-type: text/plain; charset=ascii",
      "Server: httpd 1.0",
      ]
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version",
                                       headers=headers)
    self.assert_(isinstance(cr.headers, list))
    self.assertEqual(sorted(cr.headers), sorted(headers))
    self.assertEqual(cr.url, "https://localhost:1234/version")

  def testPostData(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version",
                                       post_data="Hello World")
    self.assertEqual(cr.post_data, "Hello World")

  def testNoPostData(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version")
    self.assertEqual(cr.post_data, "")

  def testIdentity(self):
    # These should all use different connections, hence also have a different
    # identity
    cr1 = http.client.HttpClientRequest("localhost", 1234, "GET", "/version")
    cr2 = http.client.HttpClientRequest("localhost", 9999, "GET", "/version")
    cr3 = http.client.HttpClientRequest("node1", 1234, "GET", "/version")
    cr4 = http.client.HttpClientRequest("node1", 9999, "GET", "/version")

    self.assertEqual(len(set([cr1.identity, cr2.identity,
                              cr3.identity, cr4.identity])), 4)

    # But this one should have the same
    cr1vglist = http.client.HttpClientRequest("localhost", 1234,
                                              "GET", "/vg_list")
    self.assertEqual(cr1.identity, cr1vglist.identity)


class TestClient(unittest.TestCase):
  def test(self):
    pool = http.client.HttpClientPool(None)
    self.assertFalse(pool._pool)


if __name__ == '__main__':
  testutils.GanetiTestProgram()
