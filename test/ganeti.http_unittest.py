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
    fake_request = http.HttpMessage()
    fake_request.start_line = \
      http.HttpClientToServerStartLine("GET", "/", "HTTP/1.1")
    server_request = http.server._HttpServerRequest(fake_request)

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

  def testClientSizeLimits(self):
    """Test HTTP client size limits"""
    message_reader_class = http.client._HttpServerToClientMessageReader
    self.assert_(message_reader_class.START_LINE_LENGTH_MAX > 0)
    self.assert_(message_reader_class.HEADER_LENGTH_MAX > 0)


class _FakeRequestAuth(http.auth.HttpServerRequestAuthentication):
  def __init__(self, realm):
    http.auth.HttpServerRequestAuthentication.__init__(self)

    self.realm = realm

  def GetAuthRealm(self, req):
    return self.realm


class TestAuth(unittest.TestCase):
  """Authentication tests"""

  hsra = http.auth.HttpServerRequestAuthentication

  def testConstants(self):
    self.assertEqual(self.hsra._CLEARTEXT_SCHEME,
                     self.hsra._CLEARTEXT_SCHEME.upper())
    self.assertEqual(self.hsra._HA1_SCHEME,
                     self.hsra._HA1_SCHEME.upper())

  def _testVerifyBasicAuthPassword(self, realm, user, password, expected):
    ra = _FakeRequestAuth(realm)

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

    self.failIf(tvbap(None, "user", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.failIf(tvbap("Admin area", "user", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.failIf(tvbap("This is only a test", "someone", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.failIf(tvbap("This is only a test", "user", "something",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))


if __name__ == '__main__':
  testutils.GanetiTestProgram()
