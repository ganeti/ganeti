#
#

# Copyright (C) 2026 the Ganeti project
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

This module provides a simple, thread-based HTTP/HTTPS server implementation
using Python's standard library.

"""

import hashlib
import html
import logging
import os
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler

from ganeti import http
from ganeti import netutils


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

# Headers whose values should be redacted in debug logs.
SENSITIVE_HEADERS = frozenset([
  "authorization",
  "cookie",
  "set-cookie",
  "proxy-authorization",
  "x-auth-token",
  "api-key",
])


class _HttpServerRequest(object):
  """Data structure for HTTP request on server side.

  """
  def __init__(self, method, path, headers, body, sock):
    self.request_method = method
    self.request_path = path
    self.request_headers = headers
    self.request_body = body
    self.request_sock = sock
    self.resp_headers = {}
    self.private = None


def _FormatCertificateDigest(der_cert):
  """Compute SHA1 digest of a DER-encoded certificate.

  Returns the digest in the same colon-separated hex format as
  PyOpenSSL's C{X509.digest()}, for compatibility with existing
  certificate digest storage (ssconf, etc.).

  @type der_cert: bytes
  @param der_cert: DER-encoded certificate
  @rtype: string
  @return: SHA1 digest in "XX:XX:XX:..." format

  """
  raw = hashlib.sha1(der_cert).digest()
  return ":".join(f"{b:02X}" for b in raw)


class _ChildProcessReaper(object):
  """Background thread that reaps zombie child processes.

  The threaded server doesn't integrate with the mainloop's signal
  handling, so we need a separate mechanism to reap child processes.

  This class runs a background daemon thread that periodically calls
  os.waitpid() to reap any zombie children. This is critical when the
  node daemon spawns processes (like KVM instances) that may exit while
  the daemon continues running.

  """
  # Singleton instance
  _instance = None
  _lock = threading.Lock()

  def __init__(self, check_interval=1.0):
    """Initialize the child reaper.

    @type check_interval: float
    @param check_interval: Seconds between reaping checks

    """
    self._check_interval = check_interval
    self._running = False
    self._thread = None

  @classmethod
  def GetInstance(cls):
    """Get or create the singleton reaper instance.

    @rtype: _ChildProcessReaper
    @return: The singleton reaper instance

    """
    if cls._instance is None:
      with cls._lock:
        if cls._instance is None:
          cls._instance = cls()
    return cls._instance

  def Start(self):
    """Start the reaper thread if not already running."""
    if self._running:
      return

    self._running = True
    self._thread = threading.Thread(
      target=self._reaper_loop,
      name="ChildReaper",
      daemon=True
    )
    self._thread.start()
    logging.debug("Child process reaper started")

  def Stop(self):
    """Stop the reaper thread."""
    self._running = False
    if self._thread and self._thread.is_alive():
      self._thread.join(timeout=2.0)

  def _reaper_loop(self):
    """Main loop that reaps zombie children."""
    while self._running:
      try:
        while True:
          try:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
              break
            logging.debug("Reaped child process %d with status %d",
                          pid, status)
          except ChildProcessError:
            break
          except OSError as e:
            logging.warning("Error reaping child process: %s", e)
            break
      except Exception as e:
        logging.exception("Unexpected error in child reaper: %s", e)

      time.sleep(self._check_interval)


class HttpServer(HTTPServer):
  """Threaded HTTP/HTTPS server for Ganeti.

  Each request is handled by a worker thread from a bounded thread pool.
  Threads are reused across requests for efficiency.

  """
  allow_reuse_address = True

  def __init__(self, local_address, port, ganeti_handler,
               ssl_params=None, ssl_verify_peer=False,
               ssl_verify_callback=None, max_clients=20):
    """Initialize the HTTP server.

    @type local_address: string
    @param local_address: Local IP address to bind to
    @type port: int
    @param port: TCP port to listen on
    @type ganeti_handler: HttpServerHandler
    @param ganeti_handler: Ganeti-specific request handler
    @type ssl_params: HttpSslParams
    @param ssl_params: SSL parameters for HTTPS
    @type ssl_verify_peer: bool
    @param ssl_verify_peer: Whether to require and verify client certificates
    @type ssl_verify_callback: callable
    @param ssl_verify_callback: Callback for client certificate verification.
        Called with a single argument: the SHA1 digest of the client
        certificate as a colon-separated hex string (e.g. "AB:CD:EF:...").
        Must return True to accept the certificate, False to reject.
    @type max_clients: int
    @param max_clients: Maximum number of concurrent worker threads

    """
    self.ganeti_handler = ganeti_handler
    self.ssl_verify_peer = ssl_verify_peer
    self.ssl_verify_callback = ssl_verify_callback

    self._thread_pool = ThreadPoolExecutor(
      max_workers=max_clients,
      thread_name_prefix="HTTPWorker"
    )
    logging.debug("Created thread pool with %d HTTP workers", max_clients)

    self.address_family = netutils.IPAddress.GetAddressFamily(local_address)

    HTTPServer.__init__(self, (local_address, port), GanetiRequestHandler)

    self._ssl_context = None
    if ssl_params:
      self._ssl_context = self._create_ssl_context(ssl_params, ssl_verify_peer)

    self._server_thread = None

  def Start(self):
    """Start the HTTP server in a background daemon thread.

    Also starts the child process reaper.

    """
    host, port = self.server_address
    logging.info("Starting HTTP server on %s:%d", host, port)

    _ChildProcessReaper.GetInstance().Start()

    self._server_thread = threading.Thread(
      target=self.serve_forever,
      name="HTTPServer",
      daemon=True
    )
    self._server_thread.start()

  def Stop(self):
    """Stop the HTTP server.

    Gracefully shuts down the server and waits for the thread to finish.

    """
    logging.info("Stopping HTTP server")

    self.shutdown()
    self.server_close()

    if self._server_thread and self._server_thread.is_alive():
      self._server_thread.join(timeout=5.0)

    _ChildProcessReaper.GetInstance().Stop()

  def process_request(self, request, client_address):
    """Submit request to thread pool instead of creating a new thread.

    This overrides the default HTTPServer.process_request to use a bounded
    thread pool instead of creating unlimited threads.

    @type request: socket.socket
    @param request: Client socket
    @type client_address: tuple
    @param client_address: Client address (host, port)

    """
    self._thread_pool.submit(
      self._process_request_thread,
      request,
      client_address
    )

  def _process_request_thread(self, request, client_address):
    """Process the request in a worker thread.

    If SSL is enabled, the TLS handshake is performed here rather than
    in the accept loop.  This allows multiple connections to handshake
    concurrently across worker threads instead of being serialized
    through the single accept thread.

    @type request: socket.socket
    @param request: Client socket (plain TCP)
    @type client_address: tuple
    @param client_address: Client address (host, port)

    """
    try:
      if self._ssl_context:
        try:
          request = self._ssl_context.wrap_socket(request,
                                                  server_side=True)
        except (OSError, ssl.SSLError) as err:
          logging.debug("TLS handshake failed from %s:%s: %s",
                        client_address[0], client_address[1], err)
          try:
            request.close()
          except OSError:
            pass
          return

      self.finish_request(request, client_address)
    except Exception:
      self.handle_error(request, client_address)
    finally:
      self.shutdown_request(request)

  def shutdown(self):
    """Shutdown the server and wait for thread pool to finish.

    """
    HTTPServer.shutdown(self)

    logging.debug("Shutting down HTTP thread pool")
    self._thread_pool.shutdown(wait=True)
    logging.debug("HTTP thread pool shut down complete")

  @staticmethod
  def _create_ssl_context(ssl_params, ssl_verify_peer):
    """Create an SSL context for the server.

    Uses Python's stdlib ssl module. When ssl_verify_peer is enabled,
    the server certificate is loaded as a trusted CA for client
    certificate chain verification. The leaf client certificate is
    verified post-handshake by the request handler using the
    ssl_verify_callback.

    @type ssl_params: HttpSslParams
    @param ssl_params: SSL parameters (certificate and key paths)
    @type ssl_verify_peer: bool
    @param ssl_verify_peer: Whether to require client certificates
    @rtype: ssl.SSLContext
    @return: Configured SSL context

    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    if ssl_params.ssl_chain_path:
      ctx.load_cert_chain(certfile=ssl_params.ssl_chain_path,
                          keyfile=ssl_params.ssl_key_path)
    else:
      ctx.load_cert_chain(certfile=ssl_params.ssl_cert_path,
                          keyfile=ssl_params.ssl_key_path)

    if ssl_verify_peer:
      ctx.verify_mode = ssl.CERT_REQUIRED
      ctx.load_verify_locations(cafile=ssl_params.ssl_cert_path)

    logging.debug("Certificate digest: %s", ssl_params.GetCertificateDigest())
    logging.debug("Certificate filename: %s",
                  ssl_params.GetCertificateFilename())

    return ctx


class GanetiRequestHandler(BaseHTTPRequestHandler):
  """HTTP request handler for Ganeti.

  Handles individual HTTP requests and delegates to the Ganeti handler.

  """
  timeout = 10

  # 10 Megabytes max request body size
  MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024

  protocol_version = "HTTP/1.1"

  def _verify_client_certificate(self):
    """Verify the client certificate after SSL handshake.

    Chain verification (whether the client certificate was signed by
    a trusted CA) is handled by the SSL context via
    L{ssl.SSLContext.load_verify_locations}. This method performs
    additional application-level verification of the leaf certificate
    using the configured callback.

    @raise http.HttpForbidden: If certificate verification fails

    """
    if not self.server.ssl_verify_peer:
      return

    if not isinstance(self.connection, ssl.SSLSocket):
      return

    der_cert = self.connection.getpeercert(binary_form=True)
    if der_cert is None:
      raise http.HttpForbidden(
        message="No client certificate provided")

    cert_digest = _FormatCertificateDigest(der_cert)
    if not self.server.ssl_verify_callback(cert_digest):
      raise http.HttpForbidden(
        message="Client certificate verification failed")

  def handle_request_inner(self):
    """Process the HTTP request.

    This method handles the core request processing, including:
    - Verifying the client certificate (post-handshake)
    - Reading and validating the request body
    - Creating the request context
    - Calling authentication and handler functions
    - Sending the response

    """
    self.close_connection = True
    try:
      self._verify_client_certificate()

      logging.debug("Request: %s %s", self.command, self.path)

      if logging.getLogger().isEnabledFor(logging.DEBUG):
        sanitized = {}
        for key, value in self.headers.items():
          if key.lower() in SENSITIVE_HEADERS:
            sanitized[key] = "REDACTED"
          else:
            sanitized[key] = value
        logging.debug("Headers: %s", sanitized)

      content_length = int(self.headers.get("Content-Length", 0))

      logging.debug("Content-Length: %d", content_length)

      if content_length > self.MAX_REQUEST_BODY_SIZE:
        self.send_error(413, "Request body too large")
        return

      if content_length > 0:
        body = self.rfile.read(content_length)
        logging.debug("Read %d bytes of body", len(body))
      else:
        body = b""

      # Create request context (compatible with existing handlers)
      # Note: self.headers is an HTTPMessage object with case-insensitive
      # header access via get(). Don't convert to dict to preserve this.
      handler_context = _HttpServerRequest(
        method=self.command,
        path=self.path,
        headers=self.headers,
        body=body,
        sock=self.connection
      )

      # Log request without keeping reference to handler_context object.
      # Logging with %r would store handler_context in LogRecord.args,
      # preventing garbage collection of request body data.
      logging.debug("Handling request: %s %s (%d bytes)",
                    self.command, self.path, len(body))

      try:
        self.server.ganeti_handler.PreHandleRequest(handler_context)
        result = self.server.ganeti_handler.HandleRequest(handler_context)

        if not isinstance(result, (str, bytes)):
          raise http.HttpInternalServerError(
            "Handler function didn't return string type"
          )

        if isinstance(result, str):
          result_bytes = result.encode("utf-8")
        else:
          result_bytes = result

        self.send_response(http.HTTP_OK)

        for header, value in handler_context.resp_headers.items():
          self.send_header(header, value)
        self.send_header(http.HTTP_CONTENT_LENGTH, str(len(result_bytes)))
        self.send_header(http.HTTP_CONNECTION, "close")
        self.end_headers()

        self.wfile.write(result_bytes)

      except http.HttpException as err:
        self._send_error_response(err)

      except Exception as err:
        logging.exception("Caught exception")
        self._send_error_response(
          http.HttpInternalServerError(message=str(err))
        )

    except http.HttpException as err:
      self._send_error_response(err)

    except Exception as err:
      # Catch errors during body reading or context creation
      logging.exception("Error processing request")
      self.send_error(500, str(err))

  def _send_error_response(self, err):
    """Send an HTTP error response.

    @type err: HttpException
    @param err: The exception containing error details

    """
    # Get response message
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
      "message": html.escape(message),
      "explain": longmsg,
    }

    (content_type, body) = \
      self.server.ganeti_handler.FormatErrorMessage(values)

    if isinstance(body, str):
      body_bytes = body.encode("utf-8")
    else:
      body_bytes = body

    self.send_response(err.code)
    self.send_header(http.HTTP_CONTENT_TYPE, content_type)

    if err.headers:
      for header, value in err.headers.items():
        self.send_header(header, value)

    self.send_header(http.HTTP_CONTENT_LENGTH, str(len(body_bytes)))
    self.send_header(http.HTTP_CONNECTION, "close")
    self.end_headers()

    self.wfile.write(body_bytes)

  # HTTP method handlers
  def do_GET(self):
    """Handle GET request."""
    self.handle_request_inner()

  def do_POST(self):
    """Handle POST request."""
    self.handle_request_inner()

  def do_PUT(self):
    """Handle PUT request."""
    self.handle_request_inner()

  def do_DELETE(self):
    """Handle DELETE request."""
    self.handle_request_inner()

  def log_message(self, format, *args):
    """Override default logging to use Ganeti's logger.

    @type format: str
    @param format: Format string
    @param args: Format arguments

    """
    logging.info("%s - %s", self.address_string(), format % args)

  def finish(self):
    """Finish the request, properly closing SSL connections.

    This overrides BaseHTTPRequestHandler.finish() to ensure SSL
    connections are properly shut down with close_notify before
    closing the underlying socket.

    """
    if isinstance(self.connection, ssl.SSLSocket):
      try:
        if not self.wfile.closed:
          self.wfile.flush()
      except OSError:
        pass

      try:
        self.connection.settimeout(0.1)
        self.connection.unwrap()
      except (OSError, ssl.SSLError) as e:
        logging.debug("SSL unwrap during finish: %s", e)

    try:
      BaseHTTPRequestHandler.finish(self)
    except OSError:
      pass


class HttpServerHandler(object):
  """Base class for handling HTTP server requests.

  Users of this class must subclass it and override the L{HandleRequest}
  function.

  """
  def PreHandleRequest(self, req):
    """Called before handling a request.

    Can be overridden by a subclass.

    @type req: _HttpServerRequest
    @param req: Request object

    """

  def HandleRequest(self, req):
    """Handles a request.

    Must be overridden by subclass.

    @type req: _HttpServerRequest
    @param req: Request object
    @return: Response body as string or bytes

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
