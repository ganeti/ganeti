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

from ganeti import daemon

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


class _MyAsyncUDPSocket(daemon.AsyncUDPSocket):

  def __init__(self):
    daemon.AsyncUDPSocket.__init__(self)
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


class TestAsyncUDPSocket(testutils.GanetiTestCase):
  """Test daemon.AsyncUDPSocket"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.mainloop = daemon.Mainloop()
    self.server = _MyAsyncUDPSocket()
    self.client = _MyAsyncUDPSocket()
    self.server.bind(("127.0.0.1", 0))
    self.port = self.server.getsockname()[1]

  def tearDown(self):
    self.server.close()
    self.client.close()
    testutils.GanetiTestCase.tearDown(self)

  def testNoDoubleBind(self):
    self.assertRaises(socket.error, self.client.bind, ("127.0.0.1", self.port))

  def _ThreadedClient(self, payload):
    self.client.enqueue_send("127.0.0.1", self.port, payload)
    print "sending %s" % payload
    while self.client.writable():
      self.client.handle_write()

  def testAsyncClientServer(self):
    self.client.enqueue_send("127.0.0.1", self.port, "p1")
    self.client.enqueue_send("127.0.0.1", self.port, "p2")
    self.client.enqueue_send("127.0.0.1", self.port, "terminate")
    self.mainloop.Run()
    self.assertEquals(self.server.received, ["p1", "p2", "terminate"])

  def testSyncClientServer(self):
    self.client.enqueue_send("127.0.0.1", self.port, "p1")
    self.client.enqueue_send("127.0.0.1", self.port, "p2")
    while self.client.writable():
      self.client.handle_write()
    self.server.process_next_packet()
    self.assertEquals(self.server.received, ["p1"])
    self.server.process_next_packet()
    self.assertEquals(self.server.received, ["p1", "p2"])
    self.client.enqueue_send("127.0.0.1", self.port, "p3")
    while self.client.writable():
      self.client.handle_write()
    self.server.process_next_packet()
    self.assertEquals(self.server.received, ["p1", "p2", "p3"])

  def testErrorHandling(self):
    self.client.enqueue_send("127.0.0.1", self.port, "p1")
    self.client.enqueue_send("127.0.0.1", self.port, "p2")
    self.client.enqueue_send("127.0.0.1", self.port, "error")
    self.client.enqueue_send("127.0.0.1", self.port, "p3")
    self.client.enqueue_send("127.0.0.1", self.port, "error")
    self.client.enqueue_send("127.0.0.1", self.port, "terminate")
    self.mainloop.Run()
    self.assertEquals(self.server.received,
                      ["p1", "p2", "error", "p3", "error", "terminate"])
    self.assertEquals(self.server.error_count, 2)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
