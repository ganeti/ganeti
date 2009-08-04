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

from qa_utils import AssertEqual, AssertNotEqual, AssertIn, StartSSH


# Create opener which doesn't try to look for proxies.
NoProxyOpener = urllib2.build_opener(urllib2.ProxyHandler({}))


INSTANCE_FIELDS = ("name", "os", "pnode", "snodes",
                   "admin_state",
                   "disk_template", "disk.sizes",
                   "nic.ips", "nic.macs", "nic.bridges",
                   "beparams", "hvparams",
                   "oper_state", "oper_ram", "status", "tags")

NODE_FIELDS = ("name", "dtotal", "dfree",
               "mtotal", "mnode", "mfree",
               "pinst_cnt", "sinst_cnt", "tags")

LIST_FIELDS = ("id", "uri")


def Enabled():
  """Return whether remote API tests should be run.

  """
  return qa_config.TestEnabled('rapi')


def _DoTests(uris):
  master = qa_config.GetMasterNode()
  host = master["primary"]
  port = qa_config.get("rapi-port", default=constants.DEFAULT_RAPI_PORT)

  for uri, verify in uris:
    assert uri.startswith("/")

    url = "https://%s:%s%s" % (host, port, uri)

    print "Testing %s ..." % url

    response = NoProxyOpener.open(url)

    AssertEqual(response.info()["Content-type"], "application/json")

    data = serializer.LoadJson(response.read())

    if verify is not None:
      if callable(verify):
        verify(data)
      else:
        AssertEqual(data, verify)


def TestVersion():
  """Testing remote API version.

  """
  _DoTests([
    ("/version", constants.RAPI_VERSION),
    ])


def TestEmptyCluster():
  """Testing remote API on an empty cluster.

  """
  master_name = qa_config.GetMasterNode()["primary"]

  def _VerifyInfo(data):
    AssertIn("name", data)
    AssertIn("master", data)
    AssertEqual(data["master"], master_name)

  def _VerifyNodes(data):
    master_entry = {
      "id": master_name,
      "uri": "/2/nodes/%s" % master_name,
      }
    AssertIn(master_entry, data)

  def _VerifyNodesBulk(data):
    for node in data:
      for entry in NODE_FIELDS:
        AssertIn(entry, node)

  _DoTests([
    ("/", None),
    ("/2/info", _VerifyInfo),
    ("/2/tags", None),
    ("/2/nodes", _VerifyNodes),
    ("/2/nodes?bulk=1", _VerifyNodesBulk),
    ("/2/instances", []),
    ("/2/instances?bulk=1", []),
    ("/2/os", None),
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
    ("/2/instances/%s" % instance["name"], _VerifyInstance),
    ("/2/instances", _VerifyInstancesList),
    ("/2/instances?bulk=1", _VerifyInstancesBulk),
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
    ("/2/nodes/%s" % node["primary"], _VerifyNode),
    ("/2/nodes", _VerifyNodesList),
    ("/2/nodes?bulk=1", _VerifyNodesBulk),
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
    # Create copies to modify
    should = tags[:]
    should.sort()

    returned = data[:]
    returned.sort()
    AssertEqual(should, returned)

  _DoTests([
    (uri, _VerifyTags),
    ])
