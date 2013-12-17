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
import re
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


class TestHostname(unittest.TestCase):
  """Testing case for Hostname"""

  def testUppercase(self):
    data = "AbC.example.com"
    self.assertEqual(netutils.Hostname.GetNormalizedName(data), data.lower())

  def testTooLongName(self):
    data = "a.b." + "c" * 255
    self.assertRaises(errors.OpPrereqError,
                      netutils.Hostname.GetNormalizedName, data)

  def testTrailingDot(self):
    data = "a.b.c"
    self.assertEqual(netutils.Hostname.GetNormalizedName(data + "."), data)

  def testInvalidName(self):
    data = [
      "a b",
      "a/b",
      ".a.b",
      "a..b",
      ]
    for value in data:
      self.assertRaises(errors.OpPrereqError,
                        netutils.Hostname.GetNormalizedName, value)

  def testValidName(self):
    data = [
      "a.b",
      "a-b",
      "a_b",
      "a.b.c",
      ]
    for value in data:
      self.assertEqual(netutils.Hostname.GetNormalizedName(value), value)


class TestIPAddress(unittest.TestCase):
  def testIsValid(self):
    self.assert_(netutils.IPAddress.IsValid("0.0.0.0"))
    self.assert_(netutils.IPAddress.IsValid("127.0.0.1"))
    self.assert_(netutils.IPAddress.IsValid("::"))
    self.assert_(netutils.IPAddress.IsValid("::1"))

  def testNotIsValid(self):
    self.assertFalse(netutils.IPAddress.IsValid("0"))
    self.assertFalse(netutils.IPAddress.IsValid("1.1.1.256"))
    self.assertFalse(netutils.IPAddress.IsValid("a:g::1"))

  def testGetAddressFamily(self):
    fn = netutils.IPAddress.GetAddressFamily
    self.assertEqual(fn("127.0.0.1"), socket.AF_INET)
    self.assertEqual(fn("10.2.0.127"), socket.AF_INET)
    self.assertEqual(fn("::1"), socket.AF_INET6)
    self.assertEqual(fn("2001:db8::1"), socket.AF_INET6)
    self.assertRaises(errors.IPAddressError, fn, "0")

  def testValidateNetmask(self):
    for netmask in [0, 33]:
      self.assertFalse(netutils.IP4Address.ValidateNetmask(netmask))

    for netmask in [1, 32]:
      self.assertTrue(netutils.IP4Address.ValidateNetmask(netmask))

    for netmask in [0, 129]:
      self.assertFalse(netutils.IP6Address.ValidateNetmask(netmask))

    for netmask in [1, 128]:
      self.assertTrue(netutils.IP6Address.ValidateNetmask(netmask))

  def testGetClassFromX(self):
    self.assert_(
        netutils.IPAddress.GetClassFromIpVersion(constants.IP4_VERSION) ==
        netutils.IP4Address)
    self.assert_(
        netutils.IPAddress.GetClassFromIpVersion(constants.IP6_VERSION) ==
        netutils.IP6Address)
    self.assert_(
        netutils.IPAddress.GetClassFromIpFamily(socket.AF_INET) ==
        netutils.IP4Address)
    self.assert_(
        netutils.IPAddress.GetClassFromIpFamily(socket.AF_INET6) ==
        netutils.IP6Address)

  def testOwnLoopback(self):
    # FIXME: In a pure IPv6 environment this is no longer true
    self.assert_(netutils.IPAddress.Own("127.0.0.1"),
                 "Should own 127.0.0.1 address")

  def testNotOwnAddress(self):
    self.assertFalse(netutils.IPAddress.Own("2001:db8::1"),
                     "Should not own IP address 2001:db8::1")
    self.assertFalse(netutils.IPAddress.Own("192.0.2.1"),
                     "Should not own IP address 192.0.2.1")

  def testFamilyVersionConversions(self):
    # IPAddress.GetAddressFamilyFromVersion
    self.assertEqual(
        netutils.IPAddress.GetAddressFamilyFromVersion(constants.IP4_VERSION),
        socket.AF_INET)
    self.assertEqual(
        netutils.IPAddress.GetAddressFamilyFromVersion(constants.IP6_VERSION),
        socket.AF_INET6)
    self.assertRaises(errors.ProgrammerError,
        netutils.IPAddress.GetAddressFamilyFromVersion, 3)

    # IPAddress.GetVersionFromAddressFamily
    self.assertEqual(
        netutils.IPAddress.GetVersionFromAddressFamily(socket.AF_INET),
        constants.IP4_VERSION)
    self.assertEqual(
        netutils.IPAddress.GetVersionFromAddressFamily(socket.AF_INET6),
        constants.IP6_VERSION)
    self.assertRaises(errors.ProgrammerError,
        netutils.IPAddress.GetVersionFromAddressFamily, socket.AF_UNIX)


class TestIP4Address(unittest.TestCase):
  def testGetIPIntFromString(self):
    fn = netutils.IP4Address._GetIPIntFromString
    self.assertEqual(fn("0.0.0.0"), 0)
    self.assertEqual(fn("0.0.0.1"), 1)
    self.assertEqual(fn("127.0.0.1"), 2130706433)
    self.assertEqual(fn("192.0.2.129"), 3221226113)
    self.assertEqual(fn("255.255.255.255"), 2**32 - 1)
    self.assertNotEqual(fn("0.0.0.0"), 1)
    self.assertNotEqual(fn("0.0.0.0"), 1)

  def testIsValid(self):
    self.assert_(netutils.IP4Address.IsValid("0.0.0.0"))
    self.assert_(netutils.IP4Address.IsValid("127.0.0.1"))
    self.assert_(netutils.IP4Address.IsValid("192.0.2.199"))
    self.assert_(netutils.IP4Address.IsValid("255.255.255.255"))

  def testNotIsValid(self):
    self.assertFalse(netutils.IP4Address.IsValid("0"))
    self.assertFalse(netutils.IP4Address.IsValid("1"))
    self.assertFalse(netutils.IP4Address.IsValid("1.1.1"))
    self.assertFalse(netutils.IP4Address.IsValid("255.255.255.256"))
    self.assertFalse(netutils.IP4Address.IsValid("::1"))

  def testInNetwork(self):
    self.assert_(netutils.IP4Address.InNetwork("127.0.0.0/8", "127.0.0.1"))

  def testNotInNetwork(self):
    self.assertFalse(netutils.IP4Address.InNetwork("192.0.2.0/24",
                                                   "127.0.0.1"))

  def testIsLoopback(self):
    self.assert_(netutils.IP4Address.IsLoopback("127.0.0.1"))

  def testNotIsLoopback(self):
    self.assertFalse(netutils.IP4Address.IsLoopback("192.0.2.1"))


class TestIP6Address(unittest.TestCase):
  def testGetIPIntFromString(self):
    fn = netutils.IP6Address._GetIPIntFromString
    self.assertEqual(fn("::"), 0)
    self.assertEqual(fn("::1"), 1)
    self.assertEqual(fn("2001:db8::1"),
                     42540766411282592856903984951653826561L)
    self.assertEqual(fn("ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"), 2**128-1)
    self.assertNotEqual(netutils.IP6Address._GetIPIntFromString("::2"), 1)

  def testIsValid(self):
    self.assert_(netutils.IP6Address.IsValid("::"))
    self.assert_(netutils.IP6Address.IsValid("::1"))
    self.assert_(netutils.IP6Address.IsValid("1" + (":1" * 7)))
    self.assert_(netutils.IP6Address.IsValid("ffff" + (":ffff" * 7)))
    self.assert_(netutils.IP6Address.IsValid("::"))

  def testNotIsValid(self):
    self.assertFalse(netutils.IP6Address.IsValid("0"))
    self.assertFalse(netutils.IP6Address.IsValid(":1"))
    self.assertFalse(netutils.IP6Address.IsValid("f" + (":f" * 6)))
    self.assertFalse(netutils.IP6Address.IsValid("fffg" + (":ffff" * 7)))
    self.assertFalse(netutils.IP6Address.IsValid("fffff" + (":ffff" * 7)))
    self.assertFalse(netutils.IP6Address.IsValid("1" + (":1" * 8)))
    self.assertFalse(netutils.IP6Address.IsValid("127.0.0.1"))

  def testInNetwork(self):
    self.assert_(netutils.IP6Address.InNetwork("::1/128", "::1"))

  def testNotInNetwork(self):
    self.assertFalse(netutils.IP6Address.InNetwork("2001:db8::1/128", "::1"))

  def testIsLoopback(self):
    self.assert_(netutils.IP6Address.IsLoopback("::1"))

  def testNotIsLoopback(self):
    self.assertFalse(netutils.IP6Address.IsLoopback("2001:db8::1"))


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


class TestFormatAddress(unittest.TestCase):
  """Testcase for FormatAddress"""

  def testFormatAddressUnixSocket(self):
    res1 = netutils.FormatAddress(("12352", 0, 0), family=socket.AF_UNIX)
    self.assertEqual(res1, "pid=12352, uid=0, gid=0")

  def testFormatAddressIP4(self):
    res1 = netutils.FormatAddress(("127.0.0.1", 1234), family=socket.AF_INET)
    self.assertEqual(res1, "127.0.0.1:1234")
    res2 = netutils.FormatAddress(("192.0.2.32", None), family=socket.AF_INET)
    self.assertEqual(res2, "192.0.2.32")

  def testFormatAddressIP6(self):
    res1 = netutils.FormatAddress(("::1", 1234), family=socket.AF_INET6)
    self.assertEqual(res1, "[::1]:1234")
    res2 = netutils.FormatAddress(("::1", None), family=socket.AF_INET6)
    self.assertEqual(res2, "[::1]")
    res2 = netutils.FormatAddress(("2001:db8::beef", "80"),
                                  family=socket.AF_INET6)
    self.assertEqual(res2, "[2001:db8::beef]:80")

  def testFormatAddressWithoutFamily(self):
    res1 = netutils.FormatAddress(("127.0.0.1", 1234))
    self.assertEqual(res1, "127.0.0.1:1234")
    res2 = netutils.FormatAddress(("::1", 1234))
    self.assertEqual(res2, "[::1]:1234")


  def testInvalidFormatAddress(self):
    self.assertRaises(errors.ParameterError, netutils.FormatAddress,
                      "127.0.0.1")
    self.assertRaises(errors.ParameterError, netutils.FormatAddress,
                      "127.0.0.1", family=socket.AF_INET)
    self.assertRaises(errors.ParameterError, netutils.FormatAddress,
                      ("::1"), family=socket.AF_INET )

class TestIpParsing(testutils.GanetiTestCase):
  """Test the code that parses the ip command output"""

  def testIp4(self):
    valid_addresses = [constants.IP4_ADDRESS_ANY,
                       constants.IP4_ADDRESS_LOCALHOST,
                       "192.0.2.1",     # RFC5737, IPv4 address blocks for docs
                       "198.51.100.1",
                       "203.0.113.1",
                      ]
    for addr in valid_addresses:
      self.failUnless(re.search(netutils._IP_RE_TEXT, addr))

  def testIp6(self):
    valid_addresses = [constants.IP6_ADDRESS_ANY,
                       constants.IP6_ADDRESS_LOCALHOST,
                       "0:0:0:0:0:0:0:1", # other form for IP6_ADDRESS_LOCALHOST
                       "0:0:0:0:0:0:0:0", # other form for IP6_ADDRESS_ANY
                       "2001:db8:85a3::8a2e:370:7334", # RFC3849 IP6 docs block
                       "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
                       "0:0:0:0:0:FFFF:192.0.2.1",  # IPv4-compatible IPv6
                       "::FFFF:192.0.2.1",
                       "0:0:0:0:0:0:203.0.113.1",   # IPv4-mapped IPv6
                       "::203.0.113.1",
                      ]
    for addr in valid_addresses:
      self.failUnless(re.search(netutils._IP_RE_TEXT, addr))

  def testParseIpCommandOutput(self):
    # IPv4-only, fake loopback interface
    tests = ["ip-addr-show-lo-ipv4.txt", "ip-addr-show-lo-oneline-ipv4.txt"]
    for test_file in tests:
      data = testutils.ReadTestData(test_file)
      addr = netutils._GetIpAddressesFromIpOutput(data)
      self.failUnless(len(addr[4]) == 1 and addr[4][0] == "127.0.0.1" and not
                      addr[6])

    # IPv6-only, fake loopback interface
    tests = ["ip-addr-show-lo-ipv6.txt", "ip-addr-show-lo-ipv6.txt"]
    for test_file in tests:
      data = testutils.ReadTestData(test_file)
      addr = netutils._GetIpAddressesFromIpOutput(data)
      self.failUnless(len(addr[6]) == 1 and addr[6][0] == "::1" and not addr[4])

    # IPv4 and IPv6, fake loopback interface
    tests = ["ip-addr-show-lo.txt", "ip-addr-show-lo-oneline.txt"]
    for test_file in tests:
      data = testutils.ReadTestData(test_file)
      addr = netutils._GetIpAddressesFromIpOutput(data)
      self.failUnless(len(addr[6]) == 1 and addr[6][0] == "::1" and
                      len(addr[4]) == 1 and addr[4][0] == "127.0.0.1")

    # IPv4 and IPv6, dummy interface
    data = testutils.ReadTestData("ip-addr-show-dummy0.txt")
    addr = netutils._GetIpAddressesFromIpOutput(data)
    self.failUnless(len(addr[6]) == 1 and
                    addr[6][0] == "2001:db8:85a3::8a2e:370:7334" and
                    len(addr[4]) == 1 and
                    addr[4][0] == "192.0.2.1")


class TestValidatePortNumber(unittest.TestCase):
  """Test netutils.ValidatePortNumber"""

  def testPortNumberInt(self):
    self.assertRaises(ValueError, lambda: \
      netutils.ValidatePortNumber(500000))
    self.assertEqual(netutils.ValidatePortNumber(5000), 5000)

  def testPortNumberStr(self):
    self.assertRaises(ValueError, lambda: \
      netutils.ValidatePortNumber("pinky bunny"))
    self.assertEqual(netutils.ValidatePortNumber("5000"), 5000)

if __name__ == "__main__":
  testutils.GanetiTestProgram()
