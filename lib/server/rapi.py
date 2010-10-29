#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010 Google Inc.
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

"""Ganeti Remote API master script.

"""

# pylint: disable-msg=C0103,W0142

# C0103: Invalid name ganeti-watcher

import logging
import optparse
import sys
import os
import os.path
import errno

try:
  from pyinotify import pyinotify # pylint: disable-msg=E0611
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import constants
from ganeti import http
from ganeti import daemon
from ganeti import ssconf
from ganeti import luxi
from ganeti import serializer
from ganeti import compat
from ganeti import utils
from ganeti.rapi import connector

import ganeti.http.auth   # pylint: disable-msg=W0611
import ganeti.http.server


class RemoteApiRequestContext(object):
  """Data structure for Remote API requests.

  """
  def __init__(self):
    self.handler = None
    self.handler_fn = None
    self.handler_access = None
    self.body_data = None


class JsonErrorRequestExecutor(http.server.HttpServerRequestExecutor):
  """Custom Request Executor class that formats HTTP errors in JSON.

  """
  error_content_type = http.HTTP_APP_JSON

  def _FormatErrorMessage(self, values):
    """Formats the body of an error message.

    @type values: dict
    @param values: dictionary with keys code, message and explain.
    @rtype: string
    @return: the body of the message

    """
    return serializer.DumpJson(values, indent=True)


class RemoteApiHttpServer(http.auth.HttpServerRequestAuthentication,
                          http.server.HttpServer):
  """REST Request Handler Class.

  """
  AUTH_REALM = "Ganeti Remote API"

  def __init__(self, *args, **kwargs):
    # pylint: disable-msg=W0233
    # it seems pylint doesn't see the second parent class there
    http.server.HttpServer.__init__(self, *args, **kwargs)
    http.auth.HttpServerRequestAuthentication.__init__(self)
    self._resmap = connector.Mapper()
    self._users = None

  def LoadUsers(self, filename):
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

    except Exception, err: # pylint: disable-msg=W0703
      # We don't care about the type of exception
      logging.error("Error while parsing %s: %s", filename, err)
      return False

    self._users = users

    return True

  def _GetRequestContext(self, req):
    """Returns the context for a request.

    The context is cached in the req.private variable.

    """
    if req.private is None:
      (HandlerClass, items, args) = \
                     self._resmap.getController(req.request_path)

      ctx = RemoteApiRequestContext()
      ctx.handler = HandlerClass(items, args, req)

      method = req.request_method.upper()
      try:
        ctx.handler_fn = getattr(ctx.handler, method)
      except AttributeError:
        raise http.HttpNotImplemented("Method %s is unsupported for path %s" %
                                      (method, req.request_path))

      ctx.handler_access = getattr(ctx.handler, "%s_ACCESS" % method, None)

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
    return bool(self._GetRequestContext(req).handler_access)

  def Authenticate(self, req, username, password):
    """Checks whether a user can access a resource.

    """
    ctx = self._GetRequestContext(req)

    # Check username and password
    valid_user = False
    if self._users:
      user = self._users.get(username, None)
      if user and self.VerifyBasicAuthPassword(req, username, password,
                                               user.password):
        valid_user = True

    if not valid_user:
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
    except luxi.TimeoutError:
      raise http.HttpGatewayTimeout()
    except luxi.ProtocolError, err:
      raise http.HttpBadGateway(str(err))
    except:
      method = req.request_method.upper()
      logging.exception("Error while handling the %s request", method)
      raise

    req.resp_headers[http.HTTP_CONTENT_TYPE] = http.HTTP_APP_JSON

    return serializer.DumpJson(result)


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
  server = RemoteApiHttpServer(mainloop, options.bind_address, options.port,
                               ssl_params=options.ssl_params,
                               ssl_verify_peer=False,
                               request_executor_class=JsonErrorRequestExecutor)

  # Setup file watcher (it'll be driven by asyncore)
  SetupFileWatcher(constants.RAPI_USERS_FILE,
                   compat.partial(server.LoadUsers, constants.RAPI_USERS_FILE))

  server.LoadUsers(constants.RAPI_USERS_FILE)

  # pylint: disable-msg=E1101
  # it seems pylint doesn't see the second parent class there
  server.Start()

  return (mainloop, server)


def ExecRapi(options, args, prep_data): # pylint: disable-msg=W0613
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
                    usage="%prog [-f] [-d] [-p port] [-b ADDRESS]",
                    version="%%prog (ganeti) %s" % constants.RELEASE_VERSION)

  daemon.GenericMain(constants.RAPI, parser, CheckRapi, PrepRapi, ExecRapi,
                     default_ssl_cert=constants.RAPI_CERT_FILE,
                     default_ssl_key=constants.RAPI_CERT_FILE)
