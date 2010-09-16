# Copyright (C) 2007 Google Inc.
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


"""Tags related QA tests.

"""

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils
import qa_rapi

from qa_utils import AssertEqual, StartSSH


_TEMP_TAG_NAMES = ["TEMP-Ganeti-QA-Tag%d" % i for i in range(3)]
_TEMP_TAG_RE = r'^TEMP-Ganeti-QA-Tag\d+$'

_KIND_TO_COMMAND = {
  constants.TAG_CLUSTER: "gnt-cluster",
  constants.TAG_NODE: "gnt-node",
  constants.TAG_INSTANCE: "gnt-instance",
  }


def _TestTags(kind, name):
  """Generic function for add-tags.

  """
  master = qa_config.GetMasterNode()

  def cmdfn(subcmd):
    cmd = [_KIND_TO_COMMAND[kind], subcmd]

    if kind != constants.TAG_CLUSTER:
      cmd.append(name)

    return cmd

  cmd = cmdfn('add-tags') + _TEMP_TAG_NAMES
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  cmd = cmdfn('list-tags')
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  cmd = ['gnt-cluster', 'search-tags', _TEMP_TAG_RE]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  cmd = cmdfn('remove-tags') + _TEMP_TAG_NAMES
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  if qa_rapi.Enabled():
    qa_rapi.TestTags(kind, name, _TEMP_TAG_NAMES)


def TestClusterTags():
  """gnt-cluster tags"""
  _TestTags(constants.TAG_CLUSTER, "")


def TestNodeTags(node):
  """gnt-node tags"""
  _TestTags(constants.TAG_NODE, node["primary"])


def TestInstanceTags(instance):
  """gnt-instance tags"""
  _TestTags(constants.TAG_INSTANCE, instance["name"])
