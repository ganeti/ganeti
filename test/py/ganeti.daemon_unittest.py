#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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
    self.assertEqual(self.sendsig_events, [signal.SIGTERM])

  def testTerminatingSignals(self):
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGINT])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events, [signal.SIGCHLD, signal.SIGINT])
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events, [signal.SIGCHLD, signal.SIGINT,
                                            signal.SIGTERM])

  def testSchedulerCancel(self):
    handle = self.mainloop.scheduler.enter(0.1, 1, self._SendSig,
                                           [signal.SIGTERM])
    self.mainloop.scheduler.cancel(handle)
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events, [signal.SIGCHLD, signal.SIGTERM])

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
    self.assertEqual(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEqual(self.onsignal_events, self.sendsig_events)

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
    self.assertEqual(self.sendsig_events, [signal.SIGCHLD, signal.SIGTERM])
    self.assertEqual(self.onsignal_events, self.sendsig_events)

  def testReRun(self):
    self.mainloop.RegisterSignal(self)
    self.mainloop.scheduler.enter(0.1, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.scheduler.enter(0.4, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.scheduler.enter(0.5, 1, self._SendSig, [signal.SIGCHLD])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEqual(self.onsignal_events, self.sendsig_events)
    self.mainloop.scheduler.enter(0.3, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events,
                      [signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM,
                       signal.SIGCHLD, signal.SIGCHLD, signal.SIGTERM])
    self.assertEqual(self.onsignal_events, self.sendsig_events)

  def testPriority(self):
    # for events at the same time, the highest priority one executes first
    now = time.time()
    self.mainloop.scheduler.enterabs(now + 0.1, 2, self._SendSig,
                                     [signal.SIGCHLD])
    self.mainloop.scheduler.enterabs(now + 0.1, 1, self._SendSig,
                                     [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events, [signal.SIGTERM])
    self.mainloop.scheduler.enter(0.2, 1, self._SendSig, [signal.SIGTERM])
    self.mainloop.Run()
    self.assertEqual(self.sendsig_events,
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
    self.assertEqual(self.server.received, ["p1", "p2", "terminate"])

  def testSyncClientServer(self):
    self.client.handle_write()
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    while self.client.writable():
      self.client.handle_write()
    self.server.process_next_packet()
    self.assertEqual(self.server.received, ["p1"])
    self.server.process_next_packet()
    self.assertEqual(self.server.received, ["p1", "p2"])
    self.client.enqueue_send(self.address, self.port, "p3")
    while self.client.writable():
      self.client.handle_write()
    self.server.process_next_packet()
    self.assertEqual(self.server.received, ["p1", "p2", "p3"])

  def testErrorHandling(self):
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    self.client.enqueue_send(self.address, self.port, "error")
    self.client.enqueue_send(self.address, self.port, "p3")
    self.client.enqueue_send(self.address, self.port, "error")
    self.client.enqueue_send(self.address, self.port, "terminate")
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assertEqual(self.server.received,
                      ["p1", "p2", "error"])
    self.assertEqual(self.server.error_count, 1)
    self.assertRaises(errors.GenericError, self.mainloop.Run)
    self.assertEqual(self.server.received,
                      ["p1", "p2", "error", "p3", "error"])
    self.assertEqual(self.server.error_count, 2)
    self.mainloop.Run()
    self.assertEqual(self.server.received,
                      ["p1", "p2", "error", "p3", "error", "terminate"])
    self.assertEqual(self.server.error_count, 2)

  def testSignaledWhileReceiving(self):
    utils.IgnoreSignals = lambda fn, *args, **kwargs: None
    self.client.enqueue_send(self.address, self.port, "p1")
    self.client.enqueue_send(self.address, self.port, "p2")
    self.server.handle_read()
    self.assertEqual(self.server.received, [])
    self.client.enqueue_send(self.address, self.port, "terminate")
    utils.IgnoreSignals = self.saved_utils_ignoresignals
    self.mainloop.Run()
    self.assertEqual(self.server.received, ["p1", "p2", "terminate"])

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


@testutils.RequiresIPv6()
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
    self.assertEqual(self.signal_count, 1)

  def testDoubleSignaling(self):
    self.awaker.signal()
    self.awaker.signal()
    self.mainloop.Run()
    # The second signal is never delivered
    self.assertEqual(self.signal_count, 1)

  def testReallyDoubleSignaling(self):
    self.assertTrue(self.awaker.readable())
    self.awaker.signal()
    # Let's suppose two threads overlap, and both find need_signal True
    self.awaker.need_signal = True
    self.awaker.signal()
    self.mainloop.Run()
    # We still get only one signaling
    self.assertEqual(self.signal_count, 1)

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
