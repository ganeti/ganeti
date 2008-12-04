#
#

# Copyright (C) 2007, 2008 Google Inc.
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

"""HTTP client module.

"""

import BaseHTTPServer
import cgi
import logging
import OpenSSL
import os
import select
import socket
import sys
import time
import signal
import errno
import threading

from ganeti import constants
from ganeti import serializer
from ganeti import workerpool
from ganeti import utils
from ganeti import http


HTTP_CLIENT_THREADS = 10


class HttpClientRequest(object):
  def __init__(self, host, port, method, path, headers=None, post_data=None,
               ssl_params=None, ssl_verify_peer=False):
    """Describes an HTTP request.

    @type host: string
    @param host: Hostname
    @type port: int
    @param port: Port
    @type method: string
    @param method: Method name
    @type path: string
    @param path: Request path
    @type headers: dict or None
    @param headers: Additional headers to send
    @type post_data: string or None
    @param post_data: Additional data to send
    @type ssl_params: HttpSslParams
    @param ssl_params: SSL key and certificate
    @type ssl_verify_peer: bool
    @param ssl_verify_peer: Whether to compare our certificate with server's
                            certificate

    """
    if post_data is not None:
      assert method.upper() in (http.HTTP_POST, http.HTTP_PUT), \
        "Only POST and GET requests support sending data"

    assert path.startswith("/"), "Path must start with slash (/)"

    # Request attributes
    self.host = host
    self.port = port
    self.ssl_params = ssl_params
    self.ssl_verify_peer = ssl_verify_peer
    self.method = method
    self.path = path
    self.headers = headers
    self.post_data = post_data

    self.success = None
    self.error = None

    # Raw response
    self.response = None

    # Response attributes
    self.resp_version = None
    self.resp_status_code = None
    self.resp_reason = None
    self.resp_headers = None
    self.resp_body = None


class _HttpClientToServerMessageWriter(http.HttpMessageWriter):
  pass


class _HttpServerToClientMessageReader(http.HttpMessageReader):
  # Length limits
  START_LINE_LENGTH_MAX = 512
  HEADER_LENGTH_MAX = 4096

  def ParseStartLine(self, start_line):
    """Parses the status line sent by the server.

    """
    # Empty lines are skipped when reading
    assert start_line

    try:
      [version, status, reason] = start_line.split(None, 2)
    except ValueError:
      try:
        [version, status] = start_line.split(None, 1)
        reason = ""
      except ValueError:
        version = http.HTTP_0_9

    if version:
      version = version.upper()

    # The status code is a three-digit number
    try:
      status = int(status)
      if status < 100 or status > 999:
        status = -1
    except ValueError:
      status = -1

    if status == -1:
      raise http.HttpError("Invalid status code (%r)" % start_line)

    return http.HttpServerToClientStartLine(version, status, reason)


class HttpClientRequestExecutor(http.HttpSocketBase):
  # Default headers
  DEFAULT_HEADERS = {
    http.HTTP_USER_AGENT: http.HTTP_GANETI_VERSION,
    # TODO: For keep-alive, don't send "Connection: close"
    http.HTTP_CONNECTION: "close",
    }

  # Timeouts in seconds for socket layer
  # TODO: Soft timeout instead of only socket timeout?
  # TODO: Make read timeout configurable per OpCode?
  CONNECT_TIMEOUT = 5
  WRITE_TIMEOUT = 10
  READ_TIMEOUT = None
  CLOSE_TIMEOUT = 1

  def __init__(self, req):
    """Initializes the HttpClientRequestExecutor class.

    @type req: HttpClientRequest
    @param req: Request object

    """
    http.HttpSocketBase.__init__(self)
    self.request = req

    self.poller = select.poll()

    try:
      # TODO: Implement connection caching/keep-alive
      self.sock = self._CreateSocket(req.ssl_params,
                                     req.ssl_verify_peer)

      # Disable Python's timeout
      self.sock.settimeout(None)

      # Operate in non-blocking mode
      self.sock.setblocking(0)

      response_msg_reader = None
      response_msg = None
      force_close = True

      self._Connect()
      try:
        self._SendRequest()
        (response_msg_reader, response_msg) = self._ReadResponse()

        # Only wait for server to close if we didn't have any exception.
        force_close = False
      finally:
        # TODO: Keep-alive is not supported, always close connection
        force_close = True
        http.ShutdownConnection(self.poller, self.sock,
                                self.CLOSE_TIMEOUT, self.WRITE_TIMEOUT,
                                response_msg_reader, force_close)

      self.sock.close()
      self.sock = None

      req.response = response_msg

      req.resp_version = req.response.start_line.version
      req.resp_status_code = req.response.start_line.code
      req.resp_reason = req.response.start_line.reason
      req.resp_headers = req.response.headers
      req.resp_body = req.response.body

      req.success = True
      req.error = None

    except http.HttpError, err:
      req.success = False
      req.error = str(err)

  def _Connect(self):
    """Non-blocking connect to host with timeout.

    """
    connected = False
    while True:
      try:
        connect_error = self.sock.connect_ex((self.request.host,
                                              self.request.port))
      except socket.gaierror, err:
        raise http.HttpError("Connection failed: %s" % str(err))

      if connect_error == errno.EINTR:
        # Mask signals
        pass

      elif connect_error == 0:
        # Connection established
        connected = True
        break

      elif connect_error == errno.EINPROGRESS:
        # Connection started
        break

      raise http.HttpError("Connection failed (%s: %s)" %
                             (connect_error, os.strerror(connect_error)))

    if not connected:
      # Wait for connection
      event = http.WaitForSocketCondition(self.poller, self.sock,
                                          select.POLLOUT, self.CONNECT_TIMEOUT)
      if event is None:
        raise http.HttpError("Timeout while connecting to server")

      # Get error code
      connect_error = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
      if connect_error != 0:
        raise http.HttpError("Connection failed (%s: %s)" %
                               (connect_error, os.strerror(connect_error)))

    # Enable TCP keep-alive
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    # If needed, Linux specific options are available to change the TCP
    # keep-alive settings, see "man 7 tcp" for TCP_KEEPCNT, TCP_KEEPIDLE and
    # TCP_KEEPINTVL.

  def _SendRequest(self):
    """Sends request to server.

    """
    # Headers
    send_headers = self.DEFAULT_HEADERS.copy()

    if self.request.headers:
      send_headers.update(self.request.headers)

    send_headers[http.HTTP_HOST] = "%s:%s" % (self.request.host, self.request.port)

    # Response message
    msg = http.HttpMessage()

    # Combine request line. We only support HTTP/1.0 (no chunked transfers and
    # no keep-alive).
    # TODO: For keep-alive, change to HTTP/1.1
    msg.start_line = \
      http.HttpClientToServerStartLine(method=self.request.method.upper(),
                                       path=self.request.path, version=http.HTTP_1_0)
    msg.headers = send_headers
    msg.body = self.request.post_data

    try:
      _HttpClientToServerMessageWriter(self.sock, msg, self.WRITE_TIMEOUT)
    except http.HttpSocketTimeout:
      raise http.HttpError("Timeout while sending request")
    except socket.error, err:
      raise http.HttpError("Error sending request: %s" % err)

  def _ReadResponse(self):
    """Read response from server.

    """
    response_msg = http.HttpMessage()

    try:
      response_msg_reader = \
        _HttpServerToClientMessageReader(self.sock, response_msg,
                                         self.READ_TIMEOUT)
    except http.HttpSocketTimeout:
      raise http.HttpError("Timeout while reading response")
    except socket.error, err:
      raise http.HttpError("Error reading response: %s" % err)

    return (response_msg_reader, response_msg)


class _HttpClientPendingRequest(object):
  """Data class for pending requests.

  """
  def __init__(self, request):
    self.request = request

    # Thread synchronization
    self.done = threading.Event()


class HttpClientWorker(workerpool.BaseWorker):
  """HTTP client worker class.

  """
  def RunTask(self, pend_req):
    try:
      HttpClientRequestExecutor(pend_req.request)
    finally:
      pend_req.done.set()


class HttpClientWorkerPool(workerpool.WorkerPool):
  def __init__(self, manager):
    workerpool.WorkerPool.__init__(self, HTTP_CLIENT_THREADS,
                                   HttpClientWorker)
    self.manager = manager


class HttpClientManager(object):
  """Manages HTTP requests.

  """
  def __init__(self):
    self._wpool = HttpClientWorkerPool(self)

  def __del__(self):
    self.Shutdown()

  def ExecRequests(self, requests):
    """Execute HTTP requests.

    This function can be called from multiple threads at the same time.

    @type requests: List of HttpClientRequest instances
    @param requests: The requests to execute
    @rtype: List of HttpClientRequest instances
    @returns: The list of requests passed in

    """
    # _HttpClientPendingRequest is used for internal thread synchronization
    pending = [_HttpClientPendingRequest(req) for req in requests]

    try:
      # Add requests to queue
      for pend_req in pending:
        self._wpool.AddTask(pend_req)

    finally:
      # In case of an exception we should still wait for the rest, otherwise
      # another thread from the worker pool could modify the request object
      # after we returned.

      # And wait for them to finish
      for pend_req in pending:
        pend_req.done.wait()

    # Return original list
    return requests

  def Shutdown(self):
    self._wpool.Quiesce()
    self._wpool.TerminateWorkers()
