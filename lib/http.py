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

import BaseHTTPServer
import cgi
import logging
import mimetools
import OpenSSL
import os
import select
import socket
import sys
import time
import signal
import logging

from ganeti import constants
from ganeti import serializer


WEEKDAYNAME = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MONTHNAME = [None,
             'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# Default error message
DEFAULT_ERROR_CONTENT_TYPE = "text/html"
DEFAULT_ERROR_MESSAGE = """\
<head>
<title>Error response</title>
</head>
<body>
<h1>Error response</h1>
<p>Error code %(code)d.
<p>Message: %(message)s.
<p>Error code explanation: %(code)s = %(explain)s.
</body>
"""

HTTP_OK = 200
HTTP_NO_CONTENT = 204
HTTP_NOT_MODIFIED = 304

HTTP_0_9 = "HTTP/0.9"
HTTP_1_0 = "HTTP/1.0"
HTTP_1_1 = "HTTP/1.1"

HTTP_GET = "GET"
HTTP_HEAD = "HEAD"
HTTP_ETAG = "ETag"


class SocketClosed(socket.error):
  pass


class HTTPException(Exception):
  code = None
  message = None

  def __init__(self, message=None):
    Exception.__init__(self)
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


class HTTPVersionNotSupported(HTTPException):
  code = 505


class ApacheLogfile:
  """Utility class to write HTTP server log files.

  The written format is the "Common Log Format" as defined by Apache:
  http://httpd.apache.org/docs/2.2/mod/mod_log_config.html#examples

  """
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
    self._fd.flush()

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
    format = "%d/" + MONTHNAME[month] + "/%Y:%H:%M:%S +0000"
    return time.strftime(format, tm)


class HTTPJsonConverter:
  CONTENT_TYPE = "application/json"

  def Encode(self, data):
    return serializer.DumpJson(data)

  def Decode(self, data):
    return serializer.LoadJson(data)


class _HttpConnectionHandler(object):
  """Implements server side of HTTP

  This class implements the server side of HTTP. It's based on code of Python's
  BaseHTTPServer, from both version 2.4 and 3k. It does not support non-ASCII
  character encodings. Keep-alive connections are not supported.

  """
  # String for "Server" header
  server_version = "Ganeti %s" % constants.RELEASE_VERSION

  # The default request version.  This only affects responses up until
  # the point where the request line is parsed, so it mainly decides what
  # the client gets back when sending a malformed request line.
  # Most web servers default to HTTP 0.9, i.e. don't send a status line.
  default_request_version = HTTP_0_9

  # Error message settings
  error_message_format = DEFAULT_ERROR_MESSAGE
  error_content_type = DEFAULT_ERROR_CONTENT_TYPE

  responses = BaseHTTPServer.BaseHTTPRequestHandler.responses

  def __init__(self, server, conn, client_addr, fileio_class):
    """Initializes this class.

    Part of the initialization is reading the request and eventual POST/PUT
    data sent by the client.

    """
    self._server = server

    # We default rfile to buffered because otherwise it could be
    # really slow for large data (a getc() call per byte); we make
    # wfile unbuffered because (a) often after a write() we want to
    # read and we need to flush the line; (b) big writes to unbuffered
    # files are typically optimized by stdio even when big reads
    # aren't.
    self.rfile = fileio_class(conn, mode="rb", bufsize=-1)
    self.wfile = fileio_class(conn, mode="wb", bufsize=0)

    self.client_addr = client_addr

    self.request_headers = None
    self.request_method = None
    self.request_path = None
    self.request_requestline = None
    self.request_version = self.default_request_version

    self.response_body = None
    self.response_code = HTTP_OK
    self.response_content_type = None
    self.response_headers = {}

    self.should_fork = False

    try:
      self._ReadRequest()
      self._ReadPostData()
    except HTTPException, err:
      self._SetErrorStatus(err)

  def Close(self):
    if not self.wfile.closed:
      self.wfile.flush()
    self.wfile.close()
    self.rfile.close()

  def _DateTimeHeader(self):
    """Return the current date and time formatted for a message header.

    """
    (year, month, day, hh, mm, ss, wd, _, _) = time.gmtime()
    return ("%s, %02d %3s %4d %02d:%02d:%02d GMT" %
            (WEEKDAYNAME[wd], day, MONTHNAME[month], year, hh, mm, ss))

  def _SetErrorStatus(self, err):
    """Sets the response code and body from a HTTPException.

    @type err: HTTPException
    @param err: Exception instance

    """
    try:
      (shortmsg, longmsg) = self.responses[err.code]
    except KeyError:
      shortmsg = longmsg = "Unknown"

    if err.message:
      message = err.message
    else:
      message = shortmsg

    values = {
      "code": err.code,
      "message": cgi.escape(message),
      "explain": longmsg,
      }

    self.response_code = err.code
    self.response_content_type = self.error_content_type
    self.response_body = self.error_message_format % values

  def HandleRequest(self):
    """Handle the actual request.

    Calls the actual handler function and converts exceptions into HTTP errors.

    """
    # Don't do anything if there's already been a problem
    if self.response_code != HTTP_OK:
      return

    assert self.request_method, "Status code %s requires a method" % HTTP_OK

    # Check whether client is still there
    self.rfile.read(0)

    try:
      try:
        result = self._server.HandleRequest(self)

        # TODO: Content-type
        encoder = HTTPJsonConverter()
        body = encoder.Encode(result)

        self.response_content_type = encoder.CONTENT_TYPE
        self.response_body = body
      except (HTTPException, KeyboardInterrupt, SystemExit):
        raise
      except Exception, err:
        logging.exception("Caught exception")
        raise HTTPInternalError(message=str(err))
      except:
        logging.exception("Unknown exception")
        raise HTTPInternalError(message="Unknown error")

    except HTTPException, err:
      self._SetErrorStatus(err)

  def SendResponse(self):
    """Sends response to the client.

    """
    # Check whether client is still there
    self.rfile.read(0)

    logging.info("%s:%s %s %s", self.client_addr[0], self.client_addr[1],
                 self.request_requestline, self.response_code)

    if self.response_code in self.responses:
      response_message = self.responses[self.response_code][0]
    else:
      response_message = ""

    if self.request_version != HTTP_0_9:
      self.wfile.write("%s %d %s\r\n" %
                       (self.request_version, self.response_code,
                        response_message))
      self._SendHeader("Server", self.server_version)
      self._SendHeader("Date", self._DateTimeHeader())
      self._SendHeader("Content-Type", self.response_content_type)
      self._SendHeader("Content-Length", str(len(self.response_body)))
      for key, val in self.response_headers.iteritems():
        self._SendHeader(key, val)

      # We don't support keep-alive at this time
      self._SendHeader("Connection", "close")
      self.wfile.write("\r\n")

    if (self.request_method != HTTP_HEAD and
        self.response_code >= HTTP_OK and
        self.response_code not in (HTTP_NO_CONTENT, HTTP_NOT_MODIFIED)):
      self.wfile.write(self.response_body)

  def _SendHeader(self, name, value):
    if self.request_version != HTTP_0_9:
      self.wfile.write("%s: %s\r\n" % (name, value))

  def _ReadRequest(self):
    """Reads and parses request line

    """
    raw_requestline = self.rfile.readline()

    requestline = raw_requestline
    if requestline[-2:] == '\r\n':
      requestline = requestline[:-2]
    elif requestline[-1:] == '\n':
      requestline = requestline[:-1]

    if not requestline:
      raise HTTPBadRequest("Empty request line")

    self.request_requestline = requestline

    logging.debug("HTTP request: %s", raw_requestline.rstrip("\r\n"))

    words = requestline.split()

    if len(words) == 3:
      [method, path, version] = words
      if version[:5] != 'HTTP/':
        raise HTTPBadRequest("Bad request version (%r)" % version)

      try:
        base_version_number = version.split('/', 1)[1]
        version_number = base_version_number.split(".")

        # RFC 2145 section 3.1 says there can be only one "." and
        #   - major and minor numbers MUST be treated as
        #      separate integers;
        #   - HTTP/2.4 is a lower version than HTTP/2.13, which in
        #      turn is lower than HTTP/12.3;
        #   - Leading zeros MUST be ignored by recipients.
        if len(version_number) != 2:
          raise HTTPBadRequest("Bad request version (%r)" % version)

        version_number = int(version_number[0]), int(version_number[1])
      except (ValueError, IndexError):
        raise HTTPBadRequest("Bad request version (%r)" % version)

      if version_number >= (2, 0):
        raise HTTPVersionNotSupported("Invalid HTTP Version (%s)" %
                                      base_version_number)

    elif len(words) == 2:
      version = HTTP_0_9
      [method, path] = words
      if method != HTTP_GET:
        raise HTTPBadRequest("Bad HTTP/0.9 request type (%r)" % method)

    else:
      raise HTTPBadRequest("Bad request syntax (%r)" % requestline)

    # Examine the headers and look for a Connection directive
    headers = mimetools.Message(self.rfile, 0)

    self.request_method = method
    self.request_path = path
    self.request_version = version
    self.request_headers = headers

  def _ReadPostData(self):
    """Reads POST/PUT data

    """
    if not self.request_method or self.request_method.upper() not in ("POST", "PUT"):
      self.request_post_data = None
      return

    # TODO: Decide what to do when Content-Length header was not sent
    try:
      content_length = int(self.request_headers.get('Content-Length', 0))
    except ValueError:
      raise HTTPBadRequest("No Content-Length header or invalid format")

    data = self.rfile.read(content_length)

    # TODO: Content-type, error handling
    self.request_post_data = HTTPJsonConverter().Decode(data)

    logging.debug("HTTP POST data: %s", self.request_post_data)


class HttpServer(object):
  """Generic HTTP server class

  Users of this class must subclass it and override the HandleRequest function.

  """
  MAX_CHILDREN = 20

  def __init__(self, mainloop, server_address):
    self.mainloop = mainloop
    self.server_address = server_address

    # TODO: SSL support
    self.ssl_cert = None
    self.ssl_key = self.ssl_cert

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    if self.ssl_cert and self.ssl_key:
      ctx = OpenSSL.SSL.Context(OpenSSL.SSL.SSLv23_METHOD)
      ctx.set_options(OpenSSL.SSL.OP_NO_SSLv2)

      ctx.use_certificate_file(self.ssl_cert)
      ctx.use_privatekey_file(self.ssl_key)

      self.socket = OpenSSL.SSL.Connection(ctx, sock)
      self._fileio_class = _SSLFileObject
    else:
      self.socket = sock
      self._fileio_class = socket._fileobject

    # Allow port to be reused
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    self._children = []

    mainloop.RegisterIO(self, self.socket.fileno(), select.POLLIN)
    mainloop.RegisterSignal(self)

  def Start(self):
    self.socket.bind(self.server_address)
    self.socket.listen(5)

  def Stop(self):
    self.socket.close()

  def OnIO(self, fd, condition):
    if condition & select.POLLIN:
      self._IncomingConnection()

  def OnSignal(self, signum):
    if signum == signal.SIGCHLD:
      self._CollectChildren(True)

  def _CollectChildren(self, quick):
    """Checks whether any child processes are done

    @type quick: bool
    @param quick: Whether to only use non-blocking functions

    """
    if not quick:
      # Don't wait for other processes if it should be a quick check
      while len(self._children) > self.MAX_CHILDREN:
        try:
          # Waiting without a timeout brings us into a potential DoS situation.
          # As soon as too many children run, we'll not respond to new
          # requests. The real solution would be to add a timeout for children
          # and killing them after some time.
          pid, status = os.waitpid(0, 0)
        except os.error:
          pid = None
        if pid and pid in self._children:
          self._children.remove(pid)

    for child in self._children:
      try:
        pid, status = os.waitpid(child, os.WNOHANG)
      except os.error:
        pid = None
      if pid and pid in self._children:
        self._children.remove(pid)

  def _IncomingConnection(self):
    """Called for each incoming connection

    """
    (connection, client_addr) = self.socket.accept()

    self._CollectChildren(False)

    pid = os.fork()
    if pid == 0:
      # Child process
      logging.info("Connection from %s:%s", client_addr[0], client_addr[1])

      try:
        try:
          try:
            handler = None
            try:
              # Read, parse and handle request
              handler = _HttpConnectionHandler(self, connection, client_addr,
                                               self._fileio_class)
              handler.HandleRequest()
            finally:
              # Try to send a response
              if handler:
                handler.SendResponse()
                handler.Close()
          except SocketClosed:
            pass
        finally:
          logging.info("Disconnected %s:%s", client_addr[0], client_addr[1])
      except:
        logging.exception("Error while handling request from %s:%s",
                          client_addr[0], client_addr[1])
        os._exit(1)
      os._exit(0)
    else:
      self._children.append(pid)

  def HandleRequest(self, req):
    raise NotImplementedError()


class _SSLFileObject(object):
  """Wrapper around socket._fileobject

  This wrapper is required to handle OpenSSL exceptions.

  """
  def _RequireOpenSocket(fn):
    def wrapper(self, *args, **kwargs):
      if self.closed:
        raise SocketClosed("Socket is closed")
      return fn(self, *args, **kwargs)
    return wrapper

  def __init__(self, sock, mode='rb', bufsize=-1):
    self._base = socket._fileobject(sock, mode=mode, bufsize=bufsize)

  def _ConnectionLost(self):
    self._base = None

  def _getclosed(self):
    return self._base is None or self._base.closed
  closed = property(_getclosed, doc="True if the file is closed")

  @_RequireOpenSocket
  def close(self):
    return self._base.close()

  @_RequireOpenSocket
  def flush(self):
    return self._base.flush()

  @_RequireOpenSocket
  def fileno(self):
    return self._base.fileno()

  @_RequireOpenSocket
  def read(self, size=-1):
    return self._ReadWrapper(self._base.read, size=size)

  @_RequireOpenSocket
  def readline(self, size=-1):
    return self._ReadWrapper(self._base.readline, size=size)

  def _ReadWrapper(self, fn, *args, **kwargs):
    while True:
      try:
        return fn(*args, **kwargs)

      except OpenSSL.SSL.ZeroReturnError, err:
        self._ConnectionLost()
        return ""

      except OpenSSL.SSL.WantReadError:
        continue

      #except OpenSSL.SSL.WantWriteError:
      # TODO

      except OpenSSL.SSL.SysCallError, (retval, desc):
        if ((retval == -1 and desc == "Unexpected EOF")
            or retval > 0):
          self._ConnectionLost()
          return ""

        logging.exception("Error in OpenSSL")
        self._ConnectionLost()
        raise socket.error(err.args)

      except OpenSSL.SSL.Error, err:
        self._ConnectionLost()
        raise socket.error(err.args)

  @_RequireOpenSocket
  def write(self, data):
    return self._WriteWrapper(self._base.write, data)

  def _WriteWrapper(self, fn, *args, **kwargs):
    while True:
      try:
        return fn(*args, **kwargs)
      except OpenSSL.SSL.ZeroReturnError, err:
        self._ConnectionLost()
        return 0

      except OpenSSL.SSL.WantWriteError:
        continue

      #except OpenSSL.SSL.WantReadError:
      # TODO

      except OpenSSL.SSL.SysCallError, err:
        if err.args[0] == -1 and data == "":
          # errors when writing empty strings are expected
          # and can be ignored
          return 0

        self._ConnectionLost()
        raise socket.error(err.args)

      except OpenSSL.SSL.Error, err:
        self._ConnectionLost()
        raise socket.error(err.args)
