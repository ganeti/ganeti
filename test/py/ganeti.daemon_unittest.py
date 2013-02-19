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


"""Script for unittesting the daemon module"""

import unittest
import signal
import os
import socket
import time
import tempfile
import shutil

from ganeti import daemon
from ganeti import errors
from ganeti import constants
from ganeti import utils

import testutils


class TestMainloop(testutils.GanetiTestCase):
  """Test daemon.Mainloop"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    self.sendsig_events = []
    self.onsignal_events = []

  def _CancelEvent(self, handle):
    self.mainloop.scheduler.cancel(handle)

  def _SendSig(self, sig):
    self.sendsig_events.append(sig)
    os.kill(os.getpid(), sig)

  def OnSignal(self, signum):
    self.onsignal_events.append(signum)

  def testRunAndTermBySched(self):
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run() # terminates by _SendSig being scheduled
    self.assertEquals(self.sendsig_events, [signal.SIGTERM])

  def testTerminatingSignals(self):
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGINT])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGCHLD, signal.SIGINT])
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGCHLD, signal.SIGINT,
                                            signal.SIGTERM])

  def testSchedulerCancel(self):
    handle = self.mainloop.scheduler.enter(0.1, 1, self._SendSig,
                                           [signal.SIGTERM])
    self.mainloop.scheduler.cancel(handle)
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGCHLD, signal.SIGTERM])

  def testRegisterSignal(self):
    self.mainloop.RegisterSignal(self)
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    handle = self.mainloop.scheduler.enter(0.1, 1, self._SendSig,
                                           [signal.SIGTERM])
    self.mainloop.scheduler.cancel(handle)
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    # ...not delievered because they are scheduled after TERM
    self.mainloop.scheduler.enter(0.4, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.5, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEquals(self.onsignal_events, self.sendsig_events)

  def testDeferredCancel(self):
    self.mainloop.RegisterSignal(self)
    now = time.time()
    self.mainloop.scheduler.enterabs(now + 0.1, 1, self._SendSig,
                                     [signal.SIGCHLD])
    handle1 = self.mainloop.scheduler.enterabs(now + 0.3, 2, self._SendSig,
                                               [signal.SIGCHLD])
    handle2 = self.mainloop.scheduler.enterabs(now + 0.4, 2, self._SendSig,
                                               [signal.SIGCHLD])
    self.mainloop.scheduler.enterabs(now + 0.2, 1, self._CancelEvent,
                                     [handle1])
    self.mainloop.scheduler.enterabs(now + 0.2, 1, self._CancelEvent,
                                     [handle2])
    self.mainloop.scheduler.enter(0.5, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGCHLD, signal.SIGTERM])
    self.assertEquals(self.onsignal_events, self.sendsig_events)

  def testReRun(self):
    self.mainloop.RegisterSignal(self)
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.scheduler.enter(0.4, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.5, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEquals(self.onsignal_events, self.sendsig_events)
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM,
                       signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEquals(self.onsignal_events, self.sendsig_events)

  def testPriority(self):
    # for events at the same time, the highest priority one executes first
    now = time.time()
    self.mainloop.scheduler.enterabs(now + 0.1, 2, self._SendSig,
                                     [signal.SIGCHLD])
    self.mainloop.scheduler.enterabs(now + 0.1, 1, self._SendSig,
                                     [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events, [signal.SIGTERM])
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEquals(self.sendsig_events,
                      [signal.SIGTERM, signal.SIGCHLD, signal.SIGTERM])


class _MyAsyncUDPSocket(daemon.AsyncUDPSocket):

  def __init__(self, family):
    daemon.AsyncUDPSocket.__init__(self, family)
    self.received = []
    self.error_count = 0

  def handle_datagram(self, payload, ip, port):
    self.received.append((payload))
    if payload == "terminate":
      os.kill(os.getpid(), signal.SIGTERM)
    elif payload == "error":
      raise errors.GenericError("error")

  def handle_error(self):
    self.error_count += 1
    raise


class _BaseAsyncUDPSocketTest:
  """Base class for  AsyncUDPSocket tests"""

  family = None
  address = None

  def setUp(self):
    self.mainloop = daemon.Mainloop()
    self.server = _MyAsyncUDPSocket(self.family)
    self.client = _MyAsyncUDPSocket(self.family)
    self.server.bind((self.address, 0))
    self.port = self.server.getsockname()[1]
    # Save utils.IgnoreSignals so we can do evil things to it...
    self.saved_utils_ignoresignals = utils.IgnoreSignals

  def tearDown(self):
    self.server.close()
    self.client.close()
    # ...and restore it as well
    utils.IgnoreSignals = self.saved_utils_ignoresignals
    testutils.GanetiTestCase.tearDown(self)

  def testNoDoubleBind(self):
    self.assertRaises(socket.error, self.client.bind, (self.address, self.port))

  def testAsyncClientServer(self):
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    self.client.enqueue_send(self.address, self.port, "terminate")
    self.mainloop.Run()
    self.assertEquals(self.server.received, ["p1", "p2", "terminate"])

  def testSyncClientServer(self):
    self.client.handle_write()
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    while self.client.writable():
      self.client.handle_write()
    self.server.process_next_packet()
    self.assertEquals(self.server.received, ["p1"])
    self.server.process_next_packet()
    self.assertEquals(self.server.received, ["p1", "p2"])
    self.client.enqueue_send(self.address, self.port, "p3")
    while self.client.writable():
      self.client.handle_write()
    self.server.process_next_packet()
    self.assertEquals(self.server.received, ["p1", "p2", "p3"])

  def testErrorHandling(self):
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    self.client.enqueue_send(self.address, self.port, "error")
    self.client.enqueue_send(self.address, self.port, "p3")
    self.client.enqueue_send(self.address, self.port, "error")
    self.client.enqueue_send(self.address, self.port, "terminate")
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assertEquals(self.server.received,
                      ["p1", "p2", "error"])
    self.assertEquals(self.server.error_count, 1)
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assertEquals(self.server.received,
                      ["p1", "p2", "error", "p3", "error"])
    self.assertEquals(self.server.error_count, 2)
    self.mainloop.Run()
    self.assertEquals(self.server.received,
                      ["p1", "p2", "error", "p3", "error", "terminate"])
    self.assertEquals(self.server.error_count, 2)

  def testSignaledWhileReceiving(self):
    utils.IgnoreSignals = lambda fn, *args, **kwargs: None
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    self.server.handle_read()
    self.assertEquals(self.server.received, [])
    self.client.enqueue_send(self.address, self.port, "terminate")
    utils.IgnoreSignals = self.saved_utils_ignoresignals
    self.mainloop.Run()
    self.assertEquals(self.server.received, ["p1", "p2", "terminate"])

  def testOversizedDatagram(self):
    oversized_data = (constants.MAX_UDP_DATA_SIZE + 1) * "a"
    self.assertRaises(errors.UdpDataSizeError, self.client.enqueue_send,
                      self.address, self.port, oversized_data)


class TestAsyncIP4UDPSocket(testutils.GanetiTestCase, _BaseAsyncUDPSocketTest):
  """Test IP4 daemon.AsyncUDPSocket"""

  family = socket.AF_INET
  address = "127.0.0.1"

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    _BaseAsyncUDPSocketTest.setUp(self)

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    _BaseAsyncUDPSocketTest.tearDown(self)


class TestAsyncIP6UDPSocket(testutils.GanetiTestCase, _BaseAsyncUDPSocketTest):
  """Test IP6 daemon.AsyncUDPSocket"""

  family = socket.AF_INET6
  address = "::1"

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    _BaseAsyncUDPSocketTest.setUp(self)

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    _BaseAsyncUDPSocketTest.tearDown(self)


class _MyAsyncStreamServer(daemon.AsyncStreamServer):

  def __init__(self, family, address, handle_connection_fn):
    daemon.AsyncStreamServer.__init__(self, family, address)
    self.handle_connection_fn = handle_connection_fn
    self.error_count = 0
    self.expt_count = 0

  def handle_connection(self, connected_socket, client_address):
    self.handle_connection_fn(connected_socket, client_address)

  def handle_error(self):
    self.error_count += 1
    self.close()
    raise

  def handle_expt(self):
    self.expt_count += 1
    self.close()


class _MyMessageStreamHandler(daemon.AsyncTerminatedMessageStream):

  def __init__(self, connected_socket, client_address, terminator, family,
               message_fn, client_id, unhandled_limit):
    daemon.AsyncTerminatedMessageStream.__init__(self, connected_socket,
                                                 client_address,
                                                 terminator, family,
                                                 unhandled_limit)
    self.message_fn = message_fn
    self.client_id = client_id
    self.error_count = 0

  def handle_message(self, message, message_id):
    self.message_fn(self, message, message_id)

  def handle_error(self):
    self.error_count += 1
    raise


class TestAsyncStreamServerTCP(testutils.GanetiTestCase):
  """Test daemon.AsyncStreamServer with a TCP connection"""

  family = socket.AF_INET

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    self.address = self.getAddress()
    self.server = _MyAsyncStreamServer(self.family, self.address,
                                       self.handle_connection)
    self.client_handler = _MyMessageStreamHandler
    self.unhandled_limit = None
    self.terminator = "\3"
    self.address = self.server.getsockname()
    self.clients = []
    self.connections = []
    self.messages = {}
    self.connect_terminate_count = 0
    self.message_terminate_count = 0
    self.next_client_id = 0
    # Save utils.IgnoreSignals so we can do evil things to it...
    self.saved_utils_ignoresignals = utils.IgnoreSignals

  def tearDown(self):
    for c in self.clients:
      c.close()
    for c in self.connections:
      c.close()
    self.server.close()
    # ...and restore it as well
    utils.IgnoreSignals = self.saved_utils_ignoresignals
    testutils.GanetiTestCase.tearDown(self)

  def getAddress(self):
    return ("127.0.0.1", 0)

  def countTerminate(self, name):
    value = getattr(self, name)
    if value is not None:
      value -= 1
      setattr(self, name, value)
      if value <= 0:
        os.kill(os.getpid(), signal.SIGTERM)

  def handle_connection(self, connected_socket, client_address):
    client_id = self.next_client_id
    self.next_client_id += 1
    client_handler = self.client_handler(connected_socket, client_address,
                                         self.terminator, self.family,
                                         self.handle_message,
                                         client_id, self.unhandled_limit)
    self.connections.append(client_handler)
    self.countTerminate("connect_terminate_count")

  def handle_message(self, handler, message, message_id):
    self.messages.setdefault(handler.client_id, [])
    # We should just check that the message_ids are monotonically increasing.
    # If in the unit tests we never remove messages from the received queue,
    # though, we can just require that the queue length is the same as the
    # message id, before pushing the message to it. This forces a more
    # restrictive check, but we can live with this for now.
    self.assertEquals(len(self.messages[handler.client_id]), message_id)
    self.messages[handler.client_id].append(message)
    if message == "error":
      raise errors.GenericError("error")
    self.countTerminate("message_terminate_count")

  def getClient(self):
    client = socket.socket(self.family, socket.SOCK_STREAM)
    client.connect(self.address)
    self.clients.append(client)
    return client

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    self.server.close()

  def testConnect(self):
    self.getClient()
    self.mainloop.Run()
    self.assertEquals(len(self.connections), 1)
    self.getClient()
    self.mainloop.Run()
    self.assertEquals(len(self.connections), 2)
    self.connect_terminate_count = 4
    self.getClient()
    self.getClient()
    self.getClient()
    self.getClient()
    self.mainloop.Run()
    self.assertEquals(len(self.connections), 6)

  def testBasicMessage(self):
    self.connect_terminate_count = None
    client = self.getClient()
    client.send("ciao\3")
    self.mainloop.Run()
    self.assertEquals(len(self.connections), 1)
    self.assertEquals(len(self.messages[0]), 1)
    self.assertEquals(self.messages[0][0], "ciao")

  def testDoubleMessage(self):
    self.connect_terminate_count = None
    client = self.getClient()
    client.send("ciao\3")
    self.mainloop.Run()
    client.send("foobar\3")
    self.mainloop.Run()
    self.assertEquals(len(self.connections), 1)
    self.assertEquals(len(self.messages[0]), 2)
    self.assertEquals(self.messages[0][1], "foobar")

  def testComposedMessage(self):
    self.connect_terminate_count = None
    self.message_terminate_count = 3
    client = self.getClient()
    client.send("one\3composed\3message\3")
    self.mainloop.Run()
    self.assertEquals(len(self.messages[0]), 3)
    self.assertEquals(self.messages[0], ["one", "composed", "message"])

  def testLongTerminator(self):
    self.terminator = "\0\1\2"
    self.connect_terminate_count = None
    self.message_terminate_count = 3
    client = self.getClient()
    client.send("one\0\1\2composed\0\1\2message\0\1\2")
    self.mainloop.Run()
    self.assertEquals(len(self.messages[0]), 3)
    self.assertEquals(self.messages[0], ["one", "composed", "message"])

  def testErrorHandling(self):
    self.connect_terminate_count = None
    self.message_terminate_count = None
    client = self.getClient()
    client.send("one\3two\3error\3three\3")
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assertEquals(self.connections[0].error_count, 1)
    self.assertEquals(self.messages[0], ["one", "two", "error"])
    client.send("error\3")
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assertEquals(self.connections[0].error_count, 2)
    self.assertEquals(self.messages[0], ["one", "two", "error", "three",
                                         "error"])

  def testDoubleClient(self):
    self.connect_terminate_count = None
    self.message_terminate_count = 2
    client1 = self.getClient()
    client2 = self.getClient()
    client1.send("c1m1\3")
    client2.send("c2m1\3")
    self.mainloop.Run()
    self.assertEquals(self.messages[0], ["c1m1"])
    self.assertEquals(self.messages[1], ["c2m1"])

  def testUnterminatedMessage(self):
    self.connect_terminate_count = None
    self.message_terminate_count = 3
    client1 = self.getClient()
    client2 = self.getClient()
    client1.send("message\3unterminated")
    client2.send("c2m1\3c2m2\3")
    self.mainloop.Run()
    self.assertEquals(self.messages[0], ["message"])
    self.assertEquals(self.messages[1], ["c2m1", "c2m2"])
    client1.send("message\3")
    self.mainloop.Run()
    self.assertEquals(self.messages[0], ["message", "unterminatedmessage"])

  def testSignaledWhileAccepting(self):
    utils.IgnoreSignals = lambda fn, *args, **kwargs: None
    client1 = self.getClient()
    self.server.handle_accept()
    # When interrupted while accepting we don't have a connection, but we
    # didn't crash either.
    self.assertEquals(len(self.connections), 0)
    utils.IgnoreSignals = self.saved_utils_ignoresignals
    self.mainloop.Run()
    self.assertEquals(len(self.connections), 1)

  def testSendMessage(self):
    self.connect_terminate_count = None
    self.message_terminate_count = 3
    client1 = self.getClient()
    client2 = self.getClient()
    client1.send("one\3composed\3message\3")
    self.mainloop.Run()
    self.assertEquals(self.messages[0], ["one", "composed", "message"])
    self.assertFalse(self.connections[0].writable())
    self.assertFalse(self.connections[1].writable())
    self.connections[0].send_message("r0")
    self.assert_(self.connections[0].writable())
    self.assertFalse(self.connections[1].writable())
    self.connections[0].send_message("r1")
    self.connections[0].send_message("r2")
    # We currently have no way to terminate the mainloop on write events, but
    # let's assume handle_write will be called if writable() is True.
    while self.connections[0].writable():
      self.connections[0].handle_write()
    client1.setblocking(0)
    client2.setblocking(0)
    self.assertEquals(client1.recv(4096), "r0\3r1\3r2\3")
    self.assertRaises(socket.error, client2.recv, 4096)

  def testLimitedUnhandledMessages(self):
    self.connect_terminate_count = None
    self.message_terminate_count = 3
    self.unhandled_limit = 2
    client1 = self.getClient()
    client2 = self.getClient()
    client1.send("one\3composed\3long\3message\3")
    client2.send("c2one\3")
    self.mainloop.Run()
    self.assertEquals(self.messages[0], ["one", "composed"])
    self.assertEquals(self.messages[1], ["c2one"])
    self.assertFalse(self.connections[0].readable())
    self.assert_(self.connections[1].readable())
    self.connections[0].send_message("r0")
    self.message_terminate_count = None
    client1.send("another\3")
    # when we write replies messages queued also get handled, but not the ones
    # in the socket.
    while self.connections[0].writable():
      self.connections[0].handle_write()
    self.assertFalse(self.connections[0].readable())
    self.assertEquals(self.messages[0], ["one", "composed", "long"])
    self.connections[0].send_message("r1")
    self.connections[0].send_message("r2")
    while self.connections[0].writable():
      self.connections[0].handle_write()
    self.assertEquals(self.messages[0], ["one", "composed", "long", "message"])
    self.assert_(self.connections[0].readable())

  def testLimitedUnhandledMessagesOne(self):
    self.connect_terminate_count = None
    self.message_terminate_count = 2
    self.unhandled_limit = 1
    client1 = self.getClient()
    client2 = self.getClient()
    client1.send("one\3composed\3message\3")
    client2.send("c2one\3")
    self.mainloop.Run()
    self.assertEquals(self.messages[0], ["one"])
    self.assertEquals(self.messages[1], ["c2one"])
    self.assertFalse(self.connections[0].readable())
    self.assertFalse(self.connections[1].readable())
    self.connections[0].send_message("r0")
    self.message_terminate_count = None
    while self.connections[0].writable():
      self.connections[0].handle_write()
    self.assertFalse(self.connections[0].readable())
    self.assertEquals(self.messages[0], ["one", "composed"])
    self.connections[0].send_message("r2")
    self.connections[0].send_message("r3")
    while self.connections[0].writable():
      self.connections[0].handle_write()
    self.assertEquals(self.messages[0], ["one", "composed", "message"])
    self.assert_(self.connections[0].readable())


class TestAsyncStreamServerUnixPath(TestAsyncStreamServerTCP):
  """Test daemon.AsyncStreamServer with a Unix path connection"""

  family = socket.AF_UNIX

  def getAddress(self):
    self.tmpdir = tempfile.mkdtemp()
    return os.path.join(self.tmpdir, "server.sock")

  def tearDown(self):
    shutil.rmtree(self.tmpdir)
    TestAsyncStreamServerTCP.tearDown(self)


class TestAsyncStreamServerUnixAbstract(TestAsyncStreamServerTCP):
  """Test daemon.AsyncStreamServer with a Unix abstract connection"""

  family = socket.AF_UNIX

  def getAddress(self):
    return "\0myabstractsocketaddress"


class TestAsyncAwaker(testutils.GanetiTestCase):
  """Test daemon.AsyncAwaker"""

  family = socket.AF_INET

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    self.awaker = daemon.AsyncAwaker(signal_fn=self.handle_signal)
    self.signal_count = 0
    self.signal_terminate_count = 1

  def tearDown(self):
    self.awaker.close()

  def handle_signal(self):
    self.signal_count += 1
    self.signal_terminate_count -= 1
    if self.signal_terminate_count <= 0:
      os.kill(os.getpid(), signal.SIGTERM)

  def testBasicSignaling(self):
    self.awaker.signal()
    self.mainloop.Run()
    self.assertEquals(self.signal_count, 1)

  def testDoubleSignaling(self):
    self.awaker.signal()
    self.awaker.signal()
    self.mainloop.Run()
    # The second signal is never delivered
    self.assertEquals(self.signal_count, 1)

  def testReallyDoubleSignaling(self):
    self.assert_(self.awaker.readable())
    self.awaker.signal()
    # Let's suppose two threads overlap, and both find need_signal True
    self.awaker.need_signal = True
    self.awaker.signal()
    self.mainloop.Run()
    # We still get only one signaling
    self.assertEquals(self.signal_count, 1)

  def testNoSignalFnArgument(self):
    myawaker = daemon.AsyncAwaker()
    self.assertRaises(socket.error, myawaker.handle_read)
    myawaker.signal()
    myawaker.handle_read()
    self.assertRaises(socket.error, myawaker.handle_read)
    myawaker.signal()
    myawaker.signal()
    myawaker.handle_read()
    self.assertRaises(socket.error, myawaker.handle_read)
    myawaker.close()

  def testWrongSignalFnArgument(self):
    self.assertRaises(AssertionError, daemon.AsyncAwaker, 1)
    self.assertRaises(AssertionError, daemon.AsyncAwaker, "string")
    self.assertRaises(AssertionError, daemon.AsyncAwaker, signal_fn=1)
    self.assertRaises(AssertionError, daemon.AsyncAwaker, signal_fn="string")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
