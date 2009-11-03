#!/usr/bin/python
#

# Copyright (C) 2009 Google Inc.
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
# 0.0510-1301, USA.


"""Script for unittesting the confd client module"""


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


class TestClient(unittest.TestCase):
  """Client tests"""

  def setUp(self):
    self.mock_time = MockTime()
    confd.client.time = self.mock_time
    confd.client.ConfdAsyncUDPClient = MockConfdAsyncUDPClient
    self.logger = MockLogger()
    hmac_key = "mykeydata"
    self.mc_list = ['10.0.0.1',
                    '10.0.0.2',
                    '10.0.0.3',
                    '10.0.0.4',
                    '10.0.0.5',
                    '10.0.0.6',
                    '10.0.0.7',
                    '10.0.0.8',
                    '10.0.0.9',
                   ]
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
    new_peers = ['1.2.3.4', '1.2.3.5']
    self.client.UpdatePeerList(new_peers)
    self.assertEquals(self.client._peers, new_peers)
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    self.assertEquals(self.client._socket.send_count, len(new_peers))
    self.assert_(self.client._socket.last_address in new_peers)


if __name__ == '__main__':
  testutils.GanetiTestProgram()
