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

import testutils


class TestTimeouts(unittest.TestCase):
  def test(self):
    names = [name[len("call_"):] for name in dir(rpc.RpcRunner)
             if name.startswith("call_")]
    self.assertEqual(len(names), len(rpc._TIMEOUTS))
    self.assertFalse([name for name in names
                      if not (rpc._TIMEOUTS[name] is None or
                              rpc._TIMEOUTS[name] > 0)])


class FakeHttpPool:
  def __init__(self, response_fn):
    self._response_fn = response_fn
    self.reqcount = 0

  def ProcessRequests(self, reqs):
    for req in reqs:
      self.reqcount += 1
      self._response_fn(req)


def GetFakeSimpleStoreClass(fn):
  class FakeSimpleStore:
    GetNodePrimaryIPList = fn

  return FakeSimpleStore


class TestClient(unittest.TestCase):
  def _FakeAddressLookup(self, map):
    return lambda node_list: [map.get(node) for node in node_list]

  def _GetVersionResponse(self, req):
    self.assertEqual(req.host, "localhost")
    self.assertEqual(req.port, 24094)
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, 123))

  def testVersionSuccess(self):
    fn = self._FakeAddressLookup({"localhost": "localhost"})
    client = rpc.Client("version", None, 24094, address_lookup_fn=fn)
    client.ConnectNode("localhost")
    pool = FakeHttpPool(self._GetVersionResponse)
    result = client.GetResults(http_pool=pool)
    self.assertEqual(result.keys(), ["localhost"])
    lhresp = result["localhost"]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, "localhost")
    self.assertFalse(lhresp.fail_msg)
    self.assertEqual(lhresp.payload, 123)
    self.assertEqual(lhresp.call, "version")
    lhresp.Raise("should not raise")
    self.assertEqual(pool.reqcount, 1)

  def _GetMultiVersionResponse(self, req):
    self.assert_(req.host.startswith("node"))
    self.assertEqual(req.port, 23245)
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((True, 987))

  def testMultiVersionSuccess(self):
    nodes = ["node%s" % i for i in range(50)]
    fn = self._FakeAddressLookup(dict(zip(nodes, nodes)))
    client = rpc.Client("version", None, 23245, address_lookup_fn=fn)
    client.ConnectList(nodes)

    pool = FakeHttpPool(self._GetMultiVersionResponse)
    result = client.GetResults(http_pool=pool)
    self.assertEqual(sorted(result.keys()), sorted(nodes))

    for name in nodes:
      lhresp = result[name]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, name)
      self.assertFalse(lhresp.fail_msg)
      self.assertEqual(lhresp.payload, 987)
      self.assertEqual(lhresp.call, "version")
      lhresp.Raise("should not raise")

    self.assertEqual(pool.reqcount, len(nodes))

  def _GetVersionResponseFail(self, req):
    self.assertEqual(req.path, "/version")
    req.success = True
    req.resp_status_code = http.HTTP_OK
    req.resp_body = serializer.DumpJson((False, "Unknown error"))

  def testVersionFailure(self):
    lookup_map = {"aef9ur4i.example.com": "aef9ur4i.example.com"}
    fn = self._FakeAddressLookup(lookup_map)
    client = rpc.Client("version", None, 5903, address_lookup_fn=fn)
    client.ConnectNode("aef9ur4i.example.com")
    pool = FakeHttpPool(self._GetVersionResponseFail)
    result = client.GetResults(http_pool=pool)
    self.assertEqual(result.keys(), ["aef9ur4i.example.com"])
    lhresp = result["aef9ur4i.example.com"]
    self.assertFalse(lhresp.offline)
    self.assertEqual(lhresp.node, "aef9ur4i.example.com")
    self.assert_(lhresp.fail_msg)
    self.assertFalse(lhresp.payload)
    self.assertEqual(lhresp.call, "version")
    self.assertRaises(errors.OpExecError, lhresp.Raise, "failed")
    self.assertEqual(pool.reqcount, 1)

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
    fn = self._FakeAddressLookup(dict(zip(nodes, nodes)))

    httperrnodes = set(nodes[1::7])
    self.assertEqual(len(httperrnodes), 7)

    failnodes = set(nodes[2::3]) - httperrnodes
    self.assertEqual(len(failnodes), 14)

    self.assertEqual(len(set(nodes) - failnodes - httperrnodes), 29)

    client = rpc.Client("vg_list", None, 15165, address_lookup_fn=fn)
    client.ConnectList(nodes)

    pool = FakeHttpPool(compat.partial(self._GetHttpErrorResponse,
                                       httperrnodes, failnodes))
    result = client.GetResults(http_pool=pool)
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

    self.assertEqual(pool.reqcount, len(nodes))

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
    lookup_map = {"oqo7lanhly.example.com": "oqo7lanhly.example.com"}
    fn = self._FakeAddressLookup(lookup_map)
    client = rpc.Client("version", None, 19978, address_lookup_fn=fn)
    for fn in [self._GetInvalidResponseA, self._GetInvalidResponseB]:
      client.ConnectNode("oqo7lanhly.example.com")
      pool = FakeHttpPool(fn)
      result = client.GetResults(http_pool=pool)
      self.assertEqual(result.keys(), ["oqo7lanhly.example.com"])
      lhresp = result["oqo7lanhly.example.com"]
      self.assertFalse(lhresp.offline)
      self.assertEqual(lhresp.node, "oqo7lanhly.example.com")
      self.assert_(lhresp.fail_msg)
      self.assertFalse(lhresp.payload)
      self.assertEqual(lhresp.call, "version")
      self.assertRaises(errors.OpExecError, lhresp.Raise, "failed")
      self.assertEqual(pool.reqcount, 1)

  def testAddressLookupSimpleStore(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    node_addr_list = [ " ".join(t) for t in zip(node_list, addr_list)]
    ssc = GetFakeSimpleStoreClass(lambda s: node_addr_list)
    result = rpc._AddressLookup(node_list, ssc=ssc)
    self.assertEqual(result, addr_list)

  def testAddressLookupNSLookup(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    ssc = GetFakeSimpleStoreClass(lambda s: [])
    node_addr_map = dict(zip(node_list, addr_list))
    nslookup_fn = lambda name: (None, None, [node_addr_map.get(name)])
    result = rpc._AddressLookup(node_list, ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, addr_list)

  def testAddressLookupBoth(self):
    addr_list = ["192.0.2.%d" % n for n in range(0, 255, 13)]
    node_list = ["node%d.example.com" % n for n in range(0, 255, 13)]
    n = len(addr_list) / 2
    node_addr_list = [ " ".join(t) for t in zip(node_list[n:], addr_list[n:])]
    ssc = GetFakeSimpleStoreClass(lambda s: node_addr_list)
    node_addr_map = dict(zip(node_list[:n], addr_list[:n]))
    nslookup_fn = lambda name: (None, None, [node_addr_map.get(name)])
    result = rpc._AddressLookup(node_list, ssc=ssc, nslookup_fn=nslookup_fn)
    self.assertEqual(result, addr_list)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
