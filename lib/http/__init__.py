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

"""HTTP module.

"""

import errno
import email
import logging
import select
import socket

from io import StringIO

import OpenSSL

from ganeti import constants
from ganeti import utils


HTTP_GANETI_VERSION = "Ganeti %s" % constants.RELEASE_VERSION

HTTP_OK = 200
HTTP_NO_CONTENT = 204
HTTP_NOT_MODIFIED = 304

HTTP_0_9 = "HTTP/0.9"
HTTP_1_0 = "HTTP/1.0"
HTTP_1_1 = "HTTP/1.1"

HTTP_GET = "GET"
HTTP_HEAD = "HEAD"
HTTP_POST = "POST"
HTTP_PUT = "PUT"
HTTP_DELETE = "DELETE"

HTTP_ETAG = "ETag"
HTTP_HOST = "Host"
HTTP_SERVER = "Server"
HTTP_DATE = "Date"
HTTP_USER_AGENT = "User-Agent"
HTTP_CONTENT_TYPE = "Content-Type"
HTTP_CONTENT_LENGTH = "Content-Length"
HTTP_CONNECTION = "Connection"
HTTP_KEEP_ALIVE = "Keep-Alive"
HTTP_WWW_AUTHENTICATE = "WWW-Authenticate"
HTTP_AUTHORIZATION = "Authorization"
HTTP_AUTHENTICATION_INFO = "Authentication-Info"
HTTP_ALLOW = "Allow"

HTTP_APP_OCTET_STREAM = "application/octet-stream"
HTTP_APP_JSON = "application/json"

_SSL_UNEXPECTED_EOF = "Unexpected EOF"

# Socket operations
(SOCKOP_SEND,
 SOCKOP_RECV,
 SOCKOP_SHUTDOWN,
 SOCKOP_HANDSHAKE) = range(4)

# send/receive quantum
SOCK_BUF_SIZE = 32768


class HttpError(Exception):
  """Internal exception for HTTP errors.

  This should only be used for internal error reporting.

  """


class HttpConnectionClosed(Exception):
  """Internal exception for a closed connection.

  This should only be used for internal error reporting. Only use
  it if there's no other way to report this condition.

  """


class HttpSessionHandshakeUnexpectedEOF(HttpError):
  """Internal exception for errors during SSL handshake.

  This should only be used for internal error reporting.

  """


class HttpSocketTimeout(Exception):
  """Internal exception for socket timeouts.

  This should only be used for internal error reporting.

  """


class HttpException(Exception):
  code = None
  message = None

  def __init__(self, message=None, headers=None):
    Exception.__init__(self)
    self.message = message
    self.headers = headers


class HttpBadRequest(HttpException):
  """400 Bad Request

  RFC2616, 10.4.1: The request could not be understood by the server
  due to malformed syntax. The client SHOULD NOT repeat the request
  without modifications.

  """
  code = 400


class HttpUnauthorized(HttpException):
  """401 Unauthorized

  RFC2616, section 10.4.2: The request requires user
  authentication. The response MUST include a WWW-Authenticate header
  field (section 14.47) containing a challenge applicable to the
  requested resource.

  """
  code = 401


class HttpForbidden(HttpException):
  """403 Forbidden

  RFC2616, 10.4.4: The server understood the request, but is refusing
  to fulfill it.  Authorization will not help and the request SHOULD
  NOT be repeated.

  """
  code = 403


class HttpNotFound(HttpException):
  """404 Not Found

  RFC2616, 10.4.5: The server has not found anything matching the
  Request-URI.  No indication is given of whether the condition is
  temporary or permanent.

  """
  code = 404


class HttpMethodNotAllowed(HttpException):
  """405 Method Not Allowed

  RFC2616, 10.4.6: The method specified in the Request-Line is not
  allowed for the resource identified by the Request-URI. The response
  MUST include an Allow header containing a list of valid methods for
  the requested resource.

  """
  code = 405


class HttpNotAcceptable(HttpException):
  """406 Not Acceptable

  RFC2616, 10.4.7: The resource identified by the request is only capable of
  generating response entities which have content characteristics not
  acceptable according to the accept headers sent in the request.

  """
  code = 406


class HttpRequestTimeout(HttpException):
  """408 Request Timeout

  RFC2616, 10.4.9: The client did not produce a request within the
  time that the server was prepared to wait. The client MAY repeat the
  request without modifications at any later time.

  """
  code = 408


class HttpConflict(HttpException):
  """409 Conflict

  RFC2616, 10.4.10: The request could not be completed due to a
  conflict with the current state of the resource. This code is only
  allowed in situations where it is expected that the user might be
  able to resolve the conflict and resubmit the request.

  """
  code = 409


class HttpGone(HttpException):
  """410 Gone

  RFC2616, 10.4.11: The requested resource is no longer available at
  the server and no forwarding address is known. This condition is
  expected to be considered permanent.

  """
  code = 410


class HttpLengthRequired(HttpException):
  """411 Length Required

  RFC2616, 10.4.12: The server refuses to accept the request without a
  defined Content-Length. The client MAY repeat the request if it adds
  a valid Content-Length header field containing the length of the
  message-body in the request message.

  """
  code = 411


class HttpPreconditionFailed(HttpException):
  """412 Precondition Failed

  RFC2616, 10.4.13: The precondition given in one or more of the
  request-header fields evaluated to false when it was tested on the
  server.

  """
  code = 412


class HttpUnsupportedMediaType(HttpException):
  """415 Unsupported Media Type

  RFC2616, 10.4.16: The server is refusing to service the request because the
  entity of the request is in a format not supported by the requested resource
  for the requested method.

  """
  code = 415


class HttpInternalServerError(HttpException):
  """500 Internal Server Error

  RFC2616, 10.5.1: The server encountered an unexpected condition
  which prevented it from fulfilling the request.

  """
  code = 500


class HttpNotImplemented(HttpException):
  """501 Not Implemented

  RFC2616, 10.5.2: The server does not support the functionality
  required to fulfill the request.

  """
  code = 501


class HttpBadGateway(HttpException):
  """502 Bad Gateway

  RFC2616, 10.5.3: The server, while acting as a gateway or proxy,
  received an invalid response from the upstream server it accessed in
  attempting to fulfill the request.

  """
  code = 502


class HttpServiceUnavailable(HttpException):
  """503 Service Unavailable

  RFC2616, 10.5.4: The server is currently unable to handle the
  request due to a temporary overloading or maintenance of the server.

  """
  code = 503


class HttpGatewayTimeout(HttpException):
  """504 Gateway Timeout

  RFC2616, 10.5.5: The server, while acting as a gateway or proxy, did
  not receive a timely response from the upstream server specified by
  the URI (e.g.  HTTP, FTP, LDAP) or some other auxiliary server
  (e.g. DNS) it needed to access in attempting to complete the
  request.

  """
  code = 504


class HttpVersionNotSupported(HttpException):
  """505 HTTP Version Not Supported

  RFC2616, 10.5.6: The server does not support, or refuses to support,
  the HTTP protocol version that was used in the request message.

  """
  code = 505


def ParseHeaders(buf):
  """Parses HTTP headers.

  @note: This is just a trivial wrapper around C{email.message_from_file}

  """
  return email.message_from_file(buf)


def SocketOperation(sock, op, arg1, timeout):
  """Wrapper around socket functions.

  This function abstracts error handling for socket operations, especially
  for the complicated interaction with OpenSSL.

  @type sock: socket
  @param sock: Socket for the operation
  @type op: int
  @param op: Operation to execute (SOCKOP_* constants)
  @type arg1: any
  @param arg1: Parameter for function (if needed)
  @type timeout: None or float
  @param timeout: Timeout in seconds or None
  @return: Return value of socket function

  """
  # TODO: event_poll/event_check/override
  if op in (SOCKOP_SEND, SOCKOP_HANDSHAKE):
    event_poll = select.POLLOUT

  elif op == SOCKOP_RECV:
    event_poll = select.POLLIN

  elif op == SOCKOP_SHUTDOWN:
    event_poll = None

    # The timeout is only used when OpenSSL requests polling for a condition.
    # It is not advisable to have no timeout for shutdown.
    assert timeout

  else:
    raise AssertionError("Invalid socket operation")

  # Handshake is only supported by SSL sockets
  if (op == SOCKOP_HANDSHAKE and
      not isinstance(sock, OpenSSL.SSL.ConnectionType)):
    return

  # No override by default
  event_override = 0

  while True:
    # Poll only for certain operations and when asked for by an override
    if event_override or op in (SOCKOP_SEND, SOCKOP_RECV, SOCKOP_HANDSHAKE):
      if event_override:
        wait_for_event = event_override
      else:
        wait_for_event = event_poll

      event = utils.WaitForFdCondition(sock, wait_for_event, timeout)
      if event is None:
        raise HttpSocketTimeout()

      if event & (select.POLLNVAL | select.POLLHUP | select.POLLERR):
        # Let the socket functions handle these
        break

      if not event & wait_for_event:
        continue

    # Reset override
    event_override = 0

    try:
      try:
        if op == SOCKOP_SEND:
          return sock.send(arg1)

        elif op == SOCKOP_RECV:
          return sock.recv(arg1)

        elif op == SOCKOP_SHUTDOWN:
          if isinstance(sock, OpenSSL.SSL.ConnectionType):
            # PyOpenSSL's shutdown() doesn't take arguments
            return sock.shutdown()
          else:
            return sock.shutdown(arg1)

        elif op == SOCKOP_HANDSHAKE:
          return sock.do_handshake()

      except OpenSSL.SSL.WantWriteError:
        # OpenSSL wants to write, poll for POLLOUT
        event_override = select.POLLOUT
        continue

      except OpenSSL.SSL.WantReadError:
        # OpenSSL wants to read, poll for POLLIN
        event_override = select.POLLIN | select.POLLPRI
        continue

      except OpenSSL.SSL.WantX509LookupError:
        continue

      except OpenSSL.SSL.ZeroReturnError as err:
        # SSL Connection has been closed. In SSL 3.0 and TLS 1.0, this only
        # occurs if a closure alert has occurred in the protocol, i.e. the
        # connection has been closed cleanly. Note that this does not
        # necessarily mean that the transport layer (e.g. a socket) has been
        # closed.
        if op == SOCKOP_SEND:
          # Can happen during a renegotiation
          raise HttpConnectionClosed(err.args)
        elif op == SOCKOP_RECV:
          return ""

        # SSL_shutdown shouldn't return SSL_ERROR_ZERO_RETURN
        raise socket.error(err.args)

      except OpenSSL.SSL.SysCallError as err:
        if op == SOCKOP_SEND:
          # arg1 is the data when writing
          if err.args and err.args[0] == -1 and arg1 == "":
            # errors when writing empty strings are expected
            # and can be ignored
            return 0

        if err.args == (-1, _SSL_UNEXPECTED_EOF):
          if op == SOCKOP_RECV:
            return ""
          elif op == SOCKOP_HANDSHAKE:
            # Can happen if peer disconnects directly after the connection is
            # opened.
            raise HttpSessionHandshakeUnexpectedEOF(err.args)

        raise socket.error(err.args)

      except OpenSSL.SSL.Error as err:
        raise socket.error(err.args)

    except socket.error as err:
      if err.args and err.args[0] == errno.EAGAIN:
        # Ignore EAGAIN
        continue

      raise


def ShutdownConnection(sock, close_timeout, write_timeout, msgreader, force):
  """Closes the connection.

  @type sock: socket
  @param sock: Socket to be shut down
  @type close_timeout: float
  @param close_timeout: How long to wait for the peer to close
      the connection
  @type write_timeout: float
  @param write_timeout: Write timeout for shutdown
  @type msgreader: http.HttpMessageReader
  @param msgreader: Request message reader, used to determine whether
      peer should close connection
  @type force: bool
  @param force: Whether to forcibly close the connection without
      waiting for peer

  """
  #print(msgreader.peer_will_close, force)
  if msgreader and msgreader.peer_will_close and not force:
    # Wait for peer to close
    try:
      # Check whether it's actually closed
      if not SocketOperation(sock, SOCKOP_RECV, 1, close_timeout):
        return
    except (socket.error, HttpError, HttpSocketTimeout):
      # Ignore errors at this stage
      pass

  # Close the connection from our side
  try:
    # We don't care about the return value, see NOTES in SSL_shutdown(3).
    SocketOperation(sock, SOCKOP_SHUTDOWN, socket.SHUT_RDWR,
                    write_timeout)
  except HttpSocketTimeout:
    raise HttpError("Timeout while shutting down connection")
  except socket.error as err:
    # Ignore ENOTCONN
    if not (err.args and err.args[0] == errno.ENOTCONN):
      raise HttpError("Error while shutting down connection: %s" % err)


def Handshake(sock, write_timeout):
  """Shakes peer's hands.

  @type sock: socket
  @param sock: Socket to be shut down
  @type write_timeout: float
  @param write_timeout: Write timeout for handshake

  """
  try:
    return SocketOperation(sock, SOCKOP_HANDSHAKE, None, write_timeout)
  except HttpSocketTimeout:
    raise HttpError("Timeout during SSL handshake")
  except socket.error as err:
    raise HttpError("Error in SSL handshake: %s" % err)


class HttpSslParams(object):
  """Data class for SSL key and certificate.

  """
  def __init__(self, ssl_key_path, ssl_cert_path):
    """Initializes this class.

    @type ssl_key_path: string
    @param ssl_key_path: Path to file containing SSL key in PEM format
    @type ssl_cert_path: string
    @param ssl_cert_path: Path to file containing SSL certificate
        in PEM format

    """
    self.ssl_key_pem = utils.ReadFile(ssl_key_path)
    self.ssl_cert_pem = utils.ReadFile(ssl_cert_path)
    self.ssl_cert_path = ssl_cert_path

  def GetCertificateDigest(self):
    return utils.GetCertificateDigest(cert_filename=self.ssl_cert_path)

  def GetCertificateFilename(self):
    return self.ssl_cert_path

  def GetKey(self):
    return OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                          self.ssl_key_pem)

  def GetCertificate(self):
    return OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           self.ssl_cert_pem)


class HttpBase(object):
  """Base class for HTTP server and client.

  """
  def __init__(self):
    self.using_ssl = None
    self._ssl_params = None
    self._ssl_key = None
    self._ssl_cert = None

  def _CreateSocket(self, ssl_params, ssl_verify_peer, family,
                    ssl_verify_callback):
    """Creates a TCP socket and initializes SSL if needed.

    @type ssl_params: HttpSslParams
    @param ssl_params: SSL key and certificate
    @type ssl_verify_peer: bool
    @param ssl_verify_peer: Whether to require client certificate
        and compare it with our certificate
    @type family: int
    @param family: socket.AF_INET | socket.AF_INET6

    """
    assert family in (socket.AF_INET, socket.AF_INET6)
    if ssl_verify_peer:
      assert ssl_verify_callback is not None

    self._ssl_params = ssl_params
    sock = socket.socket(family, socket.SOCK_STREAM)

    # Should we enable SSL?
    self.using_ssl = ssl_params is not None

    if not self.using_ssl:
      return sock

    self._ssl_key = ssl_params.GetKey()
    self._ssl_cert = ssl_params.GetCertificate()

    ctx = OpenSSL.SSL.Context(OpenSSL.SSL.SSLv23_METHOD)
    ctx.set_options(OpenSSL.SSL.OP_NO_SSLv2)

    ciphers = self.GetSslCiphers()
    logging.debug("Setting SSL cipher string %s", ciphers)
    ctx.set_cipher_list(ciphers)

    ctx.use_privatekey(self._ssl_key)
    ctx.use_certificate(self._ssl_cert)
    ctx.check_privatekey()
    logging.debug("Certificate digest: %s.", ssl_params.GetCertificateDigest())
    logging.debug("Certificate filename: %s.",
                  ssl_params.GetCertificateFilename())

    if ssl_verify_peer:
      ctx.set_verify(OpenSSL.SSL.VERIFY_PEER |
                     OpenSSL.SSL.VERIFY_FAIL_IF_NO_PEER_CERT,
                     ssl_verify_callback)

      # Also add our certificate as a trusted CA to be sent to the client.
      # This is required at least for GnuTLS clients to work.
      try:
        # This will fail for PyOpenssl versions before 0.10
        ctx.add_client_ca(self._ssl_cert)
      except AttributeError:
        # Fall back to letting OpenSSL read the certificate file directly.
        ctx.load_client_ca(ssl_params.ssl_cert_path)

    return OpenSSL.SSL.Connection(ctx, sock)

  def GetSslCiphers(self): # pylint: disable=R0201
    """Returns the ciphers string for SSL.

    """
    return constants.OPENSSL_CIPHERS

  def _SSLVerifyCallback(self, conn, cert, errnum, errdepth, ok):
    """Verify the certificate provided by the peer

    We only compare fingerprints. The client must use the same certificate as
    we do on our side.

    """
    # some parameters are unused, but this is the API
    # pylint: disable=W0613
    assert self._ssl_params, "SSL not initialized"

    return (self._ssl_cert.digest("sha1") == cert.digest("sha1") and
            self._ssl_cert.digest("md5") == cert.digest("md5"))


class HttpMessage(object):
  """Data structure for HTTP message.

  """
  def __init__(self):
    self.start_line = None
    self.headers = None
    self.body = None


class HttpClientToServerStartLine(object):
  """Data structure for HTTP request start line.

  """
  def __init__(self, method, path, version):
    self.method = method
    self.path = path
    self.version = version

  def __str__(self):
    return "%s %s %s" % (self.method, self.path, self.version)


class HttpServerToClientStartLine(object):
  """Data structure for HTTP response start line.

  """
  def __init__(self, version, code, reason):
    self.version = version
    self.code = code
    self.reason = reason

  def __str__(self):
    return "%s %s %s" % (self.version, self.code, self.reason)


class HttpMessageWriter(object):
  """Writes an HTTP message to a socket.

  """
  def __init__(self, sock, msg, write_timeout):
    """Initializes this class and writes an HTTP message to a socket.

    @type sock: socket
    @param sock: Socket to be written to
    @type msg: http.HttpMessage
    @param msg: HTTP message to be written
    @type write_timeout: float
    @param write_timeout: Write timeout for socket

    """
    self._msg = msg

    self._PrepareMessage()

    buf = self._FormatMessage()

    pos = 0
    end = len(buf)
    while pos < end:
      # Send only SOCK_BUF_SIZE bytes at a time
      data = buf[pos:(pos + SOCK_BUF_SIZE)]

      sent = SocketOperation(sock, SOCKOP_SEND, data, write_timeout)

      # Remove sent bytes
      pos += sent

    assert pos == end, "Message wasn't sent completely"

  def _PrepareMessage(self):
    """Prepares the HTTP message by setting mandatory headers.

    """
    # RFC2616, section 4.3: "The presence of a message-body in a request is
    # signaled by the inclusion of a Content-Length or Transfer-Encoding header
    # field in the request's message-headers."
    if self._msg.body:
      self._msg.headers[HTTP_CONTENT_LENGTH] = len(self._msg.body)

  def _FormatMessage(self):
    """Serializes the HTTP message into a string.

    """
    buf = StringIO()

    # Add start line
    buf.write(str(self._msg.start_line))
    buf.write("\r\n")

    # Add headers
    if self._msg.start_line.version != HTTP_0_9:
      for name, value in self._msg.headers.items():
        buf.write("%s: %s\r\n" % (name, value))

    buf.write("\r\n")

    # Add message body if needed
    if self.HasMessageBody():
      buf.write(self._msg.body.decode())

    elif self._msg.body:
      logging.warning("Ignoring message body")

    return buf.getvalue()

  def HasMessageBody(self):
    """Checks whether the HTTP message contains a body.

    Can be overridden by subclasses.

    """
    return bool(self._msg.body)


class HttpMessageReader(object):
  """Reads HTTP message from socket.

  """
  # Length limits
  START_LINE_LENGTH_MAX = None
  HEADER_LENGTH_MAX = None

  # Parser state machine
  PS_START_LINE = "start-line"
  PS_HEADERS = "headers"
  PS_BODY = "entity-body"
  PS_COMPLETE = "complete"

  def __init__(self, sock, msg, read_timeout):
    """Reads an HTTP message from a socket.

    @type sock: socket
    @param sock: Socket to be read from
    @type msg: http.HttpMessage
    @param msg: Object for the read message
    @type read_timeout: float
    @param read_timeout: Read timeout for socket

    """
    self.sock = sock
    self.msg = msg

    self.start_line_buffer = None
    self.header_buffer = StringIO()
    self.body_buffer = StringIO()
    self.parser_status = self.PS_START_LINE
    self.content_length = None
    self.peer_will_close = None

    buf = ""
    eof = False
    while self.parser_status != self.PS_COMPLETE:
      # TODO: Don't read more than necessary (Content-Length), otherwise
      # data might be lost and/or an error could occur
      data = SocketOperation(sock, SOCKOP_RECV, SOCK_BUF_SIZE, read_timeout)

      if data:
        buf += data.decode()
      else:
        eof = True

      # Do some parsing and error checking while more data arrives
      buf = self._ContinueParsing(buf, eof)

      # Must be done only after the buffer has been evaluated
      # TODO: Content-Length < len(data read) and connection closed
      if (eof and
          self.parser_status in (self.PS_START_LINE,
                                 self.PS_HEADERS)):
        raise HttpError("Connection closed prematurely")

    # Parse rest
    buf = self._ContinueParsing(buf, True)

    assert self.parser_status == self.PS_COMPLETE
    assert not buf, "Parser didn't read full response"

    # Body is complete
    msg.body = self.body_buffer.getvalue()

  def _ContinueParsing(self, buf, eof):
    """Main function for HTTP message state machine.

    @type buf: string
    @param buf: Receive buffer
    @type eof: bool
    @param eof: Whether we've reached EOF on the socket
    @rtype: string
    @return: Updated receive buffer

    """
    # TODO: Use offset instead of slicing when possible
    if self.parser_status == self.PS_START_LINE:
      # Expect start line
      while True:
        idx = buf.find("\r\n")

        # RFC2616, section 4.1: "In the interest of robustness, servers SHOULD
        # ignore any empty line(s) received where a Request-Line is expected.
        # In other words, if the server is reading the protocol stream at the
        # beginning of a message and receives a CRLF first, it should ignore
        # the CRLF."
        if idx == 0:
          # TODO: Limit number of CRLFs/empty lines for safety?
          buf = buf[2:]
          continue

        if idx > 0:
          self.start_line_buffer = buf[:idx]

          self._CheckStartLineLength(len(self.start_line_buffer))

          # Remove status line, including CRLF
          buf = buf[idx + 2:]

          self.msg.start_line = self.ParseStartLine(self.start_line_buffer)

          self.parser_status = self.PS_HEADERS
        else:
          # Check whether incoming data is getting too large, otherwise we just
          # fill our read buffer.
          self._CheckStartLineLength(len(buf))

        break

    # TODO: Handle messages without headers
    if self.parser_status == self.PS_HEADERS:
      # Wait for header end
      idx = buf.find("\r\n\r\n")
      if idx >= 0:
        self.header_buffer.write(buf[:idx + 2])

        self._CheckHeaderLength(self.header_buffer.tell())

        # Remove headers, including CRLF
        buf = buf[idx + 4:]

        self._ParseHeaders()

        self.parser_status = self.PS_BODY
      else:
        # Check whether incoming data is getting too large, otherwise we just
        # fill our read buffer.
        self._CheckHeaderLength(len(buf))

    if self.parser_status == self.PS_BODY:
      # TODO: Implement max size for body_buffer
      self.body_buffer.write(buf)
      buf = ""

      # Check whether we've read everything
      #
      # RFC2616, section 4.4: "When a message-body is included with a message,
      # the transfer-length of that body is determined by one of the following
      # [...] 5. By the server closing the connection. (Closing the connection
      # cannot be used to indicate the end of a request body, since that would
      # leave no possibility for the server to send back a response.)"
      #
      # TODO: Error when buffer length > Content-Length header
      if (eof or
          self.content_length is None or
          (self.content_length is not None and
           self.body_buffer.tell() >= self.content_length)):
        self.parser_status = self.PS_COMPLETE

    return buf

  def _CheckStartLineLength(self, length):
    """Limits the start line buffer size.

    @type length: int
    @param length: Buffer size

    """
    if (self.START_LINE_LENGTH_MAX is not None and
        length > self.START_LINE_LENGTH_MAX):
      raise HttpError("Start line longer than %d chars" %
                       self.START_LINE_LENGTH_MAX)

  def _CheckHeaderLength(self, length):
    """Limits the header buffer size.

    @type length: int
    @param length: Buffer size

    """
    if (self.HEADER_LENGTH_MAX is not None and
        length > self.HEADER_LENGTH_MAX):
      raise HttpError("Headers longer than %d chars" % self.HEADER_LENGTH_MAX)

  def ParseStartLine(self, start_line):
    """Parses the start line of a message.

    Must be overridden by subclass.

    @type start_line: string
    @param start_line: Start line string

    """
    raise NotImplementedError()

  def _WillPeerCloseConnection(self):
    """Evaluate whether peer will close the connection.

    @rtype: bool
    @return: Whether peer will close the connection

    """
    # RFC2616, section 14.10: "HTTP/1.1 defines the "close" connection option
    # for the sender to signal that the connection will be closed after
    # completion of the response. For example,
    #
    #        Connection: close
    #
    # in either the request or the response header fields indicates that the
    # connection SHOULD NOT be considered `persistent' (section 8.1) after the
    # current request/response is complete."

    hdr_connection = self.msg.headers.get(HTTP_CONNECTION, None)
    if hdr_connection:
      hdr_connection = hdr_connection.lower()

    # An HTTP/1.1 server is assumed to stay open unless explicitly closed.
    if self.msg.start_line.version == HTTP_1_1:
      return (hdr_connection and "close" in hdr_connection)

    # Some HTTP/1.0 implementations have support for persistent connections,
    # using rules different than HTTP/1.1.

    # For older HTTP, Keep-Alive indicates persistent connection.
    if self.msg.headers.get(HTTP_KEEP_ALIVE):
      return False

    # At least Akamai returns a "Connection: Keep-Alive" header, which was
    # supposed to be sent by the client.
    if hdr_connection and "keep-alive" in hdr_connection:
      return False

    return True

  def _ParseHeaders(self):
    """Parses the headers.

    This function also adjusts internal variables based on header values.

    RFC2616, section 4.3: The presence of a message-body in a request is
    signaled by the inclusion of a Content-Length or Transfer-Encoding header
    field in the request's message-headers.

    """
    # Parse headers
    self.header_buffer.seek(0, 0)
    self.msg.headers = ParseHeaders(self.header_buffer)

    self.peer_will_close = self._WillPeerCloseConnection()

    # Do we have a Content-Length header?
    hdr_content_length = self.msg.headers.get(HTTP_CONTENT_LENGTH, None)
    if hdr_content_length:
      try:
        self.content_length = int(hdr_content_length)
      except (TypeError, ValueError):
        self.content_length = None
      if self.content_length is not None and self.content_length < 0:
        self.content_length = None

    # if the connection remains open and a content-length was not provided,
    # then assume that the connection WILL close.
    if self.content_length is None:
      self.peer_will_close = True
