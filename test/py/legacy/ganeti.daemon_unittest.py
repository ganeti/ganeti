#!/usr/bin/python3
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

import signal
import os
import socket

from ganeti import daemon

import testutils


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
