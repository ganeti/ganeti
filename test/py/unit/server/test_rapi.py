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

"""Pytest tests for ganeti.server.rapi module.

Converted from legacy unittest-based tests.

"""

import pytest
import tempfile
from io import StringIO
from unittest.mock import Mock

from ganeti import constants
from ganeti import http
from ganeti import serializer
from ganeti import objects
from ganeti.http import auth
from ganeti.server import rapi


class FakeLuxiClientForQuery:
  """Mock LUXI client for query tests."""

  def __init__(self, *args, **kwargs):
    pass

  def Query(self, *args):
    return objects.QueryResponse(fields=[])


@pytest.fixture
def make_auth_headers():
  """Factory for creating Basic Auth headers."""
  def _make_headers(username, password):
    import base64
    credentials = f"{username}:{password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"
  return _make_headers


class TestRemoteApiHandler:
  """Test RemoteApiHandler class."""

  @pytest.fixture
  def user_lookup_none(self):
    """User lookup that returns None (no user found)."""
    def _lookup(username):
      return None
    return _lookup

  @pytest.fixture
  def user_lookup_admin(self):
    """User lookup that returns admin with password."""
    def _lookup(username):
      if username == "admin":
        return auth.PasswordFileUser("admin", "password123", ["write"])
      return None
    return _lookup

  @pytest.fixture
  def basic_handler(self, user_lookup_none):
    """Create a basic RemoteApiHandler."""
    return rapi.RemoteApiHandler(user_lookup_none, reqauth=False)

  def _make_request(self, handler, method, path, headers_str, body):
    """Helper to make a request through the handler.

    Note: This is a simplified test helper. In a real scenario,
    we'd use the testutils._RapiMock from lib/rapi/testutils.py
    """
    # Parse headers
    if headers_str:
      headers = http.ParseHeaders(StringIO(headers_str))
    else:
      headers = {}

    # Create request context
    from ganeti.http.server import _HttpServerRequest
    req = _HttpServerRequest(method, path, headers, body, None)

    try:
      # Call PreHandleRequest (authentication)
      handler.PreHandleRequest(req)

      # Call HandleRequest
      result = handler.HandleRequest(req)

      # Parse JSON result
      data = serializer.LoadJson(result) if result else None

      return (http.HTTP_OK, req.resp_headers, data)

    except http.HttpException as err:
      # Format error response
      # Get default HTTP status message if exception doesn't provide one
      from http.server import BaseHTTPRequestHandler
      default_message = ""
      default_explain = ""
      if err.code in BaseHTTPRequestHandler.responses:
        default_message, default_explain = \
          BaseHTTPRequestHandler.responses[err.code]

      values = {
        "code": err.code,
        "message": err.message if err.message else default_message,
        "explain": default_explain
      }
      content_type, body = handler.FormatErrorMessage(values)
      data = serializer.LoadJson(body)
      return (err.code, err.headers or {}, data)

  def test_root_endpoint(self, basic_handler):
    """Test GET / returns None."""
    code, headers, data = self._make_request(basic_handler, "GET", "/", "",
                                             None)

    assert code == http.HTTP_OK
    assert data is None

  def test_version_endpoint(self, basic_handler):
    """Test GET /version returns RAPI version."""
    code, headers, data = self._make_request(
      basic_handler, "GET", "/version", "", None
    )

    assert code == http.HTTP_OK
    assert data == constants.RAPI_VERSION

  def test_unsupported_method(self, basic_handler):
    """Test unsupported HTTP method returns 501."""
    code, headers, data = self._make_request(
      basic_handler, "PUT", "/2/instances", "", None
    )

    assert code == http.HttpNotImplemented.code
    assert "Method PUT is unsupported" in data["message"]

  def test_unsupported_media_type(self, basic_handler):
    """Test request with unsupported Content-Type."""
    headers = "Content-Type: text/plain\r\n\r\n"

    code, _, data = self._make_request(
      basic_handler, "GET", "/", headers, "body"
    )

    assert code == http.HttpUnsupportedMediaType.code
    assert data["message"] == "Unsupported Media Type"

  def test_invalid_json_body(self, basic_handler):
    """Test request with invalid JSON in body."""
    headers = "Content-Type: application/json\r\n\r\n"
    invalid_json = "_this/is/no'valid.json"

    # Verify it's actually invalid JSON
    with pytest.raises(Exception):
      serializer.LoadJson(invalid_json)

    code, _, data = self._make_request(
      basic_handler, "GET", "/", headers, invalid_json
    )

    assert code == http.HttpBadRequest.code
    assert data["message"] == "Unable to parse JSON data"

  @pytest.mark.parametrize("auth_header", [
    "Unsupported scheme",  # Unknown scheme
    "Basic",  # Incomplete
    "",  # Empty
  ])
  def test_invalid_auth_headers(self, user_lookup_admin, auth_header):
    """Test various invalid authentication headers."""
    handler = rapi.RemoteApiHandler(user_lookup_admin, reqauth=False)

    headers = f"Authorization: {auth_header}\r\n\r\n"

    code, _, _ = self._make_request(
      handler, "POST", "/2/instances", headers, ""
    )

    # Should get either 401 Unauthorized or 400 Bad Request
    assert code in (http.HttpUnauthorized.code, http.HttpBadRequest.code)

  def test_authentication_with_wrong_password(self, user_lookup_admin,
                                              make_auth_headers):
    """Test authentication with wrong password."""
    handler = rapi.RemoteApiHandler(user_lookup_admin, reqauth=False)

    auth_value = make_auth_headers("admin", "wrongpassword")
    headers = f"Authorization: {auth_value}\r\nContent-Type: " \
      "application/json\r\n\r\n"

    code, _, _ = self._make_request(
      handler, "POST", "/2/instances", headers, ""
    )

    assert code == http.HttpUnauthorized.code

  def test_authentication_with_unknown_user(self, user_lookup_admin,
                                            make_auth_headers):
    """Test authentication with unknown username."""
    handler = rapi.RemoteApiHandler(user_lookup_admin, reqauth=False)

    auth_value = make_auth_headers("unknown", "password")
    headers = f"Authorization: {auth_value}\r\nContent-Type: " \
      "application/json\r\n\r\n"

    code, _, _ = self._make_request(
      handler, "POST", "/2/instances", headers, ""
    )

    assert code == http.HttpUnauthorized.code

  def test_format_error_message_returns_json(self):
    """Test error messages are formatted as JSON."""
    handler = rapi.RemoteApiHandler(lambda x: None, reqauth=False)

    values = {
      "code": 404,
      "message": "Not Found",
      "explain": "Resource not found"
    }

    content_type, body = handler.FormatErrorMessage(values)

    assert content_type == http.HTTP_APP_JSON
    data = serializer.LoadJson(body)
    assert data["code"] == 404


class TestRapiUsers:
  """Test RapiUsers class."""

  def test_get_no_users_loaded(self):
    """Test Get returns None when no users loaded."""
    users = rapi.RapiUsers()
    assert users.Get("anyone") is None

  def test_load_simple_users_file(self, tmp_path):
    """Test loading a simple users file."""
    users_file = tmp_path / "rapi_users"
    users_file.write_text("admin password123\n")

    users = rapi.RapiUsers()
    result = users.Load(str(users_file))

    assert result is True
    admin_user = users.Get("admin")
    assert admin_user is not None
    assert admin_user.password == "password123"
    assert len(admin_user.options) == 0

  def test_load_users_with_options(self, tmp_path):
    """Test loading users file with options."""
    users_file = tmp_path / "rapi_users"
    users_file.write_text(
      "# Comment line\n"
      "admin adminpass write,read\n"
      "readonly ropass read\n"
      "\n"  # Empty line
      "# Another comment\n"
    )

    users = rapi.RapiUsers()
    result = users.Load(str(users_file))

    assert result is True

    # Check admin user
    admin = users.Get("admin")
    assert admin.password == "adminpass"
    assert "write" in admin.options
    assert "read" in admin.options

    # Check readonly user
    readonly = users.Get("readonly")
    assert readonly.password == "ropass"
    assert "read" in readonly.options
    assert "write" not in readonly.options

  def test_load_nonexistent_file(self):
    """Test loading non-existent file returns False."""
    users = rapi.RapiUsers()
    result = users.Load("/nonexistent/path/to/users")

    assert result is False
    assert users.Get("anyone") is None

  def test_load_invalid_file(self, tmp_path, caplog):
    """Test loading invalid users file."""
    import logging
    caplog.set_level(logging.ERROR)

    users_file = tmp_path / "rapi_users"
    # Write something that will cause parsing error
    # (actual error depends on ParsePasswordFile implementation)
    users_file.write_bytes(b'\xff\xfe Invalid UTF-8')

    users = rapi.RapiUsers()
    result = users.Load(str(users_file))

    # Should handle error gracefully
    assert result is False


class TestRemoteApiHandlerIntegration:
  """Integration tests using rapi.testutils if available."""

  def test_handler_creation(self):
    """Test creating RemoteApiHandler."""
    def user_fn(username):
      return None

    handler = rapi.RemoteApiHandler(user_fn, reqauth=False)

    assert handler is not None
    assert hasattr(handler, 'HandleRequest')
    assert hasattr(handler, 'PreHandleRequest')

  def test_handler_with_auth_required(self):
    """Test handler with authentication required."""
    def user_fn(username):
      if username == "testuser":
        return auth.PasswordFileUser("testuser", "testpass", [])
      return None

    handler = rapi.RemoteApiHandler(user_fn, reqauth=True)

    # Create unauthenticated request
    from ganeti.http.server import _HttpServerRequest
    req = _HttpServerRequest("GET", "/", {}, b"", None)

    # Should raise HttpUnauthorized for authenticated resource
    with pytest.raises(http.HttpUnauthorized):
      handler.PreHandleRequest(req)


