#!/usr/bin/python
#

# Copyright (C) 2010, 2011, 2012, 2013 Google Inc.
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


"""Script for testing ganeti.rpc"""

import os
import sys
import unittest
import random
import tempfile

from ganeti import constants
from ganeti import compat
from ganeti.rpc import node as rpc
from ganeti import rpc_defs
from ganeti import http
from ganeti import errors
from ganeti import serializer
from ganeti import objects
from ganeti import backend

import testutils
import mocks


class _FakeRequestProcessor:
  def __init__(self, response_fn):
    self._response_fn = response_fn
    self.reqcount = 0

  def __call__(self, reqs, lock_monitor_cb=None):
    assert lock_monitor_cb is None or callable(lock_monitor_cb)
    for req in reqs:
      self.reqcount += 1
      self._response_fn(req)


def GetFakeSimpleStoreClass(fn):
  class FakeSimpleStore:
    GetNodePrimaryIPList = fn
    GetPrimaryIPFamily = lambda _: None

  return FakeSimpleStore


def _RaiseNotImplemented():
  """Simple wrapper to raise NotImplementedError.

  """
  raise NotImplementedError


class TestRpcProcessor(unittest.TestCase):
  def _FakeAddressLookup(self, map):
    return lambda node_list: [map.get(node) for node in node_list]

  def _GetVersionResponse(self, req):
    self.assertEqual(req.host, "127.0.0.1")
    self.assertEqual(req.port, 24094)
    self.assertEqual(req.path, "/version")
    self.assertEqual(req.read_timeout, constants.RPC_TMO_URGENT)
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, 123))

  def testVersionSuccess(self):
    resolver = rpc._StaticResolver(["127.0.0.1"])
    http_proc = _FakeRequestProcessor(self._GetVersionResponse)
    proc = rpc._RpcProcessor(resolver, 24094)
    result = proc(["localhost"], "version", {"localhost": ""}, 60,
                  NotImplemented, _req_process_fn=http_proc)
    self.assertEqual(list(result), ["localhost"])
    lhresp = result["localhost"]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, "localhost")
    self.assertFalse(lhresp.fail_msg)
    self.assertEqual(lhresp.payload, 123)
    self.assertEqual(lhresp.call, "version")
    lhresp.Raise("should not raise")
    self.assertEqual(http_proc.reqcount, 1)

  def _ReadTimeoutResponse(self, req):
    self.assertEqual(req.host, "192.0.2.13")
    self.assertEqual(req.port, 19176)
    self.assertEqual(req.path, "/version")
    self.assertEqual(req.read_timeout, 12356)
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, -1))

  def testReadTimeout(self):
    resolver = rpc._StaticResolver(["192.0.2.13"])
    http_proc = _FakeRequestProcessor(self._ReadTimeoutResponse)
    proc = rpc._RpcProcessor(resolver, 19176)
    host = "node31856"
    body = {host: ""}
    result = proc([host], "version", body, 12356, NotImplemented,
                  _req_process_fn=http_proc)
    self.assertEqual(list(result), [host])
    lhresp = result[host]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, host)
    self.assertFalse(lhresp.fail_msg)
    self.assertEqual(lhresp.payload, -1)
    self.assertEqual(lhresp.call, "version")
    lhresp.Raise("should not raise")
    self.assertEqual(http_proc.reqcount, 1)

  def testOfflineNode(self):
    resolver = rpc._StaticResolver([rpc._OFFLINE])
    http_proc = _FakeRequestProcessor(NotImplemented)
    proc = rpc._RpcProcessor(resolver, 30668)
    host = "n17296"
    body = {host: ""}
    result = proc([host], "version", body, 60, NotImplemented,
                  _req_process_fn=http_proc)
    self.assertEqual(list(result), [host])
    lhresp = result[host]
    self.assertTrue(lhresp.offline)
    self.assertEqual(lhresp.node, host)
    self.assertTrue(lhresp.fail_msg)
    self.assertFalse(lhresp.payload)
    self.assertEqual(lhresp.call, "version")

    # With a message
    self.assertRaises(errors.OpExecError, lhresp.Raise, "should raise")

    # No message
    self.assertRaises(errors.OpExecError, lhresp.Raise, None)

    self.assertEqual(http_proc.reqcount, 0)

  def _GetMultiVersionResponse(self, req):
    self.assertTrue(req.host.startswith("node"))
    self.assertEqual(req.port, 23245)
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, 987))

  def testMultiVersionSuccess(self):
    nodes = ["node%s" % i for i in range(50)]
    body = dict((n, "") for n in nodes)
    resolver = rpc._StaticResolver(nodes)
    http_proc = _FakeRequestProcessor(self._GetMultiVersionResponse)
    proc = rpc._RpcProcessor(resolver, 23245)
    result = proc(nodes, "version", body, 60, NotImplemented,
                  _req_process_fn=http_proc)
    self.assertEqual(sorted(result.keys()), sorted(nodes))

    for name in nodes:
      lhresp = result[name]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, name)
      self.assertFalse(lhresp.fail_msg)
      self.assertEqual(lhresp.payload, 987)
      self.assertEqual(lhresp.call, "version")
      lhresp.Raise("should not raise")

    self.assertEqual(http_proc.reqcount, len(nodes))

  def _GetVersionResponseFail(self, errinfo, req):
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((False, errinfo))

  def testVersionFailure(self):
    resolver = rpc._StaticResolver(["aef9ur4i.example.com"])
    proc = rpc._RpcProcessor(resolver, 5903)
    for errinfo in [None, "Unknown error"]:
      http_proc = \
        _FakeRequestProcessor(compat.partial(self._GetVersionResponseFail,
                                             errinfo))
      host = "aef9ur4i.example.com"
      body = {host: ""}
      result = proc(list(body), "version", body, 60, NotImplemented,
                    _req_process_fn=http_proc)
      self.assertEqual(list(result), [host])
      lhresp = result[host]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, host)
      self.assertTrue(lhresp.fail_msg)
      self.assertFalse(lhresp.payload)
      self.assertEqual(lhresp.call, "version")
      self.assertRaises(errors.OpExecError, lhresp.Raise, "failed")
      self.assertEqual(http_proc.reqcount, 1)

  def _GetHttpErrorResponse(self, httperrnodes, failnodes, req):
    self.assertEqual(req.path, "/vg_list")
    self.assertEqual(req.port, 15165)

    if req.host in httperrnodes:
      req.success = False
      req.error = "Node set up for HTTP errors"

    elif req.host in failnodes:
      req.success = True
      req.resp_status_code = 404
      req.resp_body = serializer.DumpJson({
        "code": 404,
        "message": "Method not found",
        "explain": "Explanation goes here",
        })
    else:
      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, hash(req.host)))

  def testHttpError(self):
    nodes = ["uaf6pbbv%s" % i for i in range(50)]
    body = dict((n, "") for n in nodes)
    resolver = rpc._StaticResolver(nodes)

    httperrnodes = set(nodes[1::7])
    self.assertEqual(len(httperrnodes), 7)

    failnodes = set(nodes[2::3]) - httperrnodes
    self.assertEqual(len(failnodes), 14)

    self.assertEqual(len(set(nodes) - failnodes - httperrnodes), 29)

    proc = rpc._RpcProcessor(resolver, 15165)
    http_proc = \
      _FakeRequestProcessor(compat.partial(self._GetHttpErrorResponse,
                                           httperrnodes, failnodes))
    result = proc(nodes, "vg_list", body,
                  constants.RPC_TMO_URGENT, NotImplemented,
                  _req_process_fn=http_proc)
    self.assertEqual(sorted(result.keys()), sorted(nodes))

    for name in nodes:
      lhresp = result[name]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, name)
      self.assertEqual(lhresp.call, "vg_list")

      if name in httperrnodes:
        self.assertTrue(lhresp.fail_msg)
        self.assertRaises(errors.OpExecError, lhresp.Raise, "failed")
      elif name in failnodes:
        self.assertTrue(lhresp.fail_msg)
        self.assertRaises(errors.OpPrereqError, lhresp.Raise, "failed",
                          prereq=True, ecode=errors.ECODE_INVAL)
      else:
        self.assertFalse(lhresp.fail_msg)
        self.assertEqual(lhresp.payload, hash(name))
        lhresp.Raise("should not raise")

    self.assertEqual(http_proc.reqcount, len(nodes))

  def _GetInvalidResponseA(self, req):
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson(("This", "is", "an", "invalid",
                                         "response", "!", 1, 2, 3))

  def _GetInvalidResponseB(self, req):
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson("invalid response")

  def testInvalidResponse(self):
    resolver = rpc._StaticResolver(["oqo7lanhly.example.com"])
    proc = rpc._RpcProcessor(resolver, 19978)

    for fn in [self._GetInvalidResponseA, self._GetInvalidResponseB]:
      http_proc = _FakeRequestProcessor(fn)
      host = "oqo7lanhly.example.com"
      body = {host: ""}
      result = proc([host], "version", body, 60, NotImplemented,
                    _req_process_fn=http_proc)
      self.assertEqual(list(result), [host])
      lhresp = result[host]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, host)
      self.assertTrue(lhresp.fail_msg)
      self.assertFalse(lhresp.payload)
      self.assertEqual(lhresp.call, "version")
      self.assertRaises(errors.OpExecError, lhresp.Raise, "failed")
      self.assertEqual(http_proc.reqcount, 1)

  def _GetBodyTestResponse(self, test_data, req):
    self.assertEqual(req.host, "192.0.2.84")
    self.assertEqual(req.port, 18700)
    self.assertEqual(req.path, "/upload_file")
    self.assertEqual(serializer.LoadJson(req.post_data), test_data)
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, None))

  def testResponseBody(self):
    test_data = {
      "Hello": "World",
      "xyz": range(10),
      }
    resolver = rpc._StaticResolver(["192.0.2.84"])
    http_proc = _FakeRequestProcessor(compat.partial(self._GetBodyTestResponse,
                                                     test_data))
    proc = rpc._RpcProcessor(resolver, 18700)
    host = "node19759"
    body = {host: serializer.DumpJson(test_data)}
    result = proc([host], "upload_file", body, 30, NotImplemented,
                  _req_process_fn=http_proc)
    self.assertEqual(list(result), [host])
    lhresp = result[host]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, host)
    self.assertFalse(lhresp.fail_msg)
    self.assertEqual(lhresp.payload, None)
    self.assertEqual(lhresp.call, "upload_file")
    lhresp.Raise("should not raise")
    self.assertEqual(http_proc.reqcount, 1)


class TestSsconfResolver(unittest.TestCase):
  def testSsconfLookup(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    node_addr_list = [" ".join(t) for t in zip(node_list, addr_list)]
    ssc = GetFakeSimpleStoreClass(lambda _: node_addr_list)
    result = rpc._SsconfResolver(True, node_list, NotImplemented,
                                 ssc=ssc, nslookup_fn=NotImplemented)
    self.assertEqual(result, zip(node_list, addr_list, node_list))

  def testNsLookup(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    ssc = GetFakeSimpleStoreClass(lambda _: [])
    node_addr_map = dict(zip(node_list, addr_list))
    nslookup_fn = lambda name, family=None: node_addr_map.get(name)
    result = rpc._SsconfResolver(True, node_list, NotImplemented,
                                 ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, zip(node_list, addr_list, node_list))

  def testDisabledSsconfIp(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    ssc = GetFakeSimpleStoreClass(_RaiseNotImplemented)
    node_addr_map = dict(zip(node_list, addr_list))
    nslookup_fn = lambda name, family=None: node_addr_map.get(name)
    result = rpc._SsconfResolver(False, node_list, NotImplemented,
                                 ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, zip(node_list, addr_list, node_list))

  def testBothLookups(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    n = len(addr_list) // 2
    node_addr_list = [" ".join(t) for t in zip(node_list[n:], addr_list[n:])]
    ssc = GetFakeSimpleStoreClass(lambda _: node_addr_list)
    node_addr_map = dict(zip(node_list[:n], addr_list[:n]))
    nslookup_fn = lambda name, family=None: node_addr_map.get(name)
    result = rpc._SsconfResolver(True, node_list, NotImplemented,
                                 ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, zip(node_list, addr_list, node_list))

  def testAddressLookupIPv6(self):
    addr_list = ["2001:db8::%d" % n for n in range(0, 255, 11)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 11)]
    node_addr_list = [" ".join(t) for t in zip(node_list, addr_list)]
    ssc = GetFakeSimpleStoreClass(lambda _: node_addr_list)
    result = rpc._SsconfResolver(True, node_list, NotImplemented,
                                 ssc=ssc, nslookup_fn=NotImplemented)
    self.assertEqual(result, zip(node_list, addr_list, node_list))


class TestStaticResolver(unittest.TestCase):
  def test(self):
    addresses = ["192.0.2.%d" % n for n in range(0, 123, 7)]
    nodes = ["node%s.example.com" % n for n in range(0, 123, 7)]
    res = rpc._StaticResolver(addresses)
    self.assertEqual(res(nodes, NotImplemented), zip(nodes, addresses, nodes))

  def testWrongLength(self):
    res = rpc._StaticResolver([])
    self.assertRaises(AssertionError, res, ["abc"], NotImplemented)


class TestNodeConfigResolver(unittest.TestCase):
  @staticmethod
  def _GetSingleOnlineNode(uuid):
    assert uuid == "node90-uuid"
    return objects.Node(name="node90.example.com",
                        uuid=uuid,
                        offline=False,
                        primary_ip="192.0.2.90")

  @staticmethod
  def _GetSingleOfflineNode(uuid):
    assert uuid == "node100-uuid"
    return objects.Node(name="node100.example.com",
                        uuid=uuid,
                        offline=True,
                        primary_ip="192.0.2.100")

  def testSingleOnline(self):
    self.assertEqual(rpc._NodeConfigResolver(self._GetSingleOnlineNode,
                                             NotImplemented,
                                             ["node90-uuid"], None),
                     [("node90.example.com", "192.0.2.90", "node90-uuid")])

  def testSingleOffline(self):
    self.assertEqual(rpc._NodeConfigResolver(self._GetSingleOfflineNode,
                                             NotImplemented,
                                             ["node100-uuid"], None),
                     [("node100.example.com", rpc._OFFLINE, "node100-uuid")])

  def testSingleOfflineWithAcceptOffline(self):
    fn = self._GetSingleOfflineNode
    assert fn("node100-uuid").offline
    self.assertEqual(rpc._NodeConfigResolver(fn, NotImplemented,
                                             ["node100-uuid"],
                                             rpc_defs.ACCEPT_OFFLINE_NODE),
                     [("node100.example.com", "192.0.2.100", "node100-uuid")])
    for i in [False, True, "", "Hello", 0, 1]:
      self.assertRaises(AssertionError, rpc._NodeConfigResolver,
                        fn, NotImplemented, ["node100.example.com"], i)

  def testUnknownSingleNode(self):
    self.assertEqual(rpc._NodeConfigResolver(lambda _: None, NotImplemented,
                                             ["node110.example.com"], None),
                     [("node110.example.com", "node110.example.com",
                       "node110.example.com")])

  def testMultiEmpty(self):
    self.assertEqual(rpc._NodeConfigResolver(NotImplemented,
                                             lambda: {},
                                             [], None),
                     [])

  def testMultiSomeOffline(self):
    nodes = dict(("node%s-uuid" % i,
                  objects.Node(name="node%s.example.com" % i,
                               offline=((i % 3) == 0),
                               primary_ip="192.0.2.%s" % i,
                               uuid="node%s-uuid" % i))
                  for i in range(1, 255))

    # Resolve no names
    self.assertEqual(rpc._NodeConfigResolver(NotImplemented,
                                             lambda: nodes,
                                             [], None),
                     [])

    # Offline, online and unknown hosts
    self.assertEqual(rpc._NodeConfigResolver(NotImplemented,
                                             lambda: nodes,
                                             ["node3-uuid",
                                              "node92-uuid",
                                              "node54-uuid",
                                              "unknown.example.com",],
                                             None), [
      ("node3.example.com", rpc._OFFLINE, "node3-uuid"),
      ("node92.example.com", "192.0.2.92", "node92-uuid"),
      ("node54.example.com", rpc._OFFLINE, "node54-uuid"),
      ("unknown.example.com", "unknown.example.com", "unknown.example.com"),
      ])


class TestCompress(unittest.TestCase):
  def test(self):
    for data in ["", "Hello", "Hello World!\nnew\nlines"]:
      self.assertEqual(rpc._Compress(NotImplemented, data),
                       (constants.RPC_ENCODING_NONE, data))

    for data in [512 * " ", 5242 * "Hello World!\n"]:
      compressed = rpc._Compress(NotImplemented, data)
      self.assertEqual(len(compressed), 2)
      self.assertEqual(backend._Decompress(compressed), data)

  def testDecompression(self):
    self.assertRaises(AssertionError, backend._Decompress, "")
    self.assertRaises(AssertionError, backend._Decompress, [""])
    self.assertRaises(AssertionError, backend._Decompress,
                      ("unknown compression", "data"))
    self.assertRaises(Exception, backend._Decompress,
                      (constants.RPC_ENCODING_ZLIB_BASE64, "invalid zlib data"))


class TestRpcClientBase(unittest.TestCase):
  def testNoHosts(self):
    cdef = ("test_call", NotImplemented, None, constants.RPC_TMO_SLOW, [],
            None, None, NotImplemented)
    http_proc = _FakeRequestProcessor(NotImplemented)
    client = rpc._RpcClientBase(rpc._StaticResolver([]), NotImplemented,
                                _req_process_fn=http_proc)
    self.assertEqual(client._Call(cdef, [], []), {})

    # Test wrong number of arguments
    self.assertRaises(errors.ProgrammerError, client._Call,
                      cdef, [], [0, 1, 2])

  def testTimeout(self):
    def _CalcTimeout(args):
      (arg1, arg2) = args
      return arg1 + arg2

    def _VerifyRequest(exp_timeout, req):
      self.assertEqual(req.read_timeout, exp_timeout)

      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, hex(req.read_timeout)))

    resolver = rpc._StaticResolver([
      "192.0.2.1",
      "192.0.2.2",
      ])

    nodes = [
      "node1.example.com",
      "node2.example.com",
      ]

    tests = [(100, None, 100), (30, None, 30)]
    tests.extend((_CalcTimeout, i, i + 300)
                 for i in [0, 5, 16485, 30516])

    for timeout, arg1, exp_timeout in tests:
      cdef = ("test_call", NotImplemented, None, timeout, [
        ("arg1", None, NotImplemented),
        ("arg2", None, NotImplemented),
        ], None, None, NotImplemented)

      http_proc = _FakeRequestProcessor(compat.partial(_VerifyRequest,
                                                       exp_timeout))
      client = rpc._RpcClientBase(resolver, NotImplemented,
                                  _req_process_fn=http_proc)
      result = client._Call(cdef, nodes, [arg1, 300])
      self.assertEqual(len(result), len(nodes))
      self.assertTrue(compat.all(not res.fail_msg and
                                 res.payload == hex(exp_timeout)
                                 for res in result.values()))

  def testArgumentEncoder(self):
    (AT1, AT2) = range(1, 3)

    resolver = rpc._StaticResolver([
      "192.0.2.5",
      "192.0.2.6",
      ])

    nodes = [
      "node5.example.com",
      "node6.example.com",
      ]

    encoders = {
      AT1: lambda _, value: hex(value),
      AT2: lambda _, value: hash(value),
      }

    cdef = ("test_call", NotImplemented, None, constants.RPC_TMO_NORMAL, [
      ("arg0", None, NotImplemented),
      ("arg1", AT1, NotImplemented),
      ("arg1", AT2, NotImplemented),
      ], None, None, NotImplemented)

    def _VerifyRequest(req):
      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, req.post_data))

    http_proc = _FakeRequestProcessor(_VerifyRequest)

    for num in [0, 3796, 9032119]:
      client = rpc._RpcClientBase(resolver, encoders.get,
                                  _req_process_fn=http_proc)
      result = client._Call(cdef, nodes, ["foo", num, "Hello%s" % num])
      self.assertEqual(len(result), len(nodes))
      for res in result.values():
        self.assertFalse(res.fail_msg)
        self.assertEqual(serializer.LoadJson(res.payload),
                         ["foo", hex(num), hash("Hello%s" % num)])

  def testPostProc(self):
    def _VerifyRequest(nums, req):
      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, nums))

    resolver = rpc._StaticResolver([
      "192.0.2.90",
      "192.0.2.95",
      ])

    nodes = [
      "node90.example.com",
      "node95.example.com",
      ]

    def _PostProc(res):
      self.assertFalse(res.fail_msg)
      res.payload = sum(res.payload)
      return res

    cdef = ("test_call", NotImplemented, None, constants.RPC_TMO_NORMAL, [],
            None, _PostProc, NotImplemented)

    # Seeded random generator
    rnd = random.Random(20299)

    for i in [0, 4, 74, 1391]:
      nums = [rnd.randint(0, 1000) for _ in range(i)]
      http_proc = _FakeRequestProcessor(compat.partial(_VerifyRequest, nums))
      client = rpc._RpcClientBase(resolver, NotImplemented,
                                  _req_process_fn=http_proc)
      result = client._Call(cdef, nodes, [])
      self.assertEqual(len(result), len(nodes))
      for res in result.values():
        self.assertFalse(res.fail_msg)
        self.assertEqual(res.payload, sum(nums))

  def testPreProc(self):
    def _VerifyRequest(req):
      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, req.post_data))

    resolver = rpc._StaticResolver([
      "192.0.2.30",
      "192.0.2.35",
      ])

    nodes = [
      "node30.example.com",
      "node35.example.com",
      ]

    def _PreProc(node, data):
      self.assertEqual(len(data), 1)
      return data[0] + node

    cdef = ("test_call", NotImplemented, None, constants.RPC_TMO_NORMAL, [
      ("arg0", None, NotImplemented),
      ], _PreProc, None, NotImplemented)

    http_proc = _FakeRequestProcessor(_VerifyRequest)
    client = rpc._RpcClientBase(resolver, NotImplemented,
                                _req_process_fn=http_proc)

    for prefix in ["foo", "bar", "baz"]:
      result = client._Call(cdef, nodes, [prefix])
      self.assertEqual(len(result), len(nodes))
      for (idx, (node, res)) in enumerate(result.items()):
        self.assertFalse(res.fail_msg)
        self.assertEqual(serializer.LoadJson(res.payload), prefix + node)

  def testResolverOptions(self):
    def _VerifyRequest(req):
      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, req.post_data))

    nodes = [
      "node30.example.com",
      "node35.example.com",
      ]

    def _Resolver(expected, hosts, options):
      self.assertEqual(hosts, nodes)
      self.assertEqual(options, expected)
      return zip(hosts, nodes, hosts)

    def _DynamicResolverOptions(args):
      (arg0, ) = args
      return sum(arg0)

    tests = [
      (None, None, None),
      (rpc_defs.ACCEPT_OFFLINE_NODE, None, rpc_defs.ACCEPT_OFFLINE_NODE),
      (False, None, False),
      (True, None, True),
      (0, None, 0),
      (_DynamicResolverOptions, [1, 2, 3], 6),
      (_DynamicResolverOptions, range(4, 19), 165),
      ]

    for (resolver_opts, arg0, expected) in tests:
      cdef = ("test_call", NotImplemented, resolver_opts,
              constants.RPC_TMO_NORMAL, [
        ("arg0", None, NotImplemented),
        ], None, None, NotImplemented)

      http_proc = _FakeRequestProcessor(_VerifyRequest)

      client = rpc._RpcClientBase(compat.partial(_Resolver, expected),
                                  NotImplemented, _req_process_fn=http_proc)
      result = client._Call(cdef, nodes, [arg0])
      self.assertEqual(len(result), len(nodes))
      for (idx, (node, res)) in enumerate(result.items()):
        self.assertFalse(res.fail_msg)


class _FakeConfigForRpcRunner:
  GetAllNodesInfo = NotImplemented

  def __init__(self, cluster=NotImplemented):
    self._cluster = cluster
    self._disks = [
      objects.Disk(dev_type=constants.DT_PLAIN, size=4096,
                   logical_id=("vg", "disk6120"),
                   uuid="disk_uuid_1"),
      objects.Disk(dev_type=constants.DT_PLAIN, size=1024,
                   logical_id=("vg", "disk8508"),
                   uuid="disk_uuid_2"),
      ]
    for disk in self._disks:
      disk.UpgradeConfig()

  def GetNodeInfo(self, name):
    return objects.Node(name=name)

  def GetMultiNodeInfo(self, names):
    return [(name, self.GetNodeInfo(name)) for name in names]

  def GetClusterInfo(self):
    return self._cluster

  def GetInstanceDiskParams(self, _):
    return constants.DISK_DT_DEFAULTS

  def GetInstanceSecondaryNodes(self, _):
    return []

  def GetInstanceDisks(self, _):
    return self._disks


class TestRpcRunner(unittest.TestCase):
  def testUploadFile(self):
    data = 1779 * "Hello World\n"

    tmpfile = tempfile.NamedTemporaryFile()
    tmpfile.write(data)
    tmpfile.flush()
    st = os.stat(tmpfile.name)

    nodes = [
      "node1.example.com",
      ]

    def _VerifyRequest(req):
      (uldata, ) = serializer.LoadJson(req.post_data)
      self.assertEqual(len(uldata), 7)
      self.assertEqual(uldata[0], tmpfile.name)
      self.assertEqual(list(uldata[1]), list(rpc._Compress(nodes[0], data)))
      self.assertEqual(uldata[2], st.st_mode)
      self.assertEqual(uldata[3], "user%s" % os.getuid())
      self.assertEqual(uldata[4], "group%s" % os.getgid())
      self.assertTrue(uldata[5] is not None)
      self.assertEqual(uldata[6], st.st_mtime)

      req.success = True
      req.resp_status_code = http.HTTP_OK
      req.resp_body = serializer.DumpJson((True, None))

    http_proc = _FakeRequestProcessor(_VerifyRequest)

    std_runner = rpc.RpcRunner(_FakeConfigForRpcRunner(), None,
                               _req_process_fn=http_proc,
                               _getents=mocks.FakeGetentResolver)

    cfg_runner = rpc.ConfigRunner(None, ["192.0.2.13"],
                                  _req_process_fn=http_proc,
                                  _getents=mocks.FakeGetentResolver)

    for runner in [std_runner, cfg_runner]:
      result = runner.call_upload_file(nodes, tmpfile.name)
      self.assertEqual(len(result), len(nodes))
      for (idx, (node, res)) in enumerate(result.items()):
        self.assertFalse(res.fail_msg)

  def testEncodeInstance(self):
    cluster = objects.Cluster(hvparams={
      constants.HT_KVM: {
        constants.HV_CDROM_IMAGE_PATH: "foo",
        },
      },
      beparams={
        constants.PP_DEFAULT: {
          constants.BE_MAXMEM: 8192,
          },
        },
      os_hvp={},
      osparams={
        "linux": {
          "role": "unknown",
          },
        })
    cluster.UpgradeConfig()

    inst = objects.Instance(name="inst1.example.com",
      hypervisor=constants.HT_KVM,
      os="linux",
      hvparams={
        constants.HV_CDROM_IMAGE_PATH: "bar",
        constants.HV_ROOT_PATH: "/tmp",
        },
      beparams={
        constants.BE_MINMEM: 128,
        constants.BE_MAXMEM: 256,
        },
      nics=[
        objects.NIC(nicparams={
          constants.NIC_MODE: "mymode",
          }),
        ],
      disk_template=constants.DT_PLAIN,
      disks=["disk_uuid_1", "disk_uuid_2"]
      )
    inst.UpgradeConfig()

    cfg = _FakeConfigForRpcRunner(cluster=cluster)
    runner = rpc.RpcRunner(cfg, None,
                           _req_process_fn=NotImplemented,
                           _getents=mocks.FakeGetentResolver)

    def _CheckBasics(result):
      self.assertEqual(result["name"], "inst1.example.com")
      self.assertEqual(result["os"], "linux")
      self.assertEqual(result["beparams"][constants.BE_MINMEM], 128)
      self.assertEqual(len(result["nics"]), 1)
      self.assertEqual(result["nics"][0]["nicparams"][constants.NIC_MODE],
                       "mymode")

    # Generic object serialization
    result = runner._encoder(NotImplemented, (rpc_defs.ED_OBJECT_DICT, inst))
    _CheckBasics(result)
    self.assertEqual(len(result["hvparams"]), 2)

    result = runner._encoder(NotImplemented,
                             (rpc_defs.ED_OBJECT_DICT_LIST, 5 * [inst]))
    for r in result:
      _CheckBasics(r)
      self.assertEqual(len(r["hvparams"]), 2)

    # Just an instance
    result = runner._encoder(NotImplemented, (rpc_defs.ED_INST_DICT, inst))
    _CheckBasics(result)
    self.assertEqual(result["beparams"][constants.BE_MAXMEM], 256)
    self.assertEqual(result["hvparams"][constants.HV_CDROM_IMAGE_PATH], "bar")
    self.assertEqual(result["hvparams"][constants.HV_ROOT_PATH], "/tmp")
    self.assertEqual(result["osparams"], {
      "role": "unknown",
      })
    self.assertEqual(len(result["hvparams"]),
                     len(constants.HVC_DEFAULTS[constants.HT_KVM]))

    # Instance with OS parameters
    result = runner._encoder(NotImplemented,
                             (rpc_defs.ED_INST_DICT_OSP_DP, (inst, {
                               "role": "webserver",
                               "other": "field",
                             })))
    _CheckBasics(result)
    self.assertEqual(result["beparams"][constants.BE_MAXMEM], 256)
    self.assertEqual(result["hvparams"][constants.HV_CDROM_IMAGE_PATH], "bar")
    self.assertEqual(result["hvparams"][constants.HV_ROOT_PATH], "/tmp")
    self.assertEqual(result["osparams"], {
      "role": "webserver",
      "other": "field",
      })

    # Instance with hypervisor and backend parameters
    result = runner._encoder(NotImplemented,
                             (rpc_defs.ED_INST_DICT_HVP_BEP_DP, (inst, {
      constants.HT_KVM: {
        constants.HV_BOOT_ORDER: "xyz",
        },
      }, {
      constants.BE_VCPUS: 100,
      constants.BE_MAXMEM: 4096,
      })))
    _CheckBasics(result)
    self.assertEqual(result["beparams"][constants.BE_MAXMEM], 4096)
    self.assertEqual(result["beparams"][constants.BE_VCPUS], 100)
    self.assertEqual(result["hvparams"][constants.HT_KVM], {
      constants.HV_BOOT_ORDER: "xyz",
      })
    del result["disks_info"][0]["ctime"]
    del result["disks_info"][0]["mtime"]
    del result["disks_info"][1]["ctime"]
    del result["disks_info"][1]["mtime"]
    self.assertEqual(result["disks_info"], [{
      "dev_type": constants.DT_PLAIN,
      "dynamic_params": {},
      "size": 4096,
      "logical_id": ("vg", "disk6120"),
      "params": constants.DISK_DT_DEFAULTS[inst.disk_template],
      "serial_no": 1,
      "uuid": "disk_uuid_1",
      }, {
      "dev_type": constants.DT_PLAIN,
      "dynamic_params": {},
      "size": 1024,
      "logical_id": ("vg", "disk8508"),
      "params": constants.DISK_DT_DEFAULTS[inst.disk_template],
      "serial_no": 1,
      "uuid": "disk_uuid_2",
      }])

    inst_disks = cfg.GetInstanceDisks(inst.uuid)
    self.assertTrue(compat.all(disk.params == {} for disk in inst_disks),
                    msg="Configuration objects were modified")


class TestLegacyNodeInfo(unittest.TestCase):
  KEY_BOOT = "bootid"
  KEY_NAME = "name"
  KEY_STORAGE_FREE = "storage_free"
  KEY_STORAGE_TOTAL = "storage_size"
  KEY_CPU_COUNT = "cpu_count"
  KEY_SPINDLES_FREE = "spindles_free"
  KEY_SPINDLES_TOTAL = "spindles_total"
  KEY_STORAGE_TYPE = "type" # key for storage type
  VAL_BOOT = 0
  VAL_VG_NAME = "xy"
  VAL_VG_FREE = 11
  VAL_VG_TOTAL = 12
  VAL_VG_TYPE = "lvm-vg"
  VAL_CPU_COUNT = 2
  VAL_PV_NAME = "ab"
  VAL_PV_FREE = 31
  VAL_PV_TOTAL = 32
  VAL_PV_TYPE = "lvm-pv"
  DICT_VG = {
    KEY_NAME: VAL_VG_NAME,
    KEY_STORAGE_FREE: VAL_VG_FREE,
    KEY_STORAGE_TOTAL: VAL_VG_TOTAL,
    KEY_STORAGE_TYPE: VAL_VG_TYPE,
    }
  DICT_HV = {KEY_CPU_COUNT: VAL_CPU_COUNT}
  DICT_SP = {
    KEY_STORAGE_TYPE: VAL_PV_TYPE,
    KEY_NAME: VAL_PV_NAME,
    KEY_STORAGE_FREE: VAL_PV_FREE,
    KEY_STORAGE_TOTAL: VAL_PV_TOTAL,
    }
  STD_LST = [VAL_BOOT, [DICT_VG, DICT_SP], [DICT_HV]]
  STD_DICT = {
    KEY_BOOT: VAL_BOOT,
    KEY_NAME: VAL_VG_NAME,
    KEY_STORAGE_FREE: VAL_VG_FREE,
    KEY_STORAGE_TOTAL: VAL_VG_TOTAL,
    KEY_SPINDLES_FREE: VAL_PV_FREE,
    KEY_SPINDLES_TOTAL: VAL_PV_TOTAL,
    KEY_CPU_COUNT: VAL_CPU_COUNT,
    }

  def testWithSpindles(self):
    result = rpc.MakeLegacyNodeInfo(self.STD_LST, constants.DT_PLAIN)
    self.assertEqual(result, self.STD_DICT)

  def testNoSpindles(self):
    my_lst = [self.VAL_BOOT, [self.DICT_VG], [self.DICT_HV]]
    result = rpc.MakeLegacyNodeInfo(my_lst, constants.DT_PLAIN)
    expected_dict = dict((k,v) for k, v in self.STD_DICT.items())
    expected_dict[self.KEY_SPINDLES_FREE] = 0
    expected_dict[self.KEY_SPINDLES_TOTAL] = 0
    self.assertEqual(result, expected_dict)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
