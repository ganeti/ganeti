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

# pylint: disable=C0103

# C0103: Invalid name ganeti-watcher

import logging
import optparse
import sys
import os
import os.path
import errno

try:
  from pyinotify import pyinotify # pylint: disable=E0611
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import constants
from ganeti import http
from ganeti import daemon
from ganeti import ssconf
import ganeti.rpc.errors as rpcerr
from ganeti import serializer
from ganeti import compat
from ganeti import utils
from ganeti import pathutils
from ganeti.rapi import connector
from ganeti.rapi import baserlib

import ganeti.http.auth   # pylint: disable=W0611
import ganeti.http.server # pylint: disable=W0611


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

  def __init__(self, user_fn, reqauth, _client_cls=None):
    """Initializes this class.

    @type user_fn: callable
    @param user_fn: Function receiving username as string and returning
      L{http.auth.PasswordFileUser} or C{None} if user is not found
    @type reqauth: bool
    @param reqauth: Whether to require authentication

    """
    # pylint: disable=W0233
    # it seems pylint doesn't see the second parent class there
    http.server.HttpServerHandler.__init__(self)
    http.auth.HttpServerRequestAuthentication.__init__(self)
    self._client_cls = _client_cls
    self._resmap = connector.Mapper()
    self._user_fn = user_fn
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
    return self._reqauth or bool(self._GetRequestContext(req).handler_access)

  def Authenticate(self, req, username, password):
    """Checks whether a user can access a resource.

    """
    ctx = self._GetRequestContext(req)

    user = self._user_fn(username)
    if not (user and
            self.VerifyBasicAuthPassword(req, username, password,
                                         user.password)):
      # Unknown user or password wrong
      return False

    if (not ctx.handler_access or
        set(user.options).intersection(ctx.handler_access)):
      # Allow access
      return True

    # Access forbidden
    raise http.HttpForbidden()

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


class RapiUsers(object):
  def __init__(self):
    """Initializes this class.

    """
    self._users = None

  def Get(self, username):
    """Checks whether a user exists.

    """
    if self._users:
      return self._users.get(username, None)
    else:
      return None

  def Load(self, filename):
    """Loads a file containing users and passwords.

    @type filename: string
    @param filename: Path to file

    """
    logging.info("Reading users file at %s", filename)
    try:
      try:
        contents = utils.ReadFile(filename)
      except EnvironmentError, err:
        self._users = None
        if err.errno == errno.ENOENT:
          logging.warning("No users file at %s", filename)
        else:
          logging.warning("Error while reading %s: %s", filename, err)
        return False

      users = http.auth.ParsePasswordFile(contents)

    except Exception, err: # pylint: disable=W0703
      # We don't care about the type of exception
      logging.error("Error while parsing %s: %s", filename, err)
      return False

    self._users = users

    return True


class FileEventHandler(asyncnotifier.FileEventHandlerBase):
  def __init__(self, wm, path, cb):
    """Initializes this class.

    @param wm: Inotify watch manager
    @type path: string
    @param path: File path
    @type cb: callable
    @param cb: Function called on file change

    """
    asyncnotifier.FileEventHandlerBase.__init__(self, wm)

    self._cb = cb
    self._filename = os.path.basename(path)

    # Different Pyinotify versions have the flag constants at different places,
    # hence not accessing them directly
    mask = (pyinotify.EventsCodes.ALL_FLAGS["IN_CLOSE_WRITE"] |
            pyinotify.EventsCodes.ALL_FLAGS["IN_DELETE"] |
            pyinotify.EventsCodes.ALL_FLAGS["IN_MOVED_FROM"] |
            pyinotify.EventsCodes.ALL_FLAGS["IN_MOVED_TO"])

    self._handle = self.AddWatch(os.path.dirname(path), mask)

  def process_default(self, event):
    """Called upon inotify event.

    """
    if event.name == self._filename:
      logging.debug("Received inotify event %s", event)
      self._cb()


def SetupFileWatcher(filename, cb):
  """Configures an inotify watcher for a file.

  @type filename: string
  @param filename: File to watch
  @type cb: callable
  @param cb: Function called on file change

  """
  wm = pyinotify.WatchManager()
  handler = FileEventHandler(wm, filename, cb)
  asyncnotifier.AsyncNotifier(wm, default_proc_fun=handler)


def CheckRapi(options, args):
  """Initial checks whether to run or exit with a failure.

  """
  if args: # rapi doesn't take any arguments
    print >> sys.stderr, ("Usage: %s [-f] [-d] [-p port] [-b ADDRESS]" %
                          sys.argv[0])
    sys.exit(constants.EXIT_FAILURE)

  if options.max_clients < 1:
    print >> sys.stderr, ("%s --max-clients argument must be >= 1" %
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

  users = RapiUsers()

  handler = RemoteApiHandler(users.Get, options.reqauth)

  # Setup file watcher (it'll be driven by asyncore)
  SetupFileWatcher(pathutils.RAPI_USERS_FILE,
                   compat.partial(users.Load, pathutils.RAPI_USERS_FILE))

  users.Load(pathutils.RAPI_USERS_FILE)

  server = http.server.HttpServer(
      mainloop, options.bind_address, options.port, options.max_clients,
      handler, ssl_params=options.ssl_params, ssl_verify_peer=False)
  server.Start()

  return (mainloop, server)


def ExecRapi(options, args, prep_data): # pylint: disable=W0613
  """Main remote API function, executed with the PID file held.

  """
  (mainloop, server) = prep_data
  try:
    mainloop.Run()
  finally:
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
  parser.add_option("--max-clients", dest="max_clients",
                    default=20, type="int",
                    help="Number of simultaneous connections accepted"
                    " by ganeti-rapi")

  daemon.GenericMain(constants.RAPI, parser, CheckRapi, PrepRapi, ExecRapi,
                     default_ssl_cert=pathutils.RAPI_CERT_FILE,
                     default_ssl_key=pathutils.RAPI_CERT_FILE)
