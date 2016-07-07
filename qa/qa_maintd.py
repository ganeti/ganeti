#
#

# Copyright (C) 2015 Google Inc.
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


"""Maintainance daemon tests.

"""

import random
import os.path

from ganeti import serializer
from ganeti.utils import retry

import qa_config
import qa_error

from qa_utils import AssertCommand, \
                     UploadData, \
                     stdout_of
from qa_instance_utils import CreateInstanceDrbd8, \
                              RemoveInstance


def _GetMaintTags(node):
  tags = stdout_of([
    "gnt-node", "list-tags", node.primary
  ]).split()
  return [t for t in tags if t.startswith('maintd:repairready:')]


def _AssertRepairTagAddition(node):
  def fn():
    tags = _GetMaintTags(node)
    if len(tags) == 0:
      raise retry.RetryAgain()
    if len(tags) > 1:
      raise qa_error.Error("Only one tag should be added")
    else:
      return tags[0]
  return retry.Retry(fn, 5.0, 500.0)


def _AssertNodeDrained(node):
  def fn():
    out = stdout_of([
      "gnt-node", "list",
       "--output=name", "--no-headers",
       "--filter", "drained"
    ])
    if node.primary not in out:
      raise retry.RetryAgain()
  retry.Retry(fn, 5.0, 500.0)


def _AssertInstanceRunning(inst):
  def fn():
    out = stdout_of([
      "gnt-instance", "list",
      "--output=status", "--no-headers",
      "--filter", "name == \"%s\"" % inst.name
    ])
    if "running" not in out:
      raise retry.RetryAgain()
  retry.Retry(fn, 5.0, 500.0)


def _AssertInstanceMove(inst, move_type):
  def fn():
    out = stdout_of([
      "gnt-job", "list",
      "--output=status", "--no-headers",
      "--filter", '"%s(%s)" in summary' % (move_type, inst.name)
    ])
    if 'success' not in out:
      raise retry.RetryAgain()
  retry.Retry(fn, 5.0, 500.0)


def _AssertRepairCommand():
  def fn():
    out = stdout_of([
      "gnt-job", "list",
      "--output=status", "--no-headers",
      "--filter", '"REPAIR_COMMAND" in summary'
    ])
    if 'success' not in out:
      raise retry.RetryAgain()
  retry.Retry(fn, 5.0, 500.0)


def _SetUp(diagnose_dc_filename):
  AssertCommand(["gnt-cluster", "modify", "--maintenance-interval=3"])
  AssertCommand([
    "gnt-cluster", "modify",
    "--diagnose-data-collector-filename", diagnose_dc_filename
  ])


def _TearDown(node, tag, added_filepaths, drain_node=True):
  AssertCommand([
    "gnt-cluster", "modify",
    "--diagnose-data-collector-filename", '""'
  ])
  AssertCommand(["rm"] + added_filepaths, node=node)
  if drain_node:
    AssertCommand(["gnt-node", "modify", "--drained=no", node.primary])
  AssertCommand(["gnt-node", "remove-tags", node.primary, tag])
  AssertCommand(["gnt-cluster", "modify", "--maintenance-interval=300"])


def _TestEvac(filepath, filecontent, inst_move_type):
  _SetUp(os.path.basename(filepath))
  node1, node2 = qa_config.AcquireManyNodes(
    2,
    exclude=qa_config.GetMasterNode())
  inst = CreateInstanceDrbd8([node1, node2])
  _AssertInstanceRunning(inst)
  UploadData(node1.primary, filecontent, 0755, filepath)

  _AssertNodeDrained(node1)
  _AssertInstanceMove(inst, inst_move_type)
  tag = _AssertRepairTagAddition(node1)

  RemoveInstance(inst)
  inst.Release()
  node1.Release()
  node2.Release()
  _TearDown(node1, tag, [filepath])


def TestEvacuate():
  """Test node evacuate upon diagnosis.

  """
  n = random.randint(10000, 99999)
  _TestEvac('/etc/ganeti/node-diagnose-commands/evacuate',
            'echo \'' + serializer.DumpJson({
              "status": "evacuate",
              "details": "qa evacuate test %d" % n}).strip() + '\'',
            'INSTANCE_MIGRATE')


def TestEvacuateFailover():
  """Test node evacuate failover upon diagnosis.

  """
  n = random.randint(10000, 99999)
  _TestEvac('/etc/ganeti/node-diagnose-commands/evacuate-failover',
            'echo \'' + serializer.DumpJson({
              "status": "evacuate-failover",
              "details": "qa evacuate failover test %d" % n}).strip() + '\'',
            'INSTANCE_FAILOVER')


def TestLiveRepair():
  """Test node evacuate failover upon diagnosis.

  """
  _SetUp('live-repair')
  n = random.randint(10000, 99999)
  node = qa_config.AcquireNode(exclude=qa_config.GetMasterNode())
  UploadData(node.primary,
             'echo \'' + serializer.DumpJson({
               "status": "live-repair",
               "command": "repair",
               "details": str(n)}).strip() + '\'',
             0755,
             '/etc/ganeti/node-diagnose-commands/live-repair')
  UploadData(node.primary,
             """#!/usr/bin/python
import sys
import json

n = json.loads(sys.stdin.read())['details']
with open('/tmp/' + n, 'w') as f:
  f.write(n)
print 'file written'
""",
             0755,
             '/etc/ganeti/node-repair-commands/repair')
  _AssertRepairCommand()
  tag = _AssertRepairTagAddition(node)
  if str(n) != AssertCommand(["cat", "/tmp/" + str(n)], node=node)[1]:
    raise qa_error.Error('Repair command was unsuccessful')
  node.Release()
  _TearDown(
    node,
    tag,
    ['/etc/ganeti/node-diagnose-commands/live-repair',
     '/etc/ganeti/node-repair-commands/repair'],
    False)
