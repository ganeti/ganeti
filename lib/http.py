#
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

"""HTTP server module.

"""

import socket
import BaseHTTPServer
import OpenSSL
import time
import logging

from ganeti import errors
from ganeti import logger
from ganeti import serializer


class HTTPException(Exception):
  code = None
  message = None

  def __init__(self, message=None):
    if message is not None:
      self.message = message


class HTTPBadRequest(HTTPException):
  code = 400


class HTTPForbidden(HTTPException):
  code = 403


class HTTPNotFound(HTTPException):
  code = 404


class HTTPGone(HTTPException):
  code = 410


class HTTPLengthRequired(HTTPException):
  code = 411


class HTTPInternalError(HTTPException):
  code = 500


class HTTPNotImplemented(HTTPException):
  code = 501


class HTTPServiceUnavailable(HTTPException):
  code = 503


class ApacheLogfile:
  """Utility class to write HTTP server log files.

  The written format is the "Common Log Format" as defined by Apache:
  http://httpd.apache.org/docs/2.2/mod/mod_log_config.html#examples

  """
  MONTHNAME = [None,
               'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  def __init__(self, fd):
    """Constructor for ApacheLogfile class.

    Args:
    - fd: Open file object

    """
    self._fd = fd

  def LogRequest(self, request, format, *args):
    self._fd.write("%s %s %s [%s] %s\n" % (
      # Remote host address
      request.address_string(),

      # RFC1413 identity (identd)
      "-",

      # Remote user
      "-",

      # Request time
      self._FormatCurrentTime(),

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


class HTTPServer(BaseHTTPServer.HTTPServer, object):
  """Class to provide an HTTP/HTTPS server.

  """
  allow_reuse_address = True

  def __init__(self, server_address, HandlerClass, httplog=None,
               enable_ssl=False, ssl_key=None, ssl_cert=None):
    """Server constructor.

    Args:
      server_address: a touple containing:
        ip: a string with IP address, localhost if empty string
        port: port number, integer
      HandlerClass: HTTPRequestHandler object
      httplog: Access log object
      enable_ssl: Whether to enable SSL
      ssl_key: SSL key file
      ssl_cert: SSL certificate key

    """
    BaseHTTPServer.HTTPServer.__init__(self, server_address, HandlerClass)

    self.httplog = httplog

    if enable_ssl:
      # Set up SSL
      context = OpenSSL.SSL.Context(OpenSSL.SSL.SSLv23_METHOD)
      context.use_privatekey_file(ssl_key)
      context.use_certificate_file(ssl_cert)
      self.socket = OpenSSL.SSL.Connection(context,
                                           socket.socket(self.address_family,
                                           self.socket_type))
    else:
      self.socket = socket.socket(self.address_family, self.socket_type)

    self.server_bind()
    self.server_activate()


class HTTPJsonConverter:
  CONTENT_TYPE = "application/json"

  def Encode(self, data):
    return serializer.DumpJson(data)

  def Decode(self, data):
    return serializer.LoadJson(data)


class HTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler, object):
  """Request handler class.

  """
  def setup(self):
    """Setup secure read and write file objects.

    """
    self.connection = self.request
    self.rfile = socket._fileobject(self.request, "rb", self.rbufsize)
    self.wfile = socket._fileobject(self.request, "wb", self.wbufsize)

  def handle_one_request(self):
    """Parses a request and calls the handler function.

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
    logging.debug("HTTP request: %s", self.raw_requestline.rstrip("\r\n"))

    try:
      self._ReadPostData()

      result = self.HandleRequest()

      # TODO: Content-type
      encoder = HTTPJsonConverter()
      encoded_result = encoder.Encode(result)

      self.send_response(200)
      self.send_header("Content-Type", encoder.CONTENT_TYPE)
      self.send_header("Content-Length", str(len(encoded_result)))
      self.end_headers()

      self.wfile.write(encoded_result)

    except HTTPException, err:
      self.send_error(err.code, message=err.message)

    except Exception, err:
      self.send_error(HTTPInternalError.code, message=str(err))

    except:
      self.send_error(HTTPInternalError.code, message="Unknown error")

  def _ReadPostData(self):
    if self.command.upper() not in ("POST", "PUT"):
      self.post_data = None
      return

    # TODO: Decide what to do when Content-Length header was not sent
    try:
      content_length = int(self.headers.get('Content-Length', 0))
    except ValueError:
      raise HTTPBadRequest("No Content-Length header or invalid format")

    try:
      data = self.rfile.read(content_length)
    except socket.error, err:
      logger.Error("Socket error while reading: %s" % str(err))
      return

    # TODO: Content-type, error handling
    self.post_data = HTTPJsonConverter().Decode(data)

    logging.debug("HTTP POST data: %s", self.post_data)

  def HandleRequest(self):
    """Handles a request.

    """
    raise NotImplementedError()

  def log_message(self, format, *args):
    """Log an arbitrary message.

    This is used by all other logging functions.

    The first argument, FORMAT, is a format string for the
    message to be logged.  If the format string contains
    any % escapes requiring parameters, they should be
    specified as subsequent arguments (it's just like
    printf!).

    """
    logging.debug("Handled request: %s", format % args)
    if self.server.httplog:
      self.server.httplog.LogRequest(self, format, *args)
