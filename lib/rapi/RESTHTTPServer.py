#!/usr/bin/python
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

from ganeti import constants
from ganeti import logger
from ganeti.rapi import resources

"""RESTfull HTTPS Server module.

"""

class RESTHTTPServer(BaseHTTPServer.HTTPServer):
  """The class to provide HTTP/HTTPS server.

  """
  def __init__(self, server_address, HandlerClass, options):
    """REST Server Constructor.

    Args:
      server_address - a touple with pair:
        ip - a string with IP address, localhost if null-string
        port - port number, integer
      HandlerClass - HTTPRequestHandler object
      options - Command-line options
    """
    logger.SetupLogging(debug=options.debug, program='ganeti-rapi')

    BaseHTTPServer.HTTPServer.__init__(self, server_address, HandlerClass)
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

  def handle_one_request(self):
    """Handle a single REST request. """
    self.raw_requestline = None
    try:
      self.raw_requestline = self.rfile.readline()
    except OpenSSL.SSL.Error, ex:
      logger.Error("Error in SSL: %s" % str(ex))
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
    logX = logger.Info
    # who is calling?
    origin = inspect.stack()[1][0].f_code.co_name
    if origin == "log_error":
      logX = logger.Error
    logX("%s - - %s" %
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
      raise exceptions.AttributeError


def start(options):
  httpd = RESTHTTPServer(("", options.port), RESTRequestHandler, options)
  try:
    httpd.serve_forever()
  finally:
    httpd.server_close()


if __name__ == "__main__":
  pass
