#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2012, 2013 Google Inc.
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

"""Ganeti Remote API master script.

"""

# pylint: disable=C0103,W0142

# C0103: Invalid name ganeti-watcher

import logging
import optparse
import sys

from ganeti import constants
from ganeti import http
from ganeti import daemon
from ganeti import ssconf
import ganeti.rpc.errors as rpcerr
from ganeti import serializer
from ganeti import pathutils
from ganeti.rapi import connector
from ganeti.rapi import baserlib
from ganeti.rapi.auth import basic_auth
from ganeti.rapi.auth import pam

import ganeti.http.auth   # pylint: disable=W0611
import ganeti.http.server


class RemoteApiRequestContext(object):
  """Data structure for Remote API requests.

  """
  def __init__(self):
    self.handler = None
    self.handler_fn = None
    self.handler_access = None
    self.body_data = None


class RemoteApiHandler(http.auth.HttpServerRequestAuthentication,
                       http.server.HttpServerHandler):
  """REST Request Handler Class.

  """
  AUTH_REALM = "Ganeti Remote API"

  def __init__(self, authenticator, reqauth, _client_cls=None):
    """Initializes this class.

    @type authenticator: an implementation of {RapiAuthenticator} interface
    @param authenticator: a class containing an implementation of
                          ValidateRequest function
    @type reqauth: bool
    @param reqauth: Whether to require authentication

    """
    # pylint: disable=W0233
    # it seems pylint doesn't see the second parent class there
    http.server.HttpServerHandler.__init__(self)
    http.auth.HttpServerRequestAuthentication.__init__(self)
    self._client_cls = _client_cls
    self._resmap = connector.Mapper()
    self._authenticator = authenticator
    self._reqauth = reqauth

  @staticmethod
  def FormatErrorMessage(values):
    """Formats the body of an error message.

    @type values: dict
    @param values: dictionary with keys C{code}, C{message} and C{explain}.
    @rtype: tuple; (string, string)
    @return: Content-type and response body

    """
    return (http.HTTP_APP_JSON, serializer.DumpJson(values))

  def _GetRequestContext(self, req):
    """Returns the context for a request.

    The context is cached in the req.private variable.

    """
    if req.private is None:
      (HandlerClass, items, args) = \
                     self._resmap.getController(req.request_path)

      ctx = RemoteApiRequestContext()
      ctx.handler = HandlerClass(items, args, req, _client_cls=self._client_cls)

      method = req.request_method.upper()
      try:
        ctx.handler_fn = getattr(ctx.handler, method)
      except AttributeError:
        raise http.HttpNotImplemented("Method %s is unsupported for path %s" %
                                      (method, req.request_path))

      ctx.handler_access = baserlib.GetHandlerAccess(ctx.handler, method)

      # Require permissions definition (usually in the base class)
      if ctx.handler_access is None:
        raise AssertionError("Permissions definition missing")

      # This is only made available in HandleRequest
      ctx.body_data = None

      req.private = ctx

    # Check for expected attributes
    assert req.private.handler
    assert req.private.handler_fn
    assert req.private.handler_access is not None

    return req.private

  def AuthenticationRequired(self, req):
    """Determine whether authentication is required.

    """
    return self._reqauth

  def Authenticate(self, req):
    """Checks whether a user can access a resource.

    @return: username of an authenticated user or None otherwise
    """
    ctx = self._GetRequestContext(req)
    auth_user = self._authenticator.ValidateRequest(
        req, ctx.handler_access, self.GetAuthRealm(req))
    if auth_user is None:
      return False

    ctx.handler.auth_user = auth_user
    return True

  def HandleRequest(self, req):
    """Handles a request.

    """
    ctx = self._GetRequestContext(req)

    # Deserialize request parameters
    if req.request_body:
      # RFC2616, 7.2.1: Any HTTP/1.1 message containing an entity-body SHOULD
      # include a Content-Type header field defining the media type of that
      # body. [...] If the media type remains unknown, the recipient SHOULD
      # treat it as type "application/octet-stream".
      req_content_type = req.request_headers.get(http.HTTP_CONTENT_TYPE,
                                                 http.HTTP_APP_OCTET_STREAM)
      if req_content_type.lower() != http.HTTP_APP_JSON.lower():
        raise http.HttpUnsupportedMediaType()

      try:
        ctx.body_data = serializer.LoadJson(req.request_body)
      except Exception:
        raise http.HttpBadRequest(message="Unable to parse JSON data")
    else:
      ctx.body_data = None

    try:
      result = ctx.handler_fn()
    except rpcerr.TimeoutError:
      raise http.HttpGatewayTimeout()
    except rpcerr.ProtocolError, err:
      raise http.HttpBadGateway(str(err))

    req.resp_headers[http.HTTP_CONTENT_TYPE] = http.HTTP_APP_JSON

    return serializer.DumpJson(result)


def CheckRapi(options, args):
  """Initial checks whether to run or exit with a failure.

  """
  if args: # rapi doesn't take any arguments
    print >> sys.stderr, ("Usage: %s [-f] [-d] [-p port] [-b ADDRESS]" %
                          sys.argv[0])
    sys.exit(constants.EXIT_FAILURE)

  ssconf.CheckMaster(options.debug)

  # Read SSL certificate (this is a little hackish to read the cert as root)
  if options.ssl:
    options.ssl_params = http.HttpSslParams(ssl_key_path=options.ssl_key,
                                            ssl_cert_path=options.ssl_cert)
  else:
    options.ssl_params = None


def PrepRapi(options, _):
  """Prep remote API function, executed with the PID file held.

  """
  mainloop = daemon.Mainloop()

  if options.pamauth:
    options.reqauth = True
    authenticator = pam.PamAuthenticator()
  else:
    authenticator = basic_auth.BasicAuthenticator()

  handler = RemoteApiHandler(authenticator, options.reqauth)

  server = \
    http.server.HttpServer(mainloop, options.bind_address, options.port,
                           handler,
                           ssl_params=options.ssl_params, ssl_verify_peer=False)
  server.Start()

  return (mainloop, server)


def ExecRapi(options, args, prep_data): # pylint: disable=W0613
  """Main remote API function, executed with the PID file held.

  """

  (mainloop, server) = prep_data
  try:
    mainloop.Run()
  finally:
    logging.error("RAPI Daemon Failed")
    server.Stop()


def Main():
  """Main function.

  """
  parser = optparse.OptionParser(description="Ganeti Remote API",
                                 usage=("%prog [-f] [-d] [-p port] [-b ADDRESS]"
                                        " [-i INTERFACE]"),
                                 version="%%prog (ganeti) %s" %
                                 constants.RELEASE_VERSION)
  parser.add_option("--require-authentication", dest="reqauth",
                    default=False, action="store_true",
                    help=("Disable anonymous HTTP requests and require"
                          " authentication"))
  parser.add_option("--pam-authentication", dest="pamauth",
                    default=False, action="store_true",
                    help=("Enable RAPI authentication and authorization via"
                          " PAM"))

  daemon.GenericMain(constants.RAPI, parser, CheckRapi, PrepRapi, ExecRapi,
                     default_ssl_cert=pathutils.RAPI_CERT_FILE,
                     default_ssl_key=pathutils.RAPI_CERT_FILE)
