#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
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


"""Node-related QA tests.

"""

from ganeti import utils
from ganeti import constants
from ganeti import query
from ganeti import serializer

from qa import qa_config
from qa import qa_error
from qa import qa_utils

from qa_utils import AssertCommand, AssertRedirectedCommand, AssertEqual, \
  AssertIn, GetCommandOutput


def NodeAdd(node, readd=False, group=None):
  if not readd and node.added:
    raise qa_error.Error("Node %s already in cluster" % node.primary)
  elif readd and not node.added:
    raise qa_error.Error("Node %s not yet in cluster" % node.primary)

  cmd = ["gnt-node", "add", "--no-ssh-key-check"]
  if node.secondary:
    cmd.append("--secondary-ip=%s" % node.secondary)
  if readd:
    cmd.append("--readd")
  if group is not None:
    cmd.extend(["--node-group", group])

  if not qa_config.GetModifySshSetup():
    cmd.append("--no-node-setup")

  cmd.append(node.primary)

  AssertCommand(cmd)

  if readd:
    AssertRedirectedCommand(["gnt-cluster", "verify"])

  if readd:
    assert node.added
  else:
    node.MarkAdded()


def NodeRemove(node):
  AssertCommand(["gnt-node", "remove", node.primary])
  node.MarkRemoved()


def MakeNodeOffline(node, value):
  """gnt-node modify --offline=value"""
  # value in ["yes", "no"]
  AssertCommand(["gnt-node", "modify", "--offline", value, node.primary])


def TestNodeAddAll():
  """Adding all nodes to cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get("nodes"):
    if node != master:
      NodeAdd(node, readd=False)


def MarkNodeAddedAll():
  """Mark all nodes as added.

  This is useful if we don't create the cluster ourselves (in qa).

  """
  master = qa_config.GetMasterNode()
  for node in qa_config.get("nodes"):
    if node != master:
      node.MarkAdded()


def TestNodeRemoveAll():
  """Removing all nodes from cluster."""
  master = qa_config.GetMasterNode()
  for node in qa_config.get("nodes"):
    if node != master:
      NodeRemove(node)


def TestNodeReadd(node):
  """gnt-node add --readd"""
  NodeAdd(node, readd=True)


def TestNodeInfo():
  """gnt-node info"""
  AssertCommand(["gnt-node", "info"])


def TestNodeVolumes():
  """gnt-node volumes"""
  AssertCommand(["gnt-node", "volumes"])


def TestNodeStorage():
  """gnt-node storage"""
  master = qa_config.GetMasterNode()

  # FIXME: test all storage_types in constants.STORAGE_TYPES
  # as soon as they are implemented.
  enabled_storage_types = qa_config.GetEnabledStorageTypes()
  testable_storage_types = list(set(enabled_storage_types).intersection(
      set([constants.ST_FILE, constants.ST_LVM_VG, constants.ST_LVM_PV])))

  for storage_type in testable_storage_types:

    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type]

    # Test simple list
    AssertCommand(cmd)

    # Test all storage fields
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
           "--output=%s" % ",".join(list(constants.VALID_STORAGE_FIELDS))]
    AssertCommand(cmd)

    # Get list of valid storage devices
    cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
           "--output=node,name,allocatable", "--separator=|",
           "--no-headers"]
    output = qa_utils.GetCommandOutput(master.primary,
                                       utils.ShellQuoteArgs(cmd))

    # Test with up to two devices
    testdevcount = 2

    for line in output.splitlines()[:testdevcount]:
      (node_name, st_name, st_allocatable) = line.split("|")

      # Dummy modification without any changes
      cmd = ["gnt-node", "modify-storage", node_name, storage_type, st_name]
      AssertCommand(cmd)

      # Make sure we end up with the same value as before
      if st_allocatable.lower() == "y":
        test_allocatable = ["no", "yes"]
      else:
        test_allocatable = ["yes", "no"]

      fail = (constants.SF_ALLOCATABLE not in
              constants.MODIFIABLE_STORAGE_FIELDS.get(storage_type, []))

      for i in test_allocatable:
        AssertCommand(["gnt-node", "modify-storage", "--allocatable", i,
                       node_name, storage_type, st_name], fail=fail)

        # Verify list output
        cmd = ["gnt-node", "list-storage", "--storage-type", storage_type,
               "--output=name,allocatable", "--separator=|",
               "--no-headers", node_name]
        listout = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
        for line in listout.splitlines():
          (vfy_name, vfy_allocatable) = line.split("|")
          if vfy_name == st_name and not fail:
            AssertEqual(vfy_allocatable, i[0].upper())
          else:
            AssertEqual(vfy_allocatable, st_allocatable)

      # Test repair functionality
      fail = (constants.SO_FIX_CONSISTENCY not in
              constants.VALID_STORAGE_OPERATIONS.get(storage_type, []))
      AssertCommand(["gnt-node", "repair-storage", node_name,
                     storage_type, st_name], fail=fail)


def TestNodeFailover(node, node2):
  """gnt-node failover"""
  if qa_utils.GetNodeInstances(node2, secondaries=False):
    raise qa_error.UnusableNodeError("Secondary node has at least one"
                                     " primary instance. This test requires"
                                     " it to have no primary instances.")

  # Fail over to secondary node
  AssertCommand(["gnt-node", "failover", "-f", node.primary])

  # ... and back again.
  AssertCommand(["gnt-node", "failover", "-f", node2.primary])


def TestNodeMigrate(node, node2):
  """gnt-node migrate"""
  if qa_utils.GetNodeInstances(node2, secondaries=False):
    raise qa_error.UnusableNodeError("Secondary node has at least one"
                                     " primary instance. This test requires"
                                     " it to have no primary instances.")

  # Migrate to secondary node
  AssertCommand(["gnt-node", "migrate", "-f", node.primary])

  # ... and back again.
  AssertCommand(["gnt-node", "migrate", "-f", node2.primary])


def TestNodeEvacuate(node, node2):
  """gnt-node evacuate"""
  node3 = qa_config.AcquireNode(exclude=[node, node2])
  try:
    if qa_utils.GetNodeInstances(node3, secondaries=True):
      raise qa_error.UnusableNodeError("Evacuation node has at least one"
                                       " secondary instance. This test requires"
                                       " it to have no secondary instances.")

    # Evacuate all secondary instances
    AssertCommand(["gnt-node", "evacuate", "-f",
                   "--new-secondary=%s" % node3.primary, node2.primary])

    # ... and back again.
    AssertCommand(["gnt-node", "evacuate", "-f",
                   "--new-secondary=%s" % node2.primary, node3.primary])
  finally:
    node3.Release()


def TestNodeModify(node):
  """gnt-node modify"""

  default_pool_size = 10
  nodes = qa_config.GetAllNodes()
  test_pool_size = len(nodes) - 1

  # Reduce the number of master candidates, because otherwise all
  # subsequent 'gnt-cluster verify' commands fail due to not enough
  # master candidates.
  AssertCommand(["gnt-cluster", "modify",
                 "--candidate-pool-size=%s" % test_pool_size])

  # make sure enough master candidates will be available by disabling the
  # master candidate role first with --auto-promote
  AssertCommand(["gnt-node", "modify", "--master-candidate=no",
                "--auto-promote", node.primary])

  # now it's save to force-remove the master candidate role
  for flag in ["master-candidate", "drained", "offline"]:
    for value in ["yes", "no"]:
      AssertCommand(["gnt-node", "modify", "--force",
                     "--%s=%s" % (flag, value), node.primary])
      AssertCommand(["gnt-cluster", "verify"])

  AssertCommand(["gnt-node", "modify", "--master-candidate=yes", node.primary])

  # Test setting secondary IP address
  AssertCommand(["gnt-node", "modify", "--secondary-ip=%s" % node.secondary,
                 node.primary])

  AssertRedirectedCommand(["gnt-cluster", "verify"])
  AssertCommand(["gnt-cluster", "modify",
                 "--candidate-pool-size=%s" % default_pool_size])

  # For test clusters with more nodes than the default pool size,
  # we now have too many master candidates. To readjust to the original
  # size, manually demote all nodes and rely on auto-promotion to adjust.
  if len(nodes) > default_pool_size:
    master = qa_config.GetMasterNode()
    for n in nodes:
      if n.primary != master.primary:
        AssertCommand(["gnt-node", "modify", "--master-candidate=no",
                       "--auto-promote", n.primary])


def _CreateOobScriptStructure():
  """Create a simple OOB handling script and its structure."""
  master = qa_config.GetMasterNode()

  data_path = qa_utils.UploadData(master.primary, "")
  verify_path = qa_utils.UploadData(master.primary, "")
  exit_code_path = qa_utils.UploadData(master.primary, "")

  oob_script = (("#!/bin/bash\n"
                 "echo \"$@\" > %s\n"
                 "cat %s\n"
                 "exit $(< %s)\n") %
                (utils.ShellQuote(verify_path), utils.ShellQuote(data_path),
                 utils.ShellQuote(exit_code_path)))
  oob_path = qa_utils.UploadData(master.primary, oob_script, mode=0o700)

  return [oob_path, verify_path, data_path, exit_code_path]


def _UpdateOobFile(path, data):
  """Updates the data file with data."""
  master = qa_config.GetMasterNode()
  qa_utils.UploadData(master.primary, data, filename=path)


def _AssertOobCall(verify_path, expected_args):
  """Assert the OOB call was performed with expetected args."""
  master = qa_config.GetMasterNode()

  verify_output_cmd = utils.ShellQuoteArgs(["cat", verify_path])
  output = qa_utils.GetCommandOutput(master.primary, verify_output_cmd,
                                     tty=False)

  AssertEqual(expected_args, output.strip())


def TestOutOfBand():
  """gnt-node power"""
  master = qa_config.GetMasterNode()

  node = qa_config.AcquireNode(exclude=master)

  master_name = master.primary
  node_name = node.primary
  full_node_name = qa_utils.ResolveNodeName(node)

  (oob_path, verify_path,
   data_path, exit_code_path) = _CreateOobScriptStructure()

  try:
    AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                   "oob_program=%s" % oob_path])

    # No data, exit 0
    _UpdateOobFile(exit_code_path, "0")

    AssertCommand(["gnt-node", "power", "on", node_name])
    _AssertOobCall(verify_path, "power-on %s" % full_node_name)

    AssertCommand(["gnt-node", "power", "-f", "off", node_name])
    _AssertOobCall(verify_path, "power-off %s" % full_node_name)

    # Power off on master without options should fail
    AssertCommand(["gnt-node", "power", "-f", "off", master_name], fail=True)
    # With force master it should still fail
    AssertCommand(["gnt-node", "power", "-f", "--ignore-status", "off",
                   master_name],
                  fail=True)

    # Verify we can't transform back to online when not yet powered on
    AssertCommand(["gnt-node", "modify", "-O", "no", node_name],
                  fail=True)
    # Now reset state
    AssertCommand(["gnt-node", "modify", "-O", "no", "--node-powered", "yes",
                   node_name])

    AssertCommand(["gnt-node", "power", "-f", "cycle", node_name])
    _AssertOobCall(verify_path, "power-cycle %s" % full_node_name)

    # Those commands should fail as they expect output which isn't provided yet
    # But they should have called the oob helper nevermind
    AssertCommand(["gnt-node", "power", "status", node_name],
                  fail=True)
    _AssertOobCall(verify_path, "power-status %s" % full_node_name)

    AssertCommand(["gnt-node", "health", node_name],
                  fail=True)
    _AssertOobCall(verify_path, "health %s" % full_node_name)

    AssertCommand(["gnt-node", "health"], fail=True)

    # Correct Data, exit 0
    _UpdateOobFile(data_path, serializer.DumpJson({"powered": True}))

    AssertCommand(["gnt-node", "power", "status", node_name])
    _AssertOobCall(verify_path, "power-status %s" % full_node_name)

    _UpdateOobFile(data_path, serializer.DumpJson([["temp", "OK"],
                                                   ["disk0", "CRITICAL"]]))

    AssertCommand(["gnt-node", "health", node_name])
    _AssertOobCall(verify_path, "health %s" % full_node_name)

    AssertCommand(["gnt-node", "health"])

    # Those commands should fail as they expect no data regardless of exit 0
    AssertCommand(["gnt-node", "power", "on", node_name], fail=True)
    _AssertOobCall(verify_path, "power-on %s" % full_node_name)

    try:
      AssertCommand(["gnt-node", "power", "-f", "off", node_name], fail=True)
      _AssertOobCall(verify_path, "power-off %s" % full_node_name)
    finally:
      AssertCommand(["gnt-node", "modify", "-O", "no", node_name])

    AssertCommand(["gnt-node", "power", "-f", "cycle", node_name], fail=True)
    _AssertOobCall(verify_path, "power-cycle %s" % full_node_name)

    # Data, exit 1 (all should fail)
    _UpdateOobFile(exit_code_path, "1")

    AssertCommand(["gnt-node", "power", "on", node_name], fail=True)
    _AssertOobCall(verify_path, "power-on %s" % full_node_name)

    try:
      AssertCommand(["gnt-node", "power", "-f", "off", node_name], fail=True)
      _AssertOobCall(verify_path, "power-off %s" % full_node_name)
    finally:
      AssertCommand(["gnt-node", "modify", "-O", "no", node_name])

    AssertCommand(["gnt-node", "power", "-f", "cycle", node_name], fail=True)
    _AssertOobCall(verify_path, "power-cycle %s" % full_node_name)

    AssertCommand(["gnt-node", "power", "status", node_name],
                  fail=True)
    _AssertOobCall(verify_path, "power-status %s" % full_node_name)

    AssertCommand(["gnt-node", "health", node_name],
                  fail=True)
    _AssertOobCall(verify_path, "health %s" % full_node_name)

    AssertCommand(["gnt-node", "health"], fail=True)

    # No data, exit 1 (all should fail)
    _UpdateOobFile(data_path, "")
    AssertCommand(["gnt-node", "power", "on", node_name], fail=True)
    _AssertOobCall(verify_path, "power-on %s" % full_node_name)

    try:
      AssertCommand(["gnt-node", "power", "-f", "off", node_name], fail=True)
      _AssertOobCall(verify_path, "power-off %s" % full_node_name)
    finally:
      AssertCommand(["gnt-node", "modify", "-O", "no", node_name])

    AssertCommand(["gnt-node", "power", "-f", "cycle", node_name], fail=True)
    _AssertOobCall(verify_path, "power-cycle %s" % full_node_name)

    AssertCommand(["gnt-node", "power", "status", node_name],
                  fail=True)
    _AssertOobCall(verify_path, "power-status %s" % full_node_name)

    AssertCommand(["gnt-node", "health", node_name],
                  fail=True)
    _AssertOobCall(verify_path, "health %s" % full_node_name)

    AssertCommand(["gnt-node", "health"], fail=True)

    # Different OOB script for node
    verify_path2 = qa_utils.UploadData(master.primary, "")
    oob_script = ("#!/bin/sh\n"
                  "echo \"$@\" > %s\n") % verify_path2
    oob_path2 = qa_utils.UploadData(master.primary, oob_script, mode=0o700)

    try:
      AssertCommand(["gnt-node", "modify", "--node-parameters",
                     "oob_program=%s" % oob_path2, node_name])
      AssertCommand(["gnt-node", "power", "on", node_name])
      _AssertOobCall(verify_path2, "power-on %s" % full_node_name)
    finally:
      AssertCommand(["gnt-node", "modify", "--node-parameters",
                     "oob_program=default", node_name])
      AssertCommand(["rm", "-f", oob_path2, verify_path2])
  finally:
    AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                   "oob_program="])
    AssertCommand(["rm", "-f", oob_path, verify_path, data_path,
                   exit_code_path])


def TestNodeList():
  """gnt-node list"""
  qa_utils.GenericQueryTest("gnt-node", list(query.NODE_FIELDS))


def TestNodeListFields():
  """gnt-node list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-node", list(query.NODE_FIELDS))


def TestNodeListDrbd(node, is_drbd):
  """gnt-node list-drbd"""
  master = qa_config.GetMasterNode()
  result_output = GetCommandOutput(master.primary,
                                   "gnt-node list-drbd --no-header %s" %
                                   node.primary)
  # Meaningful to note: there is but one instance, and the node is either the
  # primary or one of the secondaries
  if is_drbd:
    # Invoked for both primary and secondary
    per_disk_info = result_output.splitlines()
    for line in per_disk_info:
      try:
        drbd_node, _, _, _, _, drbd_peer = line.split()
      except ValueError:
        raise qa_error.Error("Could not examine list-drbd output: expected a"
                             " single row of 6 entries, found the following:"
                             " %s" % line)

      AssertIn(node.primary, [drbd_node, drbd_peer],
               msg="The output %s does not contain the node" % line)
  else:
    # Output should be empty, barring newlines
    AssertEqual(result_output.strip(), "")


def _BuildSetESCmd(action, value, node_name):
  cmd = ["gnt-node"]
  if action == "add":
    cmd.extend(["add", "--readd"])
    if not qa_config.GetModifySshSetup():
      cmd.append("--no-node-setup")
  else:
    cmd.append("modify")
  cmd.extend(["--node-parameters", "exclusive_storage=%s" % value, node_name])
  return cmd


def TestExclStorSingleNode(node):
  """gnt-node add/modify cannot change the exclusive_storage flag.

  """
  for action in ["add", "modify"]:
    for value in (True, False, "default"):
      AssertCommand(_BuildSetESCmd(action, value, node.primary), fail=True)
