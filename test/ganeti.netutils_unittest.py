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


"""Script for unittesting the netutils module"""

import os
import shutil
import socket
import tempfile
import unittest

import testutils
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import serializer
from ganeti import utils


def _GetSocketCredentials(path):
  """Connect to a Unix socket and return remote credentials.

  """
  sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
  try:
    sock.settimeout(10)
    sock.connect(path)
    return netutils.GetSocketCredentials(sock)
  finally:
    sock.close()


class TestGetSocketCredentials(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.sockpath = utils.PathJoin(self.tmpdir, "sock")

    self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.listener.settimeout(10)
    self.listener.bind(self.sockpath)
    self.listener.listen(1)

  def tearDown(self):
    self.listener.shutdown(socket.SHUT_RDWR)
    self.listener.close()
    shutil.rmtree(self.tmpdir)

  def test(self):
    (c2pr, c2pw) = os.pipe()

    # Start child process
    child = os.fork()
    if child == 0:
      try:
        data = serializer.DumpJson(_GetSocketCredentials(self.sockpath))

        os.write(c2pw, data)
        os.close(c2pw)

        os._exit(0)
      finally:
        os._exit(1)

    os.close(c2pw)

    # Wait for one connection
    (conn, _) = self.listener.accept()
    conn.recv(1)
    conn.close()

    # Wait for result
    result = os.read(c2pr, 4096)
    os.close(c2pr)

    # Check child's exit code
    (_, status) = os.waitpid(child, 0)
    self.assertFalse(os.WIFSIGNALED(status))
    self.assertEqual(os.WEXITSTATUS(status), 0)

    # Check result
    (pid, uid, gid) = serializer.LoadJson(result)
    self.assertEqual(pid, os.getpid())
    self.assertEqual(uid, os.getuid())
    self.assertEqual(gid, os.getgid())


class TestHostInfo(unittest.TestCase):
  """Testing case for HostInfo"""

  def testUppercase(self):
    data = "AbC.example.com"
    self.failUnlessEqual(netutils.HostInfo.NormalizeName(data), data.lower())

  def testTooLongName(self):
    data = "a.b." + "c" * 255
    self.failUnlessRaises(errors.OpPrereqError,
                          netutils.HostInfo.NormalizeName, data)

  def testTrailingDot(self):
    data = "a.b.c"
    self.failUnlessEqual(netutils.HostInfo.NormalizeName(data + "."), data)

  def testInvalidName(self):
    data = [
      "a b",
      "a/b",
      ".a.b",
      "a..b",
      ]
    for value in data:
      self.failUnlessRaises(errors.OpPrereqError,
                            netutils.HostInfo.NormalizeName, value)

  def testValidName(self):
    data = [
      "a.b",
      "a-b",
      "a_b",
      "a.b.c",
      ]
    for value in data:
      netutils.HostInfo.NormalizeName(value)


class TestIsValidIP4(unittest.TestCase):
  def test(self):
    self.assert_(netutils.IsValidIP4("127.0.0.1"))
    self.assert_(netutils.IsValidIP4("0.0.0.0"))
    self.assert_(netutils.IsValidIP4("255.255.255.255"))
    self.assertFalse(netutils.IsValidIP4("0"))
    self.assertFalse(netutils.IsValidIP4("1"))
    self.assertFalse(netutils.IsValidIP4("1.1.1"))
    self.assertFalse(netutils.IsValidIP4("255.255.255.256"))
    self.assertFalse(netutils.IsValidIP4("::1"))


class TestIsValidIP6(unittest.TestCase):
  def test(self):
    self.assert_(netutils.IsValidIP6("::"))
    self.assert_(netutils.IsValidIP6("::1"))
    self.assert_(netutils.IsValidIP6("1" + (":1" * 7)))
    self.assert_(netutils.IsValidIP6("ffff" + (":ffff" * 7)))
    self.assertFalse(netutils.IsValidIP6("0"))
    self.assertFalse(netutils.IsValidIP6(":1"))
    self.assertFalse(netutils.IsValidIP6("f" + (":f" * 6)))
    self.assertFalse(netutils.IsValidIP6("fffg" + (":ffff" * 7)))
    self.assertFalse(netutils.IsValidIP6("fffff" + (":ffff" * 7)))
    self.assertFalse(netutils.IsValidIP6("1" + (":1" * 8)))
    self.assertFalse(netutils.IsValidIP6("127.0.0.1"))


class TestIsValidIP(unittest.TestCase):
  def test(self):
    self.assert_(netutils.IsValidIP("0.0.0.0"))
    self.assert_(netutils.IsValidIP("127.0.0.1"))
    self.assert_(netutils.IsValidIP("::"))
    self.assert_(netutils.IsValidIP("::1"))
    self.assertFalse(netutils.IsValidIP("0"))
    self.assertFalse(netutils.IsValidIP("1.1.1.256"))
    self.assertFalse(netutils.IsValidIP("a:g::1"))


class TestGetAddressFamily(unittest.TestCase):
  def test(self):
    self.assertEqual(netutils.GetAddressFamily("127.0.0.1"), socket.AF_INET)
    self.assertEqual(netutils.GetAddressFamily("10.2.0.127"), socket.AF_INET)
    self.assertEqual(netutils.GetAddressFamily("::1"), socket.AF_INET6)
    self.assertEqual(netutils.GetAddressFamily("fe80::a00:27ff:fe08:5048"),
                     socket.AF_INET6)
    self.assertRaises(errors.GenericError, netutils.GetAddressFamily, "0")


class _BaseTcpPingTest:
  """Base class for TcpPing tests against listen(2)ing port"""
  family = None
  address = None

  def setUp(self):
    self.listener = socket.socket(self.family, socket.SOCK_STREAM)
    self.listener.bind((self.address, 0))
    self.listenerport = self.listener.getsockname()[1]
    self.listener.listen(1)

  def tearDown(self):
    self.listener.shutdown(socket.SHUT_RDWR)
    del self.listener
    del self.listenerport

  def testTcpPingToLocalHostAccept(self):
    self.assert_(netutils.TcpPing(self.address,
                                  self.listenerport,
                                  timeout=constants.TCP_PING_TIMEOUT,
                                  live_port_needed=True,
                                  source=self.address,
                                  ),
                 "failed to connect to test listener")

    self.assert_(netutils.TcpPing(self.address, self.listenerport,
                                  timeout=constants.TCP_PING_TIMEOUT,
                                  live_port_needed=True),
                 "failed to connect to test listener (no source)")


class TestIP4TcpPing(unittest.TestCase, _BaseTcpPingTest):
  """Testcase for IPv4 TCP version of ping - against listen(2)ing port"""
  family = socket.AF_INET
  address = constants.IP4_ADDRESS_LOCALHOST

  def setUp(self):
    unittest.TestCase.setUp(self)
    _BaseTcpPingTest.setUp(self)

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    _BaseTcpPingTest.tearDown(self)


class TestIP6TcpPing(unittest.TestCase, _BaseTcpPingTest):
  """Testcase for IPv6 TCP version of ping - against listen(2)ing port"""
  family = socket.AF_INET6
  address = constants.IP6_ADDRESS_LOCALHOST

  def setUp(self):
    unittest.TestCase.setUp(self)
    _BaseTcpPingTest.setUp(self)

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    _BaseTcpPingTest.tearDown(self)


class _BaseTcpPingDeafTest:
  """Base class for TcpPing tests against non listen(2)ing port"""
  family = None
  address = None

  def setUp(self):
    self.deaflistener = socket.socket(self.family, socket.SOCK_STREAM)
    self.deaflistener.bind((self.address, 0))
    self.deaflistenerport = self.deaflistener.getsockname()[1]

  def tearDown(self):
    del self.deaflistener
    del self.deaflistenerport

  def testTcpPingToLocalHostAcceptDeaf(self):
    self.assertFalse(netutils.TcpPing(self.address,
                                      self.deaflistenerport,
                                      timeout=constants.TCP_PING_TIMEOUT,
                                      live_port_needed=True,
                                      source=self.address,
                                      ), # need successful connect(2)
                     "successfully connected to deaf listener")

    self.assertFalse(netutils.TcpPing(self.address,
                                      self.deaflistenerport,
                                      timeout=constants.TCP_PING_TIMEOUT,
                                      live_port_needed=True,
                                      ), # need successful connect(2)
                     "successfully connected to deaf listener (no source)")

  def testTcpPingToLocalHostNoAccept(self):
    self.assert_(netutils.TcpPing(self.address,
                                  self.deaflistenerport,
                                  timeout=constants.TCP_PING_TIMEOUT,
                                  live_port_needed=False,
                                  source=self.address,
                                  ), # ECONNREFUSED is OK
                 "failed to ping alive host on deaf port")

    self.assert_(netutils.TcpPing(self.address,
                                  self.deaflistenerport,
                                  timeout=constants.TCP_PING_TIMEOUT,
                                  live_port_needed=False,
                                  ), # ECONNREFUSED is OK
                 "failed to ping alive host on deaf port (no source)")


class TestIP4TcpPingDeaf(unittest.TestCase, _BaseTcpPingDeafTest):
  """Testcase for IPv4 TCP version of ping - against non listen(2)ing port"""
  family = socket.AF_INET
  address = constants.IP4_ADDRESS_LOCALHOST

  def setUp(self):
    self.deaflistener = socket.socket(self.family, socket.SOCK_STREAM)
    self.deaflistener.bind((self.address, 0))
    self.deaflistenerport = self.deaflistener.getsockname()[1]

  def tearDown(self):
    del self.deaflistener
    del self.deaflistenerport


class TestIP6TcpPingDeaf(unittest.TestCase, _BaseTcpPingDeafTest):
  """Testcase for IPv6 TCP version of ping - against non listen(2)ing port"""
  family = socket.AF_INET6
  address = constants.IP6_ADDRESS_LOCALHOST

  def setUp(self):
    unittest.TestCase.setUp(self)
    _BaseTcpPingDeafTest.setUp(self)

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    _BaseTcpPingDeafTest.tearDown(self)


class TestOwnIpAddress(unittest.TestCase):
  """Testcase for OwnIpAddress"""

  def testOwnLoopback(self):
    """check having the loopback ip"""
    self.failUnless(netutils.OwnIpAddress(constants.IP4_ADDRESS_LOCALHOST),
                    "Should own the loopback address")

  def testNowOwnAddress(self):
    """check that I don't own an address"""

    # Network 192.0.2.0/24 is reserved for test/documentation as per
    # RFC 5737, so we *should* not have an address of this range... if
    # this fails, we should extend the test to multiple addresses
    DST_IP = "192.0.2.1"
    self.failIf(netutils.OwnIpAddress(DST_IP),
                "Should not own IP address %s" % DST_IP)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
