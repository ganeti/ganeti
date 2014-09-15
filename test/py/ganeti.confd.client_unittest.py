#!/usr/bin/python
#

# Copyright (C) 2009 Google Inc.
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


"""Script for unittesting the confd client module"""


import socket
import unittest

from ganeti import confd
from ganeti import constants
from ganeti import errors

import ganeti.confd.client

import testutils


class ResettableMock(object):
  def __init__(self, *args, **kwargs):
    self.Reset()

  def Reset(self):
    pass


class MockLogger(ResettableMock):
  def Reset(self):
    self.debug_count = 0
    self.warn_count = 0
    self.error_count = 0

  def debug(string):
    self.debug_count += 1

  def warning(string):
    self.warn_count += 1

  def error(string):
    self.error_count += 1

class MockConfdAsyncUDPClient(ResettableMock):
  def Reset(self):
    self.send_count = 0
    self.last_address = ''
    self.last_port = -1
    self.last_sent = ''

  def enqueue_send(self, address, port, payload):
    self.send_count += 1
    self.last_payload = payload
    self.last_port = port
    self.last_address = address

class MockCallback(ResettableMock):
  def Reset(self):
    self.call_count = 0
    self.last_up = None

  def __call__(self, up):
    """Callback

    @type up: L{ConfdUpcallPayload}
    @param up: upper callback

    """
    self.call_count += 1
    self.last_up = up


class MockTime(ResettableMock):
  def Reset(self):
    self.mytime  = 1254213006.5175071

  def time(self):
    return self.mytime

  def increase(self, delta):
    self.mytime += delta


class _BaseClientTest:
  """Base class for client tests"""
  mc_list = None
  new_peers = None
  family = None

  def setUp(self):
    self.mock_time = MockTime()
    confd.client.time = self.mock_time
    confd.client.ConfdAsyncUDPClient = MockConfdAsyncUDPClient
    self.logger = MockLogger()
    hmac_key = "mykeydata"
    self.callback = MockCallback()
    self.client = confd.client.ConfdClient(hmac_key, self.mc_list,
                                           self.callback, logger=self.logger)

  def testRequest(self):
    req1 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.assertNotEqual(req1.rsalt, req2.rsalt)
    self.assertEqual(req1.protocol, constants.CONFD_PROTOCOL_VERSION)
    self.assertEqual(req2.protocol, constants.CONFD_PROTOCOL_VERSION)
    self.assertRaises(errors.ConfdClientError, confd.client.ConfdClientRequest,
                      type=-33)

  def testClientSend(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    # Cannot send the same request twice
    self.assertRaises(errors.ConfdClientError, self.client.SendRequest, req)
    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    # Coverage is too big
    self.assertRaises(errors.ConfdClientError, self.client.SendRequest,
                      req2, coverage=15)
    self.assertEquals(self.client._socket.send_count,
                      constants.CONFD_DEFAULT_REQ_COVERAGE)
    # Send with max coverage
    self.client.SendRequest(req2, coverage=-1)
    self.assertEquals(self.client._socket.send_count,
                      constants.CONFD_DEFAULT_REQ_COVERAGE + len(self.mc_list))
    self.assert_(self.client._socket.last_address in self.mc_list)


  def testClientExpire(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    # Make a couple of seconds pass ;)
    self.mock_time.increase(2)
    # Now sending the second request
    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req2)
    self.mock_time.increase(constants.CONFD_CLIENT_EXPIRE_TIMEOUT - 1)
    # First request should be expired, second one should not
    self.client.ExpireRequests()
    self.assertEquals(self.callback.call_count, 1)
    self.assertEquals(self.callback.last_up.type, confd.client.UPCALL_EXPIRE)
    self.assertEquals(self.callback.last_up.salt, req.rsalt)
    self.assertEquals(self.callback.last_up.orig_request, req)
    self.mock_time.increase(3)
    self.assertEquals(self.callback.call_count, 1)
    self.client.ExpireRequests()
    self.assertEquals(self.callback.call_count, 2)
    self.assertEquals(self.callback.last_up.type, confd.client.UPCALL_EXPIRE)
    self.assertEquals(self.callback.last_up.salt, req2.rsalt)
    self.assertEquals(self.callback.last_up.orig_request, req2)

  def testClientCascadeExpire(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    self.mock_time.increase(constants.CONFD_CLIENT_EXPIRE_TIMEOUT +1)
    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req2)
    self.assertEquals(self.callback.call_count, 1)

  def testUpdatePeerList(self):
    self.client.UpdatePeerList(self.new_peers)
    self.assertEquals(self.client._peers, self.new_peers)
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    self.assertEquals(self.client._socket.send_count, len(self.new_peers))
    self.assert_(self.client._socket.last_address in self.new_peers)

  def testSetPeersFamily(self):
    self.client._SetPeersAddressFamily()
    self.assertEquals(self.client._family, self.family)
    mixed_peers = ["192.0.2.99", "2001:db8:beef::13"]
    self.client.UpdatePeerList(mixed_peers)
    self.assertRaises(errors.ConfdClientError,
                      self.client._SetPeersAddressFamily)


class TestIP4Client(unittest.TestCase, _BaseClientTest):
  """Client tests"""
  mc_list = ["192.0.2.1",
             "192.0.2.2",
             "192.0.2.3",
             "192.0.2.4",
             "192.0.2.5",
             "192.0.2.6",
             "192.0.2.7",
             "192.0.2.8",
             "192.0.2.9",
            ]
  new_peers = ["198.51.100.1", "198.51.100.2"]
  family = socket.AF_INET

  def setUp(self):
    unittest.TestCase.setUp(self)
    _BaseClientTest.setUp(self)


class TestIP6Client(unittest.TestCase, _BaseClientTest):
  """Client tests"""
  mc_list = ["2001:db8::1",
             "2001:db8::2",
             "2001:db8::3",
             "2001:db8::4",
             "2001:db8::5",
             "2001:db8::6",
             "2001:db8::7",
             "2001:db8::8",
             "2001:db8::9",
            ]
  new_peers = ["2001:db8:beef::11", "2001:db8:beef::12"]
  family = socket.AF_INET6

  def setUp(self):
    unittest.TestCase.setUp(self)
    _BaseClientTest.setUp(self)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
