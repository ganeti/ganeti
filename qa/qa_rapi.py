#

# Copyright (C) 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""Remote API QA tests.

"""

import tempfile
import random

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import cli
from ganeti import rapi
from ganeti import objects
from ganeti import query
from ganeti import compat
from ganeti import qlang

import ganeti.rapi.client        # pylint: disable-msg=W0611
import ganeti.rapi.client_utils

import qa_config
import qa_utils
import qa_error

from qa_utils import (AssertEqual, AssertIn, AssertMatch, StartLocalCommand)


_rapi_ca = None
_rapi_client = None
_rapi_username = None
_rapi_password = None


def Setup(username, password):
  """Configures the RAPI client.

  """
  # pylint: disable-msg=W0603
  # due to global usage
  global _rapi_ca
  global _rapi_client
  global _rapi_username
  global _rapi_password

  _rapi_username = username
  _rapi_password = password

  master = qa_config.GetMasterNode()

  # Load RAPI certificate from master node
  cmd = ["cat", constants.RAPI_CERT_FILE]

  # Write to temporary file
  _rapi_ca = tempfile.NamedTemporaryFile()
  _rapi_ca.write(qa_utils.GetCommandOutput(master["primary"],
                                           utils.ShellQuoteArgs(cmd)))
  _rapi_ca.flush()

  port = qa_config.get("rapi-port", default=constants.DEFAULT_RAPI_PORT)
  cfg_curl = rapi.client.GenericCurlConfig(cafile=_rapi_ca.name,
                                           proxy="")

  _rapi_client = rapi.client.GanetiRapiClient(master["primary"], port=port,
                                              username=username,
                                              password=password,
                                              curl_config_fn=cfg_curl)

  print "RAPI protocol version: %s" % _rapi_client.GetVersion()


INSTANCE_FIELDS = ("name", "os", "pnode", "snodes",
                   "admin_state",
                   "disk_template", "disk.sizes",
                   "nic.ips", "nic.macs", "nic.modes", "nic.links",
                   "beparams", "hvparams",
                   "oper_state", "oper_ram", "oper_vcpus", "status", "tags")

NODE_FIELDS = ("name", "dtotal", "dfree",
               "mtotal", "mnode", "mfree",
               "pinst_cnt", "sinst_cnt", "tags")

GROUP_FIELDS = frozenset([
  "name", "uuid",
  "alloc_policy",
  "node_cnt", "node_list",
  ])

JOB_FIELDS = frozenset([
  "id", "ops", "status", "summary",
  "opstatus", "opresult", "oplog",
  "received_ts", "start_ts", "end_ts",
  ])

LIST_FIELDS = ("id", "uri")


def Enabled():
  """Return whether remote API tests should be run.

  """
  return qa_config.TestEnabled('rapi')


def _DoTests(uris):
  # pylint: disable-msg=W0212
  # due to _SendRequest usage
  results = []

  for uri, verify, method, body in uris:
    assert uri.startswith("/")

    print "%s %s" % (method, uri)
    data = _rapi_client._SendRequest(method, uri, None, body)

    if verify is not None:
      if callable(verify):
        verify(data)
      else:
        AssertEqual(data, verify)

    results.append(data)

  return results


def _VerifyReturnsJob(data):
  AssertMatch(data, r'^\d+$')


def TestVersion():
  """Testing remote API version.

  """
  _DoTests([
    ("/version", constants.RAPI_VERSION, 'GET', None),
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

  _DoTests([
    ("/", None, 'GET', None),
    ("/2/info", _VerifyInfo, 'GET', None),
    ("/2/tags", None, 'GET', None),
    ("/2/nodes", _VerifyNodes, 'GET', None),
    ("/2/nodes?bulk=1", _VerifyNodesBulk, 'GET', None),
    ("/2/groups", _VerifyGroups, 'GET', None),
    ("/2/groups?bulk=1", _VerifyGroupsBulk, 'GET', None),
    ("/2/instances", [], 'GET', None),
    ("/2/instances?bulk=1", [], 'GET', None),
    ("/2/os", None, 'GET', None),
    ])

  # Test HTTP Not Found
  for method in ["GET", "PUT", "POST", "DELETE"]:
    try:
      _DoTests([("/99/resource/not/here/99", None, method, None)])
    except rapi.client.GanetiApiError, err:
      AssertEqual(err.code, 404)
    else:
      raise qa_error.Error("Non-existent resource didn't return HTTP 404")

  # Test HTTP Not Implemented
  for method in ["PUT", "POST", "DELETE"]:
    try:
      _DoTests([("/version", None, method, None)])
    except rapi.client.GanetiApiError, err:
      AssertEqual(err.code, 501)
    else:
      raise qa_error.Error("Non-implemented method didn't fail")


def TestRapiQuery():
  """Testing resource queries via remote API.

  """
  master_name = qa_utils.ResolveNodeName(qa_config.GetMasterNode())
  rnd = random.Random(7818)

  for what in constants.QR_VIA_RAPI:
    all_fields = query.ALL_FIELDS[what].keys()
    rnd.shuffle(all_fields)

    # No fields, should return everything
    result = _rapi_client.QueryFields(what)
    qresult = objects.QueryFieldsResponse.FromDict(result)
    AssertEqual(len(qresult.fields), len(all_fields))

    # One field
    result = _rapi_client.QueryFields(what, fields=["name"])
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
      ("/2/query/%s/fields?fields=name,name,%s" % (what, all_fields[0]),
       None, "GET", None),
      ])

    # Try missing query argument
    try:
      _DoTests([
        ("/2/query/%s" % what, None, "GET", None),
        ])
    except rapi.client.GanetiApiError, err:
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

      ("/2/query/%s?fields=name" % what,
       compat.partial(_Check, ["name"]), "GET", None),

      # Note the spaces
      ("/2/query/%s?fields=name,%%20name%%09,name%%20" % what,
       compat.partial(_Check, ["name"] * 3), "GET", None),

      # PUT with fields in query
      ("/2/query/%s?fields=name" % what,
       compat.partial(_Check, ["name"]), "PUT", {}),

      # Fields in body
      ("/2/query/%s" % what, compat.partial(_Check, all_fields), "PUT", {
         "fields": all_fields,
         }),

      ("/2/query/%s" % what, compat.partial(_Check, ["name"] * 4), "PUT", {
         "fields": ["name"] * 4,
         }),
      ])

    def _CheckFilter():
      _DoTests([
        # With filter
        ("/2/query/%s" % what, compat.partial(_Check, all_fields), "PUT", {
           "fields": all_fields,
           "filter": [qlang.OP_TRUE, "name"],
           }),
        ])

    if what == constants.QR_LOCK:
      # Locks can't be filtered
      try:
        _CheckFilter()
      except rapi.client.GanetiApiError, err:
        AssertEqual(err.code, 500)
      else:
        raise qa_error.Error("Filtering locks didn't fail")
    else:
      _CheckFilter()

    if what == constants.QR_NODE:
      # Test with filter
      (nodes, ) = _DoTests([("/2/query/%s" % what,
        compat.partial(_Check, ["name", "master"]), "PUT", {
        "fields": ["name", "master"],
        "filter": [qlang.OP_TRUE, "master"],
        })])
      qresult = objects.QueryResponse.FromDict(nodes)
      AssertEqual(qresult.data, [
        [[constants.RS_NORMAL, master_name], [constants.RS_NORMAL, True]],
        ])


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
    ("/2/instances/%s" % instance["name"], _VerifyInstance, 'GET', None),
    ("/2/instances", _VerifyInstancesList, 'GET', None),
    ("/2/instances?bulk=1", _VerifyInstancesBulk, 'GET', None),
    ("/2/instances/%s/activate-disks" % instance["name"],
     _VerifyReturnsJob, 'PUT', None),
    ("/2/instances/%s/deactivate-disks" % instance["name"],
     _VerifyReturnsJob, 'PUT', None),
    ])

  # Test OpBackupPrepare
  (job_id, ) = _DoTests([
    ("/2/instances/%s/prepare-export?mode=%s" %
     (instance["name"], constants.EXPORT_MODE_REMOTE),
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
    ("/2/nodes/%s" % node["primary"], _VerifyNode, 'GET', None),
    ("/2/nodes", _VerifyNodesList, 'GET', None),
    ("/2/nodes?bulk=1", _VerifyNodesBulk, 'GET', None),
    ])


def TestTags(kind, name, tags):
  """Tests .../tags resources.

  """
  if kind == constants.TAG_CLUSTER:
    uri = "/2/tags"
  elif kind == constants.TAG_NODE:
    uri = "/2/nodes/%s/tags" % name
  elif kind == constants.TAG_INSTANCE:
    uri = "/2/instances/%s/tags" % name
  else:
    raise errors.ProgrammerError("Unknown tag kind")

  def _VerifyTags(data):
    AssertEqual(sorted(tags), sorted(data))

  queryargs = "&".join("tag=%s" % i for i in tags)

  # Add tags
  (job_id, ) = _DoTests([
    ("%s?%s" % (uri, queryargs), _VerifyReturnsJob, "PUT", None),
    ])
  _WaitForRapiJob(job_id)

  # Retrieve tags
  _DoTests([
    (uri, _VerifyTags, 'GET', None),
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
  groups = qa_config.get("groups", {})
  group1, group2, group3 = groups.get("inexistent-groups",
                                      ["group1", "group2", "group3"])[:3]

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

  # Delete groups
  for group in [group1, group3]:
    (job_id, ) = _DoTests([
      ("/2/groups/%s" % group, _VerifyReturnsJob, "DELETE", None),
      ])

    _WaitForRapiJob(job_id)


def TestRapiInstanceAdd(node, use_client):
  """Test adding a new instance via RAPI"""
  instance = qa_config.AcquireInstance()
  try:
    memory = utils.ParseUnit(qa_config.get("mem"))
    disk_sizes = [utils.ParseUnit(size) for size in qa_config.get("disk")]
    disks = [{"size": size} for size in disk_sizes]
    nics = [{}]

    beparams = {
      constants.BE_MEMORY: memory,
      }

    if use_client:
      job_id = _rapi_client.CreateInstance(constants.INSTANCE_CREATE,
                                           instance["name"],
                                           constants.DT_PLAIN,
                                           disks, nics,
                                           os=qa_config.get("os"),
                                           pnode=node["primary"],
                                           beparams=beparams)
    else:
      body = {
        "__version__": 1,
        "mode": constants.INSTANCE_CREATE,
        "name": instance["name"],
        "os_type": qa_config.get("os"),
        "disk_template": constants.DT_PLAIN,
        "pnode": node["primary"],
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
    qa_config.ReleaseInstance(instance)
    raise


def TestRapiInstanceRemove(instance, use_client):
  """Test removing instance via RAPI"""
  if use_client:
    job_id = _rapi_client.DeleteInstance(instance["name"])
  else:
    (job_id, ) = _DoTests([
      ("/2/instances/%s" % instance["name"], _VerifyReturnsJob, "DELETE", None),
      ])

  _WaitForRapiJob(job_id)

  qa_config.ReleaseInstance(instance)


def TestRapiInstanceMigrate(instance):
  """Test migrating instance via RAPI"""
  # Move to secondary node
  _WaitForRapiJob(_rapi_client.MigrateInstance(instance["name"]))
  # And back to previous primary
  _WaitForRapiJob(_rapi_client.MigrateInstance(instance["name"]))


def TestRapiInstanceRename(rename_source, rename_target):
  """Test renaming instance via RAPI"""
  _WaitForRapiJob(_rapi_client.RenameInstance(rename_source, rename_target))


def TestRapiInstanceReinstall(instance):
  """Test reinstalling an instance via RAPI"""
  _WaitForRapiJob(_rapi_client.ReinstallInstance(instance["name"]))


def TestRapiInstanceModify(instance):
  """Test modifying instance via RAPI"""
  def _ModifyInstance(**kwargs):
    _WaitForRapiJob(_rapi_client.ModifyInstance(instance["name"], **kwargs))

  _ModifyInstance(hvparams={
    constants.HV_KERNEL_ARGS: "single",
    })

  _ModifyInstance(beparams={
    constants.BE_VCPUS: 3,
    })

  _ModifyInstance(beparams={
    constants.BE_VCPUS: constants.VALUE_DEFAULT,
    })

  _ModifyInstance(hvparams={
    constants.HV_KERNEL_ARGS: constants.VALUE_DEFAULT,
    })


def TestRapiInstanceConsole(instance):
  """Test getting instance console information via RAPI"""
  result = _rapi_client.GetInstanceConsole(instance["name"])
  console = objects.InstanceConsole.FromDict(result)
  AssertEqual(console.Validate(), True)
  AssertEqual(console.instance, qa_utils.ResolveInstanceName(instance["name"]))


def TestRapiStoppedInstanceConsole(instance):
  """Test getting stopped instance's console information via RAPI"""
  try:
    _rapi_client.GetInstanceConsole(instance["name"])
  except rapi.client.GanetiApiError, err:
    AssertEqual(err.code, 503)
  else:
    raise qa_error.Error("Getting console for stopped instance didn't"
                         " return HTTP 503")


def GetOperatingSystems():
  """Retrieves a list of all available operating systems.

  """
  return _rapi_client.GetOperatingSystems()


def TestInterClusterInstanceMove(src_instance, dest_instance,
                                 pnode, snode, tnode):
  """Test tools/move-instance"""
  master = qa_config.GetMasterNode()

  rapi_pw_file = tempfile.NamedTemporaryFile()
  rapi_pw_file.write(_rapi_password)
  rapi_pw_file.flush()

  # TODO: Run some instance tests before moving back

  if snode is None:
    # instance is not redundant, but we still need to pass a node
    # (which will be ignored)
    fsec = tnode
  else:
    fsec = snode
  # note: pnode:snode are the *current* nodes, so we move it first to
  # tnode:pnode, then back to pnode:snode
  for si, di, pn, sn in [(src_instance["name"], dest_instance["name"],
                          tnode["primary"], pnode["primary"]),
                         (dest_instance["name"], src_instance["name"],
                          pnode["primary"], fsec["primary"])]:
    cmd = [
      "../tools/move-instance",
      "--verbose",
      "--src-ca-file=%s" % _rapi_ca.name,
      "--src-username=%s" % _rapi_username,
      "--src-password-file=%s" % rapi_pw_file.name,
      "--dest-instance-name=%s" % di,
      "--dest-primary-node=%s" % pn,
      "--dest-secondary-node=%s" % sn,
      "--net=0:mac=%s" % constants.VALUE_GENERATE,
      master["primary"],
      master["primary"],
      si,
      ]

    AssertEqual(StartLocalCommand(cmd).wait(), 0)
