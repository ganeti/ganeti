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

"""RESTfull HTTPS Server module.

"""

import socket
import SocketServer
import BaseHTTPServer
import OpenSSL
import time

from ganeti import constants
from ganeti import errors
from ganeti import logger
from ganeti.rapi import resources


class HttpLogfile:
  """Utility class to write HTTP server log files.

  The written format is the "Common Log Format" as defined by Apache:
  http://httpd.apache.org/docs/2.2/mod/mod_log_config.html#examples

  """
  MONTHNAME = [None,
               'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  def __init__(self, path):
    self._fd = open(path, 'a', 1)

  def __del__(self):
    try:
      self.Close()
    except:
      # Swallow exceptions
      pass

  def Close(self):
    if self._fd is not None:
      self._fd.close()
      self._fd = None

  def LogRequest(self, request, format, *args):
    if self._fd is None:
      raise errors.ProgrammerError("Logfile already closed")

    request_time = self._FormatCurrentTime()

    self._fd.write("%s %s %s [%s] %s\n" % (
      # Remote host address
      request.address_string(),

      # RFC1413 identity (identd)
      "-",

      # Remote user
      "-",

      # Request time
      request_time,

      # Message
      format % args,
      ))

  def _FormatCurrentTime(self):
    """Formats current time in Common Log Format.

    """
    return self._FormatLogTime(time.time())

  def _FormatLogTime(self, seconds):
    """Formats time for Common Log Format.

    All timestamps are logged in the UTC timezone.

    Args:
    - seconds: Time in seconds since the epoch

    """
    (_, month, _, _, _, _, _, _, _) = tm = time.gmtime(seconds)
    format = "%d/" + self.MONTHNAME[month] + "/%Y:%H:%M:%S +0000"
    return time.strftime(format, tm)


class RESTHTTPServer(BaseHTTPServer.HTTPServer):
  """Class to provide an HTTP/HTTPS server.

  """
  allow_reuse_address = True

  def __init__(self, server_address, HandlerClass, options):
    """REST Server Constructor.

    Args:
      server_address: a touple containing:
        ip: a string with IP address, localhost if empty string
        port: port number, integer
      HandlerClass: HTTPRequestHandler object
      options: Command-line options

    """
    logger.SetupLogging(debug=options.debug, program='ganeti-rapi')

    self.httplog = HttpLogfile(constants.LOG_RAPIACCESS)

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
  """REST Request Handler Class.

  """
  def authenticate(self):
    """Perform authentication check.

    """
    return True

  def setup(self):
    """Setup secure read and write file objects.

    """
    self.connection = self.request
    self.rfile = socket._fileobject(self.request, "rb", self.rbufsize)
    self.wfile = socket._fileobject(self.request, "wb", self.wbufsize)
    self.map = resources.Mapper()

  def handle_one_request(self):
    """Handle a single REST request.

    """
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
      self.send_error(401, "Access Denied")
      return
    try:
      rname = self.R_Resource(self.path)
      rname.set_headers(self.headers)
      rname.do_Request(self.command)
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

    """
    self.server.httplog.LogRequest(self, format, *args)

  def R_Resource(self, uri):
    """Create controller from the URL.

    Args:
      uri: a string with requested URL.

    Returns:
      R_Generic class inheritor.

    """
    controller = self.map.getController(uri)
    if not controller:
      raise AttributeError()

    (handler, items, args) = controller

    return handler(self, items, args)


def start(options):
  httpd = RESTHTTPServer(("", options.port), RESTRequestHandler, options)
  try:
    httpd.serve_forever()
  finally:
    httpd.server_close()
