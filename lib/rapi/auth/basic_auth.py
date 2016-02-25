#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2012, 2013, 2015 Google Inc.
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


"""Module interacting with RAPI users config file

"""

import logging
import os
try:
  from pyinotify import pyinotify # pylint: disable=E0611
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import compat
from ganeti import http
from ganeti.http.auth import HttpServerRequestAuthentication
from ganeti import pathutils
from ganeti.rapi import auth
from ganeti.rapi.auth import users_file


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


class BasicAuthenticator(auth.RapiAuthenticator):
  """Class providing an Authenticate method based on basic http authentication.

  """

  def __init__(self, user_fn=None):
    """Loads users file and initializes a watcher for it.

    @param user_fn: A function that should be called to obtain a user info
                    instead of the default users_file interface.

    """
    if user_fn:
      self.user_fn = user_fn
      return

    self.users = users_file.RapiUsers()
    self.user_fn = self.users.Get
    # Setup file watcher (it'll be driven by asyncore)
    SetupFileWatcher(pathutils.RAPI_USERS_FILE,
                     compat.partial(self.users.Load,
                                    pathutils.RAPI_USERS_FILE))

    self.users.Load(pathutils.RAPI_USERS_FILE)

  def ValidateRequest(self, req, handler_access, realm):
    """Checks whether a user can access a resource.

    """
    request_username, request_password = HttpServerRequestAuthentication \
                                           .ExtractUserPassword(req)
    if request_username is None:
      raise http.HttpUnauthorized()
    if request_password is None:
      raise http.HttpBadRequest(message=("Basic authentication requires"
                                         " password"))

    user = self.user_fn(request_username)
    if not (user and HttpServerRequestAuthentication
                       .VerifyBasicAuthPassword(request_username,
                                                request_password,
                                                user.password, realm)):
      # Unknown user or password wrong
      return None

    if (not handler_access or
        set(user.options).intersection(handler_access)):
      # Allow access
      return request_username

    # Access forbidden
    raise http.HttpForbidden()
