#
#

# Copyright (C) 2026 the Ganeti project
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

"""Pytest tests for ganeti.confd.client module."""

import errno
import socket

import pytest

from ganeti import confd
from ganeti import constants
from ganeti import errors

import ganeti.confd.client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockUDPClient:
  """Mock replacing UDPClient so ConfdClient tests don't need real sockets."""

  def __init__(self, client, family):
    self.send_count = 0
    self.last_address = ""
    self.last_port = -1
    self.last_payload = ""

  def enqueue_send(self, address, port, payload):
    self.send_count += 1
    self.last_payload = payload
    self.last_port = port
    self.last_address = address

  def flush_send_queue(self):
    pass

  def writable(self):
    return False

  def process_next_packet(self, timeout=0):
    return False

  def close(self):
    pass


class MockCallback:
  def __init__(self):
    self.call_count = 0
    self.last_up = None

  def __call__(self, up):
    self.call_count += 1
    self.last_up = up


class MockTime:
  def __init__(self):
    self.mytime = 1254213006.5175071

  def time(self):
    return self.mytime

  def increase(self, delta):
    self.mytime += delta


def _has_ipv6():
  """Check if IPv6 loopback is available."""
  try:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.bind(("::1", 0))
    sock.close()
    return True
  except socket.error as err:
    if err.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
      return False
    raise


requires_ipv6 = pytest.mark.skipif(not _has_ipv6(),
                                   reason="IPv6 not available")


# ---------------------------------------------------------------------------
# UDPClient tests (real sockets over loopback)
# ---------------------------------------------------------------------------

class TestUDPClientIPv4:
  """Test UDPClient with IPv4 loopback sockets."""

  @pytest.fixture(autouse=True)
  def setup_sockets(self):
    """Create a receiver socket and UDPClient sender."""
    self.receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.receiver.bind(("127.0.0.1", 0))
    self.port = self.receiver.getsockname()[1]
    self.received = []

    class _Collector:
      def HandleResponse(inner_self, payload, ip, port):
        self.received.append(payload)

    self.client = confd.client.UDPClient(_Collector(), socket.AF_INET)
    yield
    self.client.close()
    self.receiver.close()

  def test_enqueue_and_flush(self):
    self.client.enqueue_send("127.0.0.1", self.port, "hello")
    self.client.enqueue_send("127.0.0.1", self.port, "world")
    assert self.client.writable()
    self.client.flush_send_queue()
    assert not self.client.writable()

    self.receiver.settimeout(1)
    data1, _ = self.receiver.recvfrom(4096)
    data2, _ = self.receiver.recvfrom(4096)
    assert data1 == b"hello"
    assert data2 == b"world"

  def test_handle_write_sends_one(self):
    self.client.enqueue_send("127.0.0.1", self.port, "p1")
    self.client.enqueue_send("127.0.0.1", self.port, "p2")
    self.client.handle_write()
    # Only one sent
    assert self.client.writable()
    self.receiver.settimeout(1)
    data, _ = self.receiver.recvfrom(4096)
    assert data == b"p1"

  def test_process_next_packet(self):
    """Send a datagram and verify process_next_packet dispatches it."""
    # Send directly to the UDPClient's own socket
    self.client.socket.bind(("127.0.0.1", 0))
    client_port = self.client.socket.getsockname()[1]

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(b"test-payload", ("127.0.0.1", client_port))
    sender.close()

    result = self.client.process_next_packet(timeout=1)
    assert result is True
    assert self.received == [b"test-payload"]

  def test_process_next_packet_timeout(self):
    """Verify process_next_packet returns False on timeout."""
    result = self.client.process_next_packet(timeout=0)
    assert result is False

  def test_oversized_datagram_rejected(self):
    oversized = "a" * (constants.MAX_UDP_DATA_SIZE + 1)
    with pytest.raises(errors.UdpDataSizeError):
      self.client.enqueue_send("127.0.0.1", self.port, oversized)

  def test_string_payload_encoded(self):
    self.client.enqueue_send("127.0.0.1", self.port, "text")
    self.client.flush_send_queue()
    self.receiver.settimeout(1)
    data, _ = self.receiver.recvfrom(4096)
    assert data == b"text"

  def test_bytes_payload_sent_as_is(self):
    self.client.enqueue_send("127.0.0.1", self.port, b"\x00\x01\x02")
    self.client.flush_send_queue()
    self.receiver.settimeout(1)
    data, _ = self.receiver.recvfrom(4096)
    assert data == b"\x00\x01\x02"


@requires_ipv6
class TestUDPClientIPv6:
  """Test UDPClient with IPv6 loopback sockets."""

  @pytest.fixture(autouse=True)
  def setup_sockets(self):
    self.receiver = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    self.receiver.bind(("::1", 0))
    self.port = self.receiver.getsockname()[1]
    self.received = []

    class _Collector:
      def HandleResponse(inner_self, payload, ip, port):
        self.received.append((payload, ip))

    self.client = confd.client.UDPClient(_Collector(), socket.AF_INET6)
    yield
    self.client.close()
    self.receiver.close()

  def test_send_and_receive(self):
    self.client.enqueue_send("::1", self.port, "ipv6-test")
    self.client.flush_send_queue()

    self.receiver.settimeout(1)
    data, _ = self.receiver.recvfrom(4096)
    assert data == b"ipv6-test"

  def test_process_next_packet_ipv6(self):
    """Verify IPv6 address tuple (ip, port, flow, scope) is handled."""
    self.client.socket.bind(("::1", 0))
    client_port = self.client.socket.getsockname()[1]

    sender = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sender.sendto(b"v6-payload", ("::1", client_port))
    sender.close()

    result = self.client.process_next_packet(timeout=1)
    assert result is True
    assert len(self.received) == 1
    assert self.received[0][0] == b"v6-payload"
    assert self.received[0][1] == "::1"


# ---------------------------------------------------------------------------
# ConfdClient tests (mocked socket)
# ---------------------------------------------------------------------------

@pytest.fixture()
def confd_client_env(monkeypatch):
  """Set up a ConfdClient with mocked time and socket for testing."""
  mock_time = MockTime()
  monkeypatch.setattr(confd.client, "time", mock_time)
  monkeypatch.setattr(confd.client, "UDPClient", MockUDPClient)

  callback = MockCallback()
  return mock_time, callback


IPV4_MC_LIST = [
  "192.0.2.1",
  "192.0.2.2",
  "192.0.2.3",
  "192.0.2.4",
  "192.0.2.5",
  "192.0.2.6",
  "192.0.2.7",
  "192.0.2.8",
  "192.0.2.9",
]

IPV6_MC_LIST = [
  "2001:db8::1",
  "2001:db8::2",
  "2001:db8::3",
  "2001:db8::4",
  "2001:db8::5",
  "2001:db8::6",
  "2001:db8::7",
  "2001:db8::8",
  "2001:db8::9",
]


class TestConfdClientRequest:
  """Tests for ConfdClientRequest creation."""

  def test_unique_salts(self):
    req1 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    assert req1.rsalt != req2.rsalt

  def test_protocol_version(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    assert req.protocol == constants.CONFD_PROTOCOL_VERSION

  def test_invalid_type_rejected(self):
    with pytest.raises(errors.ConfdClientError):
      confd.client.ConfdClientRequest(type=-33)


class TestConfdClientIPv4:
  """ConfdClient tests with IPv4 master candidate list."""

  @pytest.fixture(autouse=True)
  def setup_client(self, confd_client_env):
    self.mock_time, self.callback = confd_client_env
    self.client = confd.client.ConfdClient(
      "mykeydata", IPV4_MC_LIST, self.callback)

  def test_send_request(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    assert self.client._socket.send_count == \
        constants.CONFD_DEFAULT_REQ_COVERAGE

  def test_duplicate_request_rejected(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    with pytest.raises(errors.ConfdClientError):
      self.client.SendRequest(req)

  def test_coverage_too_big(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    with pytest.raises(errors.ConfdClientError):
      self.client.SendRequest(req, coverage=15)

  def test_send_max_coverage(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req, coverage=-1)
    assert self.client._socket.send_count == len(IPV4_MC_LIST)
    assert self.client._socket.last_address in IPV4_MC_LIST

  def test_expire_requests(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    self.mock_time.increase(2)

    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req2)
    self.mock_time.increase(constants.CONFD_CLIENT_EXPIRE_TIMEOUT - 1)

    # First request should be expired, second should not
    self.client.ExpireRequests()
    assert self.callback.call_count == 1
    assert self.callback.last_up.type == confd.client.UPCALL_EXPIRE
    assert self.callback.last_up.salt == req.rsalt
    assert self.callback.last_up.orig_request == req

    self.mock_time.increase(3)
    assert self.callback.call_count == 1
    self.client.ExpireRequests()
    assert self.callback.call_count == 2
    assert self.callback.last_up.type == confd.client.UPCALL_EXPIRE
    assert self.callback.last_up.salt == req2.rsalt
    assert self.callback.last_up.orig_request == req2

  def test_cascade_expire(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    self.mock_time.increase(constants.CONFD_CLIENT_EXPIRE_TIMEOUT + 1)

    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req2)
    # Sending req2 calls ExpireRequests internally, expiring req
    assert self.callback.call_count == 1

  def test_update_peer_list(self):
    new_peers = ["198.51.100.1", "198.51.100.2"]
    self.client.UpdatePeerList(new_peers)
    assert self.client._peers == new_peers

    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    assert self.client._socket.send_count == len(new_peers)
    assert self.client._socket.last_address in new_peers

  def test_address_family(self):
    self.client._SetPeersAddressFamily()
    assert self.client._family == socket.AF_INET

  def test_mixed_address_family_rejected(self):
    self.client.UpdatePeerList(["192.0.2.99", "2001:db8:beef::13"])
    with pytest.raises(errors.ConfdClientError):
      self.client._SetPeersAddressFamily()


class TestConfdClientIPv6:
  """ConfdClient tests with IPv6 master candidate list."""

  @pytest.fixture(autouse=True)
  def setup_client(self, confd_client_env):
    self.mock_time, self.callback = confd_client_env
    self.client = confd.client.ConfdClient(
      "mykeydata", IPV6_MC_LIST, self.callback)

  def test_send_request(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    assert self.client._socket.send_count == \
        constants.CONFD_DEFAULT_REQ_COVERAGE

  def test_send_max_coverage(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req, coverage=-1)
    assert self.client._socket.send_count == len(IPV6_MC_LIST)
    assert self.client._socket.last_address in IPV6_MC_LIST

  def test_expire_requests(self):
    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    self.mock_time.increase(2)

    req2 = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req2)
    self.mock_time.increase(constants.CONFD_CLIENT_EXPIRE_TIMEOUT - 1)

    self.client.ExpireRequests()
    assert self.callback.call_count == 1
    assert self.callback.last_up.salt == req.rsalt

    self.mock_time.increase(3)
    self.client.ExpireRequests()
    assert self.callback.call_count == 2
    assert self.callback.last_up.salt == req2.rsalt

  def test_update_peer_list(self):
    new_peers = ["2001:db8:beef::11", "2001:db8:beef::12"]
    self.client.UpdatePeerList(new_peers)
    assert self.client._peers == new_peers

    req = confd.client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.client.SendRequest(req)
    assert self.client._socket.send_count == len(new_peers)
    assert self.client._socket.last_address in new_peers

  def test_address_family(self):
    self.client._SetPeersAddressFamily()
    assert self.client._family == socket.AF_INET6


class TestNeededReplies:
  """Tests for ConfdClient._NeededReplies algorithm."""

  @pytest.mark.parametrize("peers,expected", [
    (1, 1),
    (2, 2),
    (3, 2),
    (4, 3),
    (5, 3),
    (6, 4),
    (7, 4),
    (8, 5),
  ])
  def test_needed_replies(self, peers, expected):
    assert confd.client.ConfdClient._NeededReplies(peers) == expected
