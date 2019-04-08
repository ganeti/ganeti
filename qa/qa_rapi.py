#
#

# Copyright (C) 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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


"""Remote API QA tests.

"""

import copy
import itertools
import os.path
import random
import re
import tempfile
import uuid as uuid_module

from ganeti import cli
from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import objects
from ganeti import opcodes
from ganeti import pathutils
from ganeti import qlang
from ganeti import query
from ganeti import rapi
from ganeti import utils

from ganeti.http.auth import ParsePasswordFile
import ganeti.rapi.client        # pylint: disable=W0611
import ganeti.rapi.client_utils

import qa_config
import qa_error
import qa_logging
import qa_utils

from qa_instance import GetInstanceInfo
from qa_instance import IsDiskReplacingSupported
from qa_instance import IsFailoverSupported
from qa_instance import IsMigrationSupported
from qa_job_utils import RunWithLocks
from qa_utils import (AssertEqual, AssertIn, AssertMatch, AssertCommand,
                      StartLocalCommand)
from qa_utils import InstanceCheck, INST_DOWN, INST_UP, FIRST_ARG


_rapi_ca = None
_rapi_client = None
_rapi_username = None
_rapi_password = None

# The files to copy if the RAPI files QA config value is set
_FILES_TO_COPY = [
  pathutils.CLUSTER_DOMAIN_SECRET_FILE,
  pathutils.RAPI_CERT_FILE,
  pathutils.RAPI_USERS_FILE,
]


def _EnsureRapiFilesPresence():
  """Ensures that the specified RAPI files are present on the cluster, if any.

  """
  rapi_files_location = qa_config.get("rapi-files-location", None)
  if rapi_files_location is None:
    # No files to be had
    return

  print(qa_logging.FormatWarning("Replacing the certificate and users file on"
                                 " the node with the ones provided in %s"
                                 % rapi_files_location))

  # The RAPI files
  AssertCommand(["mkdir", "-p", pathutils.RAPI_DATA_DIR])

  for filename in _FILES_TO_COPY:
    basename = os.path.split(filename)[-1]
    AssertCommand(["cp", os.path.join(rapi_files_location, basename),
                   filename])
    AssertCommand(["gnt-cluster", "copyfile", filename])

  # The certificates have to be reloaded now
  AssertCommand(["service", "ganeti", "restart"])


def ReloadCertificates(ensure_presence=True):
  """Reloads the client RAPI certificate with the one present on the node.

  If the QA is set up to use a specific certificate using the
  "rapi-files-location" parameter, it will be put in place prior to retrieving
  it.

  """
  if ensure_presence:
    _EnsureRapiFilesPresence()

  if _rapi_username is None or _rapi_password is None:
    raise qa_error.Error("RAPI username and password have to be set before"
                         " attempting to reload a certificate.")

  # pylint: disable=W0603
  # due to global usage
  global _rapi_ca
  global _rapi_client

  master = qa_config.GetMasterNode()

  # Load RAPI certificate from master node
  cmd = ["openssl", "x509", "-in",
         qa_utils.MakeNodePath(master, pathutils.RAPI_CERT_FILE)]

  # Write to temporary file
  _rapi_ca = tempfile.NamedTemporaryFile()
  _rapi_ca.write(qa_utils.GetCommandOutput(master.primary,
                                           utils.ShellQuoteArgs(cmd)))
  _rapi_ca.flush()

  port = qa_config.get("rapi-port", default=constants.DEFAULT_RAPI_PORT)
  cfg_curl = rapi.client.GenericCurlConfig(cafile=_rapi_ca.name,
                                           proxy="")

  if qa_config.UseVirtualCluster():
    # TODO: Implement full support for RAPI on virtual clusters
    print(qa_logging.FormatWarning("RAPI tests are not yet supported on"
                                   " virtual clusters and will be disabled"))

    assert _rapi_client is None
  else:
    _rapi_client = rapi.client.GanetiRapiClient(master.primary, port=port,
                                                username=_rapi_username,
                                                password=_rapi_password,
                                                curl_config_fn=cfg_curl)

    print("RAPI protocol version: %s" % _rapi_client.GetVersion())


#TODO(riba): Remove in 2.13, used just by rapi-workload which disappears there
def GetClient():
  """Retrieves the RAPI client prepared by this module.

  """
  return _rapi_client


def _CreateRapiUser(rapi_user):
  """RAPI credentials creation, with the secret auto-generated.

  """
  rapi_secret = utils.GenerateSecret()

  master = qa_config.GetMasterNode()

  rapi_users_path = qa_utils.MakeNodePath(master, pathutils.RAPI_USERS_FILE)
  rapi_dir = os.path.dirname(rapi_users_path)

  fh = tempfile.NamedTemporaryFile()
  try:
    fh.write("%s %s write\n" % (rapi_user, rapi_secret))
    fh.flush()

    tmpru = qa_utils.UploadFile(master.primary, fh.name)
    try:
      AssertCommand(["mkdir", "-p", rapi_dir])
      AssertCommand(["mv", tmpru, rapi_users_path])
    finally:
      AssertCommand(["rm", "-f", tmpru])
  finally:
    fh.close()

  # The certificates have to be reloaded now
  AssertCommand(["service", "ganeti", "restart"])

  return rapi_secret


def _LookupRapiSecret(rapi_user):
  """Find the RAPI secret for the given user on the QA machines.

  @param rapi_user: Login user
  @return: Login secret for the user

  """
  CTEXT = "{CLEARTEXT}"
  master = qa_config.GetMasterNode()
  cmd = ["cat", qa_utils.MakeNodePath(master, pathutils.RAPI_USERS_FILE)]
  file_content = qa_utils.GetCommandOutput(master.primary,
                                           utils.ShellQuoteArgs(cmd))
  users = ParsePasswordFile(file_content)
  entry = users.get(rapi_user)
  if not entry:
    raise qa_error.Error("User %s not found in RAPI users file" % rapi_user)
  secret = entry.password
  if secret.upper().startswith(CTEXT):
    secret = secret[len(CTEXT):]
  elif secret.startswith("{"):
    raise qa_error.Error("Unsupported password schema for RAPI user %s:"
                         " not a clear text password" % rapi_user)
  return secret


def _ReadRapiSecret(password_file_path):
  """Reads a RAPI secret stored locally.

  @type password_file_path: string
  @return: Login secret for the user

  """
  try:
    with open(password_file_path, 'r') as pw_file:
      return pw_file.readline().strip()
  except IOError:
    raise qa_error.Error("Could not open the RAPI password file located at"
                         " %s" % password_file_path)


def _GetRapiSecret(rapi_user):
  """Returns the secret to be used for RAPI access.

  Where exactly this secret can be found depends on the QA configuration
  options, and this function invokes additional tools as needed. It can
  look up a local secret, a remote one, or create a user with a new secret.

  @param rapi_user: Login user
  @return: Login secret for the user

  """
  password_file_path = qa_config.get("rapi-password-file", None)
  if password_file_path is not None:
    # If the password file is specified, we use the password within.
    # The file must be present on the QA runner.
    return _ReadRapiSecret(password_file_path)
  else:
    # On an existing cluster, just find out the user's secret
    return _LookupRapiSecret(rapi_user)


def SetupRapi():
  """Sets up the RAPI certificate and usernames for the client.

  """
  if not Enabled():
    return (None, None)

  # pylint: disable=W0603
  # due to global usage
  global _rapi_username
  global _rapi_password

  _rapi_username = qa_config.get("rapi-user", "ganeti-qa")

  if qa_config.TestEnabled("create-cluster") and \
     qa_config.get("rapi-files-location") is None:
    # For a new cluster, we have to invent a secret and a user, unless it has
    # been provided separately
    _rapi_password = _CreateRapiUser(_rapi_username)
  else:
    _EnsureRapiFilesPresence()
    _rapi_password = _GetRapiSecret(_rapi_username)

  # Once a username and password have been set, we can fetch the certs and
  # get all we need for a working RAPI client.
  ReloadCertificates(ensure_presence=False)


INSTANCE_FIELDS = ("name", "os", "pnode", "snodes",
                   "admin_state",
                   "disk_template", "disk.sizes", "disk.spindles",
                   "nic.ips", "nic.macs", "nic.modes", "nic.links",
                   "beparams", "hvparams",
                   "oper_state", "oper_ram", "oper_vcpus", "status", "tags")

NODE_FIELDS = ("name", "dtotal", "dfree", "sptotal", "spfree",
               "mtotal", "mnode", "mfree",
               "pinst_cnt", "sinst_cnt", "tags")

GROUP_FIELDS = compat.UniqueFrozenset([
  "name", "uuid",
  "alloc_policy",
  "node_cnt", "node_list",
  ])

JOB_FIELDS = compat.UniqueFrozenset([
  "id", "ops", "status", "summary",
  "opstatus", "opresult", "oplog",
  "received_ts", "start_ts", "end_ts",
  ])

FILTER_FIELDS = compat.UniqueFrozenset([
  "watermark",
  "priority",
  "predicates",
  "action",
  "reason_trail",
  "uuid",
  ])

LIST_FIELDS = ("id", "uri")


def Enabled():
  """Return whether remote API tests should be run.

  """
  # TODO: Implement RAPI tests for virtual clusters
  return (qa_config.TestEnabled("rapi") and
          not qa_config.UseVirtualCluster())


def _DoTests(uris):
  # pylint: disable=W0212
  # due to _SendRequest usage
  results = []

  for uri, verify, method, body in uris:
    assert uri.startswith("/")

    print("%s %s" % (method, uri))
    data = _rapi_client._SendRequest(method, uri, None, body)

    if verify is not None:
      if callable(verify):
        verify(data)
      else:
        AssertEqual(data, verify)

    results.append(data)

  return results


# pylint: disable=W0212
# Due to _SendRequest usage
def _DoGetPutTests(get_uri, modify_uri, opcode_params, rapi_only_aliases=None,
                   modify_method="PUT", exceptions=None, set_exceptions=None):
  """ Test if all params of an object can be retrieved, and set as well.

  @type get_uri: string
  @param get_uri: The URI from which information about the object can be
                  retrieved.
  @type modify_uri: string
  @param modify_uri: The URI which can be used to modify the object.
  @type opcode_params: list of tuple
  @param opcode_params: The parameters of the underlying opcode, used to
                        determine which parameters are actually present.
  @type rapi_only_aliases: list of string or None
  @param rapi_only_aliases: Aliases for parameters which differ from the opcode,
                            and become renamed before opcode submission.
  @type modify_method: string
  @param modify_method: The method to be used in the modification.
  @type exceptions: list of string or None
  @param exceptions: The parameters which have not been exposed and should not
                     be tested at all.
  @type set_exceptions: list of string or None
  @param set_exceptions: The parameters whose setting should not be tested as a
                         part of this test.

  """

  assert get_uri.startswith("/")
  assert modify_uri.startswith("/")

  if exceptions is None:
    exceptions = []
  if set_exceptions is None:
    set_exceptions = []

  print("Testing get/modify symmetry of %s and %s" % (get_uri, modify_uri))

  # First we see if all parameters of the opcode are returned through RAPI
  params_of_interest = map(lambda x: x[0], opcode_params)

  # The RAPI-specific aliases are to be checked as well
  if rapi_only_aliases is not None:
    params_of_interest.extend(rapi_only_aliases)

  info = _rapi_client._SendRequest("GET", get_uri, None, {})

  missing_params = filter(lambda x: x not in info and x not in exceptions,
                          params_of_interest)
  if missing_params:
    raise qa_error.Error("The parameters %s which can be set through the "
                         "appropriate opcode are not present in the response "
                         "from %s" % (','.join(missing_params), get_uri))

  print("GET successful at %s" % get_uri)

  # Then if we can perform a set with the same values as received
  put_payload = {}
  for param in params_of_interest:
    if param not in exceptions and param not in set_exceptions:
      put_payload[param] = info[param]

  _rapi_client._SendRequest(modify_method, modify_uri, None, put_payload)

  print("%s successful at %s" % (modify_method, modify_uri))
# pylint: enable=W0212


def _VerifyReturnsJob(data):
  if not isinstance(data, int):
    AssertMatch(data, r"^\d+$")


def TestVersion():
  """Testing remote API version.

  """
  _DoTests([
    ("/version", constants.RAPI_VERSION, "GET", None),
    ])


def TestEmptyCluster():
  """Testing remote API on an empty cluster.

  """
  master = qa_config.GetMasterNode()
  master_full = qa_utils.ResolveNodeName(master)

  def _VerifyInfo(data):
    AssertIn("name", data)
    AssertIn("master", data)
    AssertEqual(data["master"], master_full)

  def _VerifyNodes(data):
    master_entry = {
      "id": master_full,
      "uri": "/2/nodes/%s" % master_full,
      }
    AssertIn(master_entry, data)

  def _VerifyNodesBulk(data):
    for node in data:
      for entry in NODE_FIELDS:
        AssertIn(entry, node)

  def _VerifyGroups(data):
    default_group = {
      "name": constants.INITIAL_NODE_GROUP_NAME,
      "uri": "/2/groups/" + constants.INITIAL_NODE_GROUP_NAME,
      }
    AssertIn(default_group, data)

  def _VerifyGroupsBulk(data):
    for group in data:
      for field in GROUP_FIELDS:
        AssertIn(field, group)

  def _VerifyFiltersBulk(data):
    for group in data:
      for field in FILTER_FIELDS:
        AssertIn(field, group)

  _DoTests([
    ("/", None, "GET", None),
    ("/2/info", _VerifyInfo, "GET", None),
    ("/2/tags", None, "GET", None),
    ("/2/nodes", _VerifyNodes, "GET", None),
    ("/2/nodes?bulk=1", _VerifyNodesBulk, "GET", None),
    ("/2/groups", _VerifyGroups, "GET", None),
    ("/2/groups?bulk=1", _VerifyGroupsBulk, "GET", None),
    ("/2/instances", [], "GET", None),
    ("/2/instances?bulk=1", [], "GET", None),
    ("/2/os", None, "GET", None),
    ("/2/filters", [], "GET", None),
    ("/2/filters?bulk=1", _VerifyFiltersBulk, "GET", None),
    ])

  # Test HTTP Not Found
  for method in ["GET", "PUT", "POST", "DELETE"]:
    try:
      _DoTests([("/99/resource/not/here/99", None, method, None)])
    except rapi.client.GanetiApiError as err:
      AssertEqual(err.code, 404)
    else:
      raise qa_error.Error("Non-existent resource didn't return HTTP 404")

  # Test HTTP Not Implemented
  for method in ["PUT", "POST", "DELETE"]:
    try:
      _DoTests([("/version", None, method, None)])
    except rapi.client.GanetiApiError as err:
      AssertEqual(err.code, 501)
    else:
      raise qa_error.Error("Non-implemented method didn't fail")

  # Test GET/PUT symmetry
  LEGITIMATELY_MISSING = [
    "force",       # Standard option
    "add_uids",    # Modifies UID pool, is not a param itself
    "remove_uids", # Same as above
    "osparams_private_cluster", # Should not be returned
  ]
  NOT_EXPOSED_YET = ["hv_state", "disk_state", "modify_etc_hosts"]
  # The nicparams are returned under the default entry, yet accepted as they
  # are - this is a TODO to fix!
  DEFAULT_ISSUES = ["nicparams"]
  # Cannot be set over RAPI due to security issues
  FORBIDDEN_PARAMS = ["compression_tools"]

  _DoGetPutTests("/2/info", "/2/modify", opcodes.OpClusterSetParams.OP_PARAMS,
                 exceptions=(LEGITIMATELY_MISSING + NOT_EXPOSED_YET),
                 set_exceptions=DEFAULT_ISSUES + FORBIDDEN_PARAMS)


def TestRapiQuery():
  """Testing resource queries via remote API.

  """
  # FIXME: the tests are failing if no LVM is enabled, investigate
  # if it is a bug in the QA or in the code
  if not qa_config.IsStorageTypeSupported(constants.ST_LVM_VG):
    return

  master_name = qa_utils.ResolveNodeName(qa_config.GetMasterNode())
  rnd = random.Random(7818)

  for what in constants.QR_VIA_RAPI:
    namefield = {
      constants.QR_JOB: "id",
      constants.QR_EXPORT: "export",
      constants.QR_FILTER: "uuid",
    }.get(what, "name")

    all_fields = list(query.ALL_FIELDS[what])
    rnd.shuffle(all_fields)

    # No fields, should return everything
    result = _rapi_client.QueryFields(what)
    qresult = objects.QueryFieldsResponse.FromDict(result)
    AssertEqual(len(qresult.fields), len(all_fields))

    # One field
    result = _rapi_client.QueryFields(what, fields=[namefield])
    qresult = objects.QueryFieldsResponse.FromDict(result)
    AssertEqual(len(qresult.fields), 1)

    # Specify all fields, order must be correct
    result = _rapi_client.QueryFields(what, fields=all_fields)
    qresult = objects.QueryFieldsResponse.FromDict(result)
    AssertEqual(len(qresult.fields), len(all_fields))
    AssertEqual([fdef.name for fdef in qresult.fields], all_fields)

    # Unknown field
    result = _rapi_client.QueryFields(what, fields=["_unknown!"])
    qresult = objects.QueryFieldsResponse.FromDict(result)
    AssertEqual(len(qresult.fields), 1)
    AssertEqual(qresult.fields[0].name, "_unknown!")
    AssertEqual(qresult.fields[0].kind, constants.QFT_UNKNOWN)

    # Try once more, this time without the client
    _DoTests([
      ("/2/query/%s/fields" % what, None, "GET", None),
      ("/2/query/%s/fields?fields=%s,%s,%s" % (what, namefield, namefield,
                                               all_fields[0]),
       None, "GET", None),
      ])

    # Try missing query argument
    try:
      _DoTests([
        ("/2/query/%s" % what, None, "GET", None),
        ])
    except rapi.client.GanetiApiError as err:
      AssertEqual(err.code, 400)
    else:
      raise qa_error.Error("Request missing 'fields' parameter didn't fail")

    def _Check(exp_fields, data):
      qresult = objects.QueryResponse.FromDict(data)
      AssertEqual([fdef.name for fdef in qresult.fields], exp_fields)
      if not isinstance(qresult.data, list):
        raise qa_error.Error("Query did not return a list")

    _DoTests([
      # Specify fields in query
      ("/2/query/%s?fields=%s" % (what, ",".join(all_fields)),
       compat.partial(_Check, all_fields), "GET", None),

      ("/2/query/%s?fields=%s" % (what, namefield),
       compat.partial(_Check, [namefield]), "GET", None),

      # Note the spaces
      ("/2/query/%s?fields=%s,%%20%s%%09,%s%%20" %
       (what, namefield, namefield, namefield),
       compat.partial(_Check, [namefield] * 3), "GET", None)])

    if what in constants.QR_VIA_RAPI_PUT:
      _DoTests([
        # PUT with fields in query
        ("/2/query/%s?fields=%s" % (what, namefield),
         compat.partial(_Check, [namefield]), "PUT", {}),

        ("/2/query/%s" % what, compat.partial(_Check, [namefield] * 4), "PUT", {
           "fields": [namefield] * 4,
           }),

        ("/2/query/%s" % what, compat.partial(_Check, all_fields), "PUT", {
           "fields": all_fields,
           }),

        ("/2/query/%s" % what, compat.partial(_Check, [namefield] * 4), "PUT", {
           "fields": [namefield] * 4
         })])

    if what in constants.QR_VIA_RAPI_PUT:
      trivial_filter = {
        constants.QR_JOB: [qlang.OP_GE, namefield, 0],
      }.get(what, [qlang.OP_REGEXP, namefield, ".*"])

      _DoTests([
        # With filter
        ("/2/query/%s" % what, compat.partial(_Check, all_fields), "PUT", {
           "fields": all_fields,
           "filter": trivial_filter
           }),
        ])

    if what == constants.QR_NODE:
      # Test with filter
      (nodes, ) = _DoTests(
        [("/2/query/%s" % what,
          compat.partial(_Check, ["name", "master"]), "PUT",
          {"fields": ["name", "master"],
           "filter": [qlang.OP_TRUE, "master"],
           })])
      qresult = objects.QueryResponse.FromDict(nodes)
      AssertEqual(qresult.data, [
        [[constants.RS_NORMAL, master_name], [constants.RS_NORMAL, True]],
        ])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstance(instance):
  """Testing getting instance(s) info via remote API.

  """
  def _VerifyInstance(data):
    for entry in INSTANCE_FIELDS:
      AssertIn(entry, data)

  def _VerifyInstancesList(data):
    for instance in data:
      for entry in LIST_FIELDS:
        AssertIn(entry, instance)

  def _VerifyInstancesBulk(data):
    for instance_data in data:
      _VerifyInstance(instance_data)

  _DoTests([
    ("/2/instances/%s" % instance.name, _VerifyInstance, "GET", None),
    ("/2/instances", _VerifyInstancesList, "GET", None),
    ("/2/instances?bulk=1", _VerifyInstancesBulk, "GET", None),
    ("/2/instances/%s/activate-disks" % instance.name,
     _VerifyReturnsJob, "PUT", None),
    ("/2/instances/%s/deactivate-disks" % instance.name,
     _VerifyReturnsJob, "PUT", None),
    ])

  # Test OpBackupPrepare
  (job_id, ) = _DoTests([
    ("/2/instances/%s/prepare-export?mode=%s" %
     (instance.name, constants.EXPORT_MODE_REMOTE),
     _VerifyReturnsJob, "PUT", None),
    ])

  result = _WaitForRapiJob(job_id)[0]
  AssertEqual(len(result["handshake"]), 3)
  AssertEqual(result["handshake"][0], constants.RIE_VERSION)
  AssertEqual(len(result["x509_key_name"]), 3)
  AssertIn("-----BEGIN CERTIFICATE-----", result["x509_ca"])


def TestNode(node):
  """Testing getting node(s) info via remote API.

  """
  def _VerifyNode(data):
    for entry in NODE_FIELDS:
      AssertIn(entry, data)

  def _VerifyNodesList(data):
    for node in data:
      for entry in LIST_FIELDS:
        AssertIn(entry, node)

  def _VerifyNodesBulk(data):
    for node_data in data:
      _VerifyNode(node_data)

  _DoTests([
    ("/2/nodes/%s" % node.primary, _VerifyNode, "GET", None),
    ("/2/nodes", _VerifyNodesList, "GET", None),
    ("/2/nodes?bulk=1", _VerifyNodesBulk, "GET", None),
    ])

  # Not parameters of the node, but controlling opcode behavior
  LEGITIMATELY_MISSING = ["force", "powered"]
  # Identifying the node - RAPI provides these itself
  IDENTIFIERS = ["node_name", "node_uuid"]
  # As the name states, these can be set but not retrieved yet
  NOT_EXPOSED_YET = ["hv_state", "disk_state", "auto_promote"]

  _DoGetPutTests("/2/nodes/%s" % node.primary,
                 "/2/nodes/%s/modify" % node.primary,
                 opcodes.OpNodeSetParams.OP_PARAMS,
                 modify_method="POST",
                 exceptions=(LEGITIMATELY_MISSING + NOT_EXPOSED_YET +
                             IDENTIFIERS))


def _FilterTags(seq):
  """Removes unwanted tags from a sequence.

  """
  ignore_re = qa_config.get("ignore-tags-re", None)

  if ignore_re:
    return itertools.filterfalse(re.compile(ignore_re).match, seq)
  else:
    return seq


def TestTags(kind, name, tags):
  """Tests .../tags resources.

  """
  if kind == constants.TAG_CLUSTER:
    uri = "/2/tags"
  elif kind == constants.TAG_NODE:
    uri = "/2/nodes/%s/tags" % name
  elif kind == constants.TAG_INSTANCE:
    uri = "/2/instances/%s/tags" % name
  elif kind == constants.TAG_NODEGROUP:
    uri = "/2/groups/%s/tags" % name
  elif kind == constants.TAG_NETWORK:
    uri = "/2/networks/%s/tags" % name
  else:
    raise errors.ProgrammerError("Unknown tag kind")

  def _VerifyTags(data):
    AssertEqual(sorted(tags), sorted(_FilterTags(data)))

  queryargs = "&".join("tag=%s" % i for i in tags)

  # Add tags
  (job_id, ) = _DoTests([
    ("%s?%s" % (uri, queryargs), _VerifyReturnsJob, "PUT", None),
    ])
  _WaitForRapiJob(job_id)

  # Retrieve tags
  _DoTests([
    (uri, _VerifyTags, "GET", None),
    ])

  # Remove tags
  (job_id, ) = _DoTests([
    ("%s?%s" % (uri, queryargs), _VerifyReturnsJob, "DELETE", None),
    ])
  _WaitForRapiJob(job_id)


def _WaitForRapiJob(job_id):
  """Waits for a job to finish.

  """
  def _VerifyJob(data):
    AssertEqual(data["id"], job_id)
    for field in JOB_FIELDS:
      AssertIn(field, data)

  _DoTests([
    ("/2/jobs/%s" % job_id, _VerifyJob, "GET", None),
    ])

  return rapi.client_utils.PollJob(_rapi_client, job_id,
                                   cli.StdioJobPollReportCb())


def TestRapiNodeGroups():
  """Test several node group operations using RAPI.

  """
  (group1, group2, group3) = qa_utils.GetNonexistentGroups(3)

  # Create a group with no attributes
  body = {
    "name": group1,
    }

  (job_id, ) = _DoTests([
    ("/2/groups", _VerifyReturnsJob, "POST", body),
    ])

  _WaitForRapiJob(job_id)

  # Create a group specifying alloc_policy
  body = {
    "name": group2,
    "alloc_policy": constants.ALLOC_POLICY_UNALLOCABLE,
    }

  (job_id, ) = _DoTests([
    ("/2/groups", _VerifyReturnsJob, "POST", body),
    ])

  _WaitForRapiJob(job_id)

  # Modify alloc_policy
  body = {
    "alloc_policy": constants.ALLOC_POLICY_UNALLOCABLE,
    }

  (job_id, ) = _DoTests([
    ("/2/groups/%s/modify" % group1, _VerifyReturnsJob, "PUT", body),
    ])

  _WaitForRapiJob(job_id)

  # Rename a group
  body = {
    "new_name": group3,
    }

  (job_id, ) = _DoTests([
    ("/2/groups/%s/rename" % group2, _VerifyReturnsJob, "PUT", body),
    ])

  _WaitForRapiJob(job_id)

  # Test for get/set symmetry

  # Identifying the node - RAPI provides these itself
  IDENTIFIERS = ["group_name"]
  # As the name states, not exposed yet
  NOT_EXPOSED_YET = ["hv_state", "disk_state"]

  # The parameters we do not want to get and set (as that sets the
  # group-specific params to the filled ones)
  FILLED_PARAMS = ["ndparams", "ipolicy", "diskparams"]

  # The aliases that we can use to perform this test with the group-specific
  # params
  CUSTOM_PARAMS = ["custom_ndparams", "custom_ipolicy", "custom_diskparams"]

  _DoGetPutTests("/2/groups/%s" % group3, "/2/groups/%s/modify" % group3,
                 opcodes.OpGroupSetParams.OP_PARAMS,
                 rapi_only_aliases=CUSTOM_PARAMS,
                 exceptions=(IDENTIFIERS + NOT_EXPOSED_YET),
                 set_exceptions=FILLED_PARAMS)

  # Delete groups
  for group in [group1, group3]:
    (job_id, ) = _DoTests([
      ("/2/groups/%s" % group, _VerifyReturnsJob, "DELETE", None),
      ])

    _WaitForRapiJob(job_id)


def TestRapiInstanceAdd(node, use_client):
  """Test adding a new instance via RAPI"""
  if not qa_config.IsTemplateSupported(constants.DT_PLAIN):
    return
  instance = qa_config.AcquireInstance()
  instance.SetDiskTemplate(constants.DT_PLAIN)
  try:
    disks = [{"size": utils.ParseUnit(d.get("size")),
              "name": str(d.get("name"))}
             for d in qa_config.GetDiskOptions()]
    nic0_mac = instance.GetNicMacAddr(0, constants.VALUE_GENERATE)
    nics = [{
      constants.INIC_MAC: nic0_mac,
      }]

    beparams = {
      constants.BE_MAXMEM: utils.ParseUnit(qa_config.get(constants.BE_MAXMEM)),
      constants.BE_MINMEM: utils.ParseUnit(qa_config.get(constants.BE_MINMEM)),
      }

    if use_client:
      job_id = _rapi_client.CreateInstance(constants.INSTANCE_CREATE,
                                           instance.name,
                                           constants.DT_PLAIN,
                                           disks, nics,
                                           os=qa_config.get("os"),
                                           pnode=node.primary,
                                           beparams=beparams)
    else:
      body = {
        "__version__": 1,
        "mode": constants.INSTANCE_CREATE,
        "name": instance.name,
        "os_type": qa_config.get("os"),
        "disk_template": constants.DT_PLAIN,
        "pnode": node.primary,
        "beparams": beparams,
        "disks": disks,
        "nics": nics,
        }

      (job_id, ) = _DoTests([
        ("/2/instances", _VerifyReturnsJob, "POST", body),
        ])

    _WaitForRapiJob(job_id)

    return instance
  except:
    instance.Release()
    raise


def _GenInstanceAllocationDict(node, instance):
  """Creates an instance allocation dict to be used with the RAPI"""
  instance.SetDiskTemplate(constants.DT_PLAIN)

  disks = [{"size": utils.ParseUnit(d.get("size")),
              "name": str(d.get("name"))}
             for d in qa_config.GetDiskOptions()]

  nic0_mac = instance.GetNicMacAddr(0, constants.VALUE_GENERATE)
  nics = [{
    constants.INIC_MAC: nic0_mac,
    }]

  beparams = {
    constants.BE_MAXMEM: utils.ParseUnit(qa_config.get(constants.BE_MAXMEM)),
    constants.BE_MINMEM: utils.ParseUnit(qa_config.get(constants.BE_MINMEM)),
    }

  return _rapi_client.InstanceAllocation(constants.INSTANCE_CREATE,
                                         instance.name,
                                         constants.DT_PLAIN,
                                         disks, nics,
                                         os=qa_config.get("os"),
                                         pnode=node.primary,
                                         beparams=beparams)


def TestRapiInstanceMultiAlloc(node):
  """Test adding two new instances via the RAPI instance-multi-alloc method"""
  if not qa_config.IsTemplateSupported(constants.DT_PLAIN):
    return

  JOBS_KEY = "jobs"

  instance_one = qa_config.AcquireInstance()
  instance_two = qa_config.AcquireInstance()
  instance_list = [instance_one, instance_two]
  try:
    rapi_dicts = [_GenInstanceAllocationDict(node, i) for i in instance_list]

    job_id = _rapi_client.InstancesMultiAlloc(rapi_dicts)

    results, = _WaitForRapiJob(job_id)

    if JOBS_KEY not in results:
      raise qa_error.Error("RAPI instance-multi-alloc did not deliver "
                           "information about created jobs")

    if len(results[JOBS_KEY]) != len(instance_list):
      raise qa_error.Error("RAPI instance-multi-alloc failed to return the "
                           "desired number of jobs!")

    for success, job in results[JOBS_KEY]:
      if success:
        _WaitForRapiJob(job)
      else:
        raise qa_error.Error("Failed to create instance in "
                             "instance-multi-alloc call")
  except:
    # Note that although released, it may be that some of the instance creations
    # have in fact succeeded. Handling this in a better way may be possible, but
    # is not necessary as the QA has already failed at this point.
    for instance in instance_list:
      instance.Release()
    raise

  return (instance_one, instance_two)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestRapiInstanceRemove(instance, use_client):
  """Test removing instance via RAPI"""
  # FIXME: this does not work if LVM is not enabled. Find out if this is a bug
  # in RAPI or in the test
  if not qa_config.IsStorageTypeSupported(constants.ST_LVM_VG):
    return

  if use_client:
    job_id = _rapi_client.DeleteInstance(instance.name)
  else:
    (job_id, ) = _DoTests([
      ("/2/instances/%s" % instance.name, _VerifyReturnsJob, "DELETE", None),
      ])

  _WaitForRapiJob(job_id)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRapiInstanceMigrate(instance):
  """Test migrating instance via RAPI"""
  if not IsMigrationSupported(instance):
    print(qa_logging.FormatInfo("Instance doesn't support migration, skipping"
                                " test"))
    return
  # Move to secondary node
  _WaitForRapiJob(_rapi_client.MigrateInstance(instance.name))
  qa_utils.RunInstanceCheck(instance, True)
  # And back to previous primary
  _WaitForRapiJob(_rapi_client.MigrateInstance(instance.name))


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRapiInstanceFailover(instance):
  """Test failing over instance via RAPI"""
  if not IsFailoverSupported(instance):
    print(qa_logging.FormatInfo("Instance doesn't support failover, skipping"
                                " test"))
    return
  # Move to secondary node
  _WaitForRapiJob(_rapi_client.FailoverInstance(instance.name))
  qa_utils.RunInstanceCheck(instance, True)
  # And back to previous primary
  _WaitForRapiJob(_rapi_client.FailoverInstance(instance.name))


@InstanceCheck(INST_UP, INST_DOWN, FIRST_ARG)
def TestRapiInstanceShutdown(instance):
  """Test stopping an instance via RAPI"""
  _WaitForRapiJob(_rapi_client.ShutdownInstance(instance.name))


@InstanceCheck(INST_DOWN, INST_UP, FIRST_ARG)
def TestRapiInstanceStartup(instance):
  """Test starting an instance via RAPI"""
  _WaitForRapiJob(_rapi_client.StartupInstance(instance.name))


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestRapiInstanceRenameAndBack(rename_source, rename_target):
  """Test renaming instance via RAPI

  This must leave the instance with the original name (in the
  non-failure case).

  """
  _WaitForRapiJob(_rapi_client.RenameInstance(rename_source, rename_target))
  qa_utils.RunInstanceCheck(rename_source, False)
  qa_utils.RunInstanceCheck(rename_target, False)
  _WaitForRapiJob(_rapi_client.RenameInstance(rename_target, rename_source))
  qa_utils.RunInstanceCheck(rename_target, False)


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestRapiInstanceReinstall(instance):
  """Test reinstalling an instance via RAPI"""
  if instance.disk_template == constants.DT_DISKLESS:
    print(qa_logging.FormatInfo("Test not supported for diskless instances"))
    return

  _WaitForRapiJob(_rapi_client.ReinstallInstance(instance.name))
  # By default, the instance is started again
  qa_utils.RunInstanceCheck(instance, True)

  # Reinstall again without starting
  _WaitForRapiJob(_rapi_client.ReinstallInstance(instance.name,
                                                 no_startup=True))


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRapiInstanceReplaceDisks(instance):
  """Test replacing instance disks via RAPI"""
  if not IsDiskReplacingSupported(instance):
    print(qa_logging.FormatInfo("Instance doesn't support disk replacing,"
                                " skipping test"))
    return
  fn = _rapi_client.ReplaceInstanceDisks
  _WaitForRapiJob(fn(instance.name,
                     mode=constants.REPLACE_DISK_AUTO, disks=[]))
  _WaitForRapiJob(fn(instance.name,
                     mode=constants.REPLACE_DISK_SEC, disks="0"))


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRapiInstanceModify(instance):
  """Test modifying instance via RAPI"""
  default_hv = qa_config.GetDefaultHypervisor()

  def _ModifyInstance(**kwargs):
    _WaitForRapiJob(_rapi_client.ModifyInstance(instance.name, **kwargs))

  _ModifyInstance(beparams={
    constants.BE_VCPUS: 3,
    })

  _ModifyInstance(beparams={
    constants.BE_VCPUS: constants.VALUE_DEFAULT,
    })

  if default_hv == constants.HT_XEN_PVM:
    _ModifyInstance(hvparams={
      constants.HV_KERNEL_ARGS: "single",
      })
    _ModifyInstance(hvparams={
      constants.HV_KERNEL_ARGS: constants.VALUE_DEFAULT,
      })
  elif default_hv == constants.HT_XEN_HVM:
    _ModifyInstance(hvparams={
      constants.HV_BOOT_ORDER: "acn",
      })
    _ModifyInstance(hvparams={
      constants.HV_BOOT_ORDER: constants.VALUE_DEFAULT,
      })


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRapiInstanceConsole(instance):
  """Test getting instance console information via RAPI"""
  result = _rapi_client.GetInstanceConsole(instance.name)
  console = objects.InstanceConsole.FromDict(result)
  AssertEqual(console.Validate(), None)
  AssertEqual(console.instance, qa_utils.ResolveInstanceName(instance.name))


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestRapiStoppedInstanceConsole(instance):
  """Test getting stopped instance's console information via RAPI"""
  try:
    _rapi_client.GetInstanceConsole(instance.name)
  except rapi.client.GanetiApiError as err:
    AssertEqual(err.code, 503)
  else:
    raise qa_error.Error("Getting console for stopped instance didn't"
                         " return HTTP 503")


def GetOperatingSystems():
  """Retrieves a list of all available operating systems.

  """
  return _rapi_client.GetOperatingSystems()


def _InvokeMoveInstance(current_dest_inst, current_src_inst, rapi_pw_filename,
                        joint_master, perform_checks, target_nodes=None):
  """ Invokes the move-instance tool for testing purposes.

  """
  # Some uses of this test might require that RAPI-only commands are used,
  # and the checks are command-line based.
  if perform_checks:
    qa_utils.RunInstanceCheck(current_dest_inst, False)

  cmd = [
      "../tools/move-instance",
      "--verbose",
      "--src-ca-file=%s" % _rapi_ca.name,
      "--src-username=%s" % _rapi_username,
      "--src-password-file=%s" % rapi_pw_filename,
      "--dest-instance-name=%s" % current_dest_inst,
      ]

  if target_nodes:
    pnode, snode = target_nodes
    cmd.extend([
      "--dest-primary-node=%s" % pnode,
      "--dest-secondary-node=%s" % snode,
      ])
  else:
    cmd.extend([
      "--iallocator=%s" % constants.IALLOC_HAIL,
      "--opportunistic-tries=1",
      ])

  cmd.extend([
    "--net=0:mac=%s" % constants.VALUE_GENERATE,
    joint_master,
    joint_master,
    current_src_inst,
    ])

  AssertEqual(StartLocalCommand(cmd).wait(), 0)

  if perform_checks:
    qa_utils.RunInstanceCheck(current_src_inst, False)
    qa_utils.RunInstanceCheck(current_dest_inst, True)


def TestInterClusterInstanceMove(src_instance, dest_instance,
                                 inodes, tnode, perform_checks=True):
  """Test tools/move-instance"""
  master = qa_config.GetMasterNode()

  rapi_pw_file = tempfile.NamedTemporaryFile()
  rapi_pw_file.write(_rapi_password)
  rapi_pw_file.flush()

  # Needed only if checks are to be performed
  if perform_checks:
    dest_instance.SetDiskTemplate(src_instance.disk_template)

  # TODO: Run some instance tests before moving back

  if len(inodes) > 1:
    # No disk template currently requires more than 1 secondary node. If this
    # changes, either this test must be skipped or the script must be updated.
    assert len(inodes) == 2
    snode = inodes[1]
  else:
    # Instance is not redundant, but we still need to pass a node
    # (which will be ignored)
    snode = tnode
  pnode = inodes[0]

  # pnode:snode are the *current* nodes, and the first move is an
  # iallocator-guided move outside of pnode. The node lock for the pnode
  # assures that this happens, and while we cannot be sure where the instance
  # will land, it is a real move.
  locks = {locking.LEVEL_NODE: [pnode.primary]}
  RunWithLocks(_InvokeMoveInstance, locks, 600.0, False,
               dest_instance.name, src_instance.name, rapi_pw_file.name,
               master.primary, perform_checks)

  # And then back to pnode:snode
  _InvokeMoveInstance(src_instance.name, dest_instance.name, rapi_pw_file.name,
                      master.primary, perform_checks,
                      target_nodes=(pnode.primary, snode.primary))


def TestFilters():
  """Testing filter management via the remote API.

  """

  body = {
    "priority": 10,
    "predicates": [],
    "action": "CONTINUE",
    "reason": [(constants.OPCODE_REASON_SRC_USER,
               "reason1",
               utils.EpochNano())],
  }

  body1 = copy.deepcopy(body)
  body1["priority"] = 20

  # Query filters
  _DoTests([("/2/filters", [], "GET", None)])

  # Add a filter via POST and delete it again
  uuid = _DoTests([("/2/filters", None, "POST", body)])[0]
  uuid_module.UUID(uuid)  # Check if uuid is a valid UUID
  _DoTests([("/2/filters/%s" % uuid, lambda r: r is None, "DELETE", None)])

  _DoTests([
    # Check PUT-inserting a nonexistent filter with given UUID
    ("/2/filters/%s" % uuid, lambda u: u == uuid, "PUT", body),
    # Check PUT-inserting an existent filter with given UUID
    ("/2/filters/%s" % uuid, lambda u: u == uuid, "PUT", body1),
    # Check that the update changed the filter
    ("/2/filters/%s" % uuid, lambda f: f["priority"] == 20, "GET", None),
    # Delete it again
    ("/2/filters/%s" % uuid, lambda r: r is None, "DELETE", None),
    ])

  # Add multiple filters, query and delete them
  uuids = _DoTests([
    ("/2/filters", None, "POST", body),
    ("/2/filters", None, "POST", body),
    ("/2/filters", None, "POST", body),
    ])
  _DoTests([("/2/filters", lambda rs: [r["uuid"] for r in rs] == uuids,
             "GET", None)])
  for u in uuids:
    _DoTests([("/2/filters/%s" % u, lambda r: r is None, "DELETE", None)])


_DRBD_SECRET_RE = re.compile('shared-secret.*"([0-9A-Fa-f]+)"')


def _RetrieveSecret(instance, pnode):
  """Retrieves the DRBD secret given an instance object and the primary node.

  @type instance: L{qa_config._QaInstance}
  @type pnode: L{qa_config._QaNode}

  @rtype: string

  """
  instance_info = GetInstanceInfo(instance.name)

  # We are interested in only the first disk on the primary
  drbd_minor = instance_info["drbd-minors"][pnode.primary][0]

  # This form should work for all DRBD versions
  drbd_command = ("drbdsetup show %d; drbdsetup %d show || true" %
                  (drbd_minor, drbd_minor))
  instance_drbd_info = \
    qa_utils.GetCommandOutput(pnode.primary, drbd_command)

  match_obj = _DRBD_SECRET_RE.search(instance_drbd_info)
  if match_obj is None:
    raise qa_error.Error("Could not retrieve DRBD secret for instance %s from"
                         " node %s." % (instance.name, pnode.primary))

  return match_obj.groups(0)[0]


def TestInstanceDataCensorship(instance, inodes):
  """Test protection of sensitive instance data."""

  if instance.disk_template != constants.DT_DRBD8:
    print(qa_utils.FormatInfo("Only the DRBD secret is a sensitive parameter"
                              " right now, skipping for non-DRBD instance."))
    return

  drbd_secret = _RetrieveSecret(instance, inodes[0])

  job_id = _rapi_client.GetInstanceInfo(instance.name)
  if not _rapi_client.WaitForJobCompletion(job_id):
    raise qa_error.Error("Could not fetch instance info for instance %s" %
                         instance.name)
  info_dict = _rapi_client.GetJobStatus(job_id)

  if drbd_secret in str(info_dict):
    print(qa_utils.FormatInfo("DRBD secret: %s" % drbd_secret))
    print(qa_utils.FormatInfo("Retrieved data\n%s" % str(info_dict)))
    raise qa_error.Error("Found DRBD secret in contents of RAPI instance info"
                         " call; see above.")
