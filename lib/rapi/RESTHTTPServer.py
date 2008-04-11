#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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

import socket
import inspect
import exceptions
import SocketServer
import BaseHTTPServer
import OpenSSL
import logging
import logging.handlers
import sys
import os

from optparse import OptionParser
from ganeti.rapi import resources

"""RESTfull HTTPS Server module.

"""

def OpenLog():
  """Set up logging to the syslog.
  """
  log = logging.getLogger('ganeti-rapi')
  slh = logging.handlers.SysLogHandler('/dev/log',
                            logging.handlers.SysLogHandler.LOG_DAEMON)
  fmt = logging.Formatter('ganeti-rapi[%(process)d]:%(levelname)s: %(message)s')
  slh.setFormatter(fmt)
  log.addHandler(slh)
  log.setLevel(logging.INFO)
  log.debug("Logging initialized")

  return log


class RESTHTTPServer(BaseHTTPServer.HTTPServer):
  def __init__(self, server_address, HandlerClass, options):
    """ REST Server Constructor.

    Args:
      server_address - a touple with pair:
        ip - a string with IP address, localhost if null-string
        port - port number, integer
      HandlerClass - HTTPRequestHandler object.
      options: command-line options.
    """


    SocketServer.BaseServer.__init__(self, server_address, HandlerClass)
    if options.ssl:
      # Set up SSL
      context = OpenSSL.SSL.Context(OpenSSL.SSL.SSLv23_METHOD)
      context.use_privatekey_file(options.ssl_key)
      context.use_certificate_file(options.ssl_cert)
      self.socket = OpenSSL.SSL.Connection(context,
                                           socket.socket(self.address_family,
                                           self.socket_type))
    else:
      self.socket = socket.socket(self.address_family, self.socket_type)

    self.server_bind()
    self.server_activate()


class RESTRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
  """REST Request Handler Class."""

  def authenticate(self):
    """This method performs authentication check."""
    return True

  def setup(self):
    """Setup secure read and write file objects."""
    self.connection = self.request
    self.rfile = socket._fileobject(self.request, "rb", self.rbufsize)
    self.wfile = socket._fileobject(self.request, "wb", self.wbufsize)
    self.map = resources.Mapper()
    self.log = OpenLog()
    self.log.debug("Request handler setup.")

  def handle_one_request(self):
    """Handle a single REST request. """
    self.raw_requestline = None
    try:
      self.raw_requestline = self.rfile.readline()
    except OpenSSL.SSL.Error, ex:
      self.log.exception("Error in SSL: %s" % str(ex))
    if not self.raw_requestline:
      self.close_connection = 1
      return
    if not self.parse_request(): # An error code has been sent, just exit
      return
    if not self.authenticate():
      self.send_error(401, "Acces Denied")
      return
    try:
      rname = self.R_Resource(self.path)
      mname = 'do_' + self.command
      if not hasattr(rname, mname):
        self.send_error(501, "Unsupported method (%r)" % self.command)
        return
      method = getattr(rname, mname)
      method()
    except AttributeError, msg:
      self.send_error(501, "Resource is not available: %s" % msg)

  def log_message(self, format, *args):
    """Log an arbitrary message.

    This is used by all other logging functions.

    The first argument, FORMAT, is a format string for the
    message to be logged.  If the format string contains
    any % escapes requiring parameters, they should be
    specified as subsequent arguments (it's just like
    printf!).

    The client host and current date/time are prefixed to
    every message.

    """
    level = logging.INFO
    # who is calling?
    origin = inspect.stack()[1][0].f_code.co_name
    if origin == "log_error":
      level = logging.ERROR

    self.log.log(level, "%s - - %s\n" %
                     (self.address_string(),
                      format%args))

  def R_Resource(self, uri):
    """Create controller from the URL.

    Args:
      uri - a string with requested URL.

    Returns:
      R_Generic class inheritor.
    """
    controller = self.map.getController(uri)
    if controller:
        return eval("resources.%s(self, %s, %s)" % controller)
    else:
      raise exceptions.AttribureError


def start(options):
  port = int(options.port)
  httpd = RESTHTTPServer(("", port), RESTRequestHandler, options)
  try:
    httpd.serve_forever()
  finally:
    httpd.close()
    del httpd
    return 1


if __name__ == "__main__":
  pass
