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


def Enabled():
  """Return whether remote API tests should be run.

  """
  return constants.RAPI_ENABLE and qa_config.TestEnabled('rapi')


def PrintRemoteAPIWarning():
  """Print warning if remote API is not enabled.

  """
  if constants.RAPI_ENABLE or not qa_config.TestEnabled('rapi'):
    return
  msg = ("Remote API is not enabled in this Ganeti build. Please run"
         " `configure [...] --enable-rapi'.")
  print
  print qa_utils.FormatWarning(msg)


def _DoTests(uris):
  master = qa_config.GetMasterNode()
  host = master["primary"]
  port = qa_config.get("rapi-port", default=constants.RAPI_PORT)

  for uri, verify in uris:
    assert uri.startswith("/")

    url = "http://%s:%s%s" % (host, port, uri)

    print "Testing %s ..." % url

    response = NoProxyOpener.open(url)

    AssertEqual(response.info()["Content-type"], "application/json")

    data = serializer.LoadJson(response.read())

    if verify is not None:
      if callable(verify):
        verify(data)
      else:
        AssertEqual(data, verify)


@qa_utils.DefineHook('rapi-version')
def TestVersion():
  """Testing remote API version.

  """
  _DoTests([
    ("/version", constants.RAPI_VERSION),
    ])


@qa_utils.DefineHook('rapi-empty-cluster')
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
      "name": master_name,
      "uri": "/nodes/%s" % master_name,
      }
    AssertIn(master_entry, data)

  _DoTests([
    ("/", None),
    ("/info", _VerifyInfo),
    ("/tags", None),
    ("/nodes", _VerifyNodes),
    ("/instances", []),
    ("/os", None),
    ])


@qa_utils.DefineHook('rapi-instance')
def TestInstance(instance):
  """Testing getting instance info via remote API.

  """
  def _VerifyInstance(data):
    AssertIn("name", data)
    AssertIn("pnode", data)

  _DoTests([
    ("/instances/%s" % instance["name"], _VerifyInstance),
    ])


@qa_utils.DefineHook('rapi-node')
def TestNode(node):
  """Testing getting node info via remote API.

  """
  def _VerifyNode(data):
    AssertIn("pinst_cnt", data)
    AssertIn("sinst_cnt", data)
    AssertIn("mtotal", data)

  _DoTests([
    ("/nodes/%s" % node["primary"], _VerifyNode),
    ])


def TestTags(kind, name, tags):
  """Tests .../tags resources.

  """
  if kind == constants.TAG_CLUSTER:
    uri = "/tags"
  elif kind == constants.TAG_NODE:
    uri = "/nodes/%s/tags" % name
  elif kind == constants.TAG_INSTANCE:
    uri = "/instances/%s/tags" % name
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
