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
from ganeti import constants

import qa_config
import qa_error
import qa_utils

from qa_utils import AssertEqual, AssertNotEqual, StartSSH


def _NodeAdd(node, readd=False):
  master = qa_config.GetMasterNode()

  if not readd and node.get('_added', False):
    raise qa_error.Error("Node %s already in cluster" % node['primary'])
  elif readd and not node.get('_added', False):
    raise qa_error.Error("Node %s not yet in cluster" % node['primary'])

  cmd = ['gnt-node', 'add']
  if node.get('secondary', None):
    cmd.append('--secondary-ip=%s' % node['secondary'])
  if readd:
    cmd.append('--readd')
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
      _NodeAdd(node, readd=False)


def MarkNodeAddedAll():
  """Mark all nodes as added.

  This is useful if we don't create the cluster ourselves (in qa).

  """
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      node['_added'] = True


def TestNodeRemoveAll():
  """Removing all nodes from cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get('nodes'):
    if node != master:
      _NodeRemove(node)


def TestNodeReadd(node):
  """gnt-node add --readd"""
  _NodeAdd(node, readd=True)


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


def TestNodeStorage():
  """gnt-node storage"""
  master = qa_config.GetMasterNode()

  for storage_type in constants.VALID_STORAGE_TYPES:
    # Test simple list
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type]
    AssertEqual(StartSSH(master["primary"],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

    # Test all storage fields
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
           "--output=%s" % ",".join(list(constants.VALID_STORAGE_FIELDS) +
                                    [constants.SF_NODE, constants.SF_TYPE])]
    AssertEqual(StartSSH(master["primary"],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

    # Get list of valid storage devices
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
           "--output=node,name,allocatable", "--separator=|",
           "--no-headers"]
    output = qa_utils.GetCommandOutput(master["primary"],
                                       utils.ShellQuoteArgs(cmd))

    # Test with up to two devices
    testdevcount = 2

    for line in output.splitlines()[:testdevcount]:
      (node_name, st_name, st_allocatable) = line.split("|")

      # Dummy modification without any changes
      cmd = ["gnt-node", "modify-storage", node_name, storage_type, st_name]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)

      # Make sure we end up with the same value as before
      if st_allocatable.lower() == "y":
        test_allocatable = ["no", "yes"]
      else:
        test_allocatable = ["yes", "no"]

      if (constants.SF_ALLOCATABLE in
          constants.MODIFIABLE_STORAGE_FIELDS.get(storage_type, [])):
        assert_fn = AssertEqual
      else:
        assert_fn = AssertNotEqual

      for i in test_allocatable:
        cmd = ["gnt-node", "modify-storage", "--allocatable", i,
               node_name, storage_type, st_name]
        assert_fn(StartSSH(master["primary"],
                  utils.ShellQuoteArgs(cmd)).wait(), 0)

      # Test repair functionality
      cmd = ["gnt-node", "repair-storage", node_name, storage_type, st_name]

      if (constants.SO_FIX_CONSISTENCY in
          constants.VALID_STORAGE_OPERATIONS.get(storage_type, [])):
        assert_fn = AssertEqual
      else:
        assert_fn = AssertNotEqual

      assert_fn(StartSSH(master["primary"],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)


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
    cmd = ['gnt-node', 'evacuate', '-f',
           "--new-secondary=%s" % node3['primary'], node2['primary']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

    # ... and back again.
    cmd = ['gnt-node', 'evacuate', '-f',
           "--new-secondary=%s" % node2['primary'], node3['primary']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
  finally:
    qa_config.ReleaseNode(node3)
