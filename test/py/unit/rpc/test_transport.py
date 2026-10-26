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

"""Pytest tests for the LUXI transport receive path (issue #1654).

The transports must reassemble arbitrarily chunked message streams
byte-exactly while reading in large chunks. The terminator is a single
byte, so messages may end exactly at a chunk boundary and multiple
messages may arrive in one chunk.
"""

import socket
import threading

import pytest

from ganeti import constants
from ganeti.rpc import transport


class _FakeSocket(object):
  """Minimal socket stub delivering a fixed sequence of chunks."""

  def __init__(self, chunks):
    self._chunks = list(chunks)
    self._pos = 0
    self.recv_calls = 0
    self.sizes = []

  def recv(self, size):
    self.recv_calls += 1
    self.sizes.append(size)
    if self._pos >= len(self._chunks):
      return b""
    chunk = self._chunks[self._pos]
    self._pos += 1
    return chunk[:size]


def _make_transport(chunks):
  """Build a Transport with the socket connect faked out."""
  t = object.__new__(transport.Transport)
  t._ctimeout, t._rwtimeout = 30, 180
  t.socket = _FakeSocket(chunks)
  t._buffer = b""
  t._msgs = transport.collections.deque()
  return t


class TestTransportRecvChunking(object):
  """Transport.Recv must reassemble chunked streams byte-exactly."""

  @pytest.mark.parametrize("chunk_size", [4096, 256 * 1024])
  def test_multi_chunk_message(self, monkeypatch, chunk_size):
    """A message larger than the chunk size arrives in many chunks."""
    monkeypatch.setattr(transport, "RECV_CHUNK_SIZE", chunk_size)
    payload = b"x" * (chunk_size * 3 + 17)
    msg = payload + constants.LUXI_EOM
    step = max(1, chunk_size // 2)
    chunks = [msg[i:i + step] for i in range(0, len(msg), step)]
    t = _make_transport(chunks)
    assert t.Recv() == payload.decode()

  def test_terminator_at_chunk_boundary(self):
    """A message ending exactly at a chunk boundary is not lost."""
    payload = b"full-message"
    # first read: complete message plus the start of the next one
    t = _make_transport([payload + constants.LUXI_EOM + b"next-partial"])
    assert t.Recv() == payload.decode()
    # the remainder stays buffered for the next message
    assert t._buffer == b"next-partial"

  def test_partial_remainder_survives_to_next_recv(self):
    """A partial message buffered across Recv() calls is completed later."""
    t = _make_transport([b"first" + constants.LUXI_EOM + b"sec",
                         b"ond" + constants.LUXI_EOM])
    assert t.Recv() == "first"
    assert t.Recv() == "second"

  def test_multiple_messages_in_one_chunk(self):
    """Two complete messages arriving in a single read are both queued."""
    a, b = b"first", b"second"
    data = (a + constants.LUXI_EOM + b + constants.LUXI_EOM)
    t = _make_transport([data])
    assert t.Recv() == a.decode()
    assert t.Recv() == b.decode()

  def test_message_split_across_chunks_with_remainder(self):
    """A message spanning chunks plus a trailing partial is reassembled."""
    a = b"A" * 10
    b = b"B" * 10
    stream = (a + constants.LUXI_EOM + b + constants.LUXI_EOM)
    # split in the middle of message b
    chunks = [stream[:len(a) + 1 + 5], stream[len(a) + 1 + 5:]]
    t = _make_transport(chunks)
    assert t.Recv() == a.decode()
    assert t.Recv() == b.decode()

  def test_large_message_real_socket(self, monkeypatch):
    """End-to-end over a socketpair: ~1MB payload reassembles byte-exactly
    and is read in large chunks (the issue #1654 regression)."""
    sizes = []
    me = threading.get_ident()
    real_recv = socket.socket.recv

    def recording_recv(self, size):
      # other threads may share this patched class method (e.g. leaked
      # helper threads from unrelated tests); record only our own reads
      if threading.get_ident() == me:
        sizes.append(size)
      return real_recv(self, size)

    monkeypatch.setattr(socket.socket, "recv", recording_recv)
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
      payload = b"p" * (1024 * 1024 + 3)
      threading.Thread(
        target=lambda: b.sendall(payload + constants.LUXI_EOM)).start()
      t = transport.Transport.__new__(transport.Transport)
      t._ctimeout, t._rwtimeout = 30, 180
      t.socket = a
      t._buffer = b""
      t._msgs = transport.collections.deque()
      assert t.Recv() == payload.decode()
      assert sizes and min(sizes) >= 64 * 1024
    finally:
      a.close()
      b.close()


class TestFdTransportRecvChunking(object):
  """FdTransport.Recv must behave identically."""

  def test_multi_chunk(self, tmp_path):
    """Messages chunked below the read size reassemble byte-exactly."""
    import io
    import os
    r, w = os.pipe()
    try:
      a = b"payload-one"
      bmsg = b"payload-two"
      data = (a + constants.LUXI_EOM + bmsg + constants.LUXI_EOM)
      os.write(w, data)
      os.close(w)
      t = transport.FdTransport.__new__(transport.FdTransport)
      # io.open() takes ownership of the fds; t.Close() closes them
      t._rstream = io.open(r, "rb", 0)
      t._wstream = io.open(os.devnull, "wb", 0)
      t._buffer = b""
      t._msgs = transport.collections.deque()
      assert t.Recv() == a.decode()
      assert t.Recv() == bmsg.decode()
      t.Close()
    finally:
      try:
        os.close(r)
      except OSError:
        pass  # already closed by t.Close()
