#
#

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
import qa_utils

from qa_utils import AssertEqual, StartSSH


@qa_utils.DefineHook('node-add')
def _NodeAdd(node, readd=False):
  master = qa_config.GetMasterNode()

  if not readd and node.get('_added', False):
    raise qa_error.Error("Node %s already in cluster" % node['primary'])
  elif readd and not node.get('_added', False):
    raise qa_error.Error("Node not yet %s in cluster" % node['primary'])

  cmd = ['gnt-node', 'add']
  if node.get('secondary', None):
    cmd.append('--secondary-ip=%s' % node['secondary'])
  if readd:
    cmd.append('--readd')
  cmd.append(node['primary'])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  node['_added'] = True


@qa_utils.DefineHook('node-remove')
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
      _NodeAdd(node, readd=False)


def TestNodeRemoveAll():
  """Removing all nodes from cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      _NodeRemove(node)


@qa_utils.DefineHook('node-readd')
def TestNodeReadd(node):
  """gnt-node add --readd"""
  _NodeAdd(node, readd=True)


@qa_utils.DefineHook('node-info')
def TestNodeInfo():
  """gnt-node info"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-node', 'info']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('node-volumes')
def TestNodeVolumes():
  """gnt-node volumes"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-node', 'volumes']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('node-failover')
def TestNodeFailover(node, node2):
  """gnt-node failover"""
  master = qa_config.GetMasterNode()

  if qa_utils.GetNodeInstances(node2, secondaries=False):
    raise qa_error.UnusableNodeError("Secondary node has at least one"
                                     " primary instance. This test requires"
                                     " it to have no primary instances.")

  # Fail over to secondary node
  cmd = ['gnt-node', 'failover', '-f', node['primary']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  # ... and back again.
  cmd = ['gnt-node', 'failover', '-f', node2['primary']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('node-evacuate')
def TestNodeEvacuate(node, node2):
  """gnt-node evacuate"""
  master = qa_config.GetMasterNode()

  node3 = qa_config.AcquireNode(exclude=[node, node2])
  try:
    if qa_utils.GetNodeInstances(node3, secondaries=True):
      raise qa_error.UnusableNodeError("Evacuation node has at least one"
                                       " secondary instance. This test requires"
                                       " it to have no secondary instances.")

    # Evacuate all secondary instances
    cmd = ['gnt-node', 'evacuate', '-f', node2['primary'], node3['primary']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

    # ... and back again.
    cmd = ['gnt-node', 'evacuate', '-f', node3['primary'], node2['primary']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
  finally:
    qa_config.ReleaseNode(node3)
