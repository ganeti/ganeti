#
#

# Copyright (C) 2010 Google Inc.
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
import simplejson
import socket
import urllib
import threading
import pycurl

try:
  from cStringIO import StringIO
except ImportError:
  from StringIO import StringIO


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

NODE_ROLE_DRAINED = "drained"
NODE_ROLE_MASTER_CANDIATE = "master-candidate"
NODE_ROLE_MASTER = "master"
NODE_ROLE_OFFLINE = "offline"
NODE_ROLE_REGULAR = "regular"

# Internal constants
_REQ_DATA_VERSION_FIELD = "__version__"
_INST_CREATE_REQV1 = "instance-create-reqv1"
_INST_NIC_PARAMS = frozenset(["mac", "ip", "mode", "link", "bridge"])
_INST_CREATE_V0_DISK_PARAMS = frozenset(["size"])
_INST_CREATE_V0_PARAMS = frozenset([
  "os", "pnode", "snode", "iallocator", "start", "ip_check", "name_check",
  "hypervisor", "file_storage_dir", "file_driver", "dry_run",
  ])
_INST_CREATE_V0_DPARAMS = frozenset(["beparams", "hvparams"])

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


class CertificateError(Error):
  """Raised when a problem is found with the SSL certificate.

  """
  pass


class GanetiApiError(Error):
  """Generic error raised from Ganeti API.

  """
  def __init__(self, msg, code=None):
    Error.__init__(self, msg)
    self.code = code


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
    elif lcsslver.startswith("gnutls/"):
      if capath:
        raise Error("cURL linked against GnuTLS has no support for a"
                    " CA path (%s)" % (pycurl.version, ))
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


class GanetiRapiClient(object):
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
    @param query: query arguments to pass to urllib.urlencode
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
      urlparts.append(urllib.urlencode(self._EncodeQuery(query)))

    url = "".join(urlparts)

    self._logger.debug("Sending request %s %s (content=%r)",
                       method, url, encoded_content)

    # Buffer for response
    encoded_resp_body = StringIO()

    # Configure cURL
    curl.setopt(pycurl.CUSTOMREQUEST, str(method))
    curl.setopt(pycurl.URL, str(url))
    curl.setopt(pycurl.POSTFIELDS, str(encoded_content))
    curl.setopt(pycurl.WRITEFUNCTION, encoded_resp_body.write)

    try:
      # Send request and wait for response
      try:
        curl.perform()
      except pycurl.error, err:
        if err.args[0] in _CURL_SSL_CERT_ERRORS:
          raise CertificateError("SSL certificate error %s" % err)

        raise GanetiApiError(str(err))
    finally:
      # Reset settings to not keep references to large objects in memory
      # between requests
      curl.setopt(pycurl.POSTFIELDS, "")
      curl.setopt(pycurl.WRITEFUNCTION, lambda _: None)

    # Get HTTP response code
    http_code = curl.getinfo(pycurl.RESPONSE_CODE)

    # Was anything written to the response buffer?
    if encoded_resp_body.tell():
      response_content = simplejson.loads(encoded_resp_body.getvalue())
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
    except GanetiApiError, err:
      # Older RAPI servers don't support this resource
      if err.code == HTTP_NOT_FOUND:
        return []

      raise

  def GetOperatingSystems(self):
    """Gets the Operating Systems running in the Ganeti cluster.

    @rtype: list of str
    @return: operating systems

    """
    return self._SendRequest(HTTP_GET, "/%s/os" % GANETI_RAPI_VERSION,
                             None, None)

  def GetInfo(self):
    """Gets info about the cluster.

    @rtype: dict
    @return: information about the cluster

    """
    return self._SendRequest(HTTP_GET, "/%s/info" % GANETI_RAPI_VERSION,
                             None, None)

  def GetClusterTags(self):
    """Gets the cluster tags.

    @rtype: list of str
    @return: cluster tags

    """
    return self._SendRequest(HTTP_GET, "/%s/tags" % GANETI_RAPI_VERSION,
                             None, None)

  def AddClusterTags(self, tags, dry_run=False):
    """Adds tags to the cluster.

    @type tags: list of str
    @param tags: tags to add to the cluster
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = [("tag", t) for t in tags]
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_PUT, "/%s/tags" % GANETI_RAPI_VERSION,
                             query, None)

  def DeleteClusterTags(self, tags, dry_run=False):
    """Deletes tags from the cluster.

    @type tags: list of str
    @param tags: tags to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = [("tag", t) for t in tags]
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_DELETE, "/%s/tags" % GANETI_RAPI_VERSION,
                             query, None)

  def GetInstances(self, bulk=False):
    """Gets information about instances on the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about all instances

    @rtype: list of dict or list of str
    @return: if bulk is True, info about the instances, else a list of instances

    """
    query = []
    if bulk:
      query.append(("bulk", 1))

    instances = self._SendRequest(HTTP_GET,
                                  "/%s/instances" % GANETI_RAPI_VERSION,
                                  query, None)
    if bulk:
      return instances
    else:
      return [i["id"] for i in instances]

  def GetInstance(self, instance):
    """Gets information about an instance.

    @type instance: str
    @param instance: instance whose info to return

    @rtype: dict
    @return: info about the instance

    """
    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s" %
                              (GANETI_RAPI_VERSION, instance)), None, None)

  def GetInstanceInfo(self, instance, static=None):
    """Gets information about an instance.

    @type instance: string
    @param instance: Instance name
    @rtype: string
    @return: Job ID

    """
    if static is not None:
      query = [("static", static)]
    else:
      query = None

    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s/info" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def CreateInstance(self, mode, name, disk_template, disks, nics,
                     **kwargs):
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

    @rtype: int
    @return: job id

    """
    query = []

    if kwargs.get("dry_run"):
      query.append(("dry-run", 1))

    if _INST_CREATE_REQV1 in self.GetFeatures():
      # All required fields for request data version 1
      body = {
        _REQ_DATA_VERSION_FIELD: 1,
        "mode": mode,
        "name": name,
        "disk_template": disk_template,
        "disks": disks,
        "nics": nics,
        }

      conflicts = set(kwargs.iterkeys()) & set(body.iterkeys())
      if conflicts:
        raise GanetiApiError("Required fields can not be specified as"
                             " keywords: %s" % ", ".join(conflicts))

      body.update((key, value) for key, value in kwargs.iteritems()
                  if key != "dry_run")
    else:
      # Old request format (version 0)

      # The following code must make sure that an exception is raised when an
      # unsupported setting is requested by the caller. Otherwise this can lead
      # to bugs difficult to find. The interface of this function must stay
      # exactly the same for version 0 and 1 (e.g. they aren't allowed to
      # require different data types).

      # Validate disks
      for idx, disk in enumerate(disks):
        unsupported = set(disk.keys()) - _INST_CREATE_V0_DISK_PARAMS
        if unsupported:
          raise GanetiApiError("Server supports request version 0 only, but"
                               " disk %s specifies the unsupported parameters"
                               " %s, allowed are %s" %
                               (idx, unsupported,
                                list(_INST_CREATE_V0_DISK_PARAMS)))

      assert (len(_INST_CREATE_V0_DISK_PARAMS) == 1 and
              "size" in _INST_CREATE_V0_DISK_PARAMS)
      disk_sizes = [disk["size"] for disk in disks]

      # Validate NICs
      if not nics:
        raise GanetiApiError("Server supports request version 0 only, but"
                             " no NIC specified")
      elif len(nics) > 1:
        raise GanetiApiError("Server supports request version 0 only, but"
                             " more than one NIC specified")

      assert len(nics) == 1

      unsupported = set(nics[0].keys()) - _INST_NIC_PARAMS
      if unsupported:
        raise GanetiApiError("Server supports request version 0 only, but"
                             " NIC 0 specifies the unsupported parameters %s,"
                             " allowed are %s" %
                             (unsupported, list(_INST_NIC_PARAMS)))

      # Validate other parameters
      unsupported = (set(kwargs.keys()) - _INST_CREATE_V0_PARAMS -
                     _INST_CREATE_V0_DPARAMS)
      if unsupported:
        allowed = _INST_CREATE_V0_PARAMS.union(_INST_CREATE_V0_DPARAMS)
        raise GanetiApiError("Server supports request version 0 only, but"
                             " the following unsupported parameters are"
                             " specified: %s, allowed are %s" %
                             (unsupported, list(allowed)))

      # All required fields for request data version 0
      body = {
        _REQ_DATA_VERSION_FIELD: 0,
        "name": name,
        "disk_template": disk_template,
        "disks": disk_sizes,
        }

      # NIC fields
      assert len(nics) == 1
      assert not (set(body.keys()) & set(nics[0].keys()))
      body.update(nics[0])

      # Copy supported fields
      assert not (set(body.keys()) & set(kwargs.keys()))
      body.update(dict((key, value) for key, value in kwargs.items()
                       if key in _INST_CREATE_V0_PARAMS))

      # Merge dictionaries
      for i in (value for key, value in kwargs.items()
                if key in _INST_CREATE_V0_DPARAMS):
        assert not (set(body.keys()) & set(i.keys()))
        body.update(i)

      assert not (set(kwargs.keys()) -
                  (_INST_CREATE_V0_PARAMS | _INST_CREATE_V0_DPARAMS))
      assert not (set(body.keys()) & _INST_CREATE_V0_DPARAMS)

    return self._SendRequest(HTTP_POST, "/%s/instances" % GANETI_RAPI_VERSION,
                             query, body)

  def DeleteInstance(self, instance, dry_run=False):
    """Deletes an instance.

    @type instance: str
    @param instance: the instance to delete

    @rtype: int
    @return: job id

    """
    query = []
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/instances/%s" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ModifyInstance(self, instance, **kwargs):
    """Modifies an instance.

    More details for parameters can be found in the RAPI documentation.

    @type instance: string
    @param instance: Instance name
    @rtype: int
    @return: job id

    """
    body = kwargs

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/modify" %
                              (GANETI_RAPI_VERSION, instance)), None, body)

  def GetInstanceTags(self, instance):
    """Gets tags for an instance.

    @type instance: str
    @param instance: instance whose tags to return

    @rtype: list of str
    @return: tags for the instance

    """
    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s/tags" %
                              (GANETI_RAPI_VERSION, instance)), None, None)

  def AddInstanceTags(self, instance, tags, dry_run=False):
    """Adds tags to an instance.

    @type instance: str
    @param instance: instance to add tags to
    @type tags: list of str
    @param tags: tags to add to the instance
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = [("tag", t) for t in tags]
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/tags" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def DeleteInstanceTags(self, instance, tags, dry_run=False):
    """Deletes tags from an instance.

    @type instance: str
    @param instance: instance to delete tags from
    @type tags: list of str
    @param tags: tags to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = [("tag", t) for t in tags]
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/instances/%s/tags" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def RebootInstance(self, instance, reboot_type=None, ignore_secondaries=None,
                     dry_run=False):
    """Reboots an instance.

    @type instance: str
    @param instance: instance to rebot
    @type reboot_type: str
    @param reboot_type: one of: hard, soft, full
    @type ignore_secondaries: bool
    @param ignore_secondaries: if True, ignores errors for the secondary node
        while re-assembling disks (in hard-reboot mode only)
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = []
    if reboot_type:
      query.append(("type", reboot_type))
    if ignore_secondaries is not None:
      query.append(("ignore_secondaries", ignore_secondaries))
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/reboot" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ShutdownInstance(self, instance, dry_run=False):
    """Shuts down an instance.

    @type instance: str
    @param instance: the instance to shut down
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = []
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/shutdown" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def StartupInstance(self, instance, dry_run=False):
    """Starts up an instance.

    @type instance: str
    @param instance: the instance to start up
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = []
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/startup" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ReinstallInstance(self, instance, os=None, no_startup=False):
    """Reinstalls an instance.

    @type instance: str
    @param instance: The instance to reinstall
    @type os: str or None
    @param os: The operating system to reinstall. If None, the instance's
        current operating system will be installed again
    @type no_startup: bool
    @param no_startup: Whether to start the instance automatically

    """
    query = []
    if os:
      query.append(("os", os))
    if no_startup:
      query.append(("nostartup", 1))
    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/reinstall" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ReplaceInstanceDisks(self, instance, disks=None, mode=REPLACE_DISK_AUTO,
                           remote_node=None, iallocator=None, dry_run=False):
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
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = [
      ("mode", mode),
      ]

    if disks:
      query.append(("disks", ",".join(str(idx) for idx in disks)))

    if remote_node:
      query.append(("remote_node", remote_node))

    if iallocator:
      query.append(("iallocator", iallocator))

    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_POST,
                             ("/%s/instances/%s/replace-disks" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def PrepareExport(self, instance, mode):
    """Prepares an instance for an export.

    @type instance: string
    @param instance: Instance name
    @type mode: string
    @param mode: Export mode
    @rtype: string
    @return: Job ID

    """
    query = [("mode", mode)]
    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/prepare-export" %
                              (GANETI_RAPI_VERSION, instance)), query, None)

  def ExportInstance(self, instance, mode, destination, shutdown=None,
                     remove_instance=None,
                     x509_key_name=None, destination_x509_ca=None):
    """Exports an instance.

    @type instance: string
    @param instance: Instance name
    @type mode: string
    @param mode: Export mode
    @rtype: string
    @return: Job ID

    """
    body = {
      "destination": destination,
      "mode": mode,
      }

    if shutdown is not None:
      body["shutdown"] = shutdown

    if remove_instance is not None:
      body["remove_instance"] = remove_instance

    if x509_key_name is not None:
      body["x509_key_name"] = x509_key_name

    if destination_x509_ca is not None:
      body["destination_x509_ca"] = destination_x509_ca

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/export" %
                              (GANETI_RAPI_VERSION, instance)), None, body)

  def MigrateInstance(self, instance, mode=None, cleanup=None):
    """Migrates an instance.

    @type instance: string
    @param instance: Instance name
    @type mode: string
    @param mode: Migration mode
    @type cleanup: bool
    @param cleanup: Whether to clean up a previously failed migration

    """
    body = {}

    if mode is not None:
      body["mode"] = mode

    if cleanup is not None:
      body["cleanup"] = cleanup

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/migrate" %
                              (GANETI_RAPI_VERSION, instance)), None, body)

  def RenameInstance(self, instance, new_name, ip_check=None, name_check=None):
    """Changes the name of an instance.

    @type instance: string
    @param instance: Instance name
    @type new_name: string
    @param new_name: New instance name
    @type ip_check: bool
    @param ip_check: Whether to ensure instance's IP address is inactive
    @type name_check: bool
    @param name_check: Whether to ensure instance's name is resolvable

    """
    body = {
      "new_name": new_name,
      }

    if ip_check is not None:
      body["ip_check"] = ip_check

    if name_check is not None:
      body["name_check"] = name_check

    return self._SendRequest(HTTP_PUT,
                             ("/%s/instances/%s/rename" %
                              (GANETI_RAPI_VERSION, instance)), None, body)

  def GetJobs(self):
    """Gets all jobs for the cluster.

    @rtype: list of int
    @return: job ids for the cluster

    """
    return [int(j["id"])
            for j in self._SendRequest(HTTP_GET,
                                       "/%s/jobs" % GANETI_RAPI_VERSION,
                                       None, None)]

  def GetJobStatus(self, job_id):
    """Gets the status of a job.

    @type job_id: int
    @param job_id: job id whose status to query

    @rtype: dict
    @return: job status

    """
    return self._SendRequest(HTTP_GET,
                             "/%s/jobs/%s" % (GANETI_RAPI_VERSION, job_id),
                             None, None)

  def WaitForJobChange(self, job_id, fields, prev_job_info, prev_log_serial):
    """Waits for job changes.

    @type job_id: int
    @param job_id: Job ID for which to wait

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

    @type job_id: int
    @param job_id: id of the job to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = []
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_DELETE,
                             "/%s/jobs/%s" % (GANETI_RAPI_VERSION, job_id),
                             query, None)

  def GetNodes(self, bulk=False):
    """Gets all nodes in the cluster.

    @type bulk: bool
    @param bulk: whether to return all information about all instances

    @rtype: list of dict or str
    @return: if bulk is true, info about nodes in the cluster,
        else list of nodes in the cluster

    """
    query = []
    if bulk:
      query.append(("bulk", 1))

    nodes = self._SendRequest(HTTP_GET, "/%s/nodes" % GANETI_RAPI_VERSION,
                              query, None)
    if bulk:
      return nodes
    else:
      return [n["id"] for n in nodes]

  def GetNode(self, node):
    """Gets information about a node.

    @type node: str
    @param node: node whose info to return

    @rtype: dict
    @return: info about the node

    """
    return self._SendRequest(HTTP_GET,
                             "/%s/nodes/%s" % (GANETI_RAPI_VERSION, node),
                             None, None)

  def EvacuateNode(self, node, iallocator=None, remote_node=None,
                   dry_run=False, early_release=False):
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

    @rtype: list
    @return: list of (job ID, instance name, new secondary node); if
        dry_run was specified, then the actual move jobs were not
        submitted and the job IDs will be C{None}

    @raises GanetiApiError: if an iallocator and remote_node are both
        specified

    """
    if iallocator and remote_node:
      raise GanetiApiError("Only one of iallocator or remote_node can be used")

    query = []
    if iallocator:
      query.append(("iallocator", iallocator))
    if remote_node:
      query.append(("remote_node", remote_node))
    if dry_run:
      query.append(("dry-run", 1))
    if early_release:
      query.append(("early_release", 1))

    return self._SendRequest(HTTP_POST,
                             ("/%s/nodes/%s/evacuate" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def MigrateNode(self, node, mode=None, dry_run=False):
    """Migrates all primary instances from a node.

    @type node: str
    @param node: node to migrate
    @type mode: string
    @param mode: if passed, it will overwrite the live migration type,
        otherwise the hypervisor default will be used
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = []
    if mode is not None:
      query.append(("mode", mode))
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_POST,
                             ("/%s/nodes/%s/migrate" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def GetNodeRole(self, node):
    """Gets the current role for a node.

    @type node: str
    @param node: node whose role to return

    @rtype: str
    @return: the current role for a node

    """
    return self._SendRequest(HTTP_GET,
                             ("/%s/nodes/%s/role" %
                              (GANETI_RAPI_VERSION, node)), None, None)

  def SetNodeRole(self, node, role, force=False):
    """Sets the role for a node.

    @type node: str
    @param node: the node whose role to set
    @type role: str
    @param role: the role to set for the node
    @type force: bool
    @param force: whether to force the role change

    @rtype: int
    @return: job id

    """
    query = [
      ("force", force),
      ]

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/role" %
                              (GANETI_RAPI_VERSION, node)), query, role)

  def GetNodeStorageUnits(self, node, storage_type, output_fields):
    """Gets the storage units for a node.

    @type node: str
    @param node: the node whose storage units to return
    @type storage_type: str
    @param storage_type: storage type whose units to return
    @type output_fields: str
    @param output_fields: storage type fields to return

    @rtype: int
    @return: job id where results can be retrieved

    """
    query = [
      ("storage_type", storage_type),
      ("output_fields", output_fields),
      ]

    return self._SendRequest(HTTP_GET,
                             ("/%s/nodes/%s/storage" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def ModifyNodeStorageUnits(self, node, storage_type, name, allocatable=None):
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

    @rtype: int
    @return: job id

    """
    query = [
      ("storage_type", storage_type),
      ("name", name),
      ]

    if allocatable is not None:
      query.append(("allocatable", allocatable))

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/storage/modify" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def RepairNodeStorageUnits(self, node, storage_type, name):
    """Repairs a storage unit on the node.

    @type node: str
    @param node: node whose storage units to repair
    @type storage_type: str
    @param storage_type: storage type to repair
    @type name: str
    @param name: name of the storage unit to repair

    @rtype: int
    @return: job id

    """
    query = [
      ("storage_type", storage_type),
      ("name", name),
      ]

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/storage/repair" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def GetNodeTags(self, node):
    """Gets the tags for a node.

    @type node: str
    @param node: node whose tags to return

    @rtype: list of str
    @return: tags for the node

    """
    return self._SendRequest(HTTP_GET,
                             ("/%s/nodes/%s/tags" %
                              (GANETI_RAPI_VERSION, node)), None, None)

  def AddNodeTags(self, node, tags, dry_run=False):
    """Adds tags to a node.

    @type node: str
    @param node: node to add tags to
    @type tags: list of str
    @param tags: tags to add to the node
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = [("tag", t) for t in tags]
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_PUT,
                             ("/%s/nodes/%s/tags" %
                              (GANETI_RAPI_VERSION, node)), query, tags)

  def DeleteNodeTags(self, node, tags, dry_run=False):
    """Delete tags from a node.

    @type node: str
    @param node: node to remove tags from
    @type tags: list of str
    @param tags: tags to remove from the node
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = [("tag", t) for t in tags]
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_DELETE,
                             ("/%s/nodes/%s/tags" %
                              (GANETI_RAPI_VERSION, node)), query, None)
