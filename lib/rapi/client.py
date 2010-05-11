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


"""Ganeti RAPI client."""

import httplib
import urllib2
import logging
import simplejson
import socket
import urllib
import OpenSSL
import distutils.version


GANETI_RAPI_PORT = 5080
GANETI_RAPI_VERSION = 2

HTTP_DELETE = "DELETE"
HTTP_GET = "GET"
HTTP_PUT = "PUT"
HTTP_POST = "POST"
HTTP_OK = 200
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


def FormatX509Name(x509_name):
  """Formats an X509 name.

  @type x509_name: OpenSSL.crypto.X509Name

  """
  try:
    # Only supported in pyOpenSSL 0.7 and above
    get_components_fn = x509_name.get_components
  except AttributeError:
    return repr(x509_name)
  else:
    return "".join("/%s=%s" % (name, value)
                   for name, value in get_components_fn())


class CertAuthorityVerify:
  """Certificate verificator for SSL context.

  Configures SSL context to verify server's certificate.

  """
  _CAPATH_MINVERSION = "0.9"
  _DEFVFYPATHS_MINVERSION = "0.9"

  _PYOPENSSL_VERSION = OpenSSL.__version__
  _PARSED_PYOPENSSL_VERSION = distutils.version.LooseVersion(_PYOPENSSL_VERSION)

  _SUPPORT_CAPATH = (_PARSED_PYOPENSSL_VERSION >= _CAPATH_MINVERSION)
  _SUPPORT_DEFVFYPATHS = (_PARSED_PYOPENSSL_VERSION >= _DEFVFYPATHS_MINVERSION)

  def __init__(self, cafile=None, capath=None, use_default_verify_paths=False):
    """Initializes this class.

    @type cafile: string
    @param cafile: In which file we can find the certificates
    @type capath: string
    @param capath: In which directory we can find the certificates
    @type use_default_verify_paths: bool
    @param use_default_verify_paths: Whether the platform provided CA
                                     certificates are to be used for
                                     verification purposes

    """
    self._cafile = cafile
    self._capath = capath
    self._use_default_verify_paths = use_default_verify_paths

    if self._capath is not None and not self._SUPPORT_CAPATH:
      raise Error(("PyOpenSSL %s has no support for a CA directory,"
                   " version %s or above is required") %
                  (self._PYOPENSSL_VERSION, self._CAPATH_MINVERSION))

    if self._use_default_verify_paths and not self._SUPPORT_DEFVFYPATHS:
      raise Error(("PyOpenSSL %s has no support for using default verification"
                   " paths, version %s or above is required") %
                  (self._PYOPENSSL_VERSION, self._DEFVFYPATHS_MINVERSION))

  @staticmethod
  def _VerifySslCertCb(logger, _, cert, errnum, errdepth, ok):
    """Callback for SSL certificate verification.

    @param logger: Logging object

    """
    if ok:
      log_fn = logger.debug
    else:
      log_fn = logger.error

    log_fn("Verifying SSL certificate at depth %s, subject '%s', issuer '%s'",
           errdepth, FormatX509Name(cert.get_subject()),
           FormatX509Name(cert.get_issuer()))

    if not ok:
      try:
        # Only supported in pyOpenSSL 0.7 and above
        # pylint: disable-msg=E1101
        fn = OpenSSL.crypto.X509_verify_cert_error_string
      except AttributeError:
        errmsg = ""
      else:
        errmsg = ":%s" % fn(errnum)

      logger.error("verify error:num=%s%s", errnum, errmsg)

    return ok

  def __call__(self, ctx, logger):
    """Configures an SSL context to verify certificates.

    @type ctx: OpenSSL.SSL.Context
    @param ctx: SSL context

    """
    if self._use_default_verify_paths:
      ctx.set_default_verify_paths()

    if self._cafile or self._capath:
      if self._SUPPORT_CAPATH:
        ctx.load_verify_locations(self._cafile, self._capath)
      else:
        ctx.load_verify_locations(self._cafile)

    ctx.set_verify(OpenSSL.SSL.VERIFY_PEER,
                   lambda conn, cert, errnum, errdepth, ok: \
                     self._VerifySslCertCb(logger, conn, cert,
                                           errnum, errdepth, ok))


class _HTTPSConnectionOpenSSL(httplib.HTTPSConnection):
  """HTTPS Connection handler that verifies the SSL certificate.

  """
  def __init__(self, *args, **kwargs):
    """Initializes this class.

    """
    httplib.HTTPSConnection.__init__(self, *args, **kwargs)
    self._logger = None
    self._config_ssl_verification = None

  def Setup(self, logger, config_ssl_verification):
    """Sets the SSL verification config function.

    @param logger: Logging object
    @type config_ssl_verification: callable

    """
    assert self._logger is None
    assert self._config_ssl_verification is None

    self._logger = logger
    self._config_ssl_verification = config_ssl_verification

  def connect(self):
    """Connect to the server specified when the object was created.

    This ensures that SSL certificates are verified.

    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    ctx = OpenSSL.SSL.Context(OpenSSL.SSL.TLSv1_METHOD)
    ctx.set_options(OpenSSL.SSL.OP_NO_SSLv2)

    if self._config_ssl_verification:
      self._config_ssl_verification(ctx, self._logger)

    ssl = OpenSSL.SSL.Connection(ctx, sock)
    ssl.connect((self.host, self.port))

    self.sock = httplib.FakeSocket(sock, ssl)


class _HTTPSHandler(urllib2.HTTPSHandler):
  def __init__(self, logger, config_ssl_verification):
    """Initializes this class.

    @param logger: Logging object
    @type config_ssl_verification: callable
    @param config_ssl_verification: Function to configure SSL context for
                                    certificate verification

    """
    urllib2.HTTPSHandler.__init__(self)
    self._logger = logger
    self._config_ssl_verification = config_ssl_verification

  def _CreateHttpsConnection(self, *args, **kwargs):
    """Wrapper around L{_HTTPSConnectionOpenSSL} to add SSL verification.

    This wrapper is necessary provide a compatible API to urllib2.

    """
    conn = _HTTPSConnectionOpenSSL(*args, **kwargs)
    conn.Setup(self._logger, self._config_ssl_verification)
    return conn

  def https_open(self, req):
    """Creates HTTPS connection.

    Called by urllib2.

    """
    return self.do_open(self._CreateHttpsConnection, req)


class _RapiRequest(urllib2.Request):
  def __init__(self, method, url, headers, data):
    """Initializes this class.

    """
    urllib2.Request.__init__(self, url, data=data, headers=headers)
    self._method = method

  def get_method(self):
    """Returns the HTTP request method.

    """
    return self._method


class GanetiRapiClient(object):
  """Ganeti RAPI client.

  """
  USER_AGENT = "Ganeti RAPI Client"
  _json_encoder = simplejson.JSONEncoder(sort_keys=True)

  def __init__(self, host, port=GANETI_RAPI_PORT,
               username=None, password=None,
               config_ssl_verification=None, ignore_proxy=False,
               logger=logging):
    """Constructor.

    @type host: string
    @param host: the ganeti cluster master to interact with
    @type port: int
    @param port: the port on which the RAPI is running (default is 5080)
    @type username: string
    @param username: the username to connect with
    @type password: string
    @param password: the password to connect with
    @type config_ssl_verification: callable
    @param config_ssl_verification: Function to configure SSL context for
                                    certificate verification
    @type ignore_proxy: bool
    @param ignore_proxy: Whether to ignore proxy settings
    @param logger: Logging object

    """
    self._host = host
    self._port = port
    self._logger = logger

    self._base_url = "https://%s:%s" % (host, port)

    handlers = [_HTTPSHandler(self._logger, config_ssl_verification)]

    if username is not None:
      pwmgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
      pwmgr.add_password(None, self._base_url, username, password)
      handlers.append(urllib2.HTTPBasicAuthHandler(pwmgr))
    elif password:
      raise Error("Specified password without username")

    if ignore_proxy:
      handlers.append(urllib2.ProxyHandler({}))

    self._http = urllib2.build_opener(*handlers) # pylint: disable-msg=W0142

    self._headers = {
      "Accept": HTTP_APP_JSON,
      "Content-type": HTTP_APP_JSON,
      "User-Agent": self.USER_AGENT,
      }

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

    if content:
      encoded_content = self._json_encoder.encode(content)
    else:
      encoded_content = None

    # Build URL
    url = [self._base_url, path]
    if query:
      url.append("?")
      url.append(urllib.urlencode(self._EncodeQuery(query)))

    req = _RapiRequest(method, "".join(url), self._headers, encoded_content)

    try:
      resp = self._http.open(req)
      encoded_response_content = resp.read()
    except (OpenSSL.SSL.Error, OpenSSL.crypto.Error), err:
      raise CertificateError("SSL issue: %s" % err)

    if encoded_response_content:
      response_content = simplejson.loads(encoded_response_content)
    else:
      response_content = None

    # TODO: Are there other status codes that are valid? (redirect?)
    if resp.code != HTTP_OK:
      if isinstance(response_content, dict):
        msg = ("%s %s: %s" %
               (response_content["code"],
                response_content["message"],
                response_content["explain"]))
      else:
        msg = str(response_content)

      raise GanetiApiError(msg, code=resp.code)

    return response_content

  def GetVersion(self):
    """Gets the Remote API version running on the cluster.

    @rtype: int
    @return: Ganeti Remote API version

    """
    return self._SendRequest(HTTP_GET, "/version", None, None)

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

  def GetInstanceInfo(self, instance):
    """Gets information about an instance.

    @type instance: str
    @param instance: instance whose info to return

    @rtype: dict
    @return: info about the instance

    """
    return self._SendRequest(HTTP_GET,
                             ("/%s/instances/%s" %
                              (GANETI_RAPI_VERSION, instance)), None, None)

  def CreateInstance(self, dry_run=False):
    """Creates a new instance.

    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    # TODO: Pass arguments needed to actually create an instance.
    query = []
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_POST, "/%s/instances" % GANETI_RAPI_VERSION,
                             query, None)

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

  def ReinstallInstance(self, instance, os, no_startup=False):
    """Reinstalls an instance.

    @type instance: str
    @param instance: the instance to reinstall
    @type os: str
    @param os: the os to reinstall
    @type no_startup: bool
    @param no_startup: whether to start the instance automatically

    """
    query = [("os", os)]
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

  def GetNodeInfo(self, node):
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
                   dry_run=False):
    """Evacuates instances from a Ganeti node.

    @type node: str
    @param node: node to evacuate
    @type iallocator: str or None
    @param iallocator: instance allocator to use
    @type remote_node: str
    @param remote_node: node to evaucate to
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    @raises GanetiApiError: if an iallocator and remote_node are both specified

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

    return self._SendRequest(HTTP_POST,
                             ("/%s/nodes/%s/evacuate" %
                              (GANETI_RAPI_VERSION, node)), query, None)

  def MigrateNode(self, node, live=True, dry_run=False):
    """Migrates all primary instances from a node.

    @type node: str
    @param node: node to migrate
    @type live: bool
    @param live: whether to use live migration
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    """
    query = []
    if live:
      query.append(("live", 1))
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
