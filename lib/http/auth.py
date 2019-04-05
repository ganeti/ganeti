#
#

# Copyright (C) 2007, 2008 Google Inc.
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

"""HTTP authentication module.

"""

import logging
import re
import base64
import binascii

from cStringIO import StringIO

from ganeti import compat
from ganeti import http
from ganeti import utils

# Digest types from RFC2617
HTTP_BASIC_AUTH = "Basic"
HTTP_DIGEST_AUTH = "Digest"

# Not exactly as described in RFC2616, section 2.2, but good enough
_NOQUOTE = re.compile(r"^[-_a-z0-9]+$", re.I)


def _FormatAuthHeader(scheme, params):
  """Formats WWW-Authentication header value as per RFC2617, section 1.2

  @type scheme: str
  @param scheme: Authentication scheme
  @type params: dict
  @param params: Additional parameters
  @rtype: str
  @return: Formatted header value

  """
  buf = StringIO()

  buf.write(scheme)

  for name, value in params.items():
    buf.write(" ")
    buf.write(name)
    buf.write("=")
    if _NOQUOTE.match(value):
      buf.write(value)
    else:
      buf.write("\"")
      # TODO: Better quoting
      buf.write(value.replace("\"", "\\\""))
      buf.write("\"")

  return buf.getvalue()


class HttpServerRequestAuthentication(object):
  # Default authentication realm
  AUTH_REALM = "Unspecified"

  # Schemes for passwords
  _CLEARTEXT_SCHEME = "{CLEARTEXT}"
  _HA1_SCHEME = "{HA1}"

  def GetAuthRealm(self, req):
    """Returns the authentication realm for a request.

    May be overridden by a subclass, which then can return different realms for
    different paths.

    @type req: L{http.server._HttpServerRequest}
    @param req: HTTP request context
    @rtype: string
    @return: Authentication realm

    """
    # today we don't have per-request filtering, but we might want to
    # add it in the future
    # pylint: disable=W0613
    return self.AUTH_REALM

  def AuthenticationRequired(self, req):
    """Determines whether authentication is required for a request.

    To enable authentication, override this function in a subclass and return
    C{True}. L{AUTH_REALM} must be set.

    @type req: L{http.server._HttpServerRequest}
    @param req: HTTP request context

    """
    # Unused argument, method could be a function
    # pylint: disable=W0613,R0201
    return False

  def PreHandleRequest(self, req):
    """Called before a request is handled.

    @type req: L{http.server._HttpServerRequest}
    @param req: HTTP request context

    """
    # Authentication not required, and no credentials given?
    if not (self.AuthenticationRequired(req) or
            (req.request_headers and
             http.HTTP_AUTHORIZATION in req.request_headers)):
      return

    realm = self.GetAuthRealm(req)

    if not realm:
      raise AssertionError("No authentication realm")

    # Check "Authorization" header
    if self._CheckAuthorization(req):
      # User successfully authenticated
      return

    # Send 401 Unauthorized response
    params = {
      "realm": realm,
      }

    # TODO: Support for Digest authentication (RFC2617, section 3).
    # TODO: Support for more than one WWW-Authenticate header with the same
    # response (RFC2617, section 4.6).
    headers = {
      http.HTTP_WWW_AUTHENTICATE: _FormatAuthHeader(HTTP_BASIC_AUTH, params),
      }

    raise http.HttpUnauthorized(headers=headers)

  def _CheckAuthorization(self, req):
    """Checks 'Authorization' header sent by client.

    @type req: L{http.server._HttpServerRequest}
    @param req: HTTP request context
    @rtype: bool
    @return: Whether user is allowed to execute request

    """
    credentials = req.request_headers.get(http.HTTP_AUTHORIZATION, None)
    if not credentials:
      return False

    # Extract scheme
    parts = credentials.strip().split(None, 2)
    if len(parts) < 1:
      # Missing scheme
      return False

    # RFC2617, section 1.2: "[...] It uses an extensible, case-insensitive
    # token to identify the authentication scheme [...]"
    scheme = parts[0].lower()

    if scheme == HTTP_BASIC_AUTH.lower():
      # Do basic authentication
      if len(parts) < 2:
        raise http.HttpBadRequest(message=("Basic authentication requires"
                                           " credentials"))
      return self._CheckBasicAuthorization(req, parts[1])

    elif scheme == HTTP_DIGEST_AUTH.lower():
      # TODO: Implement digest authentication
      # RFC2617, section 3.3: "Note that the HTTP server does not actually need
      # to know the user's cleartext password. As long as H(A1) is available to
      # the server, the validity of an Authorization header may be verified."
      pass

    # Unsupported authentication scheme
    return False

  def _CheckBasicAuthorization(self, req, in_data):
    """Checks credentials sent for basic authentication.

    @type req: L{http.server._HttpServerRequest}
    @param req: HTTP request context
    @type in_data: str
    @param in_data: Username and password encoded as Base64
    @rtype: bool
    @return: Whether user is allowed to execute request

    """
    try:
      creds = base64.b64decode(in_data.encode("ascii")).decode("ascii")
    except (TypeError, binascii.Error, UnicodeError):
      logging.exception("Error when decoding Basic authentication credentials")
      return False

    if ":" not in creds:
      return False

    (user, password) = creds.split(":", 1)

    return self.Authenticate(req, user, password)

  def Authenticate(self, req, user, password):
    """Checks the password for a user.

    This function MUST be overridden by a subclass.

    """
    raise NotImplementedError()

  def VerifyBasicAuthPassword(self, req, username, password, expected):
    """Checks the password for basic authentication.

    As long as they don't start with an opening brace ("E{lb}"), old passwords
    are supported. A new scheme uses H(A1) from RFC2617, where H is MD5 and A1
    consists of the username, the authentication realm and the actual password.

    @type req: L{http.server._HttpServerRequest}
    @param req: HTTP request context
    @type username: string
    @param username: Username from HTTP headers
    @type password: string
    @param password: Password from HTTP headers
    @type expected: string
    @param expected: Expected password with optional scheme prefix (e.g. from
                     users file)

    """
    # Backwards compatibility for old-style passwords without a scheme
    if not expected.startswith("{"):
      expected = self._CLEARTEXT_SCHEME + expected

    # Check again, just to be sure
    if not expected.startswith("{"):
      raise AssertionError("Invalid scheme")

    scheme_end_idx = expected.find("}", 1)

    # Ensure scheme has a length of at least one character
    if scheme_end_idx <= 1:
      logging.warning("Invalid scheme in password for user '%s'", username)
      return False

    scheme = expected[:scheme_end_idx + 1].upper()
    expected_password = expected[scheme_end_idx + 1:]

    # Good old plain text password
    if scheme == self._CLEARTEXT_SCHEME:
      return password == expected_password

    # H(A1) as described in RFC2617
    if scheme == self._HA1_SCHEME:
      realm = self.GetAuthRealm(req)
      if not realm:
        # There can not be a valid password for this case
        raise AssertionError("No authentication realm")

      expha1 = compat.md5_hash()
      expha1.update("%s:%s:%s" % (username, realm, password))

      return (expected_password.lower() == expha1.hexdigest().lower())

    logging.warning("Unknown scheme '%s' in password for user '%s'",
                    scheme, username)

    return False


class PasswordFileUser(object):
  """Data structure for users from password file.

  """
  def __init__(self, name, password, options):
    self.name = name
    self.password = password
    self.options = options


def ParsePasswordFile(contents):
  """Parses the contents of a password file.

  Lines in the password file are of the following format::

      <username> <password> [options]

  Fields are separated by whitespace. Username and password are mandatory,
  options are optional and separated by comma (','). Empty lines and comments
  ('#') are ignored.

  @type contents: str
  @param contents: Contents of password file
  @rtype: dict
  @return: Dictionary containing L{PasswordFileUser} instances

  """
  users = {}

  for line in utils.FilterEmptyLinesAndComments(contents):
    parts = line.split(None, 2)
    if len(parts) < 2:
      # Invalid line
      # TODO: Return line number from FilterEmptyLinesAndComments
      logging.warning("Ignoring non-comment line with less than two fields")
      continue

    name = parts[0]
    password = parts[1]

    # Extract options
    options = []
    if len(parts) >= 3:
      for part in parts[2].split(","):
        options.append(part.strip())
    else:
      logging.warning("Ignoring values for user '%s': %s", name, parts[3:])

    users[name] = PasswordFileUser(name, password, options)

  return users
