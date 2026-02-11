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

"""Unit tests for ganeti.http.server module (threading implementation)."""

import hashlib
import pytest
import ssl
import threading
import time
import socket
from unittest.mock import Mock, MagicMock, patch
from http.client import HTTPConnection

import ganeti.http.server as server
from ganeti import http


class MockHandler(server.HttpServerHandler):
  """Mock HTTP handler for testing."""

  def __init__(self, response='{"status": "ok"}'):
    self.response = response
    self.pre_handle_called = False
    self.handle_called = False
    self.last_request = None
    self.last_request_body = None
    self.last_request_method = None
    self.last_request_path = None

  def PreHandleRequest(self, req):
    """Track pre-handle calls."""
    self.pre_handle_called = True
    self.last_request = req
    self.last_request_body = req.request_body
    self.last_request_method = req.request_method
    self.last_request_path = req.request_path

  def HandleRequest(self, req):
    """Return mock response."""
    self.handle_called = True
    self.last_request = req
    self.last_request_body = req.request_body
    self.last_request_method = req.request_method
    self.last_request_path = req.request_path
    return self.response


class TestHttpServerRequest:
  """Test _HttpServerRequest data structure."""

  def test_create_request(self):
    """Test creating HTTP server request object."""
    req = server._HttpServerRequest(
      method="GET",
      path="/test",
      headers={"Content-Type": "application/json"},
      body=b'{"key": "value"}',
      sock=None
    )

    assert req.request_method == "GET"
    assert req.request_path == "/test"
    assert req.request_headers == {"Content-Type": "application/json"}
    assert req.request_body == b'{"key": "value"}'
    assert req.request_sock is None
    assert isinstance(req.resp_headers, dict)
    assert len(req.resp_headers) == 0
    assert req.private is None


class TestFormatCertificateDigest:
  """Test _FormatCertificateDigest helper function."""

  def test_known_digest(self):
    """Test digest formatting with known input."""
    der_cert = b""
    result = server._FormatCertificateDigest(der_cert)
    expected_formatted = ":".join(
      f"{b:02X}" for b in hashlib.sha1(b"").digest()
    )
    assert result == expected_formatted

  def test_format_matches_pyopenssl(self):
    """Test that format matches PyOpenSSL's X509.digest() output."""
    # PyOpenSSL format is "XX:XX:XX:..." (colon-separated uppercase hex)
    der_cert = b"\x00\x01\x02\x03"
    result = server._FormatCertificateDigest(der_cert)

    # Verify format: 20 hex pairs separated by colons
    parts = result.split(":")
    assert len(parts) == 20  # SHA1 produces 20 bytes
    for part in parts:
      assert len(part) == 2
      assert part == part.upper()
      int(part, 16)  # Should not raise

  def test_different_certs_different_digests(self):
    """Test that different inputs produce different digests."""
    digest1 = server._FormatCertificateDigest(b"cert1")
    digest2 = server._FormatCertificateDigest(b"cert2")
    assert digest1 != digest2


class TestHttpServer:
  """Test HttpServer class."""

  @pytest.fixture
  def mock_handler(self):
    """Create a mock Ganeti handler."""
    return MockHandler()

  def test_server_creation_without_ssl(self, mock_handler):
    """Test creating HTTP server without SSL."""
    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler,
      max_clients=5
    )

    assert http_server.ganeti_handler == mock_handler
    assert http_server.ssl_verify_peer is False
    assert http_server.allow_reuse_address is True

    http_server.server_close()

  def test_server_binding(self, mock_handler):
    """Test server binds to specified address."""
    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler
    )

    assert http_server.server_address[0] == "127.0.0.1"
    assert http_server.server_address[1] > 0  # Got a port assigned

    http_server.server_close()

  def test_address_family_inet(self, mock_handler):
    """Test server uses correct address family for IPv4."""
    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler
    )

    assert http_server.address_family == socket.AF_INET
    http_server.server_close()


class TestGanetiRequestHandler:
  """Test GanetiRequestHandler class."""

  def test_handler_attributes(self):
    """Test handler class attributes."""
    assert server.GanetiRequestHandler.timeout == 10
    assert server.GanetiRequestHandler.MAX_REQUEST_BODY_SIZE == 10 * 1024 * 1024
    assert server.GanetiRequestHandler.protocol_version == "HTTP/1.1"

  def test_max_body_size_constant(self):
    """Test MAX_REQUEST_BODY_SIZE is reasonable."""
    max_size = server.GanetiRequestHandler.MAX_REQUEST_BODY_SIZE
    # Should be 10 MB
    assert max_size == 10485760
    assert max_size > 1024 * 1024  # At least 1 MB
    assert max_size < 100 * 1024 * 1024  # Less than 100 MB


class TestVerifyClientCertificate:
  """Test _verify_client_certificate method."""

  def _make_handler(self, ssl_verify_peer, ssl_verify_callback=None,
                    connection=None):
    """Create a GanetiRequestHandler with mocked internals.

    @rtype: GanetiRequestHandler

    """
    handler = object.__new__(server.GanetiRequestHandler)
    handler.server = Mock()
    handler.server.ssl_verify_peer = ssl_verify_peer
    handler.server.ssl_verify_callback = ssl_verify_callback
    handler.connection = connection
    return handler

  def test_skips_when_verify_disabled(self):
    """Test that verification is skipped when ssl_verify_peer is False."""
    handler = self._make_handler(ssl_verify_peer=False)
    # Should not raise
    handler._verify_client_certificate()

  def test_skips_for_non_ssl_connection(self):
    """Test that verification is skipped for non-SSL connections."""
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=Mock(),
      connection=Mock(spec=socket.socket)
    )
    # Should not raise (not an SSLSocket)
    handler._verify_client_certificate()

  def test_rejects_missing_certificate(self):
    """Test that missing client certificate is rejected."""
    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = None

    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=Mock(),
      connection=mock_ssl_sock
    )

    with pytest.raises(http.HttpForbidden):
      handler._verify_client_certificate()

  def test_calls_callback_with_digest(self):
    """Test that callback is called with correct digest format."""
    der_cert = b"test certificate data"
    expected_digest = server._FormatCertificateDigest(der_cert)

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
    """Test that request is rejected when callback returns False."""
    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = b"some cert"

    callback = Mock(return_value=False)
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=callback,
      connection=mock_ssl_sock
    )

    with pytest.raises(http.HttpForbidden):
      handler._verify_client_certificate()

  def test_accepts_when_callback_returns_true(self):
    """Test that request is accepted when callback returns True."""
    mock_ssl_sock = Mock(spec=ssl.SSLSocket)
    mock_ssl_sock.getpeercert.return_value = b"valid cert"

    callback = Mock(return_value=True)
    handler = self._make_handler(
      ssl_verify_peer=True,
      ssl_verify_callback=callback,
      connection=mock_ssl_sock
    )

    # Should not raise
    handler._verify_client_certificate()


class TestHttpServerHandler:
  """Test HttpServerHandler base class."""

  def test_handler_is_abstract(self):
    """Test handler requires HandleRequest implementation."""
    handler = server.HttpServerHandler()

    # PreHandleRequest should work (it's a hook)
    handler.PreHandleRequest(None)  # Should not raise

    # HandleRequest should raise NotImplementedError
    with pytest.raises(NotImplementedError):
      handler.HandleRequest(None)

  def test_format_error_message(self):
    """Test error message formatting."""
    values = {
      "code": 404,
      "message": "Not Found",
      "explain": "The resource was not found",
    }

    content_type, body = server.HttpServerHandler.FormatErrorMessage(values)

    assert content_type == server.DEFAULT_ERROR_CONTENT_TYPE
    assert "404" in body
    assert "Not Found" in body
    assert "The resource was not found" in body


class TestSSLContextCreation:
  """Test SSL context creation."""

  @pytest.fixture
  def cert_paths(self, tmp_path):
    """Provide paths to test certificates."""
    import shutil
    import os

    test_data_dir = os.path.join(
      os.path.dirname(__file__),
      "..", "..", "..", "data"
    )

    cert2_src = os.path.join(test_data_dir, "cert2.pem")
    cert2_dst = tmp_path / "cert2.pem"
    shutil.copy(cert2_src, cert2_dst)

    return {"cert2": str(cert2_dst)}

  def test_ssl_context_with_verification(self, cert_paths):
    """Test SSL context is configured for client certificate verification."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=cert_paths["cert2"],
      ssl_cert_path=cert_paths["cert2"]
    )

    ctx = server.HttpServer._create_ssl_context(
      ssl_params, ssl_verify_peer=True
    )

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED

  def test_ssl_context_without_verification(self, cert_paths):
    """Test SSL context without client certificate verification."""
    ssl_params = http.HttpSslParams(
      ssl_key_path=cert_paths["cert2"],
      ssl_cert_path=cert_paths["cert2"]
    )

    ctx = server.HttpServer._create_ssl_context(
      ssl_params, ssl_verify_peer=False
    )

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode != ssl.CERT_REQUIRED

  def test_ssl_server_has_ssl_context(self, cert_paths):
    """Test that server stores SSL context for per-connection wrapping."""
    mock_handler = MockHandler()

    ssl_params = http.HttpSslParams(
      ssl_key_path=cert_paths["cert2"],
      ssl_cert_path=cert_paths["cert2"]
    )

    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler,
      ssl_params=ssl_params,
      ssl_verify_peer=False
    )

    # Listening socket stays plain TCP; TLS is applied per-connection
    assert not isinstance(http_server.socket, ssl.SSLSocket)
    assert isinstance(http_server._ssl_context, ssl.SSLContext)

    http_server.server_close()

  def test_ssl_server_with_verify_peer(self, cert_paths):
    """Test SSL server with client certificate verification."""
    mock_handler = MockHandler()

    ssl_params = http.HttpSslParams(
      ssl_key_path=cert_paths["cert2"],
      ssl_cert_path=cert_paths["cert2"]
    )

    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler,
      ssl_params=ssl_params,
      ssl_verify_peer=True,
      ssl_verify_callback=Mock()
    )

    assert not isinstance(http_server.socket, ssl.SSLSocket)
    assert isinstance(http_server._ssl_context, ssl.SSLContext)
    assert http_server.ssl_verify_peer is True
    assert http_server.ssl_verify_callback is not None

    http_server.server_close()

  def test_no_ssl_context_without_ssl_params(self):
    """Test that _ssl_context is None when no SSL params given."""
    mock_handler = MockHandler()

    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler
    )

    assert http_server._ssl_context is None

    http_server.server_close()


class TestIntegration:
  """Integration tests with real HTTP requests."""

  @pytest.fixture
  def running_server(self):
    """Create and start a test server."""
    mock_handler = MockHandler(response='{"test": "response"}')

    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler,
      max_clients=5
    )

    http_server.Start()
    time.sleep(0.1)  # Let server start

    actual_port = http_server.server_address[1]

    yield (http_server, actual_port, mock_handler)

    # Cleanup
    http_server.Stop()
    time.sleep(0.1)

  def test_simple_get_request(self, running_server):
    """Test handling a simple GET request."""
    http_server, port, mock_handler = running_server

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
      conn.request("GET", "/test/path")
      response = conn.getresponse()

      assert response.status == 200
      body = response.read().decode("utf-8")
      assert body == '{"test": "response"}'

      assert mock_handler.pre_handle_called
      assert mock_handler.handle_called
      assert mock_handler.last_request_method == "GET"
      assert mock_handler.last_request_path == "/test/path"

    finally:
      conn.close()

  def test_post_request_with_body(self, running_server):
    """Test handling POST request with body."""
    http_server, port, mock_handler = running_server

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
      body_data = b'{"key": "value"}'
      headers = {"Content-Type": "application/json"}

      conn.request("POST", "/api/endpoint", body=body_data, headers=headers)
      response = conn.getresponse()

      assert response.status == 200

      assert mock_handler.last_request_body == body_data
      assert mock_handler.last_request_method == "POST"

    finally:
      conn.close()

  def test_http_methods(self, running_server):
    """Test different HTTP methods."""
    http_server, port, mock_handler = running_server

    for method in ["GET", "POST", "PUT", "DELETE"]:
      conn = HTTPConnection("127.0.0.1", port, timeout=5)
      try:
        conn.request(method, "/test")
        response = conn.getresponse()

        assert response.status == 200
        assert mock_handler.last_request_method == method

        response.read()

      finally:
        conn.close()

  def test_error_handling(self, running_server):
    """Test HTTP exception handling."""
    http_server, port, _ = running_server

    error_handler = MockHandler()

    def raise_error(req):
      raise http.HttpNotFound(message="Test not found")

    error_handler.HandleRequest = raise_error
    http_server.ganeti_handler = error_handler

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
      conn.request("GET", "/nonexistent")
      response = conn.getresponse()

      assert response.status == 404

    finally:
      conn.close()

  def test_concurrent_requests(self, running_server):
    """Test handling multiple concurrent requests."""
    http_server, port, mock_handler = running_server

    def make_request(path):
      """Make a single HTTP request."""
      conn = HTTPConnection("127.0.0.1", port, timeout=5)
      try:
        conn.request("GET", path)
        response = conn.getresponse()
        response.read()
        return response.status
      finally:
        conn.close()

    threads = []
    results = []

    for i in range(5):
      def request_thread(idx=i):
        status = make_request(f"/test/{idx}")
        results.append(status)

      t = threading.Thread(target=request_thread)
      threads.append(t)
      t.start()

    for t in threads:
      t.join(timeout=5.0)

    assert len(results) == 5
    assert all(status == 200 for status in results)


class TestSecurityFeatures:
  """Test security-related features."""

  @pytest.fixture
  def mock_handler(self):
    """Create mock handler."""
    return MockHandler()

  def test_request_body_size_limit(self, mock_handler):
    """Test request body size limit is enforced."""
    http_server = server.HttpServer(
      "127.0.0.1", 0,
      mock_handler,
      max_clients=5
    )

    http_server.Start()
    time.sleep(0.1)

    port = http_server.server_address[1]

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
      large_size = server.GanetiRequestHandler.MAX_REQUEST_BODY_SIZE + 1
      headers = {"Content-Length": str(large_size)}

      conn.request("POST", "/test", headers=headers)

      response = conn.getresponse()

      assert response.status == 413

    finally:
      conn.close()
      http_server.Stop()

  def test_timeout_configuration(self):
    """Test timeout is properly configured."""
    assert server.GanetiRequestHandler.timeout == 10
    assert 1 <= server.GanetiRequestHandler.timeout <= 60
