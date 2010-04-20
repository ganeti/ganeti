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
import httplib2
import simplejson
import socket
import urllib
from OpenSSL import SSL
from OpenSSL import crypto


HTTP_DELETE = "DELETE"
HTTP_GET = "GET"
HTTP_PUT = "PUT"
HTTP_POST = "POST"
REPLACE_DISK_PRI = "replace_on_primary"
REPLACE_DISK_SECONDARY = "replace_on_secondary"
REPLACE_DISK_CHG = "replace_new_secondary"
REPLACE_DISK_AUTO = "replace_auto"
VALID_REPLACEMENT_MODES = frozenset([
    REPLACE_DISK_PRI, REPLACE_DISK_SECONDARY, REPLACE_DISK_CHG,
    REPLACE_DISK_AUTO
    ])
VALID_NODE_ROLES = frozenset([
    "drained", "master", "master-candidate", "offline", "regular"
    ])
VALID_STORAGE_TYPES = frozenset(["file", "lvm-pv", "lvm-vg"])


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
  pass


class InvalidReplacementMode(Error):
  """Raised when an invalid disk replacement mode is attempted.

  """
  pass


class InvalidStorageType(Error):
  """Raised when an invalid storage type is used.

  """
  pass


class InvalidNodeRole(Error):
  """Raised when an invalid node role is used.

  """
  pass


class GanetiRapiClient(object):
  """Ganeti RAPI client.

  """

  USER_AGENT = "Ganeti RAPI Client"

  def __init__(self, master_hostname, port=5080, username=None, password=None,
               ssl_cert=None):
    """Constructor.

    @type master_hostname: str
    @param master_hostname: the ganeti cluster master to interact with
    @type port: int
    @param port: the port on which the RAPI is running. (default is 5080)
    @type username: str
    @param username: the username to connect with
    @type password: str
    @param password: the password to connect with
    @type ssl_cert: str or None
    @param ssl_cert: the expected SSL certificate. if None, SSL certificate
        will not be verified

    """
    self._master_hostname = master_hostname
    self._port = port
    if ssl_cert:
      _VerifyCertificate(self._master_hostname, self._port, ssl_cert)

    self._http = httplib2.Http()
    self._headers = {
        "Accept": "text/plain",
        "Content-type": "application/x-www-form-urlencoded",
        "User-Agent": self.USER_AGENT}
    self._version = None
    if username and password:
      self._http.add_credentials(username, password)

  def _MakeUrl(self, path, query=None, prepend_version=True):
    """Constructs the URL to pass to the HTTP client.

    @type path: str
    @param path: HTTP URL path
    @type query: list of two-tuples
    @param query: query arguments to pass to urllib.urlencode
    @type prepend_version: bool
    @param prepend_version: whether to automatically fetch and prepend the
        Ganeti RAPI version to the URL path

    @rtype:  str
    @return: URL path

    """
    if prepend_version:
      if not self._version:
        self._GetVersionInternal()
      path = "/%d%s" % (self._version, path)

    return "https://%(host)s:%(port)d%(path)s?%(query)s" % {
        "host": self._master_hostname,
        "port": self._port,
        "path": path,
        "query": urllib.urlencode(query or [])}

  def _SendRequest(self, method, path, query=None, content=None,
                   prepend_version=True):
    """Sends an HTTP request.

    This constructs a full URL, encodes and decodes HTTP bodies, and
    handles invalid responses in a pythonic way.

    @type method: str
    @param method: HTTP method to use
    @type path: str
    @param path: HTTP URL path
    @type query: list of two-tuples
    @param query: query arguments to pass to urllib.urlencode
    @type content: str or None
    @param content: HTTP body content
    @type prepend_version: bool
    @param prepend_version: whether to automatically fetch and prepend the
        Ganeti RAPI version to the URL path

    @rtype: str
    @return: JSON-Decoded response

    @raises GanetiApiError: If an invalid response is returned

    """
    if content:
      simplejson.JSONEncoder(sort_keys=True).encode(content)

    url = self._MakeUrl(path, query, prepend_version)
    resp_headers, resp_content = self._http.request(
        url, method, body=content, headers=self._headers)

    if resp_content:
      resp_content = simplejson.loads(resp_content)

    # TODO: Are there other status codes that are valid? (redirect?)
    if resp_headers.status != 200:
      if isinstance(resp_content, dict):
        msg = ("%s %s: %s" %
            (resp_content["code"], resp_content["message"],
             resp_content["explain"]))
      else:
        msg = resp_content
      raise GanetiApiError(msg)

    return resp_content

  def _GetVersionInternal(self):
    """Gets the Remote API version running on the cluster.

    @rtype: int
    @return: Ganeti version

    """
    self._version = self._SendRequest(HTTP_GET, "/version",
                                      prepend_version=False)
    return self._version

  def GetVersion(self):
    """Gets the Remote API version running on the cluster.

    @rtype: int
    @return: Ganeti version

    """
    if not self._version:
      self._GetVersionInternal()
    return self._version

  def GetOperatingSystems(self):
    """Gets the Operating Systems running in the Ganeti cluster.

    @rtype: list of str
    @return: operating systems

    """
    return self._SendRequest(HTTP_GET, "/os")

  def GetInfo(self):
    """Gets info about the cluster.

    @rtype: dict
    @return: information about the cluster

    """
    return self._SendRequest(HTTP_GET, "/info")

  def GetClusterTags(self):
    """Gets the cluster tags.

    @rtype: list of str
    @return: cluster tags

    """
    return self._SendRequest(HTTP_GET, "/tags")

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

    return self._SendRequest(HTTP_PUT, "/tags", query)

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

    self._SendRequest(HTTP_DELETE, "/tags", query)

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

    instances = self._SendRequest(HTTP_GET, "/instances", query)
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
    return self._SendRequest(HTTP_GET, "/instances/%s" % instance)

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

    return self._SendRequest(HTTP_POST, "/instances", query)

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

    return self._SendRequest(HTTP_DELETE, "/instances/%s" % instance, query)

  def GetInstanceTags(self, instance):
    """Gets tags for an instance.

    @type instance: str
    @param instance: instance whose tags to return

    @rtype: list of str
    @return: tags for the instance

    """
    return self._SendRequest(HTTP_GET, "/instances/%s/tags" % instance)

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

    return self._SendRequest(HTTP_PUT, "/instances/%s/tags" % instance, query)

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

    self._SendRequest(HTTP_DELETE, "/instances/%s/tags" % instance, query)

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

    self._SendRequest(HTTP_POST, "/instances/%s/reboot" % instance, query)

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

    self._SendRequest(HTTP_PUT, "/instances/%s/shutdown" % instance, query)

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

    self._SendRequest(HTTP_PUT, "/instances/%s/startup" % instance, query)

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
    self._SendRequest(HTTP_POST, "/instances/%s/reinstall" % instance, query)

  def ReplaceInstanceDisks(self, instance, disks, mode="replace_auto",
                           remote_node=None, iallocator="hail", dry_run=False):
    """Replaces disks on an instance.

    @type instance: str
    @param instance: instance whose disks to replace
    @type disks: list of str
    @param disks: disks to replace
    @type mode: str
    @param mode: replacement mode to use. defaults to replace_auto
    @type remote_node: str or None
    @param remote_node: new secondary node to use (for use with
        replace_new_secondary mdoe)
    @type iallocator: str or None
    @param iallocator: instance allocator plugin to use (for use with
        replace_auto mdoe).  default is hail
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    @rtype: int
    @return: job id

    @raises InvalidReplacementMode: If an invalid disk replacement mode is given
    @raises GanetiApiError: If no secondary node is given with a non-auto
        replacement mode is requested.

    """
    if mode not in VALID_REPLACEMENT_MODES:
      raise InvalidReplacementMode("%s is not a valid disk replacement mode.",
                                   mode)

    query = [("mode", mode), ("disks", ",".join(disks))]

    if mode is REPLACE_DISK_AUTO:
      query.append(("iallocator", iallocator))
    elif mode is REPLACE_DISK_SECONDARY:
      if remote_node is None:
        raise GanetiApiError("You must supply a new secondary node.")
      query.append(("remote_node", remote_node))

    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_POST,
                             "/instances/%s/replace-disks" % instance, query)

  def GetJobs(self):
    """Gets all jobs for the cluster.

    @rtype: list of int
    @return: job ids for the cluster

    """
    return [int(j["id"]) for j in self._SendRequest(HTTP_GET, "/jobs")]

  def GetJobStatus(self, job_id):
    """Gets the status of a job.

    @type job_id: int
    @param job_id: job id whose status to query

    @rtype: dict
    @return: job status

    """
    return self._SendRequest(HTTP_GET, "/jobs/%d" % job_id)

  def DeleteJob(self, job_id, dry_run=False):
    """Deletes a job.

    @type job_id: int
    @param job_id: id of the job to delete
    @type dry_run: bool
    @param dry_run: whether to perform a dry run

    """
    query = []
    if dry_run:
      query.append(("dry-run", 1))

    self._SendRequest(HTTP_DELETE, "/jobs/%d" % job_id, query)

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

    nodes = self._SendRequest(HTTP_GET, "/nodes", query)
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
    return self._SendRequest(HTTP_GET, "/nodes/%s" % node)

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
    query = []
    if iallocator and remote_node:
      raise GanetiApiError("Only one of iallocator or remote_node can be used.")

    if iallocator:
      query.append(("iallocator", iallocator))
    if remote_node:
      query.append(("remote_node", remote_node))
    if dry_run:
      query.append(("dry-run", 1))

    return self._SendRequest(HTTP_POST, "/nodes/%s/evacuate" % node, query)

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

    return self._SendRequest(HTTP_POST, "/nodes/%s/migrate" % node, query)

  def GetNodeRole(self, node):
    """Gets the current role for a node.

    @type node: str
    @param node: node whose role to return

    @rtype: str
    @return: the current role for a node

    """
    return self._SendRequest(HTTP_GET, "/nodes/%s/role" % node)

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

    @raise InvalidNodeRole: If an invalid node role is specified

    """
    if role not in VALID_NODE_ROLES:
      raise InvalidNodeRole("%s is not a valid node role.", role)

    query = [("force", force)]
    return self._SendRequest(HTTP_PUT, "/nodes/%s/role" % node, query,
                             content=role)

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

    @raise InvalidStorageType: If an invalid storage type is specified

    """
    # TODO: Add default for storage_type & output_fields
    if storage_type not in VALID_STORAGE_TYPES:
      raise InvalidStorageType("%s is an invalid storage type.", storage_type)

    query = [("storage_type", storage_type), ("output_fields", output_fields)]
    return self._SendRequest(HTTP_GET, "/nodes/%s/storage" % node, query)

  def ModifyNodeStorageUnits(self, node, storage_type, name, allocatable=True):
    """Modifies parameters of storage units on the node.

    @type node: str
    @param node: node whose storage units to modify
    @type storage_type: str
    @param storage_type: storage type whose units to modify
    @type name: str
    @param name: name of the storage unit
    @type allocatable: bool
    @param allocatable: TODO: Document me

    @rtype: int
    @return: job id

    @raise InvalidStorageType: If an invalid storage type is specified

    """
    if storage_type not in VALID_STORAGE_TYPES:
      raise InvalidStorageType("%s is an invalid storage type.", storage_type)

    query = [
        ("storage_type", storage_type), ("name", name),
        ("allocatable", allocatable)
        ]
    return self._SendRequest(HTTP_PUT, "/nodes/%s/storage/modify" % node, query)

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

    @raise InvalidStorageType: If an invalid storage type is specified

    """
    if storage_type not in VALID_STORAGE_TYPES:
      raise InvalidStorageType("%s is an invalid storage type.", storage_type)

    query = [("storage_type", storage_type), ("name", name)]
    return self._SendRequest(HTTP_PUT, "/nodes/%s/storage/repair" % node, query)

  def GetNodeTags(self, node):
    """Gets the tags for a node.

    @type node: str
    @param node: node whose tags to return

    @rtype: list of str
    @return: tags for the node

    """
    return self._SendRequest(HTTP_GET, "/nodes/%s/tags" % node)

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

    return self._SendRequest(HTTP_PUT, "/nodes/%s/tags" % node, query,
                             content=tags)

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

    return self._SendRequest(HTTP_DELETE, "/nodes/%s/tags" % node, query)


class HTTPSConnectionOpenSSL(httplib.HTTPSConnection):
  """HTTPS Connection handler that verifies the SSL certificate.

  """

  # pylint: disable-msg=W0142
  def __init__(self, *args, **kwargs):
    """Constructor.

    """
    httplib.HTTPSConnection.__init__(self, *args, **kwargs)

    self._ssl_cert = None
    if self.cert_file:
      f = open(self.cert_file, "r")
      self._ssl_cert = crypto.load_certificate(crypto.FILETYPE_PEM, f.read())
      f.close()

  # pylint: disable-msg=W0613
  def _VerifySSLCertCallback(self, conn, cert, errnum, errdepth, ok):
    """Verifies the SSL certificate provided by the peer.

    """
    return (self._ssl_cert.digest("sha1") == cert.digest("sha1") and
            self._ssl_cert.digest("md5") == cert.digest("md5"))

  def connect(self):
    """Connect to the server specified when the object was created.

    This ensures that SSL certificates are verified.

    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ctx = SSL.Context(SSL.SSLv23_METHOD)
    ctx.set_options(SSL.OP_NO_SSLv2)
    ctx.use_certificate(self._ssl_cert)
    ctx.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT,
                   self._VerifySSLCertCallback)

    ssl = SSL.Connection(ctx, sock)
    ssl.connect((self.host, self.port))
    self.sock = httplib.FakeSocket(sock, ssl)


def _VerifyCertificate(hostname, port, cert_file):
  """Verifies the SSL certificate for the given host/port.

  @type hostname: str
  @param hostname: the ganeti cluster master whose certificate to verify
  @type port: int
  @param port: the port on which the RAPI is running
  @type cert_file: str
  @param cert_file: filename of the expected SSL certificate

  @raises CertificateError: If an invalid SSL certificate is found

  """
  https = HTTPSConnectionOpenSSL(hostname, port, cert_file=cert_file)
  try:
    try:
      https.request(HTTP_GET, "/version")
    except (crypto.Error, SSL.Error):
      raise CertificateError("Invalid SSL certificate.")
  finally:
    https.close()
