#
#

# Copyright (C) 2007, 2008, 2010 Google Inc.
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

"""HTTP client module.

"""

import logging
import threading

from io import BytesIO

import pycurl

from ganeti import http
from ganeti import compat
from ganeti import netutils
from ganeti import locking


class HttpClientRequest(object):
  def __init__(self, host, port, method, path, headers=None, post_data=None,
               read_timeout=None, curl_config_fn=None, nicename=None,
               completion_cb=None):
    """Describes an HTTP request.

    @type host: string
    @param host: Hostname
    @type port: int
    @param port: Port
    @type method: string
    @param method: Method name
    @type path: string
    @param path: Request path
    @type headers: list or None
    @param headers: Additional headers to send, list of strings
    @type post_data: string or None
    @param post_data: Additional data to send
    @type read_timeout: int
    @param read_timeout: if passed, it will be used as the read
        timeout while reading the response from the server
    @type curl_config_fn: callable
    @param curl_config_fn: Function to configure cURL object before request
    @type nicename: string
    @param nicename: Name, presentable to a user, to describe this request (no
                     whitespace)
    @type completion_cb: callable accepting this request object as a single
                         parameter
    @param completion_cb: Callback for request completion

    """
    assert path.startswith("/"), "Path must start with slash (/)"
    assert curl_config_fn is None or callable(curl_config_fn)
    assert completion_cb is None or callable(completion_cb)

    # Request attributes
    self.host = host
    self.port = port
    self.method = method
    self.path = path
    self.read_timeout = read_timeout
    self.curl_config_fn = curl_config_fn
    self.nicename = nicename
    self.completion_cb = completion_cb

    if post_data is None:
      self.post_data = ""
    else:
      self.post_data = post_data

    if headers is None:
      self.headers = []
    elif isinstance(headers, dict):
      # Support for old interface
      self.headers = ["%s: %s" % (name, value)
                      for name, value in headers.items()]
    else:
      self.headers = headers

    # Response status
    self.success = None
    self.error = None

    # Response attributes
    self.resp_status_code = None
    self.resp_body = None

  def __repr__(self):
    status = ["%s.%s" % (self.__class__.__module__, self.__class__.__name__),
              "%s:%s" % (self.host, self.port),
              self.method,
              self.path]

    return "<%s at %#x>" % (" ".join(status), id(self))

  @property
  def url(self):
    """Returns the full URL for this requests.

    """
    if netutils.IPAddress.IsValid(self.host):
      address = netutils.FormatAddress((self.host, self.port))
    else:
      address = "%s:%s" % (self.host, self.port)
    # TODO: Support for non-SSL requests
    return "https://%s%s" % (address, self.path)


def _StartRequest(curl, req):
  """Starts a request on a cURL object.

  @type curl: pycurl.Curl
  @param curl: cURL object
  @type req: L{HttpClientRequest}
  @param req: HTTP request

  """
  logging.debug("Starting request %r", req)

  url = req.url
  method = req.method
  post_data = req.post_data
  headers = req.headers

  # Buffer for response
  resp_buffer = BytesIO()

  # Configure client for request
  curl.setopt(pycurl.VERBOSE, False)
  curl.setopt(pycurl.NOSIGNAL, True)
  curl.setopt(pycurl.USERAGENT, http.HTTP_GANETI_VERSION)
  curl.setopt(pycurl.PROXY, "")
  curl.setopt(pycurl.CUSTOMREQUEST, method)
  curl.setopt(pycurl.URL, url)
  curl.setopt(pycurl.POSTFIELDS, post_data)
  curl.setopt(pycurl.HTTPHEADER, headers)

  if req.read_timeout is None:
    curl.setopt(pycurl.TIMEOUT, 0)
  else:
    curl.setopt(pycurl.TIMEOUT, int(req.read_timeout))

  # Disable SSL session ID caching (pycurl >= 7.16.0)
  if hasattr(pycurl, "SSL_SESSIONID_CACHE"):
    curl.setopt(pycurl.SSL_SESSIONID_CACHE, False)

  curl.setopt(pycurl.WRITEFUNCTION, resp_buffer.write)

  # Pass cURL object to external config function
  if req.curl_config_fn:
    req.curl_config_fn(curl)

  return _PendingRequest(curl, req, resp_buffer.getvalue)


class _PendingRequest(object):
  def __init__(self, curl, req, resp_buffer_read):
    """Initializes this class.

    @type curl: pycurl.Curl
    @param curl: cURL object
    @type req: L{HttpClientRequest}
    @param req: HTTP request
    @type resp_buffer_read: callable
    @param resp_buffer_read: Function to read response body

    """
    assert req.success is None

    self._curl = curl
    self._req = req
    self._resp_buffer_read = resp_buffer_read

  def GetCurlHandle(self):
    """Returns the cURL object.

    """
    return self._curl

  def GetCurrentRequest(self):
    """Returns the current request.

    """
    return self._req

  def Done(self, errmsg):
    """Finishes a request.

    @type errmsg: string or None
    @param errmsg: Error message if request failed

    """
    curl = self._curl
    req = self._req

    assert req.success is None, "Request has already been finalized"

    try:
      # LOCAL_* options added in pycurl 7.21.5
      from_str = "from %s:%s " % (
          curl.getinfo(pycurl.LOCAL_IP),
          curl.getinfo(pycurl.LOCAL_PORT)
      )
    except AttributeError:
      from_str = ""
    logging.debug("Request %s%s finished, errmsg=%s", from_str, req, errmsg)

    req.success = not bool(errmsg)
    req.error = errmsg

    # Get HTTP response code
    req.resp_status_code = curl.getinfo(pycurl.RESPONSE_CODE)
    req.resp_body = self._resp_buffer_read().decode("utf-8")

    # Ensure no potentially large variables are referenced
    curl.setopt(pycurl.POSTFIELDS, "")
    curl.setopt(pycurl.WRITEFUNCTION, lambda _: None)

    if req.completion_cb:
      req.completion_cb(req)


class _NoOpRequestMonitor(object): # pylint: disable=W0232
  """No-op request monitor.

  """
  @staticmethod
  def acquire(*args, **kwargs):
    pass

  release = acquire
  Disable = acquire


class _PendingRequestMonitor(object):
  _LOCK = "_lock"

  def __init__(self, owner, pending_fn):
    """Initializes this class.

    """
    self._owner = owner
    self._pending_fn = pending_fn

    # The lock monitor runs in another thread, hence locking is necessary
    self._lock = locking.SharedLock("PendingHttpRequests")
    self.acquire = self._lock.acquire
    self.release = self._lock.release

  @locking.ssynchronized(_LOCK)
  def Disable(self):
    """Disable monitor.

    """
    self._pending_fn = None

  @locking.ssynchronized(_LOCK, shared=1)
  def GetLockInfo(self, requested): # pylint: disable=W0613
    """Retrieves information about pending requests.

    @type requested: set
    @param requested: Requested information, see C{query.LQ_*}

    """
    # No need to sort here, that's being done by the lock manager and query
    # library. There are no priorities for requests, hence all show up as
    # one item under "pending".
    result = []

    if self._pending_fn:
      owner_name = self._owner.getName()

      for client in self._pending_fn():
        req = client.GetCurrentRequest()
        if req:
          if req.nicename is None:
            name = "%s%s" % (req.host, req.path)
          else:
            name = req.nicename
          result.append(("rpc/%s" % name, None, [owner_name], None))

    return result


def _ProcessCurlRequests(multi, requests):
  """cURL request processor.

  This generator yields a tuple once for every completed request, successful or
  not. The first value in the tuple is the handle, the second an error message
  or C{None} for successful requests.

  @type multi: C{pycurl.CurlMulti}
  @param multi: cURL multi object
  @type requests: sequence
  @param requests: cURL request handles

  """
  for curl in requests:
    multi.add_handle(curl)

  while True:
    (ret, active) = multi.perform()
    assert ret in (pycurl.E_MULTI_OK, pycurl.E_CALL_MULTI_PERFORM)

    if ret == pycurl.E_CALL_MULTI_PERFORM:
      # cURL wants to be called again
      continue

    while True:
      (remaining_messages, successful, failed) = multi.info_read()

      for curl in successful:
        multi.remove_handle(curl)
        yield (curl, None)

      for curl, errnum, errmsg in failed:
        multi.remove_handle(curl)
        yield (curl, "Error %s: %s" % (errnum, errmsg))

      if remaining_messages == 0:
        break

    if active == 0:
      # No active handles anymore
      break

    # Wait for I/O. The I/O timeout shouldn't be too long so that HTTP
    # timeouts, which are only evaluated in multi.perform, aren't
    # unnecessarily delayed.
    multi.select(1.0)


def ProcessRequests(requests, lock_monitor_cb=None, _curl=pycurl.Curl,
                    _curl_multi=pycurl.CurlMulti,
                    _curl_process=_ProcessCurlRequests):
  """Processes any number of HTTP client requests.

  @type requests: list of L{HttpClientRequest}
  @param requests: List of all requests
  @param lock_monitor_cb: Callable for registering with lock monitor

  """
  assert compat.all((req.error is None and
                     req.success is None and
                     req.resp_status_code is None and
                     req.resp_body is None)
                    for req in requests)

  # Prepare all requests
  curl_to_client = \
    dict((client.GetCurlHandle(), client)
         for client in [_StartRequest(_curl(), req) for req in requests])

  assert len(curl_to_client) == len(requests)

  if lock_monitor_cb:
    monitor = _PendingRequestMonitor(threading.currentThread(),
                                     curl_to_client.values)
    lock_monitor_cb(monitor)
  else:
    monitor = _NoOpRequestMonitor

  # Process all requests and act based on the returned values
  for (curl, msg) in _curl_process(_curl_multi(), list(curl_to_client)):
    monitor.acquire(shared=0)
    try:
      curl_to_client.pop(curl).Done(msg)
    finally:
      monitor.release()

  assert not curl_to_client, "Not all requests were processed"

  # Don't try to read information anymore as all requests have been processed
  monitor.Disable()

  assert compat.all(req.error is not None or
                    (req.success and
                     req.resp_status_code is not None and
                     req.resp_body is not None)
                    for req in requests)
