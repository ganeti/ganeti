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


from ganeti import utils

import qa_config
import qa_error

from qa_utils import AssertEqual, StartSSH


def _NodeAdd(node):
  master = qa_config.GetMasterNode()

  if node.get('_added', False):
    raise qa_error.Error("Node %s already in cluster" % node['primary'])

  cmd = ['gnt-node', 'add']
  if node.get('secondary', None):
    cmd.append('--secondary-ip=%s' % node['secondary'])
  cmd.append(node['primary'])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  node['_added'] = True


def _NodeRemove(node):
  master = qa_config.GetMasterNode()

  cmd = ['gnt-node', 'remove', node['primary']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)
  node['_added'] = False


def TestNodeAddAll():
  """Adding all nodes to cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      _NodeAdd(node)


def TestNodeRemoveAll():
  """Removing all nodes from cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      _NodeRemove(node)


def TestNodeInfo():
  """gnt-node info"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-node', 'info']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestNodeVolumes():
  """gnt-node volumes"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-node', 'volumes']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)
