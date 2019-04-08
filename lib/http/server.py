#
#

# Copyright (C) 2007, 2008, 2010, 2012 Google Inc.
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

"""HTTP server module.

"""

import http.server
import cgi
import logging
import os
import socket
import time
import signal
import asyncore

from ganeti import http
from ganeti import utils
from ganeti import netutils
from ganeti import compat
from ganeti import errors


WEEKDAYNAME = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHNAME = [None,
             "Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Default error message
DEFAULT_ERROR_CONTENT_TYPE = "text/html"
DEFAULT_ERROR_MESSAGE = """\
<html>
<head>
<title>Error response</title>
</head>
<body>
<h1>Error response</h1>
<p>Error code %(code)d.
<p>Message: %(message)s.
<p>Error code explanation: %(code)s = %(explain)s.
</body>
</html>
"""


def _DateTimeHeader(gmnow=None):
  """Return the current date and time formatted for a message header.

  The time MUST be in the GMT timezone.

  """
  if gmnow is None:
    gmnow = time.gmtime()
  (year, month, day, hh, mm, ss, wd, _, _) = gmnow
  return ("%s, %02d %3s %4d %02d:%02d:%02d GMT" %
          (WEEKDAYNAME[wd], day, MONTHNAME[month], year, hh, mm, ss))


class _HttpServerRequest(object):
  """Data structure for HTTP request on server side.

  """
  def __init__(self, method, path, headers, body, sock):
    # Request attributes
    self.request_method = method
    self.request_path = path
    self.request_headers = headers
    self.request_body = body
    self.request_sock = sock

    # Response attributes
    self.resp_headers = {}

    # Private data for request handler (useful in combination with
    # authentication)
    self.private = None

  def __repr__(self):
    status = ["%s.%s" % (self.__class__.__module__, self.__class__.__name__),
              self.request_method, self.request_path,
              "headers=%r" % str(self.request_headers),
              "body=%r" % (self.request_body, )]

    return "<%s at %#x>" % (" ".join(status), id(self))


class _HttpServerToClientMessageWriter(http.HttpMessageWriter):
  """Writes an HTTP response to client.

  """
  def __init__(self, sock, request_msg, response_msg, write_timeout):
    """Writes the response to the client.

    @type sock: socket
    @param sock: Target socket
    @type request_msg: http.HttpMessage
    @param request_msg: Request message, required to determine whether
        response may have a message body
    @type response_msg: http.HttpMessage
    @param response_msg: Response message
    @type write_timeout: float
    @param write_timeout: Write timeout for socket

    """
    self._request_msg = request_msg
    self._response_msg = response_msg
    http.HttpMessageWriter.__init__(self, sock, response_msg, write_timeout)

  def HasMessageBody(self):
    """Logic to detect whether response should contain a message body.

    """
    if self._request_msg.start_line:
      request_method = self._request_msg.start_line.method
    else:
      request_method = None

    response_code = self._response_msg.start_line.code

    # RFC2616, section 4.3: "A message-body MUST NOT be included in a request
    # if the specification of the request method (section 5.1.1) does not allow
    # sending an entity-body in requests"
    #
    # RFC2616, section 9.4: "The HEAD method is identical to GET except that
    # the server MUST NOT return a message-body in the response."
    #
    # RFC2616, section 10.2.5: "The 204 response MUST NOT include a
    # message-body [...]"
    #
    # RFC2616, section 10.3.5: "The 304 response MUST NOT contain a
    # message-body, [...]"

    return (http.HttpMessageWriter.HasMessageBody(self) and
            (request_method is not None and
             request_method != http.HTTP_HEAD) and
            response_code >= http.HTTP_OK and
            response_code not in (http.HTTP_NO_CONTENT,
                                  http.HTTP_NOT_MODIFIED))


class _HttpClientToServerMessageReader(http.HttpMessageReader):
  """Reads an HTTP request sent by client.

  """
  # Length limits
  START_LINE_LENGTH_MAX = 8192
  HEADER_LENGTH_MAX = 4096

  def ParseStartLine(self, start_line):
    """Parses the start line sent by client.

    Example: "GET /index.html HTTP/1.1"

    @type start_line: string
    @param start_line: Start line

    """
    # Empty lines are skipped when reading
    assert start_line

    logging.debug("HTTP request: %s", start_line)

    words = start_line.split()

    if len(words) == 3:
      [method, path, version] = words
      if version[:5] != "HTTP/":
        raise http.HttpBadRequest("Bad request version (%r)" % version)

      try:
        base_version_number = version.split("/", 1)[1]
        version_number = base_version_number.split(".")

        # RFC 2145 section 3.1 says there can be only one "." and
        #   - major and minor numbers MUST be treated as
        #      separate integers;
        #   - HTTP/2.4 is a lower version than HTTP/2.13, which in
        #      turn is lower than HTTP/12.3;
        #   - Leading zeros MUST be ignored by recipients.
        if len(version_number) != 2:
          raise http.HttpBadRequest("Bad request version (%r)" % version)

        version_number = (int(version_number[0]), int(version_number[1]))
      except (ValueError, IndexError):
        raise http.HttpBadRequest("Bad request version (%r)" % version)

      if version_number >= (2, 0):
        raise http.HttpVersionNotSupported("Invalid HTTP Version (%s)" %
                                           base_version_number)

    elif len(words) == 2:
      version = http.HTTP_0_9
      [method, path] = words
      if method != http.HTTP_GET:
        raise http.HttpBadRequest("Bad HTTP/0.9 request type (%r)" % method)

    else:
      raise http.HttpBadRequest("Bad request syntax (%r)" % start_line)

    return http.HttpClientToServerStartLine(method, path, version)


def _HandleServerRequestInner(handler, req_msg, reader):
  """Calls the handler function for the current request.

  """
  handler_context = _HttpServerRequest(req_msg.start_line.method,
                                       req_msg.start_line.path,
                                       req_msg.headers,
                                       req_msg.body,
                                       reader.sock)

  logging.debug("Handling request %r", handler_context)

  try:
    try:
      # Authentication, etc.
      handler.PreHandleRequest(handler_context)

      # Call actual request handler
      result = handler.HandleRequest(handler_context)
    except (http.HttpException, errors.RapiTestResult,
            KeyboardInterrupt, SystemExit):
      raise
    except Exception as err:
      logging.exception("Caught exception")
      raise http.HttpInternalServerError(message=str(err))
    except:
      logging.exception("Unknown exception")
      raise http.HttpInternalServerError(message="Unknown error")

    if not isinstance(result, str):
      raise http.HttpError("Handler function didn't return string type")

    return (http.HTTP_OK, handler_context.resp_headers, result)
  finally:
    # No reason to keep this any longer, even for exceptions
    handler_context.private = None


class HttpResponder(object):
  # The default request version.  This only affects responses up until
  # the point where the request line is parsed, so it mainly decides what
  # the client gets back when sending a malformed request line.
  # Most web servers default to HTTP 0.9, i.e. don't send a status line.
  default_request_version = http.HTTP_0_9

  responses = http.server.BaseHTTPRequestHandler.responses

  def __init__(self, handler):
    """Initializes this class.

    """
    self._handler = handler

  def __call__(self, fn):
    """Handles a request.

    @type fn: callable
    @param fn: Callback for retrieving HTTP request, must return a tuple
      containing request message (L{http.HttpMessage}) and C{None} or the
      message reader (L{_HttpClientToServerMessageReader})

    """
    response_msg = http.HttpMessage()
    response_msg.start_line = \
      http.HttpServerToClientStartLine(version=self.default_request_version,
                                       code=None, reason=None)

    force_close = True

    try:
      (request_msg, req_msg_reader) = fn()

      response_msg.start_line.version = request_msg.start_line.version

      # RFC2616, 14.23: All Internet-based HTTP/1.1 servers MUST respond
      # with a 400 (Bad Request) status code to any HTTP/1.1 request
      # message which lacks a Host header field.
      if (request_msg.start_line.version == http.HTTP_1_1 and
          not (request_msg.headers and
               http.HTTP_HOST in request_msg.headers)):
        raise http.HttpBadRequest(message="Missing Host header")

      (response_msg.start_line.code, response_msg.headers,
       response_msg.body) = \
        _HandleServerRequestInner(self._handler, request_msg, req_msg_reader)
    except http.HttpException as err:
      self._SetError(self.responses, self._handler, response_msg, err)
    else:
      # Only wait for client to close if we didn't have any exception.
      force_close = False

    return (request_msg, req_msg_reader, force_close,
            self._Finalize(self.responses, response_msg))

  @staticmethod
  def _SetError(responses, handler, response_msg, err):
    """Sets the response code and body from a HttpException.

    @type err: HttpException
    @param err: Exception instance

    """
    try:
      (shortmsg, longmsg) = responses[err.code]
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

    (content_type, body) = handler.FormatErrorMessage(values)

    headers = {
      http.HTTP_CONTENT_TYPE: content_type,
      }

    if err.headers:
      headers.update(err.headers)

    response_msg.start_line.code = err.code
    response_msg.headers = headers
    response_msg.body = body

  @staticmethod
  def _Finalize(responses, msg):
    assert msg.start_line.reason is None

    if not msg.headers:
      msg.headers = {}

    msg.headers.update({
      # TODO: Keep-alive is not supported
      http.HTTP_CONNECTION: "close",
      http.HTTP_DATE: _DateTimeHeader(),
      http.HTTP_SERVER: http.HTTP_GANETI_VERSION,
      })

    # Get response reason based on code
    try:
      code_desc = responses[msg.start_line.code]
    except KeyError:
      reason = ""
    else:
      (reason, _) = code_desc

    msg.start_line.reason = reason

    return msg


class HttpServerRequestExecutor(object):
  """Implements server side of HTTP.

  This class implements the server side of HTTP. It's based on code of
  Python's BaseHTTPServer, from both version 2.4 and 3k. It does not
  support non-ASCII character encodings. Keep-alive connections are
  not supported.

  """
  # Timeouts in seconds for socket layer
  WRITE_TIMEOUT = 10
  READ_TIMEOUT = 10
  CLOSE_TIMEOUT = 1

  def __init__(self, server, handler, sock, client_addr):
    """Initializes this class.

    """
    responder = HttpResponder(handler)

    # Disable Python's timeout
    sock.settimeout(None)

    # Operate in non-blocking mode
    sock.setblocking(0)

    request_msg_reader = None
    force_close = True

    logging.debug("Connection from %s:%s", client_addr[0], client_addr[1])
    try:
      # Block for closing connection
      try:
        # Do the secret SSL handshake
        if server.using_ssl:
          sock.set_accept_state()
          try:
            http.Handshake(sock, self.WRITE_TIMEOUT)
          except http.HttpSessionHandshakeUnexpectedEOF:
            logging.debug("Unexpected EOF from %s:%s",
                          client_addr[0], client_addr[1])
            # Ignore rest
            return

        (request_msg, request_msg_reader, force_close, response_msg) = \
          responder(compat.partial(self._ReadRequest, sock, self.READ_TIMEOUT))
        if response_msg:
          # HttpMessage.start_line can be of different types
          # Instance of 'HttpClientToServerStartLine' has no 'code' member
          # pylint: disable=E1103,E1101
          logging.info("%s:%s %s %s", client_addr[0], client_addr[1],
                       request_msg.start_line, response_msg.start_line.code)
          self._SendResponse(sock, request_msg, response_msg,
                             self.WRITE_TIMEOUT)
      finally:
        http.ShutdownConnection(sock, self.CLOSE_TIMEOUT, self.WRITE_TIMEOUT,
                                request_msg_reader, force_close)

      sock.close()
    finally:
      logging.debug("Disconnected %s:%s", client_addr[0], client_addr[1])

  @staticmethod
  def _ReadRequest(sock, timeout):
    """Reads a request sent by client.

    """
    msg = http.HttpMessage()

    try:
      reader = _HttpClientToServerMessageReader(sock, msg, timeout)
    except http.HttpSocketTimeout:
      raise http.HttpError("Timeout while reading request")
    except socket.error as err:
      raise http.HttpError("Error reading request: %s" % err)

    return (msg, reader)

  @staticmethod
  def _SendResponse(sock, req_msg, msg, timeout):
    """Sends the response to the client.

    """
    try:
      _HttpServerToClientMessageWriter(sock, req_msg, msg, timeout)
    except http.HttpSocketTimeout:
      raise http.HttpError("Timeout while sending response")
    except socket.error as err:
      raise http.HttpError("Error sending response: %s" % err)


class HttpServer(http.HttpBase, asyncore.dispatcher):
  """Generic HTTP server class

  """

  def __init__(self, mainloop, local_address, port, max_clients, handler,
               ssl_params=None, ssl_verify_peer=False,
               request_executor_class=None, ssl_verify_callback=None):
    """Initializes the HTTP server

    @type mainloop: ganeti.daemon.Mainloop
    @param mainloop: Mainloop used to poll for I/O events
    @type local_address: string
    @param local_address: Local IP address to bind to
    @type port: int
    @param port: TCP port to listen on
    @type max_clients: int
    @param max_clients: maximum number of client connections
        open simultaneously.
    @type handler: HttpServerHandler
    @param handler: Request handler object
    @type ssl_params: HttpSslParams
    @param ssl_params: SSL key and certificate
    @type ssl_verify_peer: bool
    @param ssl_verify_peer: Whether to require client certificate
        and compare it with our certificate
    @type request_executor_class: class
    @param request_executor_class: a class derived from the
        HttpServerRequestExecutor class

    """
    http.HttpBase.__init__(self)
    asyncore.dispatcher.__init__(self)

    if request_executor_class is None:
      self.request_executor = HttpServerRequestExecutor
    else:
      self.request_executor = request_executor_class

    self.mainloop = mainloop
    self.local_address = local_address
    self.port = port
    self.handler = handler
    family = netutils.IPAddress.GetAddressFamily(local_address)
    self.socket = self._CreateSocket(ssl_params, ssl_verify_peer, family,
                                     ssl_verify_callback)

    # Allow port to be reused
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    self._children = []
    self.set_socket(self.socket)
    self.accepting = True
    self.max_clients = max_clients
    mainloop.RegisterSignal(self)

  def Start(self):
    self.socket.bind((self.local_address, self.port))
    self.socket.listen(1024)

  def Stop(self):
    self.socket.close()

  def handle_accept(self):
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
      while len(self._children) > self.max_clients:
        try:
          # Waiting without a timeout brings us into a potential DoS situation.
          # As soon as too many children run, we'll not respond to new
          # requests. The real solution would be to add a timeout for children
          # and killing them after some time.
          pid, _ = os.waitpid(0, 0)
        except os.error:
          pid = None
        if pid and pid in self._children:
          self._children.remove(pid)

    for child in self._children:
      try:
        pid, _ = os.waitpid(child, os.WNOHANG)
      except os.error:
        pid = None
      if pid and pid in self._children:
        self._children.remove(pid)

  def _IncomingConnection(self):
    """Called for each incoming connection

    """
    # pylint: disable=W0212
    t_start = time.time()
    (connection, client_addr) = self.socket.accept()

    self._CollectChildren(False)

    try:
      pid = os.fork()
    except OSError:
      logging.exception("Failed to fork on request from %s:%s",
                        client_addr[0], client_addr[1])
      # Immediately close the connection. No SSL handshake has been done.
      try:
        connection.close()
      except socket.error:
        pass
      return

    if pid == 0:
      # Child process
      try:
        # The client shouldn't keep the listening socket open. If the parent
        # process is restarted, it would fail when there's already something
        # listening (in this case its own child from a previous run) on the
        # same port.
        try:
          self.socket.close()
        except socket.error:
          pass
        self.socket = None

        # In case the handler code uses temporary files
        utils.ResetTempfileModule()

        t_setup = time.time()
        self.request_executor(self, self.handler, connection, client_addr)
        t_end = time.time()
        logging.debug("Request from %s:%s executed in: %.4f [setup: %.4f] "
                      "[workers: %d]", client_addr[0], client_addr[1],
                      t_end - t_start, t_setup - t_start, len(self._children))

      except Exception: # pylint: disable=W0703
        logging.exception("Error while handling request from %s:%s",
                          client_addr[0], client_addr[1])
        os._exit(1)
      os._exit(0)
    else:
      self._children.append(pid)


class HttpServerHandler(object):
  """Base class for handling HTTP server requests.

  Users of this class must subclass it and override the L{HandleRequest}
  function.

  """
  def PreHandleRequest(self, req):
    """Called before handling a request.

    Can be overridden by a subclass.

    """

  def HandleRequest(self, req):
    """Handles a request.

    Must be overridden by subclass.

    """
    raise NotImplementedError()

  @staticmethod
  def FormatErrorMessage(values):
    """Formats the body of an error message.

    @type values: dict
    @param values: dictionary with keys C{code}, C{message} and C{explain}.
    @rtype: tuple; (string, string)
    @return: Content-type and response body

    """
    return (DEFAULT_ERROR_CONTENT_TYPE, DEFAULT_ERROR_MESSAGE % values)
