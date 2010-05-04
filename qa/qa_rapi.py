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


"""Remote API QA tests.

"""

import urllib2

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import serializer

import qa_config
import qa_utils
import qa_error

from qa_utils import (AssertEqual, AssertNotEqual, AssertIn, AssertMatch,
                      StartSSH)


class OpenerFactory:
  """A factory singleton to construct urllib opener chain.

  This is needed because qa_config is not initialized yet at module load time

  """
  _opener = None
  _rapi_user = None
  _rapi_secret = None

  @classmethod
  def SetCredentials(cls, rapi_user, rapi_secret):
    """Set the credentials for authorized access.

    """
    cls._rapi_user = rapi_user
    cls._rapi_secret = rapi_secret

  @classmethod
  def Opener(cls):
    """Construct the opener if not yet done.

    """
    if not cls._opener:
      if not cls._rapi_user or not cls._rapi_secret:
        raise errors.ProgrammerError("SetCredentials was never called.")

      # Create opener which doesn't try to look for proxies and does auth
      master = qa_config.GetMasterNode()
      host = master["primary"]
      port = qa_config.get("rapi-port", default=constants.DEFAULT_RAPI_PORT)
      passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
      passman.add_password(None, 'https://%s:%s' % (host, port),
                           cls._rapi_user,
                           cls._rapi_secret)
      authhandler = urllib2.HTTPBasicAuthHandler(passman)
      cls._opener = urllib2.build_opener(urllib2.ProxyHandler({}), authhandler)

    return cls._opener


class RapiRequest(urllib2.Request):
  """This class supports other methods beside GET/POST.

  """

  def __init__(self, method, url, headers, data):
    urllib2.Request.__init__(self, url, data=data, headers=headers)
    self._method = method

  def get_method(self):
    return self._method


INSTANCE_FIELDS = ("name", "os", "pnode", "snodes",
                   "admin_state",
                   "disk_template", "disk.sizes",
                   "nic.ips", "nic.macs", "nic.modes", "nic.links",
                   "beparams", "hvparams",
                   "oper_state", "oper_ram", "status", "tags")

NODE_FIELDS = ("name", "dtotal", "dfree",
               "mtotal", "mnode", "mfree",
               "pinst_cnt", "sinst_cnt", "tags")

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
  master = qa_config.GetMasterNode()
  host = master["primary"]
  port = qa_config.get("rapi-port", default=constants.DEFAULT_RAPI_PORT)
  results = []

  for uri, verify, method, body in uris:
    assert uri.startswith("/")

    url = "https://%s:%s%s" % (host, port, uri)

    headers = {}

    if body:
      data = serializer.DumpJson(body, indent=False)
      headers["Content-Type"] = "application/json"
    else:
      data = None

    if headers or data:
      details = []
      if headers:
        details.append("headers=%s" %
                       serializer.DumpJson(headers, indent=False).rstrip())
      if data:
        details.append("data=%s" % data.rstrip())
      info = "(%s)" % (", ".join(details), )
    else:
      info = ""

    print "Testing %s %s %s..." % (method, url, info)

    req = RapiRequest(method, url, headers, data)
    response = OpenerFactory.Opener().open(req)

    AssertEqual(response.info()["Content-type"], "application/json")

    data = serializer.LoadJson(response.read())

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

  _DoTests([
    ("/", None, 'GET', None),
    ("/2/info", _VerifyInfo, 'GET', None),
    ("/2/tags", None, 'GET', None),
    ("/2/nodes", _VerifyNodes, 'GET', None),
    ("/2/nodes?bulk=1", _VerifyNodesBulk, 'GET', None),
    ("/2/instances", [], 'GET', None),
    ("/2/instances?bulk=1", [], 'GET', None),
    ("/2/os", None, 'GET', None),
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

  _DoTests([
    (uri, _VerifyTags, 'GET', None),
    ])
