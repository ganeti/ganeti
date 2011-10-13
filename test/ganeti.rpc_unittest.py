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


"""Script for testing ganeti.rpc"""

import os
import sys
import unittest

from ganeti import constants
from ganeti import compat
from ganeti import rpc
from ganeti import http
from ganeti import errors
from ganeti import serializer
from ganeti import objects

import testutils


class TestTimeouts(unittest.TestCase):
  def test(self):
    names = [name[len("call_"):] for name in dir(rpc.RpcRunner)
             if name.startswith("call_")]
    self.assertEqual(len(names), len(rpc._TIMEOUTS))
    self.assertFalse([name for name in names
                      if not (rpc._TIMEOUTS[name] is None or
                              rpc._TIMEOUTS[name] > 0)])


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


class TestRpcProcessor(unittest.TestCase):
  def _FakeAddressLookup(self, map):
    return lambda node_list: [map.get(node) for node in node_list]

  def _GetVersionResponse(self, req):
    self.assertEqual(req.host, "127.0.0.1")
    self.assertEqual(req.port, 24094)
    self.assertEqual(req.path, "/version")
    self.assertEqual(req.read_timeout, rpc._TMO_URGENT)
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, 123))

  def testVersionSuccess(self):
    resolver = rpc._StaticResolver(["127.0.0.1"])
    http_proc = _FakeRequestProcessor(self._GetVersionResponse)
    proc = rpc._RpcProcessor(resolver, 24094)
    result = proc(["localhost"], "version", None, _req_process_fn=http_proc)
    self.assertEqual(result.keys(), ["localhost"])
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
    result = proc(["node31856"], "version", None, _req_process_fn=http_proc,
                  read_timeout=12356)
    self.assertEqual(result.keys(), ["node31856"])
    lhresp = result["node31856"]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, "node31856")
    self.assertFalse(lhresp.fail_msg)
    self.assertEqual(lhresp.payload, -1)
    self.assertEqual(lhresp.call, "version")
    lhresp.Raise("should not raise")
    self.assertEqual(http_proc.reqcount, 1)

  def testOfflineNode(self):
    resolver = rpc._StaticResolver([rpc._OFFLINE])
    http_proc = _FakeRequestProcessor(NotImplemented)
    proc = rpc._RpcProcessor(resolver, 30668)
    result = proc(["n17296"], "version", None, _req_process_fn=http_proc)
    self.assertEqual(result.keys(), ["n17296"])
    lhresp = result["n17296"]
    self.assertTrue(lhresp.offline)
    self.assertEqual(lhresp.node, "n17296")
    self.assertTrue(lhresp.fail_msg)
    self.assertFalse(lhresp.payload)
    self.assertEqual(lhresp.call, "version")

    # With a message
    self.assertRaises(errors.OpExecError, lhresp.Raise, "should raise")

    # No message
    self.assertRaises(errors.OpExecError, lhresp.Raise, None)

    self.assertEqual(http_proc.reqcount, 0)

  def _GetMultiVersionResponse(self, req):
    self.assert_(req.host.startswith("node"))
    self.assertEqual(req.port, 23245)
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, 987))

  def testMultiVersionSuccess(self):
    nodes = ["node%s" % i for i in range(50)]
    resolver = rpc._StaticResolver(nodes)
    http_proc = _FakeRequestProcessor(self._GetMultiVersionResponse)
    proc = rpc._RpcProcessor(resolver, 23245)
    result = proc(nodes, "version", None, _req_process_fn=http_proc)
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
      result = proc(["aef9ur4i.example.com"], "version", None,
                    _req_process_fn=http_proc)
      self.assertEqual(result.keys(), ["aef9ur4i.example.com"])
      lhresp = result["aef9ur4i.example.com"]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, "aef9ur4i.example.com")
      self.assert_(lhresp.fail_msg)
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
    result = proc(nodes, "vg_list", None, _req_process_fn=http_proc)
    self.assertEqual(sorted(result.keys()), sorted(nodes))

    for name in nodes:
      lhresp = result[name]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, name)
      self.assertEqual(lhresp.call, "vg_list")

      if name in httperrnodes:
        self.assert_(lhresp.fail_msg)
        self.assertRaises(errors.OpExecError, lhresp.Raise, "failed")
      elif name in failnodes:
        self.assert_(lhresp.fail_msg)
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
      result = proc(["oqo7lanhly.example.com"], "version", None,
                    _req_process_fn=http_proc)
      self.assertEqual(result.keys(), ["oqo7lanhly.example.com"])
      lhresp = result["oqo7lanhly.example.com"]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, "oqo7lanhly.example.com")
      self.assert_(lhresp.fail_msg)
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
    body = serializer.DumpJson(test_data)
    result = proc(["node19759"], "upload_file", body, _req_process_fn=http_proc)
    self.assertEqual(result.keys(), ["node19759"])
    lhresp = result["node19759"]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, "node19759")
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
    result = rpc._SsconfResolver(node_list, ssc=ssc, nslookup_fn=NotImplemented)
    self.assertEqual(result, zip(node_list, addr_list))

  def testNsLookup(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    ssc = GetFakeSimpleStoreClass(lambda _: [])
    node_addr_map = dict(zip(node_list, addr_list))
    nslookup_fn = lambda name, family=None: node_addr_map.get(name)
    result = rpc._SsconfResolver(node_list, ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, zip(node_list, addr_list))

  def testBothLookups(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    n = len(addr_list) / 2
    node_addr_list = [" ".join(t) for t in zip(node_list[n:], addr_list[n:])]
    ssc = GetFakeSimpleStoreClass(lambda _: node_addr_list)
    node_addr_map = dict(zip(node_list[:n], addr_list[:n]))
    nslookup_fn = lambda name, family=None: node_addr_map.get(name)
    result = rpc._SsconfResolver(node_list, ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, zip(node_list, addr_list))

  def testAddressLookupIPv6(self):
    addr_list = ["2001:db8::%d" % n for n in range(0, 255, 11)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 11)]
    node_addr_list = [" ".join(t) for t in zip(node_list, addr_list)]
    ssc = GetFakeSimpleStoreClass(lambda _: node_addr_list)
    result = rpc._SsconfResolver(node_list, ssc=ssc, nslookup_fn=NotImplemented)
    self.assertEqual(result, zip(node_list, addr_list))


class TestStaticResolver(unittest.TestCase):
  def test(self):
    addresses = ["192.0.2.%d" % n for n in range(0, 123, 7)]
    nodes = ["node%s.example.com" % n for n in range(0, 123, 7)]
    res = rpc._StaticResolver(addresses)
    self.assertEqual(res(nodes), zip(nodes, addresses))

  def testWrongLength(self):
    res = rpc._StaticResolver([])
    self.assertRaises(AssertionError, res, ["abc"])


class TestNodeConfigResolver(unittest.TestCase):
  @staticmethod
  def _GetSingleOnlineNode(name):
    assert name == "node90.example.com"
    return objects.Node(name=name, offline=False, primary_ip="192.0.2.90")

  @staticmethod
  def _GetSingleOfflineNode(name):
    assert name == "node100.example.com"
    return objects.Node(name=name, offline=True, primary_ip="192.0.2.100")

  def testSingleOnline(self):
    self.assertEqual(rpc._NodeConfigResolver(self._GetSingleOnlineNode,
                                             NotImplemented,
                                             ["node90.example.com"]),
                     [("node90.example.com", "192.0.2.90")])

  def testSingleOffline(self):
    self.assertEqual(rpc._NodeConfigResolver(self._GetSingleOfflineNode,
                                             NotImplemented,
                                             ["node100.example.com"]),
                     [("node100.example.com", rpc._OFFLINE)])

  def testUnknownSingleNode(self):
    self.assertEqual(rpc._NodeConfigResolver(lambda _: None, NotImplemented,
                                             ["node110.example.com"]),
                     [("node110.example.com", "node110.example.com")])

  def testMultiEmpty(self):
    self.assertEqual(rpc._NodeConfigResolver(NotImplemented,
                                             lambda: {},
                                             []),
                     [])

  def testMultiSomeOffline(self):
    nodes = dict(("node%s.example.com" % i,
                  objects.Node(name="node%s.example.com" % i,
                               offline=((i % 3) == 0),
                               primary_ip="192.0.2.%s" % i))
                  for i in range(1, 255))

    # Resolve no names
    self.assertEqual(rpc._NodeConfigResolver(NotImplemented,
                                             lambda: nodes,
                                             []),
                     [])

    # Offline, online and unknown hosts
    self.assertEqual(rpc._NodeConfigResolver(NotImplemented,
                                             lambda: nodes,
                                             ["node3.example.com",
                                              "node92.example.com",
                                              "node54.example.com",
                                              "unknown.example.com",]), [
      ("node3.example.com", rpc._OFFLINE),
      ("node92.example.com", "192.0.2.92"),
      ("node54.example.com", rpc._OFFLINE),
      ("unknown.example.com", "unknown.example.com"),
      ])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
