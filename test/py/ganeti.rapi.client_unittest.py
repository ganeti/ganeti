#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Script for unittesting the RAPI client module"""


import unittest
import warnings
import pycurl

from ganeti import opcodes
from ganeti import constants
from ganeti import http
from ganeti import serializer
from ganeti import utils
from ganeti import query
from ganeti import objects
from ganeti import rapi
from ganeti import errors

import ganeti.rapi.testutils
from ganeti.rapi import connector
from ganeti.rapi import rlib2
from ganeti.rapi import client

import testutils


# List of resource handlers which aren't used by the RAPI client
_KNOWN_UNUSED = set([
  rlib2.R_root,
  rlib2.R_2,
  ])

# Global variable for collecting used handlers
_used_handlers = None


class RapiMock(object):
  def __init__(self):
    self._mapper = connector.Mapper()
    self._responses = []
    self._last_handler = None
    self._last_req_data = None

  def ResetResponses(self):
    del self._responses[:]

  def AddResponse(self, response, code=200):
    self._responses.insert(0, (code, response))

  def CountPending(self):
    return len(self._responses)

  def GetLastHandler(self):
    return self._last_handler

  def GetLastRequestData(self):
    return self._last_req_data

  def FetchResponse(self, path, method, headers, request_body):
    self._last_req_data = request_body

    try:
      (handler_cls, items, args) = self._mapper.getController(path)

      # Record handler as used
      _used_handlers.add(handler_cls)

      self._last_handler = handler_cls(items, args, None)
      if not hasattr(self._last_handler, method.upper()):
        raise http.HttpNotImplemented(message="Method not implemented")

    except http.HttpException as ex:
      code = ex.code
      response = ex.message
    else:
      if not self._responses:
        raise Exception("No responses")

      (code, response) = self._responses.pop()

    return (code, NotImplemented, response)


class TestConstants(unittest.TestCase):
  def test(self):
    self.assertEqual(client.GANETI_RAPI_PORT, constants.DEFAULT_RAPI_PORT)
    self.assertEqual(client.GANETI_RAPI_VERSION, constants.RAPI_VERSION)
    self.assertEqual(client.HTTP_APP_JSON, http.HTTP_APP_JSON)
    self.assertEqual(client._REQ_DATA_VERSION_FIELD, rlib2._REQ_DATA_VERSION)
    self.assertEqual(client.JOB_STATUS_QUEUED, constants.JOB_STATUS_QUEUED)
    self.assertEqual(client.JOB_STATUS_WAITING, constants.JOB_STATUS_WAITING)
    self.assertEqual(client.JOB_STATUS_CANCELING,
                     constants.JOB_STATUS_CANCELING)
    self.assertEqual(client.JOB_STATUS_RUNNING, constants.JOB_STATUS_RUNNING)
    self.assertEqual(client.JOB_STATUS_CANCELED, constants.JOB_STATUS_CANCELED)
    self.assertEqual(client.JOB_STATUS_SUCCESS, constants.JOB_STATUS_SUCCESS)
    self.assertEqual(client.JOB_STATUS_ERROR, constants.JOB_STATUS_ERROR)
    self.assertEqual(client.JOB_STATUS_PENDING, constants.JOBS_PENDING)
    self.assertEqual(client.JOB_STATUS_FINALIZED, constants.JOBS_FINALIZED)
    self.assertEqual(client.JOB_STATUS_ALL, constants.JOB_STATUS_ALL)

    # Node evacuation
    self.assertEqual(client.NODE_EVAC_PRI, constants.NODE_EVAC_PRI)
    self.assertEqual(client.NODE_EVAC_SEC, constants.NODE_EVAC_SEC)
    self.assertEqual(client.NODE_EVAC_ALL, constants.NODE_EVAC_ALL)

    # Legacy name
    self.assertEqual(client.JOB_STATUS_WAITLOCK, constants.JOB_STATUS_WAITING)

    # RAPI feature strings
    self.assertEqual(client._INST_CREATE_REQV1, rlib2._INST_CREATE_REQV1)
    self.assertEqual(client.INST_CREATE_REQV1, rlib2._INST_CREATE_REQV1)
    self.assertEqual(client._INST_REINSTALL_REQV1, rlib2._INST_REINSTALL_REQV1)
    self.assertEqual(client.INST_REINSTALL_REQV1, rlib2._INST_REINSTALL_REQV1)
    self.assertEqual(client._NODE_MIGRATE_REQV1, rlib2._NODE_MIGRATE_REQV1)
    self.assertEqual(client.NODE_MIGRATE_REQV1, rlib2._NODE_MIGRATE_REQV1)
    self.assertEqual(client._NODE_EVAC_RES1, rlib2._NODE_EVAC_RES1)
    self.assertEqual(client.NODE_EVAC_RES1, rlib2._NODE_EVAC_RES1)

    # Error codes
    self.assertEqual(client.ECODE_RESOLVER, errors.ECODE_RESOLVER)
    self.assertEqual(client.ECODE_NORES, errors.ECODE_NORES)
    self.assertEqual(client.ECODE_TEMP_NORES, errors.ECODE_TEMP_NORES)
    self.assertEqual(client.ECODE_INVAL, errors.ECODE_INVAL)
    self.assertEqual(client.ECODE_STATE, errors.ECODE_STATE)
    self.assertEqual(client.ECODE_NOENT, errors.ECODE_NOENT)
    self.assertEqual(client.ECODE_EXISTS, errors.ECODE_EXISTS)
    self.assertEqual(client.ECODE_NOTUNIQUE, errors.ECODE_NOTUNIQUE)
    self.assertEqual(client.ECODE_FAULT, errors.ECODE_FAULT)
    self.assertEqual(client.ECODE_ENVIRON, errors.ECODE_ENVIRON)

  def testErrors(self):
    self.assertEqual(client.ECODE_ALL, errors.ECODE_ALL)

    # Make sure all error codes are in both RAPI client and errors module
    for name in [s for s in dir(client) if (s.startswith("ECODE_") and s != "ECODE_ALL")]:
      value = getattr(client, name)
      self.assertEqual(value, getattr(errors, name))
      self.assertTrue(value in client.ECODE_ALL)
      self.assertTrue(value in errors.ECODE_ALL)


class RapiMockTest(unittest.TestCase):
  def test404(self):
    (code, _, body) = RapiMock().FetchResponse("/foo", "GET", None, None)
    self.assertEqual(code, 404)
    self.assertTrue(body is None)

  def test501(self):
    (code, _, body) = RapiMock().FetchResponse("/version", "POST", None, None)
    self.assertEqual(code, 501)
    self.assertEqual(body, "Method not implemented")

  def test200(self):
    rapi = RapiMock()
    rapi.AddResponse("2")
    (code, _, response) = rapi.FetchResponse("/version", "GET", None, None)
    self.assertEqual(200, code)
    self.assertEqual("2", response)
    self.assertTrue(isinstance(rapi.GetLastHandler(), rlib2.R_version))


def _FakeNoSslPycurlVersion():
  # Note: incomplete version tuple
  return (3, "7.16.0", 462848, "mysystem", 1581, None, 0)


def _FakeFancySslPycurlVersion():
  # Note: incomplete version tuple
  return (3, "7.16.0", 462848, "mysystem", 1581, "FancySSL/1.2.3", 0)


def _FakeOpenSslPycurlVersion():
  # Note: incomplete version tuple
  return (2, "7.15.5", 462597, "othersystem", 668, "OpenSSL/0.9.8c", 0)


def _FakeGnuTlsPycurlVersion():
  # Note: incomplete version tuple
  return (3, "7.18.0", 463360, "somesystem", 1581, "GnuTLS/2.0.4", 0)


class TestExtendedConfig(unittest.TestCase):
  def testAuth(self):
    cl = client.GanetiRapiClient("master.example.com",
      username="user", password="pw",
      curl_factory=lambda: rapi.testutils.FakeCurl(RapiMock()))

    curl = cl._CreateCurl()
    self.assertEqual(curl.getopt(pycurl.HTTPAUTH), pycurl.HTTPAUTH_BASIC)
    self.assertEqual(curl.getopt(pycurl.USERPWD), "user:pw")

  def testInvalidAuth(self):
    # No username
    self.assertRaises(client.Error, client.GanetiRapiClient,
                      "master-a.example.com", password="pw")
    # No password
    self.assertRaises(client.Error, client.GanetiRapiClient,
                      "master-b.example.com", username="user")

  def testCertVerifyInvalidCombinations(self):
    self.assertRaises(client.Error, client.GenericCurlConfig,
                      use_curl_cabundle=True, cafile="cert1.pem")
    self.assertRaises(client.Error, client.GenericCurlConfig,
                      use_curl_cabundle=True, capath="certs/")
    self.assertRaises(client.Error, client.GenericCurlConfig,
                      use_curl_cabundle=True,
                      cafile="cert1.pem", capath="certs/")

  def testProxySignalVerifyHostname(self):
    for use_gnutls in [False, True]:
      if use_gnutls:
        pcverfn = _FakeGnuTlsPycurlVersion
      else:
        pcverfn = _FakeOpenSslPycurlVersion

      for proxy in ["", "http://127.0.0.1:1234"]:
        for use_signal in [False, True]:
          for verify_hostname in [False, True]:
            cfgfn = client.GenericCurlConfig(proxy=proxy, use_signal=use_signal,
                                             verify_hostname=verify_hostname,
                                             _pycurl_version_fn=pcverfn)

            curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
            cl = client.GanetiRapiClient("master.example.com",
                                         curl_config_fn=cfgfn,
                                         curl_factory=curl_factory)

            curl = cl._CreateCurl()
            self.assertEqual(curl.getopt(pycurl.PROXY), proxy)
            self.assertEqual(curl.getopt(pycurl.NOSIGNAL), not use_signal)

            if verify_hostname:
              self.assertEqual(curl.getopt(pycurl.SSL_VERIFYHOST), 2)
            else:
              self.assertEqual(curl.getopt(pycurl.SSL_VERIFYHOST), 0)

  def testNoCertVerify(self):
    cfgfn = client.GenericCurlConfig()

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    curl = cl._CreateCurl()
    self.assertFalse(curl.getopt(pycurl.SSL_VERIFYPEER))
    self.assertFalse(curl.getopt(pycurl.CAINFO))
    self.assertFalse(curl.getopt(pycurl.CAPATH))

  def testCertVerifyCurlBundle(self):
    cfgfn = client.GenericCurlConfig(use_curl_cabundle=True)

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    curl = cl._CreateCurl()
    self.assertTrue(curl.getopt(pycurl.SSL_VERIFYPEER))
    self.assertFalse(curl.getopt(pycurl.CAINFO))
    self.assertFalse(curl.getopt(pycurl.CAPATH))

  def testCertVerifyCafile(self):
    mycert = "/tmp/some/UNUSED/cert/file.pem"
    cfgfn = client.GenericCurlConfig(cafile=mycert)

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    curl = cl._CreateCurl()
    self.assertTrue(curl.getopt(pycurl.SSL_VERIFYPEER))
    self.assertEqual(curl.getopt(pycurl.CAINFO), mycert)
    self.assertFalse(curl.getopt(pycurl.CAPATH))

  def testCertVerifyCapath(self):
    certdir = "/tmp/some/UNUSED/cert/directory"
    pcverfn = _FakeOpenSslPycurlVersion
    cfgfn = client.GenericCurlConfig(capath=certdir,
                                     _pycurl_version_fn=pcverfn)

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    curl = cl._CreateCurl()
    self.assertTrue(curl.getopt(pycurl.SSL_VERIFYPEER))
    self.assertEqual(curl.getopt(pycurl.CAPATH), certdir)
    self.assertFalse(curl.getopt(pycurl.CAINFO))

  def testCertVerifyCapathGnuTls(self):
    certdir = "/tmp/some/UNUSED/cert/directory"
    pcverfn = _FakeGnuTlsPycurlVersion
    cfgfn = client.GenericCurlConfig(capath=certdir,
                                     _pycurl_version_fn=pcverfn)

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    self.assertRaises(client.Error, cl._CreateCurl)

  def testCertVerifyNoSsl(self):
    certdir = "/tmp/some/UNUSED/cert/directory"
    pcverfn = _FakeNoSslPycurlVersion
    cfgfn = client.GenericCurlConfig(capath=certdir,
                                     _pycurl_version_fn=pcverfn)

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    self.assertRaises(client.Error, cl._CreateCurl)

  def testCertVerifyFancySsl(self):
    certdir = "/tmp/some/UNUSED/cert/directory"
    pcverfn = _FakeFancySslPycurlVersion
    cfgfn = client.GenericCurlConfig(capath=certdir,
                                     _pycurl_version_fn=pcverfn)

    curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
    cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                 curl_factory=curl_factory)

    self.assertRaises(NotImplementedError, cl._CreateCurl)

  def testCertVerifyCapath(self):
    for connect_timeout in [None, 1, 5, 10, 30, 60, 300]:
      for timeout in [None, 1, 30, 60, 3600, 24 * 3600]:
        cfgfn = client.GenericCurlConfig(connect_timeout=connect_timeout,
                                         timeout=timeout)

        curl_factory = lambda: rapi.testutils.FakeCurl(RapiMock())
        cl = client.GanetiRapiClient("master.example.com", curl_config_fn=cfgfn,
                                     curl_factory=curl_factory)

        curl = cl._CreateCurl()
        self.assertEqual(curl.getopt(pycurl.CONNECTTIMEOUT), connect_timeout)
        self.assertEqual(curl.getopt(pycurl.TIMEOUT), timeout)


class GanetiRapiClientTests(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.rapi = RapiMock()
    self.curl = rapi.testutils.FakeCurl(self.rapi)
    self.client = client.GanetiRapiClient("master.example.com",
                                          curl_factory=lambda: self.curl)

  def assertHandler(self, handler_cls):
    self.assertTrue(isinstance(self.rapi.GetLastHandler(), handler_cls))

  def assertQuery(self, key, value):
    self.assertEqual(value, self.rapi.GetLastHandler().queryargs.get(key, None))

  def assertItems(self, items):
    self.assertEqual(items, self.rapi.GetLastHandler().items)

  def assertBulk(self):
    self.assertTrue(self.rapi.GetLastHandler().useBulk())

  def assertDryRun(self):
    self.assertTrue(self.rapi.GetLastHandler().dryRun())

  def assertUseForce(self):
    self.assertTrue(self.rapi.GetLastHandler().useForce())

  def testEncodeQuery(self):
    query = [
      ("a", None),
      ("b", 1),
      ("c", 2),
      ("d", "Foo"),
      ("e", True),
      ]

    expected = [
      ("a", ""),
      ("b", 1),
      ("c", 2),
      ("d", "Foo"),
      ("e", 1),
      ]

    self.assertEqualValues(self.client._EncodeQuery(query),
                           expected)

    # invalid types
    for i in [[1, 2, 3], {"moo": "boo"}, (1, 2, 3)]:
      self.assertRaises(ValueError, self.client._EncodeQuery, [("x", i)])

  def testCurlSettings(self):
    self.rapi.AddResponse("2")
    self.assertEqual(2, self.client.GetVersion())
    self.assertHandler(rlib2.R_version)

    # Signals should be disabled by default
    self.assertTrue(self.curl.getopt(pycurl.NOSIGNAL))

    # No auth and no proxy
    self.assertFalse(self.curl.getopt(pycurl.USERPWD))
    self.assertTrue(self.curl.getopt(pycurl.PROXY) is None)

    # Content-type is required for requests
    headers = self.curl.getopt(pycurl.HTTPHEADER)
    self.assertTrue("Content-type: application/json" in headers)

  def testHttpError(self):
    self.rapi.AddResponse(None, code=404)
    try:
      self.client.GetJobStatus(15140)
    except client.GanetiApiError as err:
      self.assertEqual(err.code, 404)
    else:
      self.fail("Didn't raise exception")

  def testGetVersion(self):
    self.rapi.AddResponse("2")
    self.assertEqual(2, self.client.GetVersion())
    self.assertHandler(rlib2.R_version)

  def testGetFeatures(self):
    for features in [[], ["foo", "bar", "baz"]]:
      self.rapi.AddResponse(serializer.DumpJson(features))
      self.assertEqual(features, self.client.GetFeatures())
      self.assertHandler(rlib2.R_2_features)

  def testGetFeaturesNotFound(self):
    self.rapi.AddResponse(None, code=404)
    self.assertEqual([], self.client.GetFeatures())

  def testGetOperatingSystems(self):
    self.rapi.AddResponse("[\"beos\"]")
    self.assertEqual(["beos"], self.client.GetOperatingSystems())
    self.assertHandler(rlib2.R_2_os)

  def testGetClusterTags(self):
    self.rapi.AddResponse("[\"tag\"]")
    self.assertEqual(["tag"], self.client.GetClusterTags())
    self.assertHandler(rlib2.R_2_tags)

  def testAddClusterTags(self):
    self.rapi.AddResponse("1234")
    self.assertEqual(1234,
        self.client.AddClusterTags(["awesome"], dry_run=True))
    self.assertHandler(rlib2.R_2_tags)
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testDeleteClusterTags(self):
    self.rapi.AddResponse("5107")
    self.assertEqual(5107, self.client.DeleteClusterTags(["awesome"],
                                                         dry_run=True))
    self.assertHandler(rlib2.R_2_tags)
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testGetInfo(self):
    self.rapi.AddResponse("{}")
    self.assertEqual({}, self.client.GetInfo())
    self.assertHandler(rlib2.R_2_info)

  def testGetInstances(self):
    self.rapi.AddResponse("[]")
    self.assertEqual([], self.client.GetInstances(bulk=True))
    self.assertHandler(rlib2.R_2_instances)
    self.assertBulk()

  def testGetInstance(self):
    self.rapi.AddResponse("[]")
    self.assertEqual([], self.client.GetInstance("instance"))
    self.assertHandler(rlib2.R_2_instances_name)
    self.assertItems(["instance"])

  def testGetInstanceInfo(self):
    self.rapi.AddResponse("21291")
    self.assertEqual(21291, self.client.GetInstanceInfo("inst3"))
    self.assertHandler(rlib2.R_2_instances_name_info)
    self.assertItems(["inst3"])
    self.assertQuery("static", None)

    self.rapi.AddResponse("3428")
    self.assertEqual(3428, self.client.GetInstanceInfo("inst31", static=False))
    self.assertHandler(rlib2.R_2_instances_name_info)
    self.assertItems(["inst31"])
    self.assertQuery("static", ["0"])

    self.rapi.AddResponse("15665")
    self.assertEqual(15665, self.client.GetInstanceInfo("inst32", static=True))
    self.assertHandler(rlib2.R_2_instances_name_info)
    self.assertItems(["inst32"])
    self.assertQuery("static", ["1"])

  def testInstancesMultiAlloc(self):
    response = {
      constants.JOB_IDS_KEY: ["23423"],
      constants.ALLOCATABLE_KEY: ["foobar"],
      constants.FAILED_KEY: ["foobar2"],
      }
    self.rapi.AddResponse(serializer.DumpJson(response))
    insts = [self.client.InstanceAllocation("create", "foobar",
                                            "plain", [], []),
             self.client.InstanceAllocation("create", "foobar2",
                                            "drbd8", [{"size": 100}], [])]
    resp = self.client.InstancesMultiAlloc(insts)
    self.assertEqual(resp, response)
    self.assertHandler(rlib2.R_2_instances_multi_alloc)

  def testCreateInstanceOldVersion(self):
    # The old request format, version 0, is no longer supported
    self.rapi.AddResponse(None, code=404)
    self.assertRaises(client.GanetiApiError, self.client.CreateInstance,
                      "create", "inst1.example.com", "plain", [], [])
    self.assertEqual(self.rapi.CountPending(), 0)

  def testCreateInstance(self):
    self.rapi.AddResponse(serializer.DumpJson([rlib2._INST_CREATE_REQV1]))
    self.rapi.AddResponse("23030")
    job_id = self.client.CreateInstance("create", "inst1.example.com",
                                        "plain", [], [], dry_run=True)
    self.assertEqual(job_id, 23030)
    self.assertHandler(rlib2.R_2_instances)
    self.assertDryRun()

    data = serializer.LoadJson(self.rapi.GetLastRequestData())

    for field in ["dry_run", "beparams", "hvparams", "start"]:
      self.assertFalse(field in data)

    self.assertEqual(data["name"], "inst1.example.com")
    self.assertEqual(data["disk_template"], "plain")

  def testCreateInstance2(self):
    self.rapi.AddResponse(serializer.DumpJson([rlib2._INST_CREATE_REQV1]))
    self.rapi.AddResponse("24740")
    job_id = self.client.CreateInstance("import", "inst2.example.com",
                                        "drbd8", [{"size": 100,}],
                                        [{}, {"bridge": "br1", }],
                                        dry_run=False, start=True,
                                        pnode="node1", snode="node9",
                                        ip_check=False)
    self.assertEqual(job_id, 24740)
    self.assertHandler(rlib2.R_2_instances)

    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertEqual(data[rlib2._REQ_DATA_VERSION], 1)
    self.assertEqual(data["name"], "inst2.example.com")
    self.assertEqual(data["disk_template"], "drbd8")
    self.assertEqual(data["start"], True)
    self.assertEqual(data["ip_check"], False)
    self.assertEqualValues(data["disks"], [{"size": 100,}])
    self.assertEqualValues(data["nics"], [{}, {"bridge": "br1", }])

  def testDeleteInstance(self):
    self.rapi.AddResponse("1234")
    self.assertEqual(1234, self.client.DeleteInstance("instance", dry_run=True))
    self.assertHandler(rlib2.R_2_instances_name)
    self.assertItems(["instance"])
    self.assertDryRun()

  def testGetInstanceTags(self):
    self.rapi.AddResponse("[]")
    self.assertEqual([], self.client.GetInstanceTags("fooinstance"))
    self.assertHandler(rlib2.R_2_instances_name_tags)
    self.assertItems(["fooinstance"])

  def testAddInstanceTags(self):
    self.rapi.AddResponse("1234")
    self.assertEqual(1234,
        self.client.AddInstanceTags("fooinstance", ["awesome"], dry_run=True))
    self.assertHandler(rlib2.R_2_instances_name_tags)
    self.assertItems(["fooinstance"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testDeleteInstanceTags(self):
    self.rapi.AddResponse("25826")
    self.assertEqual(25826, self.client.DeleteInstanceTags("foo", ["awesome"],
                                                           dry_run=True))
    self.assertHandler(rlib2.R_2_instances_name_tags)
    self.assertItems(["foo"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testRebootInstance(self):
    self.rapi.AddResponse("6146")
    job_id = self.client.RebootInstance("i-bar", reboot_type="hard",
                                        ignore_secondaries=True, dry_run=True,
                                        reason="Updates")
    self.assertEqual(6146, job_id)
    self.assertHandler(rlib2.R_2_instances_name_reboot)
    self.assertItems(["i-bar"])
    self.assertDryRun()
    self.assertQuery("type", ["hard"])
    self.assertQuery("ignore_secondaries", ["1"])
    self.assertQuery("reason", ["Updates"])

  def testRebootInstanceDefaultReason(self):
    self.rapi.AddResponse("6146")
    job_id = self.client.RebootInstance("i-bar", reboot_type="hard",
                                        ignore_secondaries=True, dry_run=True)
    self.assertEqual(6146, job_id)
    self.assertHandler(rlib2.R_2_instances_name_reboot)
    self.assertItems(["i-bar"])
    self.assertDryRun()
    self.assertQuery("type", ["hard"])
    self.assertQuery("ignore_secondaries", ["1"])
    self.assertQuery("reason", None)

  def testShutdownInstance(self):
    self.rapi.AddResponse("1487")
    self.assertEqual(1487, self.client.ShutdownInstance("foo-instance",
                                                        dry_run=True,
                                                        reason="NoMore"))
    self.assertHandler(rlib2.R_2_instances_name_shutdown)
    self.assertItems(["foo-instance"])
    self.assertDryRun()
    self.assertQuery("reason", ["NoMore"])

  def testShutdownInstanceDefaultReason(self):
    self.rapi.AddResponse("1487")
    self.assertEqual(1487, self.client.ShutdownInstance("foo-instance",
                                                        dry_run=True))
    self.assertHandler(rlib2.R_2_instances_name_shutdown)
    self.assertItems(["foo-instance"])
    self.assertDryRun()
    self.assertQuery("reason", None)

  def testStartupInstance(self):
    self.rapi.AddResponse("27149")
    self.assertEqual(27149, self.client.StartupInstance("bar-instance",
                                                        dry_run=True,
                                                        reason="New"))
    self.assertHandler(rlib2.R_2_instances_name_startup)
    self.assertItems(["bar-instance"])
    self.assertDryRun()
    self.assertQuery("reason", ["New"])

  def testStartupInstanceDefaultReason(self):
    self.rapi.AddResponse("27149")
    self.assertEqual(27149, self.client.StartupInstance("bar-instance",
                                                        dry_run=True))
    self.assertHandler(rlib2.R_2_instances_name_startup)
    self.assertItems(["bar-instance"])
    self.assertDryRun()
    self.assertQuery("reason", None)

  def testReinstallInstance(self):
    self.rapi.AddResponse(serializer.DumpJson([]))
    self.rapi.AddResponse("19119")
    self.assertEqual(19119, self.client.ReinstallInstance("baz-instance",
                                                          os="DOS",
                                                          no_startup=True))
    self.assertHandler(rlib2.R_2_instances_name_reinstall)
    self.assertItems(["baz-instance"])
    self.assertQuery("os", ["DOS"])
    self.assertQuery("nostartup", ["1"])
    self.assertEqual(self.rapi.CountPending(), 0)

  def testReinstallInstanceNew(self):
    self.rapi.AddResponse(serializer.DumpJson([rlib2._INST_REINSTALL_REQV1]))
    self.rapi.AddResponse("25689")
    self.assertEqual(25689, self.client.ReinstallInstance("moo-instance",
                                                          os="Debian",
                                                          no_startup=True))
    self.assertHandler(rlib2.R_2_instances_name_reinstall)
    self.assertItems(["moo-instance"])
    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertEqual(len(data), 2)
    self.assertEqual(data["os"], "Debian")
    self.assertEqual(data["start"], False)
    self.assertEqual(self.rapi.CountPending(), 0)

  def testReinstallInstanceWithOsparams1(self):
    self.rapi.AddResponse(serializer.DumpJson([]))
    self.assertRaises(client.GanetiApiError, self.client.ReinstallInstance,
                      "doo-instance", osparams={"x": "y"})
    self.assertEqual(self.rapi.CountPending(), 0)

  def testReinstallInstanceWithOsparams2(self):
    osparams = {
      "Hello": "World",
      "foo": "bar",
      }
    self.rapi.AddResponse(serializer.DumpJson([rlib2._INST_REINSTALL_REQV1]))
    self.rapi.AddResponse("1717")
    self.assertEqual(1717, self.client.ReinstallInstance("zoo-instance",
                                                         osparams=osparams))
    self.assertHandler(rlib2.R_2_instances_name_reinstall)
    self.assertItems(["zoo-instance"])
    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertEqual(len(data), 2)
    self.assertEqual(data["osparams"], osparams)
    self.assertEqual(data["start"], True)
    self.assertEqual(self.rapi.CountPending(), 0)

  def testReplaceInstanceDisks(self):
    self.rapi.AddResponse("999")
    job_id = self.client.ReplaceInstanceDisks("instance-name",
        disks=[0, 1], iallocator="hail")
    self.assertEqual(999, job_id)
    self.assertHandler(rlib2.R_2_instances_name_replace_disks)
    self.assertItems(["instance-name"])
    self.assertQuery("disks", ["0,1"])
    self.assertQuery("mode", ["replace_auto"])
    self.assertQuery("iallocator", ["hail"])

    self.rapi.AddResponse("1000")
    job_id = self.client.ReplaceInstanceDisks("instance-bar",
        disks=[1], mode="replace_on_secondary", remote_node="foo-node")
    self.assertEqual(1000, job_id)
    self.assertItems(["instance-bar"])
    self.assertQuery("disks", ["1"])
    self.assertQuery("remote_node", ["foo-node"])

    self.rapi.AddResponse("5175")
    self.assertEqual(5175, self.client.ReplaceInstanceDisks("instance-moo"))
    self.assertItems(["instance-moo"])
    self.assertQuery("disks", None)

  def testPrepareExport(self):
    self.rapi.AddResponse("8326")
    self.assertEqual(8326, self.client.PrepareExport("inst1", "local"))
    self.assertHandler(rlib2.R_2_instances_name_prepare_export)
    self.assertItems(["inst1"])
    self.assertQuery("mode", ["local"])

  def testExportInstance(self):
    self.rapi.AddResponse("19695")
    job_id = self.client.ExportInstance("inst2", "local", "nodeX",
                                        shutdown=True)
    self.assertEqual(job_id, 19695)
    self.assertHandler(rlib2.R_2_instances_name_export)
    self.assertItems(["inst2"])

    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertEqual(data["mode"], "local")
    self.assertEqual(data["destination"], "nodeX")
    self.assertEqual(data["shutdown"], True)

  def testMigrateInstanceDefaults(self):
    self.rapi.AddResponse("24873")
    job_id = self.client.MigrateInstance("inst91")
    self.assertEqual(job_id, 24873)
    self.assertHandler(rlib2.R_2_instances_name_migrate)
    self.assertItems(["inst91"])

    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertFalse(data)

  def testMigrateInstance(self):
    for mode in constants.HT_MIGRATION_MODES:
      for cleanup in [False, True]:
        self.rapi.AddResponse("31910")
        job_id = self.client.MigrateInstance("inst289", mode=mode,
                                             cleanup=cleanup)
        self.assertEqual(job_id, 31910)
        self.assertHandler(rlib2.R_2_instances_name_migrate)
        self.assertItems(["inst289"])

        data = serializer.LoadJson(self.rapi.GetLastRequestData())
        self.assertEqual(len(data), 2)
        self.assertEqual(data["mode"], mode)
        self.assertEqual(data["cleanup"], cleanup)

  def testFailoverInstanceDefaults(self):
    self.rapi.AddResponse("7639")
    job_id = self.client.FailoverInstance("inst13579")
    self.assertEqual(job_id, 7639)
    self.assertHandler(rlib2.R_2_instances_name_failover)
    self.assertItems(["inst13579"])

    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertFalse(data)

  def testFailoverInstance(self):
    for iallocator in ["dumb", "hail"]:
      for ignore_consistency in [False, True]:
        for target_node in ["node-a", "node2"]:
          self.rapi.AddResponse("19161")
          job_id = \
            self.client.FailoverInstance("inst251", iallocator=iallocator,
                                         ignore_consistency=ignore_consistency,
                                         target_node=target_node)
          self.assertEqual(job_id, 19161)
          self.assertHandler(rlib2.R_2_instances_name_failover)
          self.assertItems(["inst251"])

          data = serializer.LoadJson(self.rapi.GetLastRequestData())
          self.assertEqual(len(data), 3)
          self.assertEqual(data["iallocator"], iallocator)
          self.assertEqual(data["ignore_consistency"], ignore_consistency)
          self.assertEqual(data["target_node"], target_node)
          self.assertEqual(self.rapi.CountPending(), 0)

  def testRenameInstanceDefaults(self):
    new_name = "newnametha7euqu"
    self.rapi.AddResponse("8791")
    job_id = self.client.RenameInstance("inst18821", new_name)
    self.assertEqual(job_id, 8791)
    self.assertHandler(rlib2.R_2_instances_name_rename)
    self.assertItems(["inst18821"])

    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertEqualValues(data, {"new_name": new_name, })

  def testRenameInstance(self):
    new_name = "new-name-yiux1iin"
    for ip_check in [False, True]:
      for name_check in [False, True]:
        self.rapi.AddResponse("24776")
        job_id = self.client.RenameInstance("inst20967", new_name,
                                             ip_check=ip_check,
                                             name_check=name_check)
        self.assertEqual(job_id, 24776)
        self.assertHandler(rlib2.R_2_instances_name_rename)
        self.assertItems(["inst20967"])

        data = serializer.LoadJson(self.rapi.GetLastRequestData())
        self.assertEqual(len(data), 3)
        self.assertEqual(data["new_name"], new_name)
        self.assertEqual(data["ip_check"], ip_check)
        self.assertEqual(data["name_check"], name_check)

  def testGetJobs(self):
    self.rapi.AddResponse('[ { "id": "123", "uri": "\\/2\\/jobs\\/123" },'
                          '  { "id": "124", "uri": "\\/2\\/jobs\\/124" } ]')
    self.assertEqual([123, 124], self.client.GetJobs())
    self.assertHandler(rlib2.R_2_jobs)

    self.rapi.AddResponse('[ { "id": "123", "uri": "\\/2\\/jobs\\/123" },'
                          '  { "id": "124", "uri": "\\/2\\/jobs\\/124" } ]')
    self.assertEqual([{"id": "123", "uri": "/2/jobs/123"},
                      {"id": "124", "uri": "/2/jobs/124"}],
                      self.client.GetJobs(bulk=True))
    self.assertHandler(rlib2.R_2_jobs)
    self.assertBulk()

  def testGetJobStatus(self):
    self.rapi.AddResponse("{\"foo\": \"bar\"}")
    self.assertEqual({"foo": "bar"}, self.client.GetJobStatus(1234))
    self.assertHandler(rlib2.R_2_jobs_id)
    self.assertItems(["1234"])

  def testWaitForJobChange(self):
    fields = ["id", "summary"]
    expected = {
      "job_info": [123, "something"],
      "log_entries": [],
      }

    self.rapi.AddResponse(serializer.DumpJson(expected))
    result = self.client.WaitForJobChange(123, fields, [], -1)
    self.assertEqualValues(expected, result)
    self.assertHandler(rlib2.R_2_jobs_id_wait)
    self.assertItems(["123"])

  def testCancelJob(self):
    self.rapi.AddResponse("[true, \"Job 123 will be canceled\"]")
    self.assertEqual([True, "Job 123 will be canceled"],
                     self.client.CancelJob(999, dry_run=True))
    self.assertHandler(rlib2.R_2_jobs_id)
    self.assertItems(["999"])
    self.assertDryRun()

  def testGetNodes(self):
    self.rapi.AddResponse("[ { \"id\": \"node1\", \"uri\": \"uri1\" },"
                          " { \"id\": \"node2\", \"uri\": \"uri2\" } ]")
    self.assertEqual(["node1", "node2"], self.client.GetNodes())
    self.assertHandler(rlib2.R_2_nodes)

    self.rapi.AddResponse("[ { \"id\": \"node1\", \"uri\": \"uri1\" },"
                          " { \"id\": \"node2\", \"uri\": \"uri2\" } ]")
    self.assertEqual([{"id": "node1", "uri": "uri1"},
                      {"id": "node2", "uri": "uri2"}],
                     self.client.GetNodes(bulk=True))
    self.assertHandler(rlib2.R_2_nodes)
    self.assertBulk()

  def testGetNode(self):
    self.rapi.AddResponse("{}")
    self.assertEqual({}, self.client.GetNode("node-foo"))
    self.assertHandler(rlib2.R_2_nodes_name)
    self.assertItems(["node-foo"])

  def testEvacuateNode(self):
    self.rapi.AddResponse(serializer.DumpJson([rlib2._NODE_EVAC_RES1]))
    self.rapi.AddResponse("9876")
    job_id = self.client.EvacuateNode("node-1", remote_node="node-2")
    self.assertEqual(9876, job_id)
    self.assertHandler(rlib2.R_2_nodes_name_evacuate)
    self.assertItems(["node-1"])
    self.assertEqual(serializer.LoadJson(self.rapi.GetLastRequestData()),
                     { "remote_node": "node-2", })
    self.assertEqual(self.rapi.CountPending(), 0)

    self.rapi.AddResponse(serializer.DumpJson([rlib2._NODE_EVAC_RES1]))
    self.rapi.AddResponse("8888")
    job_id = self.client.EvacuateNode("node-3", iallocator="hail", dry_run=True,
                                      mode=constants.NODE_EVAC_ALL,
                                      early_release=True)
    self.assertEqual(8888, job_id)
    self.assertItems(["node-3"])
    self.assertEqual(serializer.LoadJson(self.rapi.GetLastRequestData()), {
      "iallocator": "hail",
      "mode": "all",
      "early_release": True,
      })
    self.assertDryRun()

    self.assertRaises(client.GanetiApiError,
                      self.client.EvacuateNode,
                      "node-4", iallocator="hail", remote_node="node-5")
    self.assertEqual(self.rapi.CountPending(), 0)

  def testEvacuateNodeOldResponse(self):
    self.rapi.AddResponse(serializer.DumpJson([]))
    self.assertRaises(client.GanetiApiError, self.client.EvacuateNode,
                      "node-4", accept_old=False)
    self.assertEqual(self.rapi.CountPending(), 0)

    for mode in [client.NODE_EVAC_PRI, client.NODE_EVAC_ALL]:
      self.rapi.AddResponse(serializer.DumpJson([]))
      self.assertRaises(client.GanetiApiError, self.client.EvacuateNode,
                        "node-4", accept_old=True, mode=mode)
      self.assertEqual(self.rapi.CountPending(), 0)

    self.rapi.AddResponse(serializer.DumpJson([]))
    self.rapi.AddResponse(serializer.DumpJson("21533"))
    result = self.client.EvacuateNode("node-3", iallocator="hail",
                                      dry_run=True, accept_old=True,
                                      mode=client.NODE_EVAC_SEC,
                                      early_release=True)
    self.assertEqual(result, "21533")
    self.assertItems(["node-3"])
    self.assertQuery("iallocator", ["hail"])
    self.assertQuery("early_release", ["1"])
    self.assertFalse(self.rapi.GetLastRequestData())
    self.assertDryRun()
    self.assertEqual(self.rapi.CountPending(), 0)

  def testMigrateNode(self):
    self.rapi.AddResponse(serializer.DumpJson([]))
    self.rapi.AddResponse("1111")
    self.assertEqual(1111, self.client.MigrateNode("node-a", dry_run=True))
    self.assertHandler(rlib2.R_2_nodes_name_migrate)
    self.assertItems(["node-a"])
    self.assertTrue("mode" not in self.rapi.GetLastHandler().queryargs)
    self.assertDryRun()
    self.assertFalse(self.rapi.GetLastRequestData())

    self.rapi.AddResponse(serializer.DumpJson([]))
    self.rapi.AddResponse("1112")
    self.assertEqual(1112, self.client.MigrateNode("node-a", dry_run=True,
                                                   mode="live"))
    self.assertHandler(rlib2.R_2_nodes_name_migrate)
    self.assertItems(["node-a"])
    self.assertQuery("mode", ["live"])
    self.assertDryRun()
    self.assertFalse(self.rapi.GetLastRequestData())

    self.rapi.AddResponse(serializer.DumpJson([]))
    self.assertRaises(client.GanetiApiError, self.client.MigrateNode,
                      "node-c", target_node="foonode")
    self.assertEqual(self.rapi.CountPending(), 0)

  def testMigrateNodeBodyData(self):
    self.rapi.AddResponse(serializer.DumpJson([rlib2._NODE_MIGRATE_REQV1]))
    self.rapi.AddResponse("27539")
    self.assertEqual(27539, self.client.MigrateNode("node-a", dry_run=False,
                                                    mode="live"))
    self.assertHandler(rlib2.R_2_nodes_name_migrate)
    self.assertItems(["node-a"])
    self.assertFalse(self.rapi.GetLastHandler().queryargs)
    self.assertEqual(serializer.LoadJson(self.rapi.GetLastRequestData()),
                     { "mode": "live", })

    self.rapi.AddResponse(serializer.DumpJson([rlib2._NODE_MIGRATE_REQV1]))
    self.rapi.AddResponse("14219")
    self.assertEqual(14219, self.client.MigrateNode("node-x", dry_run=True,
                                                    target_node="node9",
                                                    iallocator="ial"))
    self.assertHandler(rlib2.R_2_nodes_name_migrate)
    self.assertItems(["node-x"])
    self.assertDryRun()
    self.assertEqual(serializer.LoadJson(self.rapi.GetLastRequestData()),
                     { "target_node": "node9", "iallocator": "ial", })

    self.assertEqual(self.rapi.CountPending(), 0)

  def testGetNodeRole(self):
    self.rapi.AddResponse("\"master\"")
    self.assertEqual("master", self.client.GetNodeRole("node-a"))
    self.assertHandler(rlib2.R_2_nodes_name_role)
    self.assertItems(["node-a"])

  def testSetNodeRole(self):
    self.rapi.AddResponse("789")
    self.assertEqual(789,
        self.client.SetNodeRole("node-foo", "master-candidate", force=True))
    self.assertHandler(rlib2.R_2_nodes_name_role)
    self.assertItems(["node-foo"])
    self.assertQuery("force", ["1"])
    self.assertEqual("\"master-candidate\"", self.rapi.GetLastRequestData())

  def testPowercycleNode(self):
    self.rapi.AddResponse("23051")
    self.assertEqual(23051,
        self.client.PowercycleNode("node5468", force=True))
    self.assertHandler(rlib2.R_2_nodes_name_powercycle)
    self.assertItems(["node5468"])
    self.assertQuery("force", ["1"])
    self.assertFalse(self.rapi.GetLastRequestData())
    self.assertEqual(self.rapi.CountPending(), 0)

  def testModifyNode(self):
    self.rapi.AddResponse("3783")
    job_id = self.client.ModifyNode("node16979.example.com", drained=True)
    self.assertEqual(job_id, 3783)
    self.assertHandler(rlib2.R_2_nodes_name_modify)
    self.assertItems(["node16979.example.com"])
    self.assertEqual(self.rapi.CountPending(), 0)

  def testGetNodeStorageUnits(self):
    self.rapi.AddResponse("42")
    self.assertEqual(42,
        self.client.GetNodeStorageUnits("node-x", "lvm-pv", "fields"))
    self.assertHandler(rlib2.R_2_nodes_name_storage)
    self.assertItems(["node-x"])
    self.assertQuery("storage_type", ["lvm-pv"])
    self.assertQuery("output_fields", ["fields"])

  def testModifyNodeStorageUnits(self):
    self.rapi.AddResponse("14")
    self.assertEqual(14,
        self.client.ModifyNodeStorageUnits("node-z", "lvm-pv", "hda"))
    self.assertHandler(rlib2.R_2_nodes_name_storage_modify)
    self.assertItems(["node-z"])
    self.assertQuery("storage_type", ["lvm-pv"])
    self.assertQuery("name", ["hda"])
    self.assertQuery("allocatable", None)

    for allocatable, query_allocatable in [(True, "1"), (False, "0")]:
      self.rapi.AddResponse("7205")
      job_id = self.client.ModifyNodeStorageUnits("node-z", "lvm-pv", "hda",
                                                  allocatable=allocatable)
      self.assertEqual(7205, job_id)
      self.assertHandler(rlib2.R_2_nodes_name_storage_modify)
      self.assertItems(["node-z"])
      self.assertQuery("storage_type", ["lvm-pv"])
      self.assertQuery("name", ["hda"])
      self.assertQuery("allocatable", [query_allocatable])

  def testRepairNodeStorageUnits(self):
    self.rapi.AddResponse("99")
    self.assertEqual(99, self.client.RepairNodeStorageUnits("node-z", "lvm-pv",
                                                            "hda"))
    self.assertHandler(rlib2.R_2_nodes_name_storage_repair)
    self.assertItems(["node-z"])
    self.assertQuery("storage_type", ["lvm-pv"])
    self.assertQuery("name", ["hda"])

  def testGetNodeTags(self):
    self.rapi.AddResponse("[\"fry\", \"bender\"]")
    self.assertEqual(["fry", "bender"], self.client.GetNodeTags("node-k"))
    self.assertHandler(rlib2.R_2_nodes_name_tags)
    self.assertItems(["node-k"])

  def testAddNodeTags(self):
    self.rapi.AddResponse("1234")
    self.assertEqual(1234,
        self.client.AddNodeTags("node-v", ["awesome"], dry_run=True))
    self.assertHandler(rlib2.R_2_nodes_name_tags)
    self.assertItems(["node-v"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testDeleteNodeTags(self):
    self.rapi.AddResponse("16861")
    self.assertEqual(16861, self.client.DeleteNodeTags("node-w", ["awesome"],
                                                       dry_run=True))
    self.assertHandler(rlib2.R_2_nodes_name_tags)
    self.assertItems(["node-w"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testGetGroups(self):
    groups = [{"name": "group1",
               "uri": "/2/groups/group1",
               },
              {"name": "group2",
               "uri": "/2/groups/group2",
               },
              ]
    self.rapi.AddResponse(serializer.DumpJson(groups))
    self.assertEqual(["group1", "group2"], self.client.GetGroups())
    self.assertHandler(rlib2.R_2_groups)

  def testGetGroupsBulk(self):
    groups = [{"name": "group1",
               "uri": "/2/groups/group1",
               "node_cnt": 2,
               "node_list": ["gnt1.test",
                             "gnt2.test",
                             ],
               },
              {"name": "group2",
               "uri": "/2/groups/group2",
               "node_cnt": 1,
               "node_list": ["gnt3.test",
                             ],
               },
              ]
    self.rapi.AddResponse(serializer.DumpJson(groups))

    self.assertEqual(groups, self.client.GetGroups(bulk=True))
    self.assertHandler(rlib2.R_2_groups)
    self.assertBulk()

  def testGetGroup(self):
    group = {"ctime": None,
             "name": "default",
             }
    self.rapi.AddResponse(serializer.DumpJson(group))
    self.assertEqual({"ctime": None, "name": "default"},
                     self.client.GetGroup("default"))
    self.assertHandler(rlib2.R_2_groups_name)
    self.assertItems(["default"])

  def testCreateGroup(self):
    self.rapi.AddResponse("12345")
    job_id = self.client.CreateGroup("newgroup", dry_run=True)
    self.assertEqual(job_id, 12345)
    self.assertHandler(rlib2.R_2_groups)
    self.assertDryRun()

  def testDeleteGroup(self):
    self.rapi.AddResponse("12346")
    job_id = self.client.DeleteGroup("newgroup", dry_run=True)
    self.assertEqual(job_id, 12346)
    self.assertHandler(rlib2.R_2_groups_name)
    self.assertDryRun()

  def testRenameGroup(self):
    self.rapi.AddResponse("12347")
    job_id = self.client.RenameGroup("oldname", "newname")
    self.assertEqual(job_id, 12347)
    self.assertHandler(rlib2.R_2_groups_name_rename)

  def testModifyGroup(self):
    self.rapi.AddResponse("12348")
    job_id = self.client.ModifyGroup("mygroup", alloc_policy="foo")
    self.assertEqual(job_id, 12348)
    self.assertHandler(rlib2.R_2_groups_name_modify)

  def testAssignGroupNodes(self):
    self.rapi.AddResponse("12349")
    job_id = self.client.AssignGroupNodes("mygroup", ["node1", "node2"],
                                          force=True, dry_run=True)
    self.assertEqual(job_id, 12349)
    self.assertHandler(rlib2.R_2_groups_name_assign_nodes)
    self.assertDryRun()
    self.assertUseForce()

  def testGetNetworksBulk(self):
    networks = [{"name": "network1",
               "uri": "/2/networks/network1",
               "network": "192.168.0.0/24",
               },
              {"name": "network2",
               "uri": "/2/networks/network2",
               "network": "192.168.0.0/24",
               },
              ]
    self.rapi.AddResponse(serializer.DumpJson(networks))

    self.assertEqual(networks, self.client.GetNetworks(bulk=True))
    self.assertHandler(rlib2.R_2_networks)
    self.assertBulk()

  def testGetNetwork(self):
    network = {"ctime": None,
               "name": "network1",
               }
    self.rapi.AddResponse(serializer.DumpJson(network))
    self.assertEqual({"ctime": None, "name": "network1"},
                     self.client.GetNetwork("network1"))
    self.assertHandler(rlib2.R_2_networks_name)
    self.assertItems(["network1"])

  def testCreateNetwork(self):
    self.rapi.AddResponse("12345")
    job_id = self.client.CreateNetwork("newnetwork", network="192.168.0.0/24",
                                       dry_run=True)
    self.assertEqual(job_id, 12345)
    self.assertHandler(rlib2.R_2_networks)
    self.assertDryRun()

  def testModifyNetwork(self):
    self.rapi.AddResponse("12346")
    job_id = self.client.ModifyNetwork("mynetwork", gateway="192.168.0.10",
                                     dry_run=True)
    self.assertEqual(job_id, 12346)
    self.assertHandler(rlib2.R_2_networks_name_modify)

  def testDeleteNetwork(self):
    self.rapi.AddResponse("12347")
    job_id = self.client.DeleteNetwork("newnetwork", dry_run=True)
    self.assertEqual(job_id, 12347)
    self.assertHandler(rlib2.R_2_networks_name)
    self.assertDryRun()

  def testConnectNetwork(self):
    self.rapi.AddResponse("12348")
    job_id = self.client.ConnectNetwork("mynetwork", "default",
                                        "bridged", "br0", dry_run=True)
    self.assertEqual(job_id, 12348)
    self.assertHandler(rlib2.R_2_networks_name_connect)
    self.assertDryRun()

  def testDisconnectNetwork(self):
    self.rapi.AddResponse("12349")
    job_id = self.client.DisconnectNetwork("mynetwork", "default", dry_run=True)
    self.assertEqual(job_id, 12349)
    self.assertHandler(rlib2.R_2_networks_name_disconnect)
    self.assertDryRun()

  def testGetNetworkTags(self):
    self.rapi.AddResponse("[]")
    self.assertEqual([], self.client.GetNetworkTags("fooNetwork"))
    self.assertHandler(rlib2.R_2_networks_name_tags)
    self.assertItems(["fooNetwork"])

  def testAddNetworkTags(self):
    self.rapi.AddResponse("1234")
    self.assertEqual(1234,
        self.client.AddNetworkTags("fooNetwork", ["awesome"], dry_run=True))
    self.assertHandler(rlib2.R_2_networks_name_tags)
    self.assertItems(["fooNetwork"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testDeleteNetworkTags(self):
    self.rapi.AddResponse("25826")
    self.assertEqual(25826, self.client.DeleteNetworkTags("foo", ["awesome"],
                                                          dry_run=True))
    self.assertHandler(rlib2.R_2_networks_name_tags)
    self.assertItems(["foo"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testModifyInstance(self):
    self.rapi.AddResponse("23681")
    job_id = self.client.ModifyInstance("inst7210", os_name="linux")
    self.assertEqual(job_id, 23681)
    self.assertItems(["inst7210"])
    self.assertHandler(rlib2.R_2_instances_name_modify)
    self.assertEqual(serializer.LoadJson(self.rapi.GetLastRequestData()),
                     { "os_name": "linux", })

  def testModifyCluster(self):
    for mnh in [None, False, True]:
      self.rapi.AddResponse("14470")
      self.assertEqual(14470,
        self.client.ModifyCluster(maintain_node_health=mnh,
                                  reason="PinkBunniesInvasion"))
      self.assertHandler(rlib2.R_2_cluster_modify)
      self.assertItems([])
      data = serializer.LoadJson(self.rapi.GetLastRequestData())
      self.assertEqual(len(data), 1)
      self.assertEqual(data["maintain_node_health"], mnh)
      self.assertEqual(self.rapi.CountPending(), 0)
      self.assertQuery("reason", ["PinkBunniesInvasion"])

  def testRedistributeConfig(self):
    self.rapi.AddResponse("3364")
    job_id = self.client.RedistributeConfig()
    self.assertEqual(job_id, 3364)
    self.assertItems([])
    self.assertHandler(rlib2.R_2_redist_config)

  def testActivateInstanceDisks(self):
    self.rapi.AddResponse("23547")
    job_id = self.client.ActivateInstanceDisks("inst28204")
    self.assertEqual(job_id, 23547)
    self.assertItems(["inst28204"])
    self.assertHandler(rlib2.R_2_instances_name_activate_disks)
    self.assertFalse(self.rapi.GetLastHandler().queryargs)

  def testActivateInstanceDisksIgnoreSize(self):
    self.rapi.AddResponse("11044")
    job_id = self.client.ActivateInstanceDisks("inst28204", ignore_size=True)
    self.assertEqual(job_id, 11044)
    self.assertItems(["inst28204"])
    self.assertHandler(rlib2.R_2_instances_name_activate_disks)
    self.assertQuery("ignore_size", ["1"])

  def testDeactivateInstanceDisks(self):
    self.rapi.AddResponse("14591")
    job_id = self.client.DeactivateInstanceDisks("inst28234")
    self.assertEqual(job_id, 14591)
    self.assertItems(["inst28234"])
    self.assertHandler(rlib2.R_2_instances_name_deactivate_disks)
    self.assertFalse(self.rapi.GetLastHandler().queryargs)

  def testRecreateInstanceDisks(self):
    self.rapi.AddResponse("13553")
    job_id = self.client.RecreateInstanceDisks("inst23153", iallocator="hail")
    self.assertEqual(job_id, 13553)
    self.assertItems(["inst23153"])
    data = serializer.LoadJson(self.rapi.GetLastRequestData())
    self.assertEqual("hail", data["iallocator"])
    self.assertHandler(rlib2.R_2_instances_name_recreate_disks)
    self.assertFalse(self.rapi.GetLastHandler().queryargs)

  def testGetInstanceConsole(self):
    self.rapi.AddResponse("26876")
    job_id = self.client.GetInstanceConsole("inst21491")
    self.assertEqual(job_id, 26876)
    self.assertItems(["inst21491"])
    self.assertHandler(rlib2.R_2_instances_name_console)
    self.assertFalse(self.rapi.GetLastHandler().queryargs)
    self.assertFalse(self.rapi.GetLastRequestData())

  def testGrowInstanceDisk(self):
    for idx, wait_for_sync in enumerate([None, False, True]):
      amount = 128 + (512 * idx)
      self.assertEqual(self.rapi.CountPending(), 0)
      self.rapi.AddResponse("30783")
      self.assertEqual(30783,
        self.client.GrowInstanceDisk("eze8ch", idx, amount,
                                     wait_for_sync=wait_for_sync))
      self.assertHandler(rlib2.R_2_instances_name_disk_grow)
      self.assertItems(["eze8ch", str(idx)])
      data = serializer.LoadJson(self.rapi.GetLastRequestData())
      if wait_for_sync is None:
        self.assertEqual(len(data), 1)
        self.assertTrue("wait_for_sync" not in data)
      else:
        self.assertEqual(len(data), 2)
        self.assertEqual(data["wait_for_sync"], wait_for_sync)
      self.assertEqual(data["amount"], amount)
      self.assertEqual(self.rapi.CountPending(), 0)

  def testGetGroupTags(self):
    self.rapi.AddResponse("[]")
    self.assertEqual([], self.client.GetGroupTags("fooGroup"))
    self.assertHandler(rlib2.R_2_groups_name_tags)
    self.assertItems(["fooGroup"])

  def testAddGroupTags(self):
    self.rapi.AddResponse("1234")
    self.assertEqual(1234,
        self.client.AddGroupTags("fooGroup", ["awesome"], dry_run=True))
    self.assertHandler(rlib2.R_2_groups_name_tags)
    self.assertItems(["fooGroup"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testDeleteGroupTags(self):
    self.rapi.AddResponse("25826")
    self.assertEqual(25826, self.client.DeleteGroupTags("foo", ["awesome"],
                                                        dry_run=True))
    self.assertHandler(rlib2.R_2_groups_name_tags)
    self.assertItems(["foo"])
    self.assertDryRun()
    self.assertQuery("tag", ["awesome"])

  def testQuery(self):
    for idx, what in enumerate(constants.QR_VIA_RAPI):
      for idx2, qfilter in enumerate([None, ["?", "name"]]):
        job_id = 11010 + (idx << 4) + (idx2 << 16)
        fields = sorted(query.ALL_FIELDS[what].keys())[:10]

        self.rapi.AddResponse(str(job_id))
        self.assertEqual(self.client.Query(what, fields, qfilter=qfilter),
                         job_id)
        self.assertItems([what])
        self.assertHandler(rlib2.R_2_query)
        self.assertFalse(self.rapi.GetLastHandler().queryargs)
        data = serializer.LoadJson(self.rapi.GetLastRequestData())
        self.assertEqual(data["fields"], fields)
        if qfilter is None:
          self.assertTrue("qfilter" not in data)
        else:
          self.assertEqual(data["qfilter"], qfilter)
        self.assertEqual(self.rapi.CountPending(), 0)

  def testQueryFields(self):
    exp_result = objects.QueryFieldsResponse(fields=[
      objects.QueryFieldDefinition(name="pnode", title="PNode",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="other", title="Other",
                                   kind=constants.QFT_BOOL),
      ])

    for what in constants.QR_VIA_RAPI:
      for fields in [None, ["name", "_unknown_"], ["&", "?|"]]:
        self.rapi.AddResponse(serializer.DumpJson(exp_result.ToDict()))
        result = self.client.QueryFields(what, fields=fields)
        self.assertItems([what])
        self.assertHandler(rlib2.R_2_query_fields)
        self.assertFalse(self.rapi.GetLastRequestData())

        queryargs = self.rapi.GetLastHandler().queryargs
        if fields is None:
          self.assertFalse(queryargs)
        else:
          self.assertEqual(queryargs, {
            "fields": [",".join(fields)],
            })

        self.assertEqual(objects.QueryFieldsResponse.FromDict(result).ToDict(),
                         exp_result.ToDict())

        self.assertEqual(self.rapi.CountPending(), 0)

  def testWaitForJobCompletionNoChange(self):
    resp = serializer.DumpJson({
      "status": constants.JOB_STATUS_WAITING,
      })

    for retries in [1, 5, 25]:
      for _ in range(retries):
        self.rapi.AddResponse(resp)

      self.assertFalse(self.client.WaitForJobCompletion(22789, period=None,
                                                        retries=retries))
      self.assertHandler(rlib2.R_2_jobs_id)
      self.assertItems(["22789"])

      self.assertEqual(self.rapi.CountPending(), 0)

  def testWaitForJobCompletionAlreadyFinished(self):
    self.rapi.AddResponse(serializer.DumpJson({
      "status": constants.JOB_STATUS_SUCCESS,
      }))

    self.assertTrue(self.client.WaitForJobCompletion(22793, period=None,
                                                     retries=1))
    self.assertHandler(rlib2.R_2_jobs_id)
    self.assertItems(["22793"])

    self.assertEqual(self.rapi.CountPending(), 0)

  def testWaitForJobCompletionEmptyResponse(self):
    self.rapi.AddResponse("{}")
    self.assertFalse(self.client.WaitForJobCompletion(22793, period=None,
                                                     retries=10))
    self.assertHandler(rlib2.R_2_jobs_id)
    self.assertItems(["22793"])

    self.assertEqual(self.rapi.CountPending(), 0)

  def testWaitForJobCompletionOutOfRetries(self):
    for retries in [3, 10, 21]:
      for _ in range(retries):
        self.rapi.AddResponse(serializer.DumpJson({
          "status": constants.JOB_STATUS_RUNNING,
          }))

      self.assertFalse(self.client.WaitForJobCompletion(30948, period=None,
                                                        retries=retries - 1))
      self.assertHandler(rlib2.R_2_jobs_id)
      self.assertItems(["30948"])

      self.assertEqual(self.rapi.CountPending(), 1)
      self.rapi.ResetResponses()

  def testWaitForJobCompletionSuccessAndFailure(self):
    for retries in [1, 4, 13]:
      for (success, end_status) in [(False, constants.JOB_STATUS_ERROR),
                                    (True, constants.JOB_STATUS_SUCCESS)]:
        for _ in range(retries):
          self.rapi.AddResponse(serializer.DumpJson({
            "status": constants.JOB_STATUS_RUNNING,
            }))

        self.rapi.AddResponse(serializer.DumpJson({
          "status": end_status,
          }))

        result = self.client.WaitForJobCompletion(3187, period=None,
                                                  retries=retries + 1)
        self.assertEqual(result, success)
        self.assertHandler(rlib2.R_2_jobs_id)
        self.assertItems(["3187"])

        self.assertEqual(self.rapi.CountPending(), 0)

  def testGetFilters(self):
    self.rapi.AddResponse(
      "[ { \"uuid\": \"4364c043-f232-41e3-837f-f1ce846f21d2\","
      " \"uri\": \"uri1\" },"
      " { \"uuid\": \"eceb3f7f-fee8-447a-8277-031b32a20e6b\","
      " \"uri\": \"uri2\" } ]")
    self.assertEqual(["4364c043-f232-41e3-837f-f1ce846f21d2",
                      "eceb3f7f-fee8-447a-8277-031b32a20e6b",
                     ],
                     self.client.GetFilters())
    self.assertHandler(rlib2.R_2_filters)

    self.rapi.AddResponse(
      "[ { \"uuid\": \"4364c043-f232-41e3-837f-f1ce846f21d2\","
      " \"uri\": \"uri1\" },"
      " { \"uuid\": \"eceb3f7f-fee8-447a-8277-031b32a20e6b\","
      " \"uri\": \"uri2\" } ]")
    self.assertEqual([{"uuid": "4364c043-f232-41e3-837f-f1ce846f21d2",
                       "uri": "uri1"},
                      {"uuid": "eceb3f7f-fee8-447a-8277-031b32a20e6b",
                       "uri": "uri2"},
                     ],
                     self.client.GetFilters(bulk=True))
    self.assertHandler(rlib2.R_2_filters)
    self.assertBulk()

  def testGetFilter(self):
    filter_rule = {
      "uuid": "4364c043-f232-41e3-837f-f1ce846f21d2",
      "priority": 1,
      "predicates": [["jobid", [">", "id", "watermark"]]],
      "action": "CONTINUE",
      "reason_trail": ["testReplaceFilter", "myreason", 1412159589686391000],
    }
    self.rapi.AddResponse(serializer.DumpJson(filter_rule))
    self.assertEqual(
      filter_rule,
      self.client.GetFilter("4364c043-f232-41e3-837f-f1ce846f21d2")
    )
    self.assertHandler(rlib2.R_2_filters_uuid)
    self.assertItems(["4364c043-f232-41e3-837f-f1ce846f21d2"])

  def testAddFilter(self):
    self.rapi.AddResponse("\"4364c043-f232-41e3-837f-f1ce846f21d2\"")
    self.assertEqual("4364c043-f232-41e3-837f-f1ce846f21d2",
                     self.client.AddFilter(
                       priority=1,
                       predicates=[["jobid", [">", "id", "watermark"]]],
                       action="CONTINUE",
                       reason_trail=["testAddFilter", "myreason",
                                     utils.EpochNano()],
                     ))
    self.assertHandler(rlib2.R_2_filters)

  def testReplaceFilter(self):
    self.rapi.AddResponse("\"4364c043-f232-41e3-837f-f1ce846f21d2\"")
    self.assertEqual("4364c043-f232-41e3-837f-f1ce846f21d2",
                     self.client.ReplaceFilter(
                       uuid="4364c043-f232-41e3-837f-f1ce846f21d2",
                       priority=1,
                       predicates=[["jobid", [">", "id", "watermark"]]],
                       action="CONTINUE",
                       reason_trail=["testReplaceFilter", "myreason",
                                     utils.EpochNano()],
                     ))
    self.assertHandler(rlib2.R_2_filters_uuid)

  def testDeleteFilter(self):
    self.rapi.AddResponse("null")
    self.assertEqual(None,
                     self.client.DeleteFilter(
                       uuid="4364c043-f232-41e3-837f-f1ce846f21d2",
                     ))
    self.assertHandler(rlib2.R_2_filters_uuid)


class RapiTestRunner(unittest.TextTestRunner):
  def run(self, *args):
    global _used_handlers
    assert _used_handlers is None

    _used_handlers = set()
    try:
      # Run actual tests
      result = unittest.TextTestRunner.run(self, *args)

      diff = (set(connector.CONNECTOR.values()) - _used_handlers -
             _KNOWN_UNUSED)
      if diff:
        raise AssertionError("The following RAPI resources were not used by the"
                             " RAPI client: %r" % utils.CommaJoin(diff))
    finally:
      # Reset global variable
      _used_handlers = None

    return result


if __name__ == "__main__":
  client.UsesRapiClient(testutils.GanetiTestProgram)(testRunner=RapiTestRunner)
