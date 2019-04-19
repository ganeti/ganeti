#!/usr/bin/python3
#

# Copyright (C) 2007, 2008 Google Inc.
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


"""Script for unittesting the http module"""


import os
import unittest
import time
import tempfile
import pycurl
import itertools
import threading
from io import StringIO

from ganeti import http
from ganeti import compat

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
    server_request = \
        http.server._HttpServerRequest("GET", "/", None, None, None)

    # These are expected by users of the HTTP server
    self.assertTrue(hasattr(server_request, "request_method"))
    self.assertTrue(hasattr(server_request, "request_path"))
    self.assertTrue(hasattr(server_request, "request_headers"))
    self.assertTrue(hasattr(server_request, "request_body"))
    self.assertTrue(isinstance(server_request.resp_headers, dict))
    self.assertTrue(hasattr(server_request, "private"))

  def testServerSizeLimits(self):
    """Test HTTP server size limits"""
    message_reader_class = http.server._HttpClientToServerMessageReader
    self.assertTrue(message_reader_class.START_LINE_LENGTH_MAX > 0)
    self.assertTrue(message_reader_class.HEADER_LENGTH_MAX > 0)

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
    self.assertTrue(http.auth._FormatAuthHeader("Digest", params) in
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
      self.assertTrue(scheme.startswith("{"))
      self.assertTrue(scheme.endswith("}"))

  def _testVerifyBasicAuthPassword(self, realm, user, password, expected):
    ra = _FakeRequestAuth(realm, False, None)

    return ra.VerifyBasicAuthPassword(None, user, password, expected)

  def testVerifyBasicAuthPassword(self):
    tvbap = self._testVerifyBasicAuthPassword

    good_pws = ["pw", "pw{", "pw}", "pw{}", "pw{x}y", "}pw",
                "0", "123", "foo...:xyz", "TeST"]

    for pw in good_pws:
      # Try cleartext passwords
      self.assertTrue(tvbap("abc", "user", pw, pw))
      self.assertTrue(tvbap("abc", "user", pw, "{cleartext}" + pw))
      self.assertTrue(tvbap("abc", "user", pw, "{ClearText}" + pw))
      self.assertTrue(tvbap("abc", "user", pw, "{CLEARTEXT}" + pw))

      # Try with invalid password
      self.assertFalse(tvbap("abc", "user", pw, "something"))

      # Try with invalid scheme
      self.assertFalse(tvbap("abc", "user", pw, "{000}" + pw))
      self.assertFalse(tvbap("abc", "user", pw, "{unk}" + pw))
      self.assertFalse(tvbap("abc", "user", pw, "{Unk}" + pw))
      self.assertFalse(tvbap("abc", "user", pw, "{UNK}" + pw))

    # Try with invalid scheme format
    self.assertFalse(tvbap("abc", "user", "pw", "{something"))

    # Hash is MD5("user:This is only a test:pw")
    self.assertTrue(tvbap("This is only a test", "user", "pw",
                       "{ha1}92ea58ae804481498c257b2f65561a17"))
    self.assertTrue(tvbap("This is only a test", "user", "pw",
                       "{HA1}92ea58ae804481498c257b2f65561a17"))

    self.assertRaises(AssertionError, tvbap, None, "user", "pw",
                          "{HA1}92ea58ae804481498c257b2f65561a17")
    self.assertFalse(tvbap("Admin area", "user", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.assertFalse(tvbap("This is only a test", "someone", "pw",
                      "{HA1}92ea58ae804481498c257b2f65561a17"))
    self.assertFalse(tvbap("This is only a test", "user", "something",
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
    req = http.server._HttpServerRequest("GET", "/", None, None, None)
    _FakeRequestAuth("area1", False, None).PreHandleRequest(req)

  def testNoRealm(self):
    headers = { http.HTTP_AUTHORIZATION: "", }
    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
    ra = _FakeRequestAuth(None, False, None)
    self.assertRaises(AssertionError, ra.PreHandleRequest, req)

  def testNoScheme(self):
    headers = { http.HTTP_AUTHORIZATION: "", }
    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testUnknownScheme(self):
    headers = { http.HTTP_AUTHORIZATION: "NewStyleAuth abc", }
    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testInvalidBase64(self):
    headers = { http.HTTP_AUTHORIZATION: "Basic x_=_", }
    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testAuthForPublicResource(self):
    headers = {
      http.HTTP_AUTHORIZATION: "Basic %s" % ("foo".encode("base64").strip(), ),
      }
    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
    ra = _FakeRequestAuth("area1", False, None)
    self.assertRaises(http.HttpUnauthorized, ra.PreHandleRequest, req)

  def testAuthForPublicResource(self):
    headers = {
      http.HTTP_AUTHORIZATION:
        "Basic %s" % ("foo:bar".encode("base64").strip(), ),
      }
    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
    ac = _SimpleAuthenticator("foo", "bar")
    ra = _FakeRequestAuth("area1", False, ac)
    ra.PreHandleRequest(req)

    req = http.server._HttpServerRequest("GET", "/", headers, None, None)
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
        req = http.server._HttpServerRequest("GET", "/", headers, None, None)
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
          req = http.server._HttpServerRequest("GET", "/", headers, None, None)

          ac = _SimpleAuthenticator(user, pw)
          self.assertFalse(ac.called)
          ra = _FakeRequestAuth("area1", True, ac)
          if wrong_pw:
            try:
              ra.PreHandleRequest(req)
            except http.HttpUnauthorized as err:
              www_auth = err.headers[http.HTTP_WWW_AUTHENTICATE]
              self.assertTrue(www_auth.startswith(http.auth.HTTP_BASIC_AUTH))
            else:
              self.fail("Didn't raise HttpUnauthorized")
          else:
            ra.PreHandleRequest(req)
          self.assertTrue(ac.called)


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
    self.assertTrue(repr(cr).startswith("<"))

  def testNoHeaders(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version",
                                       headers=None)
    self.assertTrue(isinstance(cr.headers, list))
    self.assertEqual(cr.headers, [])
    self.assertEqual(cr.url, "https://localhost:1234/version")

  def testPlainAddressIPv4(self):
    cr = http.client.HttpClientRequest("192.0.2.9", 19956, "GET", "/version")
    self.assertEqual(cr.url, "https://192.0.2.9:19956/version")

  def testPlainAddressIPv6(self):
    cr = http.client.HttpClientRequest("2001:db8::cafe", 15110, "GET", "/info")
    self.assertEqual(cr.url, "https://[2001:db8::cafe]:15110/info")

  def testOldStyleHeaders(self):
    headers = {
      "Content-type": "text/plain",
      "Accept": "text/html",
      }
    cr = http.client.HttpClientRequest("localhost", 16481, "GET", "/vg_list",
                                       headers=headers)
    self.assertTrue(isinstance(cr.headers, list))
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
    self.assertTrue(isinstance(cr.headers, list))
    self.assertEqual(sorted(cr.headers), sorted(headers))
    self.assertEqual(cr.url, "https://localhost:1234/version")

  def testPostData(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version",
                                       post_data="Hello World")
    self.assertEqual(cr.post_data, "Hello World")

  def testNoPostData(self):
    cr = http.client.HttpClientRequest("localhost", 1234, "GET", "/version")
    self.assertEqual(cr.post_data, "")

  def testCompletionCallback(self):
    for argname in ["completion_cb", "curl_config_fn"]:
      kwargs = {
        argname: NotImplementedError,
        }
      cr = http.client.HttpClientRequest("localhost", 14038, "GET", "/version",
                                         **kwargs)
      self.assertEqual(getattr(cr, argname), NotImplementedError)

      for fn in [NotImplemented, {}, 1]:
        kwargs = {
          argname: fn,
          }
        self.assertRaises(AssertionError, http.client.HttpClientRequest,
                          "localhost", 23150, "GET", "/version", **kwargs)


class _FakeCurl:
  def __init__(self):
    self.opts = {}
    self.info = NotImplemented

  def setopt(self, opt, value):
    assert opt not in self.opts, "Option set more than once"
    self.opts[opt] = value

  def getinfo(self, info):
    return self.info.pop(info)


class TestClientStartRequest(unittest.TestCase):
  @staticmethod
  def _TestCurlConfig(curl):
    curl.setopt(pycurl.SSLKEYTYPE, "PEM")

  def test(self):
    for method in [http.HTTP_GET, http.HTTP_PUT, "CUSTOM"]:
      for port in [8761, 29796, 19528]:
        for curl_config_fn in [None, self._TestCurlConfig]:
          for read_timeout in [None, 0, 1, 123, 36000]:
            self._TestInner(method, port, curl_config_fn, read_timeout)

  def _TestInner(self, method, port, curl_config_fn, read_timeout):
    for response_code in [http.HTTP_OK, http.HttpNotFound.code,
                          http.HTTP_NOT_MODIFIED]:
      for response_body in [None, "Hello World",
                            "Very Long\tContent here\n" * 171]:
        for errmsg in [None, "error"]:
          req = http.client.HttpClientRequest("localhost", port, method,
                                              "/version",
                                              curl_config_fn=curl_config_fn,
                                              read_timeout=read_timeout)
          curl = _FakeCurl()
          pending = http.client._StartRequest(curl, req)
          self.assertEqual(pending.GetCurlHandle(), curl)
          self.assertEqual(pending.GetCurrentRequest(), req)

          # Check options
          opts = curl.opts
          self.assertEqual(opts.pop(pycurl.CUSTOMREQUEST), method)
          self.assertEqual(opts.pop(pycurl.URL),
                           "https://localhost:%s/version" % port)
          if read_timeout is None:
            self.assertEqual(opts.pop(pycurl.TIMEOUT), 0)
          else:
            self.assertEqual(opts.pop(pycurl.TIMEOUT), read_timeout)
          self.assertFalse(opts.pop(pycurl.VERBOSE))
          self.assertTrue(opts.pop(pycurl.NOSIGNAL))
          self.assertEqual(opts.pop(pycurl.USERAGENT),
                           http.HTTP_GANETI_VERSION)
          self.assertEqual(opts.pop(pycurl.PROXY), "")
          self.assertFalse(opts.pop(pycurl.POSTFIELDS))
          self.assertFalse(opts.pop(pycurl.HTTPHEADER))
          write_fn = opts.pop(pycurl.WRITEFUNCTION)
          self.assertTrue(callable(write_fn))
          if hasattr(pycurl, "SSL_SESSIONID_CACHE"):
            self.assertFalse(opts.pop(pycurl.SSL_SESSIONID_CACHE))
          if curl_config_fn:
            self.assertEqual(opts.pop(pycurl.SSLKEYTYPE), "PEM")
          else:
            self.assertFalse(pycurl.SSLKEYTYPE in opts)
          self.assertFalse(opts)

          if response_body is not None:
            offset = 0
            while offset < len(response_body):
              piece = response_body[offset:offset + 10]
              write_fn(piece)
              offset += len(piece)

          curl.info = {
            pycurl.RESPONSE_CODE: response_code,
          }
          if hasattr(pycurl, 'LOCAL_IP'):
            curl.info[pycurl.LOCAL_IP] = '127.0.0.1'
          if hasattr(pycurl, 'LOCAL_PORT'):
            curl.info[pycurl.LOCAL_PORT] = port

          # Finalize request
          pending.Done(errmsg)

          self.assertFalse(curl.info)

          # Can only finalize once
          self.assertRaises(AssertionError, pending.Done, True)

          if errmsg:
            self.assertFalse(req.success)
          else:
            self.assertTrue(req.success)
          self.assertEqual(req.error, errmsg)
          self.assertEqual(req.resp_status_code, response_code)
          if response_body is None:
            self.assertEqual(req.resp_body, "")
          else:
            self.assertEqual(req.resp_body, response_body)

          # Check if resetting worked
          assert not hasattr(curl, "reset")
          opts = curl.opts
          self.assertFalse(opts.pop(pycurl.POSTFIELDS))
          self.assertTrue(callable(opts.pop(pycurl.WRITEFUNCTION)))
          self.assertFalse(opts)

          self.assertFalse(curl.opts,
                           msg="Previous checks did not consume all options")
          assert id(opts) == id(curl.opts)

  def _TestWrongTypes(self, *args, **kwargs):
    req = http.client.HttpClientRequest(*args, **kwargs)
    self.assertRaises(AssertionError, http.client._StartRequest,
                      _FakeCurl(), req)

  def testWrongHostType(self):
    self._TestWrongTypes(unicode("localhost"), 8080, "GET", "/version")

  def testWrongUrlType(self):
    self._TestWrongTypes("localhost", 8080, "GET", unicode("/version"))

  def testWrongMethodType(self):
    self._TestWrongTypes("localhost", 8080, unicode("GET"), "/version")

  def testWrongHeaderType(self):
    self._TestWrongTypes("localhost", 8080, "GET", "/version",
                         headers={
                           unicode("foo"): "bar",
                           })

  def testWrongPostDataType(self):
    self._TestWrongTypes("localhost", 8080, "GET", "/version",
                         post_data=unicode("verylongdata" * 100))


class _EmptyCurlMulti:
  def perform(self):
    return (pycurl.E_MULTI_OK, 0)

  def info_read(self):
    return (0, [], [])


class TestClientProcessRequests(unittest.TestCase):
  def testEmpty(self):
    requests = []
    http.client.ProcessRequests(requests, _curl=NotImplemented,
                                _curl_multi=_EmptyCurlMulti)
    self.assertEqual(requests, [])


class TestProcessCurlRequests(unittest.TestCase):
  class _FakeCurlMulti:
    def __init__(self):
      self.handles = []
      self.will_fail = []
      self._expect = ["perform"]
      self._counter = itertools.count()

    def add_handle(self, curl):
      assert curl not in self.handles
      self.handles.append(curl)
      if next(self._counter) % 3 == 0:
        self.will_fail.append(curl)

    def remove_handle(self, curl):
      self.handles.remove(curl)

    def perform(self):
      assert self._expect.pop(0) == "perform"

      if next(self._counter) % 2 == 0:
        self._expect.append("perform")
        return (pycurl.E_CALL_MULTI_PERFORM, None)

      self._expect.append("info_read")

      return (pycurl.E_MULTI_OK, len(self.handles))

    def info_read(self):
      assert self._expect.pop(0) == "info_read"
      successful = []
      failed = []
      if self.handles:
        if next(self._counter) % 17 == 0:
          curl = self.handles[0]
          if curl in self.will_fail:
            failed.append((curl, -1, "test error"))
          else:
            successful.append(curl)
        remaining_messages = len(self.handles) % 3
        if remaining_messages > 0:
          self._expect.append("info_read")
        else:
          self._expect.append("select")
      else:
        remaining_messages = 0
        self._expect.append("select")
      return (remaining_messages, successful, failed)

    def select(self, timeout):
      # Never compare floats for equality
      assert timeout >= 0.95 and timeout <= 1.05
      assert self._expect.pop(0) == "select"
      self._expect.append("perform")

  def test(self):
    requests = [_FakeCurl() for _ in range(10)]
    multi = self._FakeCurlMulti()
    for (curl, errmsg) in http.client._ProcessCurlRequests(multi, requests):
      self.assertTrue(curl not in multi.handles)
      if curl in multi.will_fail:
        self.assertTrue("test error" in errmsg)
      else:
        self.assertTrue(errmsg is None)
    self.assertFalse(multi.handles)
    self.assertEqual(multi._expect, ["select"])


class TestProcessRequests(unittest.TestCase):
  class _DummyCurlMulti:
    pass

  def testNoMonitor(self):
    self._Test(False)

  def testWithMonitor(self):
    self._Test(True)

  class _MonitorChecker:
    def __init__(self):
      self._monitor = None

    def GetMonitor(self):
      return self._monitor

    def __call__(self, monitor):
      assert callable(monitor.GetLockInfo)
      self._monitor = monitor

  def _Test(self, use_monitor):
    def cfg_fn(port, curl):
      curl.opts["__port__"] = port

    def _LockCheckReset(monitor, req):
      self.assertTrue(monitor._lock.is_owned(shared=0),
                      msg="Lock must be owned in exclusive mode")
      assert not hasattr(req, "lockcheck__")
      setattr(req, "lockcheck__", True)

    def _BuildNiceName(port, default=None):
      if port % 5 == 0:
        return "nicename%s" % port
      else:
        # Use standard name
        return default

    requests = \
      [http.client.HttpClientRequest("localhost", i, "POST", "/version%s" % i,
                                     curl_config_fn=compat.partial(cfg_fn, i),
                                     completion_cb=NotImplementedError,
                                     nicename=_BuildNiceName(i))
       for i in range(15176, 15501)]
    requests_count = len(requests)

    if use_monitor:
      lock_monitor_cb = self._MonitorChecker()
    else:
      lock_monitor_cb = None

    def _ProcessRequests(multi, handles):
      self.assertTrue(isinstance(multi, self._DummyCurlMulti))
      self.assertEqual(len(requests), len(handles))
      self.assertTrue(compat.all(isinstance(curl, _FakeCurl)
                                 for curl in handles))

      # Prepare for lock check
      for req in requests:
        assert req.completion_cb is NotImplementedError
        if use_monitor:
          req.completion_cb = \
            compat.partial(_LockCheckReset, lock_monitor_cb.GetMonitor())

      for idx, curl in enumerate(handles):
        try:
          port = curl.opts["__port__"]
        except KeyError:
          self.fail("Per-request config function was not called")

        if use_monitor:
          # Check if lock information is correct
          lock_info = lock_monitor_cb.GetMonitor().GetLockInfo(None)
          expected = \
            [("rpc/%s" % (_BuildNiceName(handle.opts["__port__"],
                                         default=("localhost/version%s" %
                                                  handle.opts["__port__"]))),
              None,
              [threading.currentThread().getName()], None)
             for handle in handles[idx:]]
          self.assertEqual(sorted(lock_info), sorted(expected))

        if port % 3 == 0:
          response_code = http.HTTP_OK
          msg = None
        else:
          response_code = http.HttpNotFound.code
          msg = "test error"

        curl.info = {
          pycurl.RESPONSE_CODE: response_code,
        }
        if hasattr(pycurl, 'LOCAL_IP'):
          curl.info[pycurl.LOCAL_IP] = '127.0.0.1'
        if hasattr(pycurl, 'LOCAL_PORT'):
          curl.info[pycurl.LOCAL_PORT] = port

        # Prepare for reset
        self.assertFalse(curl.opts.pop(pycurl.POSTFIELDS))
        self.assertTrue(callable(curl.opts.pop(pycurl.WRITEFUNCTION)))

        yield (curl, msg)

      if use_monitor:
        self.assertTrue(compat.all(req.lockcheck__ for req in requests))

    if use_monitor:
      self.assertEqual(lock_monitor_cb.GetMonitor(), None)

    http.client.ProcessRequests(requests, lock_monitor_cb=lock_monitor_cb,
                                _curl=_FakeCurl,
                                _curl_multi=self._DummyCurlMulti,
                                _curl_process=_ProcessRequests)
    for req in requests:
      if req.port % 3 == 0:
        self.assertTrue(req.success)
        self.assertEqual(req.error, None)
      else:
        self.assertFalse(req.success)
        self.assertTrue("test error" in req.error)

    # See if monitor was disabled
    if use_monitor:
      monitor = lock_monitor_cb.GetMonitor()
      self.assertEqual(monitor._pending_fn, None)
      self.assertEqual(monitor.GetLockInfo(None), [])
    else:
      self.assertEqual(lock_monitor_cb, None)

    self.assertEqual(len(requests), requests_count)

  def testBadRequest(self):
    bad_request = http.client.HttpClientRequest("localhost", 27784,
                                                "POST", "/version")
    bad_request.success = False

    self.assertRaises(AssertionError, http.client.ProcessRequests,
                      [bad_request], _curl=NotImplemented,
                      _curl_multi=NotImplemented, _curl_process=NotImplemented)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
