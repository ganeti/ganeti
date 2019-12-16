#
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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


"""Ganeti RAPI client.

@attention: To use the RAPI client, the application B{must} call
            C{pycurl.global_init} during initialization and
            C{pycurl.global_cleanup} before exiting the process. This is very
            important in multi-threaded programs. See curl_global_init(3) and
            curl_global_cleanup(3) for details. The decorator L{UsesRapiClient}
            can be used.

"""

# No Ganeti-specific modules should be imported. The RAPI client is supposed to
# be standalone.

import logging
import socket
import threading
import time

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

import pycurl
import simplejson

from io import StringIO, BytesIO

GANETI_RAPI_PORT = 5080
GANETI_RAPI_VERSION = 2

HTTP_DELETE = "DELETE"
HTTP_GET = "GET"
HTTP_PUT = "PUT"
HTTP_POST = "POST"
HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_APP_JSON = "application/json"

REPLACE_DISK_PRI = "replace_on_primary"
REPLACE_DISK_SECONDARY = "replace_on_secondary"
REPLACE_DISK_CHG = "replace_new_secondary"
REPLACE_DISK_AUTO = "replace_auto"

NODE_EVAC_PRI = "primary-only"
NODE_EVAC_SEC = "secondary-only"
NODE_EVAC_ALL = "all"

NODE_ROLE_DRAINED = "drained"
NODE_ROLE_MASTER_CANDIDATE = "master-candidate"
NODE_ROLE_MASTER = "master"
NODE_ROLE_OFFLINE = "offline"
NODE_ROLE_REGULAR = "regular"

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_WAITING = "waiting"
JOB_STATUS_CANCELING = "canceling"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_CANCELED = "canceled"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_ERROR = "error"
JOB_STATUS_PENDING = frozenset([
  JOB_STATUS_QUEUED,
  JOB_STATUS_WAITING,
  JOB_STATUS_CANCELING,
  ])
JOB_STATUS_FINALIZED = frozenset([
  JOB_STATUS_CANCELED,
  JOB_STATUS_SUCCESS,
  JOB_STATUS_ERROR,
  ])
JOB_STATUS_ALL = frozenset([
  JOB_STATUS_RUNNING,
  ]) | JOB_STATUS_PENDING | JOB_STATUS_FINALIZED

# Legacy name
JOB_STATUS_WAITLOCK = JOB_STATUS_WAITING

# Internal constants
_REQ_DATA_VERSION_FIELD = "__version__"
_QPARAM_DRY_RUN = "dry-run"
_QPARAM_FORCE = "force"

# Feature strings
INST_CREATE_REQV1 = "instance-create-reqv1"
INST_REINSTALL_REQV1 = "instance-reinstall-reqv1"
NODE_MIGRATE_REQV1 = "node-migrate-reqv1"
NODE_EVAC_RES1 = "node-evac-res1"

# Old feature constant names in case they're references by users of this module
_INST_CREATE_REQV1 = INST_CREATE_REQV1
_INST_REINSTALL_REQV1 = INST_REINSTALL_REQV1
_NODE_MIGRATE_REQV1 = NODE_MIGRATE_REQV1
_NODE_EVAC_RES1 = NODE_EVAC_RES1

#: Resolver errors
ECODE_RESOLVER = "resolver_error"

#: Not enough resources (iallocator failure, disk space, memory, etc.)
ECODE_NORES = "insufficient_resources"

#: Temporarily out of resources; operation can be tried again
ECODE_TEMP_NORES = "temp_insufficient_resources"

#: Wrong arguments (at syntax level)
ECODE_INVAL = "wrong_input"

#: Wrong entity state
ECODE_STATE = "wrong_state"

#: Entity not found
ECODE_NOENT = "unknown_entity"

#: Entity already exists
ECODE_EXISTS = "already_exists"

#: Resource not unique (e.g. MAC or IP duplication)
ECODE_NOTUNIQUE = "resource_not_unique"

#: Internal cluster error
ECODE_FAULT = "internal_error"

#: Environment error (e.g. node disk error)
ECODE_ENVIRON = "environment_error"

#: List of all failure types
ECODE_ALL = frozenset([
  ECODE_RESOLVER,
  ECODE_NORES,
  ECODE_TEMP_NORES,
  ECODE_INVAL,
  ECODE_STATE,
  ECODE_NOENT,
  ECODE_EXISTS,
  ECODE_NOTUNIQUE,
  ECODE_FAULT,
  ECODE_ENVIRON,
  ])

# Older pycURL versions don't have all error constants
try:
  _CURLE_SSL_CACERT = pycurl.E_SSL_CACERT
  _CURLE_SSL_CACERT_BADFILE = pycurl.E_SSL_CACERT_BADFILE
except AttributeError:
  _CURLE_SSL_CACERT = 60
  _CURLE_SSL_CACERT_BADFILE = 77

_CURL_SSL_CERT_ERRORS = frozenset([
  _CURLE_SSL_CACERT,
  _CURLE_SSL_CACERT_BADFILE,
  ])


class Error(Exception):
  """Base error class for this module.

  """
  pass


class GanetiApiError(Error):
  """Generic error raised from Ganeti API.

  """
  def __init__(self, msg, code=None):
    Error.__init__(self, msg)
    self.code = code


class CertificateError(GanetiApiError):
  """Raised when a problem is found with the SSL certificate.

  """
  pass


def EpochNano():
  """Return the current timestamp expressed as number of nanoseconds since the
  unix epoch

  @return: nanoseconds since the Unix epoch

  """
  return int(time.time() * 1000000000)


def _AppendIf(container, condition, value):
  """Appends to a list if a condition evaluates to truth.

  """
  if condition:
    container.append(value)

  return condition


def _AppendDryRunIf(container, condition):
  """Appends a "dry-run" parameter if a condition evaluates to truth.

  """
  return _AppendIf(container, condition, (_QPARAM_DRY_RUN, 1))


def _AppendForceIf(container, condition):
  """Appends a "force" parameter if a condition evaluates to truth.

  """
  return _AppendIf(container, condition, (_QPARAM_FORCE, 1))


def _AppendReason(container, reason):
  """Appends an element to the reason trail.

  If the user provided a reason, it is added to the reason trail.

  """
  return _AppendIf(container, reason, ("reason", reason))


def _SetItemIf(container, condition, item, value):
  """Sets an item if a condition evaluates to truth.

  """
  if condition:
    container[item] = value

  return condition


def UsesRapiClient(fn):
  """Decorator for code using RAPI client to initialize pycURL.

  """
  def wrapper(*args, **kwargs):
    # curl_global_init(3) and curl_global_cleanup(3) must be called with only
    # one thread running. This check is just a safety measure -- it doesn't
    # cover all cases.
    assert threading.activeCount() == 1, \
           "Found active threads when initializing pycURL"

    pycurl.global_init(pycurl.GLOBAL_ALL)
    try:
      return fn(*args, **kwargs)
    finally:
      pycurl.global_cleanup()

  return wrapper


def GenericCurlConfig(verbose=False, use_signal=False,
                      use_curl_cabundle=False, cafile=None, capath=None,
                      proxy=None, verify_hostname=False,
                      connect_timeout=None, timeout=None,
                      _pycurl_version_fn=pycurl.version_info):
  """Curl configuration function generator.

  @type verbose: bool
  @param verbose: Whether to set cURL to verbose mode
  @type use_signal: bool
  @param use_signal: Whether to allow cURL to use signals
  @type use_curl_cabundle: bool
  @param use_curl_cabundle: Whether to use cURL's default CA bundle
  @type cafile: string
  @param cafile: In which file we can find the certificates
  @type capath: string
  @param capath: In which directory we can find the certificates
  @type proxy: string
  @param proxy: Proxy to use, None for default behaviour and empty string for
                disabling proxies (see curl_easy_setopt(3))
  @type verify_hostname: bool
  @param verify_hostname: Whether to verify the remote peer certificate's
                          commonName
  @type connect_timeout: number
  @param connect_timeout: Timeout for establishing connection in seconds
  @type timeout: number
  @param timeout: Timeout for complete transfer in seconds (see
                  curl_easy_setopt(3)).

  """
  if use_curl_cabundle and (cafile or capath):
    raise Error("Can not use default CA bundle when CA file or path is set")

  def _ConfigCurl(curl, logger):
    """Configures a cURL object

    @type curl: pycurl.Curl
    @param curl: cURL object

    """
    logger.debug("Using cURL version %s", pycurl.version)

    # pycurl.version_info returns a tuple with information about the used
    # version of libcurl. Item 5 is the SSL library linked to it.
    # e.g.: (3, '7.18.0', 463360, 'x86_64-pc-linux-gnu', 1581, 'GnuTLS/2.0.4',
    # 0, '1.2.3.3', ...)
    sslver = _pycurl_version_fn()[5]
    if not sslver:
      raise Error("No SSL support in cURL")

    lcsslver = sslver.lower()
    if lcsslver.startswith("openssl/"):
      pass
    elif lcsslver.startswith("nss/"):
      # TODO: investigate compatibility beyond a simple test
      pass
    elif lcsslver.startswith("gnutls/"):
      if capath:
        raise Error("cURL linked against GnuTLS has no support for a"
                    " CA path (%s)" % (pycurl.version, ))
    elif lcsslver.startswith("boringssl"):
      pass
    else:
      raise NotImplementedError("cURL uses unsupported SSL version '%s'" %
                                sslver)

    curl.setopt(pycurl.VERBOSE, verbose)
    curl.setopt(pycurl.NOSIGNAL, not use_signal)

    # Whether to verify remote peer's CN
    if verify_hostname:
      # curl_easy_setopt(3): "When CURLOPT_SSL_VERIFYHOST is 2, that
      # certificate must indicate that the server is the server to which you
      # meant to connect, or the connection fails. [...] When the value is 1,
      # the certificate must contain a Common Name field, but it doesn't matter
      # what name it says. [...]"
      curl.setopt(pycurl.SSL_VERIFYHOST, 2)
    else:
      curl.setopt(pycurl.SSL_VERIFYHOST, 0)

    if cafile or capath or use_curl_cabundle:
      # Require certificates to be checked
      curl.setopt(pycurl.SSL_VERIFYPEER, True)
      if cafile:
        curl.setopt(pycurl.CAINFO, str(cafile))
      if capath:
        curl.setopt(pycurl.CAPATH, str(capath))
      # Not changing anything for using default CA bundle
    else:
      # Disable SSL certificate verification
      curl.setopt(pycurl.SSL_VERIFYPEER, False)

    if proxy is not None:
      curl.setopt(pycurl.PROXY, str(proxy))

    # Timeouts
    if connect_timeout is not None:
      curl.setopt(pycurl.CONNECTTIMEOUT, connect_timeout)
    if timeout is not None:
      curl.setopt(pycurl.TIMEOUT, timeout)

  return _ConfigCurl


class _CompatIO(object):
  """ Stream that lazy-allocates its buffer based on the first write's type

  This is a wrapper around BytesIO/StringIO that will allocate the
  respective internal buffer based on whether the first write is bytes or
  not. It is intended to be used with PycURL, which returns the response as
  bytes in Python 3 and string in Python 2.

  """
  def __init__(self):
    self.buffer = None

  def write(self, data, *args, **kwargs):
    if self.buffer is None:
      self.buffer = BytesIO() if isinstance(data, bytes) else StringIO()
    return self.buffer.write(data, *args, **kwargs)

  def read(self, *args, **kwargs):
    return self.buffer.read(*args, **kwargs)

  def tell(self):
    if self.buffer is None:
      # We were never written to
      return 0
    return self.buffer.tell()

  def seek(self, *args, **kwargs):
    return self.buffer.seek(*args, **kwargs)


class GanetiRapiClient(object): # pylint: disable=R0904
  """Ganeti RAPI client.

  """
  USER_AGENT = "Ganeti RAPI Client"
  _json_encoder = simplejson.JSONEncoder(sort_keys=True)

  def __init__(self, host, port=GANETI_RAPI_PORT,
               username=None, password=None, logger=logging,
               curl_config_fn=None, curl_factory=None):
    """Initializes this class.

    @type host: string
    @param host: the ganeti cluster master to interact with
    @type port: int
    @param port: the port on which the RAPI is running (default is 5080)
    @type username: string
    @param username: the username to connect with
    @type password: string
    @param password: the password to connect with
    @type curl_config_fn: callable
    @param curl_config_fn: Function to configure C{pycurl.Curl} object
    @param logger: Logging object

    """
    self._username = username
    self._password = password
    self._logger = logger
    self._curl_config_fn = curl_config_fn
    self._curl_factory = curl_factory

    try:
      socket.inet_pton(socket.AF_INET6, host)
      address = "[%s]:%s" % (host, port)
    except socket.error:
      address = "%s:%s" % (host, port)

    self._base_url = "https://%s" % address

    if username is not None:
      if password is None:
        raise Error("Password not specified")
    elif password:
      raise Error("Specified password without username")

  def _CreateCurl(self):
    """Creates a cURL object.

    """
    # Create pycURL object if no factory is provided
    if self._curl_factory:
      curl = self._curl_factory()
    else:
      curl = pycurl.Curl()

    # Default cURL settings
    curl.setopt(pycurl.VERBOSE, False)
    curl.setopt(pycurl.FOLLOWLOCATION, False)
    curl.setopt(pycurl.MAXREDIRS, 5)
    curl.setopt(pycurl.NOSIGNAL, True)
    curl.setopt(pycurl.USERAGENT, self.USER_AGENT)
    curl.setopt(pycurl.SSL_VERIFYHOST, 0)
    curl.setopt(pycurl.SSL_VERIFYPEER, False)
    curl.setopt(pycurl.HTTPHEADER, [
      "Accept: %s" % HTTP_APP_JSON,
      "Content-type: %s" % HTTP_APP_JSON,
      ])

    assert ((self._username is None and self._password is None) ^
            (self._username is not None and self._password is not None))

    if self._username:
      # Setup authentication
      curl.setopt(pycurl.HTTPAUTH, pycurl.HTTPAUTH_BASIC)
      curl.setopt(pycurl.USERPWD,
                  str("%s:%s" % (self._username, self._password)))

    # Call external configuration function
    if self._curl_config_fn:
      self._curl_config_fn(curl, self._logger)

    return curl

  @staticmethod
  def _EncodeQuery(query):
    """Encode query values for RAPI URL.

    @type query: list of two-tuples
    @param query: Query arguments
    @rtype: list
    @return: Query list with encoded values

    """
    result = []

    for name, value in query:
      if value is None:
        result.append((name, ""))

      elif isinstance(value, bool):
        # Boolean values must be encoded as 0 or 1
        result.append((name, int(value)))

      elif isinstance(value, (list, tuple, dict)):
        raise ValueError("Invalid query data type %r" % type(value).__name__)

      else:
        result.append((name, value))

    return result

  def _SendRequest(self, method, path, query, content):
    """Sends an HTTP request.

    This constructs a full URL, encodes and decodes HTTP bodies, and
    handles invalid responses in a pythonic way.

    @type method: string
    @param method: HTTP method to use
    @type path: string
    @param path: HTTP URL path
    @type query: list of two-tuples
    @param query: query arguments to pass to urlencode
    @type content: str or None
    @param content: HTTP body content

    @rtype: str
    @return: JSON-Decoded response

    @raises CertificateError: If an invalid SSL certificate is found
    @raises GanetiApiError: If an invalid response is returned

    """
    assert path.startswith("/")

    curl = self._CreateCurl()

    if content is not None:
      encoded_content = self._json_encoder.encode(content)
    else:
      encoded_content = ""

    # Build URL
    urlparts = [self._base_url, path]
    if query:
      urlparts.append("?")
      urlparts.append(urlencode(self._EncodeQuery(query)))

    url = "".join(urlparts)

    self._logger.debug("Sending request %s %s (content=%r)",
                       method, url, encoded_content)

    # Buffer for response
    encoded_resp_body = _CompatIO()

    # Configure cURL
    curl.setopt(pycurl.CUSTOMREQUEST, str(method))
    curl.setopt(pycurl.URL, str(url))
    curl.setopt(pycurl.POSTFIELDS, str(encoded_content))
    curl.setopt(pycurl.WRITEFUNCTION, encoded_resp_body.write)

    try:
      # Send request and wait for response
      try:
        curl.perform()
      except pycurl.error as err:
        if err.args[0] in _CURL_SSL_CERT_ERRORS:
          raise CertificateError("SSL certificate error %s" % err,
                                 code=err.args[0])

        raise GanetiApiError(str(err), code=err.args[0])
    finally:
      # Reset settings to not keep references to large objects in memory
      # between requests
      curl.setopt(pycurl.POSTFIELDS, "")
      curl.setopt(pycurl.WRITEFUNCTION, lambda _: None)

    # Get HTTP response code
    http_code = curl.getinfo(pycurl.RESPONSE_CODE)

    # Was anything written to the response buffer?
    if encoded_resp_body.tell():
      encoded_resp_body.seek(0)
      response_content = simplejson.load(encoded_resp_body)
    else:
      response_content = None

    if http_code != HTTP_OK:
      if isinstance(response_content, dict):
        msg = ("%s %s: %s" %
               (response_content["code"],
                response_content["message"],
                response_content["explain"]))
      else:
        msg = str(response_content)

      raise GanetiApiError(msg, code=http_code)

    return response_content

  def GetVersion(self):
    """Gets the Remote API version running on the cluster.

    @rtype: int
    @return: Ganeti Remote API version

    """
    return self._SendRequest(HTTP_GET, "/version", None, None)

  def GetFeatures(self):
    """Gets the list of optional features supported by RAPI server.

    @rtype: list
    @return: List of optional features

    """
    try:
      return self._SendRequest(HTTP_GET, "/%s/features" % GANETI_RAPI_VERSION,
                               None, None)
    except GanetiApiError as err:
      # Older RAPI servers don't support this resource
      if err.code == HTTP_NOT_FOUND:
        return []

      raise

  def GetOperatingSystems(self, reason=None):
    """Gets the Operating Systems running in the Ganeti cluster.

    @rtype: list of str
    @return: operating systems
    @type reason: string
    @param reason: the reason for executing this operation

    """
    query = []
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_GET, "/%s/os" % GANETI_RAPI_VERSION,
                             query, None)

  def GetInfo(self, reason=None):
    """Gets info about the cluster.

    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: dict
    @return: information about the cluster

    """
    query = []
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_GET, "/%s/info" % GANETI_RAPI_VERSION,
                             query, None)

  def RedistributeConfig(self, reason=None):
    """Tells the cluster to redistribute its configuration files.

    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_PUT,
                             "/%s/redistribute-config" % GANETI_RAPI_VERSION,
                             query, None)

  def ModifyCluster(self, reason=None, **kwargs):
    """Modifies cluster parameters.

    More details for parameters can be found in the RAPI documentation.

    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    body = kwargs

    return self._SendRequest(HTTP_PUT,
                             "/%s/modify" % GANETI_RAPI_VERSION, query, body)

  def GetClusterTags(self, reason=None):
    """Gets the cluster tags.

    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: list of str
    @return: cluster tags

    """
    query = []
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_GET, "/%s/tags" % GANETI_RAPI_VERSION,
                             query, None)

  def AddClusterTags(self, tags, dry_run=False, reason=None):
    """Adds tags to the cluster.

    @type tags: list of str
    @param tags: tags to add to the cluster
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT, "/%s/tags" % GANETI_RAPI_VERSION,
                             query, None)

  def DeleteClusterTags(self, tags, dry_run=False, reason=None):
    """Deletes tags from the cluster.

    @type tags: list of str
    @param tags: tags to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE, "/%s/tags" % GANETI_RAPI_VERSION,
                             query, None)

  def GetInstances(self, bulk=False, reason=None):
    """Gets information about instances on the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about all instances
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of dict or list of str
    @return: if bulk is True, info about the instances, else a list of instances

    """
    query = []
    _AppendIf(query, bulk, ("bulk", 1))
    _AppendReason(query, reason)

    instances = self._SendRequest(HTTP_GET,
                                  "/%s/instances" % GANETI_RAPI_VERSION,
                                  query, None)
    if bulk:
      return instances
    else:
      return [i["id"] for i in instances]

  def GetInstance(self, instance, reason=None):
    """Gets information about an instance.

    @type instance: str
    @param instance: instance whose info to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: dict
    @return: info about the instance

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def GetInstanceInfo(self, instance, static=None, reason=None):
    """Gets information about an instance.

    @type instance: string
    @param instance: Instance name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: Job ID

    """
    query = []
    if static is not None:
      query.append(("static", static))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s/info" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  @staticmethod
  def _UpdateWithKwargs(base, **kwargs):
    """Updates the base with params from kwargs.

    @param base: The base dict, filled with required fields

    @note: This is an inplace update of base

    """
    conflicts = set(kwargs.keys()) & set(base.keys())
    if conflicts:
      raise GanetiApiError("Required fields can not be specified as"
                           " keywords: %s" % ", ".join(conflicts))

    base.update((key, value) for key, value in kwargs.items()
                if key != "dry_run")

  def InstanceAllocation(self, mode, name, disk_template, disks, nics,
                         **kwargs):
    """Generates an instance allocation as used by multiallocate.

    More details for parameters can be found in the RAPI documentation.
    It is the same as used by CreateInstance.

    @type mode: string
    @param mode: Instance creation mode
    @type name: string
    @param name: Hostname of the instance to create
    @type disk_template: string
    @param disk_template: Disk template for instance (e.g. plain, diskless,
                          file, or drbd)
    @type disks: list of dicts
    @param disks: List of disk definitions
    @type nics: list of dicts
    @param nics: List of NIC definitions

    @return: A dict with the generated entry

    """
    # All required fields for request data version 1
    alloc = {
      "mode": mode,
      "name": name,
      "disk_template": disk_template,
      "disks": disks,
      "nics": nics,
      }

    self._UpdateWithKwargs(alloc, **kwargs)

    return alloc

  def InstancesMultiAlloc(self, instances, reason=None, **kwargs):
    """Tries to allocate multiple instances.

    More details for parameters can be found in the RAPI documentation.

    @param instances: A list of L{InstanceAllocation} results

    """
    query = []
    body = {
      "instances": instances,
      }
    self._UpdateWithKwargs(body, **kwargs)

    _AppendDryRunIf(query, kwargs.get("dry_run"))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_POST,
                             "/%s/instances-multi-alloc" % GANETI_RAPI_VERSION,
                             query, body)

  def CreateInstance(self, mode, name, disk_template, disks, nics,
                     reason=None, **kwargs):
    """Creates a new instance.

    More details for parameters can be found in the RAPI documentation.

    @type mode: string
    @param mode: Instance creation mode
    @type name: string
    @param name: Hostname of the instance to create
    @type disk_template: string
    @param disk_template: Disk template for instance (e.g. plain, diskless,
                          file, or drbd)
    @type disks: list of dicts
    @param disks: List of disk definitions
    @type nics: list of dicts
    @param nics: List of NIC definitions
    @type dry_run: bool
    @keyword dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []

    _AppendDryRunIf(query, kwargs.get("dry_run"))
    _AppendReason(query, reason)

    if _INST_CREATE_REQV1 in self.GetFeatures():
      body = self.InstanceAllocation(mode, name, disk_template, disks, nics,
                                     **kwargs)
      body[_REQ_DATA_VERSION_FIELD] = 1
    else:
      raise GanetiApiError("Server does not support new-style (version 1)"
                           " instance creation requests")

    return self._SendRequest(HTTP_POST, "/%s/instances" % GANETI_RAPI_VERSION,
                             query, body)

  def DeleteInstance(self, instance, dry_run=False, reason=None, **kwargs):
    """Deletes an instance.

    @type instance: str
    @param instance: the instance to delete
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    body = kwargs

    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/instances/%s" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def ModifyInstance(self, instance, reason=None, **kwargs):
    """Modifies an instance.

    More details for parameters can be found in the RAPI documentation.

    @type instance: string
    @param instance: Instance name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    body = kwargs
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/modify" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def ActivateInstanceDisks(self, instance, ignore_size=None, reason=None):
    """Activates an instance's disks.

    @type instance: string
    @param instance: Instance name
    @type ignore_size: bool
    @param ignore_size: Whether to ignore recorded size
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendIf(query, ignore_size, ("ignore_size", 1))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/activate-disks" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def DeactivateInstanceDisks(self, instance, reason=None, force=False):
    """Deactivates an instance's disks.

    @type instance: string
    @param instance: Instance name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendForceIf(query, force)
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/deactivate-disks" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def RecreateInstanceDisks(self, instance, disks=None, nodes=None,
                            reason=None, iallocator=None):
    """Recreate an instance's disks.

    @type instance: string
    @param instance: Instance name
    @type disks: list of int
    @param disks: List of disk indexes
    @type nodes: list of string
    @param nodes: New instance nodes, if relocation is desired
    @type reason: string
    @param reason: the reason for executing this operation
    @type iallocator: str or None
    @param iallocator: instance allocator plugin to use
    @rtype: string
    @return: job id

    """
    body = {}
    _SetItemIf(body, disks is not None, "disks", disks)
    _SetItemIf(body, nodes is not None, "nodes", nodes)
    _SetItemIf(body, iallocator is not None, "iallocator", iallocator)

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/recreate-disks" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def GrowInstanceDisk(self, instance, disk, amount, wait_for_sync=None,
                       reason=None):
    """Grows a disk of an instance.

    More details for parameters can be found in the RAPI documentation.

    @type instance: string
    @param instance: Instance name
    @type disk: integer
    @param disk: Disk index
    @type amount: integer
    @param amount: Grow disk by this amount (MiB)
    @type wait_for_sync: bool
    @param wait_for_sync: Wait for disk to synchronize
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    body = {
      "amount": amount,
      }

    _SetItemIf(body, wait_for_sync is not None, "wait_for_sync", wait_for_sync)

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/disk/%s/grow" %
                              (GANETI_RAPI_VERSION, instance, disk)),
                             query, body)

  def GetInstanceTags(self, instance, reason=None):
    """Gets tags for an instance.

    @type instance: str
    @param instance: instance whose tags to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of str
    @return: tags for the instance

    """
    query = []
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s/tags" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def AddInstanceTags(self, instance, tags, dry_run=False, reason=None):
    """Adds tags to an instance.

    @type instance: str
    @param instance: instance to add tags to
    @type tags: list of str
    @param tags: tags to add to the instance
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/tags" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def DeleteInstanceTags(self, instance, tags, dry_run=False, reason=None):
    """Deletes tags from an instance.

    @type instance: str
    @param instance: instance to delete tags from
    @type tags: list of str
    @param tags: tags to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/instances/%s/tags" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def RebootInstance(self, instance, reboot_type=None, ignore_secondaries=None,
                     dry_run=False, reason=None, **kwargs):
    """Reboots an instance.

    @type instance: str
    @param instance: instance to reboot
    @type reboot_type: str
    @param reboot_type: one of: hard, soft, full
    @type ignore_secondaries: bool
    @param ignore_secondaries: if True, ignores errors for the secondary node
        while re-assembling disks (in hard-reboot mode only)
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for the reboot
    @rtype: string
    @return: job id

    """
    query = []
    body = kwargs

    _AppendDryRunIf(query, dry_run)
    _AppendIf(query, reboot_type, ("type", reboot_type))
    _AppendIf(query, ignore_secondaries is not None,
              ("ignore_secondaries", ignore_secondaries))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/reboot" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def ShutdownInstance(self, instance, dry_run=False, no_remember=False,
                       reason=None, **kwargs):
    """Shuts down an instance.

    @type instance: str
    @param instance: the instance to shut down
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type no_remember: bool
    @param no_remember: if true, will not record the state change
    @type reason: string
    @param reason: the reason for the shutdown
    @rtype: string
    @return: job id

    """
    query = []
    body = kwargs

    _AppendDryRunIf(query, dry_run)
    _AppendIf(query, no_remember, ("no_remember", 1))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/shutdown" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def StartupInstance(self, instance, dry_run=False, no_remember=False,
                      reason=None):
    """Starts up an instance.

    @type instance: str
    @param instance: the instance to start up
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type no_remember: bool
    @param no_remember: if true, will not record the state change
    @type reason: string
    @param reason: the reason for the startup
    @rtype: string
    @return: job id

    """
    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendIf(query, no_remember, ("no_remember", 1))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/startup" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ReinstallInstance(self, instance, os=None, no_startup=False,
                        osparams=None, reason=None):
    """Reinstalls an instance.

    @type instance: str
    @param instance: The instance to reinstall
    @type os: str or None
    @param os: The operating system to reinstall. If None, the instance's
        current operating system will be installed again
    @type no_startup: bool
    @param no_startup: Whether to start the instance automatically
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    if _INST_REINSTALL_REQV1 in self.GetFeatures():
      body = {
        "start": not no_startup,
        }
      _SetItemIf(body, os is not None, "os", os)
      _SetItemIf(body, osparams is not None, "osparams", osparams)
      return self._SendRequest(HTTP_POST,
                               ("/%s/instances/%s/reinstall" %
                                (GANETI_RAPI_VERSION, instance)), query, body)

    # Use old request format
    if osparams:
      raise GanetiApiError("Server does not support specifying OS parameters"
                           " for instance reinstallation")

    query = []
    _AppendIf(query, os, ("os", os))
    _AppendIf(query, no_startup, ("nostartup", 1))

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/reinstall" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ReplaceInstanceDisks(self, instance, disks=None, mode=REPLACE_DISK_AUTO,
                           remote_node=None, iallocator=None, reason=None,
                           early_release=None):
    """Replaces disks on an instance.

    @type instance: str
    @param instance: instance whose disks to replace
    @type disks: list of ints
    @param disks: Indexes of disks to replace
    @type mode: str
    @param mode: replacement mode to use (defaults to replace_auto)
    @type remote_node: str or None
    @param remote_node: new secondary node to use (for use with
        replace_new_secondary mode)
    @type iallocator: str or None
    @param iallocator: instance allocator plugin to use (for use with
                       replace_auto mode)
    @type reason: string
    @param reason: the reason for executing this operation
    @type early_release: bool
    @param early_release: whether to release locks as soon as possible

    @rtype: string
    @return: job id

    """
    query = [
      ("mode", mode),
      ]

    # TODO: Convert to body parameters

    if disks is not None:
      _AppendIf(query, True,
                ("disks", ",".join(str(idx) for idx in disks)))

    _AppendIf(query, remote_node is not None, ("remote_node", remote_node))
    _AppendIf(query, iallocator is not None, ("iallocator", iallocator))
    _AppendReason(query, reason)
    _AppendIf(query, early_release is not None,
              ("early_release", early_release))

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/replace-disks" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def PrepareExport(self, instance, mode, reason=None):
    """Prepares an instance for an export.

    @type instance: string
    @param instance: Instance name
    @type mode: string
    @param mode: Export mode
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: Job ID

    """
    query = [("mode", mode)]
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/prepare-export" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ExportInstance(self, instance, mode, destination, shutdown=None,
                     remove_instance=None, x509_key_name=None,
                     destination_x509_ca=None, compress=None, reason=None):
    """Exports an instance.

    @type instance: string
    @param instance: Instance name
    @type mode: string
    @param mode: Export mode
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: Job ID

    """
    body = {
      "destination": destination,
      "mode": mode,
      }

    _SetItemIf(body, shutdown is not None, "shutdown", shutdown)
    _SetItemIf(body, remove_instance is not None,
               "remove_instance", remove_instance)
    _SetItemIf(body, x509_key_name is not None, "x509_key_name", x509_key_name)
    _SetItemIf(body, destination_x509_ca is not None,
               "destination_x509_ca", destination_x509_ca)
    _SetItemIf(body, compress is not None, "compress", compress)

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/export" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def MigrateInstance(self, instance, mode=None, cleanup=None,
                      target_node=None, reason=None):
    """Migrates an instance.

    @type instance: string
    @param instance: Instance name
    @type mode: string
    @param mode: Migration mode
    @type cleanup: bool
    @param cleanup: Whether to clean up a previously failed migration
    @type target_node: string
    @param target_node: Target Node for externally mirrored instances
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    body = {}
    _SetItemIf(body, mode is not None, "mode", mode)
    _SetItemIf(body, cleanup is not None, "cleanup", cleanup)
    _SetItemIf(body, target_node is not None, "target_node", target_node)

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/migrate" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def FailoverInstance(self, instance, iallocator=None,
                       ignore_consistency=None, target_node=None, reason=None):
    """Does a failover of an instance.

    @type instance: string
    @param instance: Instance name
    @type iallocator: string
    @param iallocator: Iallocator for deciding the target node for
      shared-storage instances
    @type ignore_consistency: bool
    @param ignore_consistency: Whether to ignore disk consistency
    @type target_node: string
    @param target_node: Target node for shared-storage instances
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    body = {}
    _SetItemIf(body, iallocator is not None, "iallocator", iallocator)
    _SetItemIf(body, ignore_consistency is not None,
               "ignore_consistency", ignore_consistency)
    _SetItemIf(body, target_node is not None, "target_node", target_node)

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/failover" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def RenameInstance(self, instance, new_name, ip_check=None, name_check=None,
                     reason=None):
    """Changes the name of an instance.

    @type instance: string
    @param instance: Instance name
    @type new_name: string
    @param new_name: New instance name
    @type ip_check: bool
    @param ip_check: Whether to ensure instance's IP address is inactive
    @type name_check: bool
    @param name_check: Whether to ensure instance's name is resolvable
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    body = {
      "new_name": new_name,
      }

    _SetItemIf(body, ip_check is not None, "ip_check", ip_check)
    _SetItemIf(body, name_check is not None, "name_check", name_check)

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/rename" %
                              (GANETI_RAPI_VERSION, instance)), query, body)

  def GetInstanceConsole(self, instance, reason=None):
    """Request information for connecting to instance's console.

    @type instance: string
    @param instance: Instance name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: dict
    @return: dictionary containing information about instance's console

    """
    query = []
    _AppendReason(query, reason)
    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s/console" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def GetJobs(self, bulk=False):
    """Gets all jobs for the cluster.

    @type bulk: bool
    @param bulk: Whether to return detailed information about jobs.
    @rtype: list of int
    @return: List of job ids for the cluster or list of dicts with detailed
             information about the jobs if bulk parameter was true.

    """
    query = []
    _AppendIf(query, bulk, ("bulk", 1))

    if bulk:
      return self._SendRequest(HTTP_GET,
                               "/%s/jobs" % GANETI_RAPI_VERSION,
                               query, None)
    else:
      return [int(j["id"])
              for j in self._SendRequest(HTTP_GET,
                                         "/%s/jobs" % GANETI_RAPI_VERSION,
                                         None, None)]

  def GetJobStatus(self, job_id):
    """Gets the status of a job.

    @type job_id: string
    @param job_id: job id whose status to query

    @rtype: dict
    @return: job status

    """
    return self._SendRequest(HTTP_GET,
                             "/%s/jobs/%s" % (GANETI_RAPI_VERSION, job_id),
                             None, None)

  def WaitForJobCompletion(self, job_id, period=5, retries=-1):
    """Polls cluster for job status until completion.

    Completion is defined as any of the following states listed in
    L{JOB_STATUS_FINALIZED}.

    @type job_id: string
    @param job_id: job id to watch
    @type period: int
    @param period: how often to poll for status (optional, default 5s)
    @type retries: int
    @param retries: how many time to poll before giving up
                    (optional, default -1 means unlimited)

    @rtype: bool
    @return: C{True} if job succeeded or C{False} if failed/status timeout
    @deprecated: It is recommended to use L{WaitForJobChange} wherever
      possible; L{WaitForJobChange} returns immediately after a job changed and
      does not use polling

    """
    while retries != 0:
      job_result = self.GetJobStatus(job_id)

      if job_result and job_result["status"] == JOB_STATUS_SUCCESS:
        return True
      elif not job_result or job_result["status"] in JOB_STATUS_FINALIZED:
        return False

      if period:
        time.sleep(period)

      if retries > 0:
        retries -= 1

    return False

  def WaitForJobChange(self, job_id, fields, prev_job_info, prev_log_serial):
    """Waits for job changes.

    @type job_id: string
    @param job_id: Job ID for which to wait
    @return: C{None} if no changes have been detected and a dict with two keys,
      C{job_info} and C{log_entries} otherwise.
    @rtype: dict

    """
    body = {
      "fields": fields,
      "previous_job_info": prev_job_info,
      "previous_log_serial": prev_log_serial,
      }

    return self._SendRequest(HTTP_GET,
                             "/%s/jobs/%s/wait" % (GANETI_RAPI_VERSION, job_id),
                             None, body)

  def CancelJob(self, job_id, dry_run=False):
    """Cancels a job.

    @type job_id: string
    @param job_id: id of the job to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @rtype: tuple
    @return: tuple containing the result, and a message (bool, string)

    """
    query = []
    _AppendDryRunIf(query, dry_run)

    return self._SendRequest(HTTP_DELETE,
                             "/%s/jobs/%s" % (GANETI_RAPI_VERSION, job_id),
                             query, None)

  def GetNodes(self, bulk=False, reason=None):
    """Gets all nodes in the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about all instances
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of dict or str
    @return: if bulk is true, info about nodes in the cluster,
        else list of nodes in the cluster

    """
    query = []
    _AppendIf(query, bulk, ("bulk", 1))
    _AppendReason(query, reason)

    nodes = self._SendRequest(HTTP_GET, "/%s/nodes" % GANETI_RAPI_VERSION,
                              query, None)
    if bulk:
      return nodes
    else:
      return [n["id"] for n in nodes]

  def GetNode(self, node, reason=None):
    """Gets information about a node.

    @type node: str
    @param node: node whose info to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: dict
    @return: info about the node

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             "/%s/nodes/%s" % (GANETI_RAPI_VERSION, node),
                             query, None)

  def EvacuateNode(self, node, iallocator=None, remote_node=None,
                   dry_run=False, early_release=None,
                   mode=None, accept_old=False, reason=None):
    """Evacuates instances from a Ganeti node.

    @type node: str
    @param node: node to evacuate
    @type iallocator: str or None
    @param iallocator: instance allocator to use
    @type remote_node: str
    @param remote_node: node to evaucate to
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type early_release: bool
    @param early_release: whether to enable parallelization
    @type mode: string
    @param mode: Node evacuation mode
    @type accept_old: bool
    @param accept_old: Whether caller is ready to accept old-style (pre-2.5)
        results
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string, or a list for pre-2.5 results
    @return: Job ID or, if C{accept_old} is set and server is pre-2.5,
      list of (job ID, instance name, new secondary node); if dry_run was
      specified, then the actual move jobs were not submitted and the job IDs
      will be C{None}

    @raises GanetiApiError: if an iallocator and remote_node are both
        specified

    """
    if iallocator and remote_node:
      raise GanetiApiError("Only one of iallocator or remote_node can be used")

    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    if _NODE_EVAC_RES1 in self.GetFeatures():
      # Server supports body parameters
      body = {}

      _SetItemIf(body, iallocator is not None, "iallocator", iallocator)
      _SetItemIf(body, remote_node is not None, "remote_node", remote_node)
      _SetItemIf(body, early_release is not None,
                 "early_release", early_release)
      _SetItemIf(body, mode is not None, "mode", mode)
    else:
      # Pre-2.5 request format
      body = None

      if not accept_old:
        raise GanetiApiError("Server is version 2.4 or earlier and caller does"
                             " not accept old-style results (parameter"
                             " accept_old)")

      # Pre-2.5 servers can only evacuate secondaries
      if mode is not None and mode != NODE_EVAC_SEC:
        raise GanetiApiError("Server can only evacuate secondary instances")

      _AppendIf(query, iallocator, ("iallocator", iallocator))
      _AppendIf(query, remote_node, ("remote_node", remote_node))
      _AppendIf(query, early_release, ("early_release", 1))

    return self._SendRequest(HTTP_POST,
                             ("/%s/nodes/%s/evacuate" %
                              (GANETI_RAPI_VERSION, node)), query, body)

  def MigrateNode(self, node, mode=None, dry_run=False, iallocator=None,
                  target_node=None, reason=None):
    """Migrates all primary instances from a node.

    @type node: str
    @param node: node to migrate
    @type mode: string
    @param mode: if passed, it will overwrite the live migration type,
        otherwise the hypervisor default will be used
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type iallocator: string
    @param iallocator: instance allocator to use
    @type target_node: string
    @param target_node: Target node for shared-storage instances
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    if _NODE_MIGRATE_REQV1 in self.GetFeatures():
      body = {}

      _SetItemIf(body, mode is not None, "mode", mode)
      _SetItemIf(body, iallocator is not None, "iallocator", iallocator)
      _SetItemIf(body, target_node is not None, "target_node", target_node)

      assert len(query) <= 1

      return self._SendRequest(HTTP_POST,
                               ("/%s/nodes/%s/migrate" %
                                (GANETI_RAPI_VERSION, node)), query, body)
    else:
      # Use old request format
      if target_node is not None:
        raise GanetiApiError("Server does not support specifying target node"
                             " for node migration")

      _AppendIf(query, mode is not None, ("mode", mode))

      return self._SendRequest(HTTP_POST,
                               ("/%s/nodes/%s/migrate" %
                                (GANETI_RAPI_VERSION, node)), query, None)

  def GetNodeRole(self, node, reason=None):
    """Gets the current role for a node.

    @type node: str
    @param node: node whose role to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: str
    @return: the current role for a node

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/nodes/%s/role" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def SetNodeRole(self, node, role, force=False, auto_promote=None,
                  reason=None):
    """Sets the role for a node.

    @type node: str
    @param node: the node whose role to set
    @type role: str
    @param role: the role to set for the node
    @type force: bool
    @param force: whether to force the role change
    @type auto_promote: bool
    @param auto_promote: Whether node(s) should be promoted to master candidate
                         if necessary
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendForceIf(query, force)
    _AppendIf(query, auto_promote is not None, ("auto-promote", auto_promote))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/role" %
                              (GANETI_RAPI_VERSION, node)), query, role)

  def PowercycleNode(self, node, force=False, reason=None):
    """Powercycles a node.

    @type node: string
    @param node: Node name
    @type force: bool
    @param force: Whether to force the operation
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendForceIf(query, force)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_POST,
                             ("/%s/nodes/%s/powercycle" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def ModifyNode(self, node, reason=None, **kwargs):
    """Modifies a node.

    More details for parameters can be found in the RAPI documentation.

    @type node: string
    @param node: Node name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_POST,
                             ("/%s/nodes/%s/modify" %
                              (GANETI_RAPI_VERSION, node)), query, kwargs)

  def GetNodeStorageUnits(self, node, storage_type, output_fields, reason=None):
    """Gets the storage units for a node.

    @type node: str
    @param node: the node whose storage units to return
    @type storage_type: str
    @param storage_type: storage type whose units to return
    @type output_fields: str
    @param output_fields: storage type fields to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id where results can be retrieved

    """
    query = [
      ("storage_type", storage_type),
      ("output_fields", output_fields),
      ]
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/nodes/%s/storage" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def ModifyNodeStorageUnits(self, node, storage_type, name, allocatable=None,
                             reason=None):
    """Modifies parameters of storage units on the node.

    @type node: str
    @param node: node whose storage units to modify
    @type storage_type: str
    @param storage_type: storage type whose units to modify
    @type name: str
    @param name: name of the storage unit
    @type allocatable: bool or None
    @param allocatable: Whether to set the "allocatable" flag on the storage
                        unit (None=no modification, True=set, False=unset)
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [
      ("storage_type", storage_type),
      ("name", name),
      ]

    _AppendIf(query, allocatable is not None, ("allocatable", allocatable))
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/storage/modify" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def RepairNodeStorageUnits(self, node, storage_type, name, reason=None):
    """Repairs a storage unit on the node.

    @type node: str
    @param node: node whose storage units to repair
    @type storage_type: str
    @param storage_type: storage type to repair
    @type name: str
    @param name: name of the storage unit to repair
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [
      ("storage_type", storage_type),
      ("name", name),
      ]
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/storage/repair" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def GetNodeTags(self, node, reason=None):
    """Gets the tags for a node.

    @type node: str
    @param node: node whose tags to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of str
    @return: tags for the node

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/nodes/%s/tags" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def AddNodeTags(self, node, tags, dry_run=False, reason=None):
    """Adds tags to a node.

    @type node: str
    @param node: node to add tags to
    @type tags: list of str
    @param tags: tags to add to the node
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/tags" %
                              (GANETI_RAPI_VERSION, node)), query, tags)

  def DeleteNodeTags(self, node, tags, dry_run=False, reason=None):
    """Delete tags from a node.

    @type node: str
    @param node: node to remove tags from
    @type tags: list of str
    @param tags: tags to remove from the node
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/nodes/%s/tags" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def GetNetworks(self, bulk=False, reason=None):
    """Gets all networks in the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about the networks

    @rtype: list of dict or str
    @return: if bulk is true, a list of dictionaries with info about all
        networks in the cluster, else a list of names of those networks

    """
    query = []
    _AppendIf(query, bulk, ("bulk", 1))
    _AppendReason(query, reason)

    networks = self._SendRequest(HTTP_GET, "/%s/networks" % GANETI_RAPI_VERSION,
                                 query, None)
    if bulk:
      return networks
    else:
      return [n["name"] for n in networks]

  def GetNetwork(self, network, reason=None):
    """Gets information about a network.

    @type network: str
    @param network: name of the network whose info to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: dict
    @return: info about the network

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             "/%s/networks/%s" % (GANETI_RAPI_VERSION, network),
                             query, None)

  def CreateNetwork(self, network_name, network, gateway=None, network6=None,
                    gateway6=None, mac_prefix=None,
                    add_reserved_ips=None, tags=None, dry_run=False,
                    reason=None):
    """Creates a new network.

    @type network_name: str
    @param network_name: the name of network to create
    @type dry_run: bool
    @param dry_run: whether to peform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    if add_reserved_ips:
      add_reserved_ips = add_reserved_ips.split(",")

    if tags:
      tags = tags.split(",")

    body = {
      "network_name": network_name,
      "gateway": gateway,
      "network": network,
      "gateway6": gateway6,
      "network6": network6,
      "mac_prefix": mac_prefix,
      "add_reserved_ips": add_reserved_ips,
      "tags": tags,
      }

    return self._SendRequest(HTTP_POST, "/%s/networks" % GANETI_RAPI_VERSION,
                             query, body)

  def ConnectNetwork(self, network_name, group_name, mode, link,
                     vlan="", dry_run=False, reason=None):
    """Connects a Network to a NodeGroup with the given netparams

    """
    body = {
      "group_name": group_name,
      "network_mode": mode,
      "network_link": link,
      "network_vlan": vlan,
      }

    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/networks/%s/connect" %
                             (GANETI_RAPI_VERSION, network_name)), query, body)

  def DisconnectNetwork(self, network_name, group_name, dry_run=False,
                        reason=None):
    """Connects a Network to a NodeGroup with the given netparams

    """
    body = {
      "group_name": group_name,
      }

    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/networks/%s/disconnect" %
                             (GANETI_RAPI_VERSION, network_name)), query, body)

  def ModifyNetwork(self, network, reason=None, **kwargs):
    """Modifies a network.

    More details for parameters can be found in the RAPI documentation.

    @type network: string
    @param network: Network name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/networks/%s/modify" %
                              (GANETI_RAPI_VERSION, network)), None, kwargs)

  def DeleteNetwork(self, network, dry_run=False, reason=None):
    """Deletes a network.

    @type network: str
    @param network: the network to delete
    @type dry_run: bool
    @param dry_run: whether to peform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/networks/%s" %
                              (GANETI_RAPI_VERSION, network)), query, None)

  def GetNetworkTags(self, network, reason=None):
    """Gets tags for a network.

    @type network: string
    @param network: Node group whose tags to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of strings
    @return: tags for the network

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/networks/%s/tags" %
                              (GANETI_RAPI_VERSION, network)), query, None)

  def AddNetworkTags(self, network, tags, dry_run=False, reason=None):
    """Adds tags to a network.

    @type network: str
    @param network: network to add tags to
    @type tags: list of string
    @param tags: tags to add to the network
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/networks/%s/tags" %
                              (GANETI_RAPI_VERSION, network)), query, None)

  def DeleteNetworkTags(self, network, tags, dry_run=False, reason=None):
    """Deletes tags from a network.

    @type network: str
    @param network: network to delete tags from
    @type tags: list of string
    @param tags: tags to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/networks/%s/tags" %
                              (GANETI_RAPI_VERSION, network)), query, None)

  def GetGroups(self, bulk=False, reason=None):
    """Gets all node groups in the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about the groups
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of dict or str
    @return: if bulk is true, a list of dictionaries with info about all node
        groups in the cluster, else a list of names of those node groups

    """
    query = []
    _AppendIf(query, bulk, ("bulk", 1))
    _AppendReason(query, reason)

    groups = self._SendRequest(HTTP_GET, "/%s/groups" % GANETI_RAPI_VERSION,
                               query, None)
    if bulk:
      return groups
    else:
      return [g["name"] for g in groups]

  def GetGroup(self, group, reason=None):
    """Gets information about a node group.

    @type group: str
    @param group: name of the node group whose info to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: dict
    @return: info about the node group

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             "/%s/groups/%s" % (GANETI_RAPI_VERSION, group),
                             query, None)

  def CreateGroup(self, name, alloc_policy=None, dry_run=False, reason=None):
    """Creates a new node group.

    @type name: str
    @param name: the name of node group to create
    @type alloc_policy: str
    @param alloc_policy: the desired allocation policy for the group, if any
    @type dry_run: bool
    @param dry_run: whether to peform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    body = {
      "name": name,
      "alloc_policy": alloc_policy,
      }

    return self._SendRequest(HTTP_POST, "/%s/groups" % GANETI_RAPI_VERSION,
                             query, body)

  def ModifyGroup(self, group, reason=None, **kwargs):
    """Modifies a node group.

    More details for parameters can be found in the RAPI documentation.

    @type group: string
    @param group: Node group name
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/groups/%s/modify" %
                              (GANETI_RAPI_VERSION, group)), query, kwargs)

  def DeleteGroup(self, group, dry_run=False, reason=None):
    """Deletes a node group.

    @type group: str
    @param group: the node group to delete
    @type dry_run: bool
    @param dry_run: whether to peform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/groups/%s" %
                              (GANETI_RAPI_VERSION, group)), query, None)

  def RenameGroup(self, group, new_name, reason=None):
    """Changes the name of a node group.

    @type group: string
    @param group: Node group name
    @type new_name: string
    @param new_name: New node group name
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    body = {
      "new_name": new_name,
      }

    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/groups/%s/rename" %
                              (GANETI_RAPI_VERSION, group)), query, body)

  def AssignGroupNodes(self, group, nodes, force=False, dry_run=False,
                       reason=None):
    """Assigns nodes to a group.

    @type group: string
    @param group: Node group name
    @type nodes: list of strings
    @param nodes: List of nodes to assign to the group
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendForceIf(query, force)
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    body = {
      "nodes": nodes,
      }

    return self._SendRequest(HTTP_PUT,
                             ("/%s/groups/%s/assign-nodes" %
                             (GANETI_RAPI_VERSION, group)), query, body)

  def GetGroupTags(self, group, reason=None):
    """Gets tags for a node group.

    @type group: string
    @param group: Node group whose tags to return
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: list of strings
    @return: tags for the group

    """
    query = []
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_GET,
                             ("/%s/groups/%s/tags" %
                              (GANETI_RAPI_VERSION, group)), query, None)

  def AddGroupTags(self, group, tags, dry_run=False, reason=None):
    """Adds tags to a node group.

    @type group: str
    @param group: group to add tags to
    @type tags: list of string
    @param tags: tags to add to the group
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/groups/%s/tags" %
                              (GANETI_RAPI_VERSION, group)), query, None)

  def DeleteGroupTags(self, group, tags, dry_run=False, reason=None):
    """Deletes tags from a node group.

    @type group: str
    @param group: group to delete tags from
    @type tags: list of string
    @param tags: tags to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run
    @type reason: string
    @param reason: the reason for executing this operation
    @rtype: string
    @return: job id

    """
    query = [("tag", t) for t in tags]
    _AppendDryRunIf(query, dry_run)
    _AppendReason(query, reason)

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/groups/%s/tags" %
                              (GANETI_RAPI_VERSION, group)), query, None)

  def Query(self, what, fields, qfilter=None, reason=None):
    """Retrieves information about resources.

    @type what: string
    @param what: Resource name, one of L{constants.QR_VIA_RAPI}
    @type fields: list of string
    @param fields: Requested fields
    @type qfilter: None or list
    @param qfilter: Query filter
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    body = {
      "fields": fields,
      }

    _SetItemIf(body, qfilter is not None, "qfilter", qfilter)
    # TODO: remove "filter" after 2.7
    _SetItemIf(body, qfilter is not None, "filter", qfilter)

    return self._SendRequest(HTTP_PUT,
                             ("/%s/query/%s" %
                              (GANETI_RAPI_VERSION, what)), query, body)

  def QueryFields(self, what, fields=None, reason=None):
    """Retrieves available fields for a resource.

    @type what: string
    @param what: Resource name, one of L{constants.QR_VIA_RAPI}
    @type fields: list of string
    @param fields: Requested fields
    @type reason: string
    @param reason: the reason for executing this operation

    @rtype: string
    @return: job id

    """
    query = []
    _AppendReason(query, reason)

    if fields is not None:
      _AppendIf(query, True, ("fields", ",".join(fields)))

    return self._SendRequest(HTTP_GET,
                             ("/%s/query/%s/fields" %
                              (GANETI_RAPI_VERSION, what)), query, None)

  def GetFilters(self, bulk=False):
    """Gets all filter rules in the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about the networks

    @rtype: list of dict or str
    @return: if bulk is true, a list of dictionaries with info about all
             filter rules in the cluster, else a list of UUIDs of those
             filters

    """
    query = []
    _AppendIf(query, bulk, ("bulk", 1))

    filters = self._SendRequest(HTTP_GET, "/%s/filters" % GANETI_RAPI_VERSION,
                                query, None)
    if bulk:
      return filters
    else:
      return [f["uuid"] for f in filters]

  def GetFilter(self, filter_uuid):
    """Gets information about a filter rule.

    @type filter_uuid: str
    @param filter_uuid: UUID of the filter whose info to return

    @rtype: dict
    @return: info about the filter

    """
    query = []

    return self._SendRequest(HTTP_GET,
                             "/%s/filters/%s" % (GANETI_RAPI_VERSION,
                                                 filter_uuid),
                             query, None)

  def AddFilter(self, priority, predicates, action, reason_trail=None):
    """Adds a filter rule

    @type reason_trail: list of (str, str, int) triples
    @param reason_trail: the reason trail for executing this operation,
                         or None

    @rtype: string
    @return: filter UUID of the added filter

    """
    if reason_trail is None:
      reason_trail = []

    assert isinstance(reason_trail, list)

    reason_trail.append(("gnt:client", "", EpochNano(),))  # add client reason

    body = {
      "priority": priority,
      "predicates": predicates,
      "action": action,
      "reason": reason_trail,
      }

    query = []

    return self._SendRequest(HTTP_POST,
                             ("/%s/filters" % (GANETI_RAPI_VERSION)),
                             query, body)

  def ReplaceFilter(self, uuid, priority, predicates, action,
                    reason_trail=None):
    """Replaces a filter rule, or creates one if it doesn't already exist

    @type reason_trail: list of (str, str, int) triples
    @param reason_trail: the reason trail for executing this operation,
                         or None

    @rtype: string
    @return: filter UUID of the replaced/added filter

    """
    if reason_trail is None:
      reason_trail = []

    assert isinstance(reason_trail, list)

    reason_trail.append(("gnt:client", "", EpochNano(),))  # add client reason

    body = {
      "priority": priority,
      "predicates": predicates,
      "action": action,
      "reason": reason_trail,
      }

    query = []

    return self._SendRequest(HTTP_PUT,
                             ("/%s/filters/%s" % (GANETI_RAPI_VERSION, uuid)),
                             query, body)

  def DeleteFilter(self, uuid):
    """Deletes a filter rule

    @return: None

    """
    body = {}
    query = []

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/filters/%s" % (GANETI_RAPI_VERSION, uuid)),
                             query, body)
