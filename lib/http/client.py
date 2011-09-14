#
#

# Copyright (C) 2007, 2008, 2010 Google Inc.
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

import logging
import pycurl
from cStringIO import StringIO

from ganeti import http
from ganeti import compat
from ganeti import netutils


class HttpClientRequest(object):
  def __init__(self, host, port, method, path, headers=None, post_data=None,
               read_timeout=None, curl_config_fn=None):
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
                           (Note: if the function configures the connection in
                           a way where it wouldn't be efficient to reuse them,
                           a "identity" property should be defined, see
                           L{HttpClientRequest.identity})

    """
    assert path.startswith("/"), "Path must start with slash (/)"
    assert curl_config_fn is None or callable(curl_config_fn)

    # Request attributes
    self.host = host
    self.port = port
    self.method = method
    self.path = path
    self.read_timeout = read_timeout
    self.curl_config_fn = curl_config_fn

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

  @property
  def identity(self):
    """Returns identifier for retrieving a pooled connection for this request.

    This allows cURL client objects to be re-used and to cache information
    (e.g. SSL session IDs or connections).

    """
    parts = [self.host, self.port]

    if self.curl_config_fn:
      try:
        parts.append(self.curl_config_fn.identity)
      except AttributeError:
        pass

    return "/".join(str(i) for i in parts)


class _HttpClient(object):
  def __init__(self, curl_config_fn):
    """Initializes this class.

    @type curl_config_fn: callable
    @param curl_config_fn: Function to configure cURL object after
                           initialization

    """
    self._req = None

    curl = self._CreateCurlHandle()
    curl.setopt(pycurl.VERBOSE, False)
    curl.setopt(pycurl.NOSIGNAL, True)
    curl.setopt(pycurl.USERAGENT, http.HTTP_GANETI_VERSION)
    curl.setopt(pycurl.PROXY, "")

    # Disable SSL session ID caching (pycurl >= 7.16.0)
    if hasattr(pycurl, "SSL_SESSIONID_CACHE"):
      curl.setopt(pycurl.SSL_SESSIONID_CACHE, False)

    # Pass cURL object to external config function
    if curl_config_fn:
      curl_config_fn(curl)

    self._curl = curl

  @staticmethod
  def _CreateCurlHandle():
    """Returns a new cURL object.

    """
    return pycurl.Curl()

  def GetCurlHandle(self):
    """Returns the cURL object.

    """
    return self._curl

  def GetCurrentRequest(self):
    """Returns the current request.

    @rtype: L{HttpClientRequest} or None

    """
    return self._req

  def StartRequest(self, req):
    """Starts a request on this client.

    @type req: L{HttpClientRequest}
    @param req: HTTP request

    """
    assert not self._req, "Another request is already started"

    logging.debug("Starting request %r", req)

    self._req = req
    self._resp_buffer = StringIO()

    url = req.url
    method = req.method
    post_data = req.post_data
    headers = req.headers

    # PycURL requires strings to be non-unicode
    assert isinstance(method, str)
    assert isinstance(url, str)
    assert isinstance(post_data, str)
    assert compat.all(isinstance(i, str) for i in headers)

    # Configure cURL object for request
    curl = self._curl
    curl.setopt(pycurl.CUSTOMREQUEST, str(method))
    curl.setopt(pycurl.URL, url)
    curl.setopt(pycurl.POSTFIELDS, post_data)
    curl.setopt(pycurl.WRITEFUNCTION, self._resp_buffer.write)
    curl.setopt(pycurl.HTTPHEADER, headers)

    if req.read_timeout is None:
      curl.setopt(pycurl.TIMEOUT, 0)
    else:
      curl.setopt(pycurl.TIMEOUT, int(req.read_timeout))

    # Pass cURL object to external config function
    if req.curl_config_fn:
      req.curl_config_fn(curl)

  def Done(self, errmsg):
    """Finishes a request.

    @type errmsg: string or None
    @param errmsg: Error message if request failed

    """
    req = self._req
    assert req, "No request"

    logging.debug("Request %s finished, errmsg=%s", req, errmsg)

    curl = self._curl

    req.success = not bool(errmsg)
    req.error = errmsg

    # Get HTTP response code
    req.resp_status_code = curl.getinfo(pycurl.RESPONSE_CODE)
    req.resp_body = self._resp_buffer.getvalue()

    # Reset client object
    self._req = None
    self._resp_buffer = None

    # Ensure no potentially large variables are referenced
    curl.setopt(pycurl.POSTFIELDS, "")
    curl.setopt(pycurl.WRITEFUNCTION, lambda _: None)


class _PooledHttpClient:
  """Data structure for HTTP client pool.

  """
  def __init__(self, identity, client):
    """Initializes this class.

    @type identity: string
    @param identity: Client identifier for pool
    @type client: L{_HttpClient}
    @param client: HTTP client

    """
    self.identity = identity
    self.client = client
    self.lastused = 0

  def __repr__(self):
    status = ["%s.%s" % (self.__class__.__module__, self.__class__.__name__),
              "id=%s" % self.identity,
              "lastuse=%s" % self.lastused,
              repr(self.client)]

    return "<%s at %#x>" % (" ".join(status), id(self))


class HttpClientPool:
  """A simple HTTP client pool.

  Supports one pooled connection per identity (see
  L{HttpClientRequest.identity}).

  """
  #: After how many generations to drop unused clients
  _MAX_GENERATIONS_DROP = 25

  def __init__(self, curl_config_fn):
    """Initializes this class.

    @type curl_config_fn: callable
    @param curl_config_fn: Function to configure cURL object after
                           initialization

    """
    self._curl_config_fn = curl_config_fn
    self._generation = 0
    self._pool = {}

    # Create custom logger for HTTP client pool. Change logging level to
    # C{logging.NOTSET} to get more details.
    self._logger = logging.getLogger(self.__class__.__name__)
    self._logger.setLevel(logging.INFO)

  @staticmethod
  def _GetHttpClientCreator():
    """Returns callable to create HTTP client.

    """
    return _HttpClient

  def _Get(self, identity):
    """Gets an HTTP client from the pool.

    @type identity: string
    @param identity: Client identifier

    """
    try:
      pclient = self._pool.pop(identity)
    except KeyError:
      # Need to create new client
      client = self._GetHttpClientCreator()(self._curl_config_fn)
      pclient = _PooledHttpClient(identity, client)
      self._logger.debug("Created new client %s", pclient)
    else:
      self._logger.debug("Reusing client %s", pclient)

    assert pclient.identity == identity

    return pclient

  def _StartRequest(self, req):
    """Starts a request.

    @type req: L{HttpClientRequest}
    @param req: HTTP request

    """
    pclient = self._Get(req.identity)

    assert req.identity not in self._pool

    pclient.client.StartRequest(req)
    pclient.lastused = self._generation

    return pclient

  def _Return(self, pclients):
    """Returns HTTP clients to the pool.

    """
    assert not frozenset(pclients) & frozenset(self._pool.values())

    for pc in pclients:
      self._logger.debug("Returning client %s to pool", pc)
      assert pc.identity not in self._pool
      self._pool[pc.identity] = pc

    # Check for unused clients
    for pc in self._pool.values():
      if (pc.lastused + self._MAX_GENERATIONS_DROP) < self._generation:
        self._logger.debug("Removing client %s which hasn't been used"
                           " for %s generations",
                           pc, self._MAX_GENERATIONS_DROP)
        self._pool.pop(pc.identity, None)

    assert compat.all(pc.lastused >= (self._generation -
                                      self._MAX_GENERATIONS_DROP)
                      for pc in self._pool.values())

  @staticmethod
  def _CreateCurlMultiHandle():
    """Creates new cURL multi handle.

    """
    return pycurl.CurlMulti()

  def ProcessRequests(self, requests):
    """Processes any number of HTTP client requests using pooled objects.

    @type requests: list of L{HttpClientRequest}
    @param requests: List of all requests

    """
    multi = self._CreateCurlMultiHandle()

    # For client cleanup
    self._generation += 1

    assert compat.all((req.error is None and
                       req.success is None and
                       req.resp_status_code is None and
                       req.resp_body is None)
                      for req in requests)

    curl_to_pclient = {}
    for req in requests:
      pclient = self._StartRequest(req)
      curl = pclient.client.GetCurlHandle()
      curl_to_pclient[curl] = pclient
      multi.add_handle(curl)
      assert pclient.client.GetCurrentRequest() == req
      assert pclient.lastused >= 0

    assert len(curl_to_pclient) == len(requests)

    done_count = 0
    while True:
      (ret, _) = multi.perform()
      assert ret in (pycurl.E_MULTI_OK, pycurl.E_CALL_MULTI_PERFORM)

      if ret == pycurl.E_CALL_MULTI_PERFORM:
        # cURL wants to be called again
        continue

      while True:
        (remaining_messages, successful, failed) = multi.info_read()

        for curl in successful:
          multi.remove_handle(curl)
          done_count += 1
          pclient = curl_to_pclient[curl]
          req = pclient.client.GetCurrentRequest()
          pclient.client.Done(None)
          assert req.success
          assert not pclient.client.GetCurrentRequest()

        for curl, errnum, errmsg in failed:
          multi.remove_handle(curl)
          done_count += 1
          pclient = curl_to_pclient[curl]
          req = pclient.client.GetCurrentRequest()
          pclient.client.Done("Error %s: %s" % (errnum, errmsg))
          assert req.error
          assert not pclient.client.GetCurrentRequest()

        if remaining_messages == 0:
          break

      assert done_count <= len(requests)

      if done_count == len(requests):
        break

      # Wait for I/O. The I/O timeout shouldn't be too long so that HTTP
      # timeouts, which are only evaluated in multi.perform, aren't
      # unnecessarily delayed.
      multi.select(1.0)

    assert compat.all(pclient.client.GetCurrentRequest() is None
                      for pclient in curl_to_pclient.values())

    # Return clients to pool
    self._Return(curl_to_pclient.values())

    assert done_count == len(requests)
    assert compat.all(req.error is not None or
                      (req.success and
                       req.resp_status_code is not None and
                       req.resp_body is not None)
                      for req in requests)
