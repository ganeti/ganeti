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

"""Tests for SSL certificate verification with stdlib ssl.

This test suite ensures that the threaded HTTP server properly verifies
client certificates using Python's stdlib ssl module with post-handshake
digest verification.

"""

import hashlib
import os
import ssl
import socket
import tempfile
import unittest
from unittest.mock import Mock

from ganeti import http
from ganeti.http import server as http_server


class TestFormatCertificateDigest(unittest.TestCase):
  """Test the _FormatCertificateDigest function."""

  def test_produces_colon_separated_hex(self):
    """Test that output is colon-separated uppercase hex."""
    result = http_server._FormatCertificateDigest(b"test data")
    parts = result.split(":")
    self.assertEqual(len(parts), 20)  # SHA1 = 20 bytes
    for part in parts:
      self.assertEqual(len(part), 2)
      self.assertEqual(part, part.upper())

  def test_matches_manual_computation(self):
    """Test that result matches manual SHA1 computation."""
    data = b"certificate data"
    expected_raw = hashlib.sha1(data).digest()
    expected = ":".join(f"{b:02X}" for b in expected_raw)
    self.assertEqual(http_server._FormatCertificateDigest(data), expected)

  def test_deterministic(self):
    """Test that same input always produces same output."""
    data = b"deterministic test"
    result1 = http_server._FormatCertificateDigest(data)
    result2 = http_server._FormatCertificateDigest(data)
    self.assertEqual(result1, result2)


class TestSSLContextCreation(unittest.TestCase):
  """Test _create_ssl_context static method."""

  def setUp(self):
    """Set up test certificates."""
    self.tmpdir = tempfile.mkdtemp()
    self._generate_test_certs()

  def tearDown(self):
    """Clean up test certificates."""
    import shutil
    shutil.rmtree(self.tmpdir)

  def _generate_test_certs(self):
    """Generate self-signed test certificates using openssl command."""
    self.cert_path = os.path.join(self.tmpdir, "server.pem")
    self.key_path = os.path.join(self.tmpdir, "server-key.pem")

    # Use test data certs if available
    test_data_dir = os.path.join(
      os.path.dirname(__file__),
      "..", "..", "..", "data"
    )
    cert2_src = os.path.join(test_data_dir, "cert2.pem")

    if os.path.exists(cert2_src):
      import shutil
      shutil.copy(cert2_src, self.cert_path)
      shutil.copy(cert2_src, self.key_path)
    else:
      self.skipTest("Test certificate data not available")

  def test_creates_ssl_context(self):
    """Test that a valid SSLContext is created."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=self.key_path,
      ssl_cert_path=self.cert_path
    )

    ctx = http_server.HttpServer._create_ssl_context(
      ssl_params, ssl_verify_peer=False
    )

    self.assertIsInstance(ctx, ssl.SSLContext)

  def test_verify_mode_with_peer_verification(self):
    """Test that verify_mode is CERT_REQUIRED when ssl_verify_peer=True."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=self.key_path,
      ssl_cert_path=self.cert_path
    )

    ctx = http_server.HttpServer._create_ssl_context(
      ssl_params, ssl_verify_peer=True
    )

    self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

  def test_verify_mode_without_peer_verification(self):
    """Test that verify_mode is not CERT_REQUIRED when ssl_verify_peer=False."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=self.key_path,
      ssl_cert_path=self.cert_path
    )

    ctx = http_server.HttpServer._create_ssl_context(
      ssl_params, ssl_verify_peer=False
    )

    self.assertNotEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

  def test_minimum_tls_version(self):
    """Test that minimum TLS version is set to 1.2."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=self.key_path,
      ssl_cert_path=self.cert_path
    )

    ctx = http_server.HttpServer._create_ssl_context(
      ssl_params, ssl_verify_peer=False
    )

    self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)

  def test_ssl_server_stores_context(self):
    """Test that server stores SSL context without wrapping listening socket."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=self.key_path,
      ssl_cert_path=self.cert_path
    )

    mock_handler = Mock()
    mock_handler.PreHandleRequest = Mock()
    mock_handler.HandleRequest = Mock(return_value="ok")
    mock_handler.FormatErrorMessage = Mock(
      return_value=("text/html", "error")
    )

    test_server = http_server.HttpServer(
      "127.0.0.1", 0,
      mock_handler,
      ssl_params=ssl_params,
      ssl_verify_peer=False
    )

    # Listening socket stays plain TCP
    self.assertNotIsInstance(test_server.socket, ssl.SSLSocket)
    # SSL context is stored for per-connection wrapping in worker threads
    self.assertIsInstance(test_server._ssl_context, ssl.SSLContext)

    test_server.server_close()


class TestPostHandshakeVerification(unittest.TestCase):
  """Test post-handshake client certificate verification."""

  def _make_handler(self, ssl_verify_peer, ssl_verify_callback=None,
                    connection=None):
    """Create a GanetiRequestHandler with mocked internals."""
    handler = object.__new__(http_server.GanetiRequestHandler)
    handler.server = Mock()
    handler.server.ssl_verify_peer = ssl_verify_peer
    handler.server.ssl_verify_callback = ssl_verify_callback
    handler.connection = connection
    return handler

  def test_skips_when_verify_disabled(self):
    """Test that verification is skipped when ssl_verify_peer is False."""
    handler = self._make_handler(ssl_verify_peer=False)
    handler._verify_client_certificate()  # Should not raise

  def test_skips_for_plain_socket(self):
    """Test that verification is skipped for non-SSL connections."""
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=Mock(),
      connection=Mock(spec=socket.socket)
    )
    handler._verify_client_certificate()  # Should not raise

  def test_rejects_when_no_peer_cert(self):
    """Test rejection when client provides no certificate."""
    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = None

    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=Mock(),
      connection=mock_ssl_sock
    )

    with self.assertRaises(http.HttpForbidden):
      handler._verify_client_certificate()

  def test_callback_receives_formatted_digest(self):
    """Test that callback receives correctly formatted digest."""
    der_cert = b"test certificate bytes"
    expected_digest = http_server._FormatCertificateDigest(der_cert)

    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = der_cert

    callback = Mock(return_value=True)
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=callback,
      connection=mock_ssl_sock
    )

    handler._verify_client_certificate()

    callback.assert_called_once_with(expected_digest)

  def test_rejects_when_callback_returns_false(self):
    """Test rejection when callback returns False."""
    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = b"some cert"

    callback = Mock(return_value=False)
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=callback,
      connection=mock_ssl_sock
    )

    with self.assertRaises(http.HttpForbidden):
      handler._verify_client_certificate()

  def test_accepts_when_callback_returns_true(self):
    """Test acceptance when callback returns True."""
    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = b"valid cert"

    callback = Mock(return_value=True)
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=callback,
      connection=mock_ssl_sock
    )

    handler._verify_client_certificate()  # Should not raise


if __name__ == "__main__":
  unittest.main()
