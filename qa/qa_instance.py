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


"""Instance related QA tests.

"""

import re
import time

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertEqual, AssertNotEqual, StartSSH


def _GetDiskStatePath(disk):
  return "/sys/block/%s/device/state" % disk


def _GetGenericAddParameters():
  return ['--os-size=%s' % qa_config.get('os-size'),
          '--swap-size=%s' % qa_config.get('swap-size'),
          '--memory=%s' % qa_config.get('mem')]


def _DiskTest(node, disk_template):
  master = qa_config.GetMasterNode()

  instance = qa_config.AcquireInstance()
  try:
    cmd = (['gnt-instance', 'add',
            '--os-type=%s' % qa_config.get('os'),
            '--disk-template=%s' % disk_template,
            '--node=%s' % node] +
           _GetGenericAddParameters())
    cmd.append(instance['name'])

    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
    return instance
  except:
    qa_config.ReleaseInstance(instance)
    raise


@qa_utils.DefineHook('instance-add-plain-disk')
def TestInstanceAddWithPlainDisk(node):
  """gnt-instance add -t plain"""
  return _DiskTest(node['primary'], 'plain')


@qa_utils.DefineHook('instance-add-local-mirror-disk')
def TestInstanceAddWithLocalMirrorDisk(node):
  """gnt-instance add -t local_raid1"""
  return _DiskTest(node['primary'], 'local_raid1')


@qa_utils.DefineHook('instance-add-remote-raid-disk')
def TestInstanceAddWithRemoteRaidDisk(node, node2):
  """gnt-instance add -t remote_raid1"""
  return _DiskTest("%s:%s" % (node['primary'], node2['primary']),
                   'remote_raid1')


@qa_utils.DefineHook('instance-add-drbd-disk')
def TestInstanceAddWithDrbdDisk(node, node2):
  """gnt-instance add -t drbd"""
  return _DiskTest("%s:%s" % (node['primary'], node2['primary']),
                   'drbd')


@qa_utils.DefineHook('instance-remove')
def TestInstanceRemove(instance):
  """gnt-instance remove"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'remove', '-f', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  qa_config.ReleaseInstance(instance)


@qa_utils.DefineHook('instance-startup')
def TestInstanceStartup(instance):
  """gnt-instance startup"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'startup', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('instance-shutdown')
def TestInstanceShutdown(instance):
  """gnt-instance shutdown"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'shutdown', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('instance-reinstall')
def TestInstanceReinstall(instance):
  """gnt-instance reinstall"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'reinstall', '-f', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('instance-failover')
def TestInstanceFailover(instance):
  """gnt-instance failover"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'failover', '--force', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('instance-info')
def TestInstanceInfo(instance):
  """gnt-instance info"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'info', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('instance-modify')
def TestInstanceModify(instance):
  """gnt-instance modify"""
  master = qa_config.GetMasterNode()

  orig_memory = qa_config.get('mem')
  orig_bridge = qa_config.get('bridge', 'xen-br0')
  args = [
    ["--memory", "128"],
    ["--memory", str(orig_memory)],
    ["--cpu", "2"],
    ["--cpu", "1"],
    ["--bridge", "xen-br1"],
    ["--bridge", orig_bridge],
    ["--kernel", "/dev/null"],
    ["--kernel", "default"],
    ["--initrd", "/dev/null"],
    ["--initrd", "none"],
    ["--initrd", "default"],
    ["--hvm-boot-order", "acn"],
    ["--hvm-boot-order", "default"],
    ]
  for alist in args:
    cmd = ['gnt-instance', 'modify'] + alist + [instance['name']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

  # check no-modify
  cmd = ['gnt-instance', 'modify', instance['name']]
  AssertNotEqual(StartSSH(master['primary'],
                          utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('instance-list')
def TestInstanceList():
  """gnt-instance list"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'list']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('backup-export')
def TestInstanceExport(instance, node):
  """gnt-backup export"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-backup', 'export', '-n', node['primary'], instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  return qa_utils.ResolveInstanceName(instance)


@qa_utils.DefineHook('backup-import')
def TestInstanceImport(node, newinst, expnode, name):
  """gnt-backup import"""
  master = qa_config.GetMasterNode()

  cmd = (['gnt-backup', 'import',
          '--disk-template=plain',
          '--no-ip-check',
          '--src-node=%s' % expnode['primary'],
          '--src-dir=%s/%s' % (constants.EXPORT_DIR, name),
          '--node=%s' % node['primary']] +
         _GetGenericAddParameters())
  cmd.append(newinst['name'])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('backup-list')
def TestBackupList(expnode):
  """gnt-backup list"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-backup', 'list', '--node=%s' % expnode['primary']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def _TestInstanceDiskFailure(instance, node, node2, onmaster):
  """Testing disk failure."""
  master = qa_config.GetMasterNode()
  sq = utils.ShellQuoteArgs

  instance_full = qa_utils.ResolveInstanceName(instance)
  node_full = qa_utils.ResolveNodeName(node)
  node2_full = qa_utils.ResolveNodeName(node2)

  cmd = ['gnt-node', 'volumes', '--separator=|', '--no-headers',
         '--output=node,phys,instance',
         node['primary'], node2['primary']]
  output = qa_utils.GetCommandOutput(master['primary'], sq(cmd))

  # Get physical disk names
  re_disk = re.compile(r'^/dev/([a-z]+)\d+$')
  node2disk = {}
  for line in output.splitlines():
    (node_name, phys, inst) = line.split('|')
    if inst == instance_full:
      if node_name not in node2disk:
        node2disk[node_name] = []

      m = re_disk.match(phys)
      if not m:
        raise qa_error.Error("Unknown disk name format: %s" % disk)

      name = m.group(1)
      if name not in node2disk[node_name]:
        node2disk[node_name].append(name)

  if [node2_full, node_full][int(onmaster)] not in node2disk:
    raise qa_error.Error("Couldn't find physical disks used on"
                         " %s node" % ["secondary", "master"][int(onmaster)])

  # Check whether nodes have ability to stop disks
  for node_name, disks in node2disk.iteritems():
    cmds = []
    for disk in disks:
      cmds.append(sq(["test", "-f", _GetDiskStatePath(disk)]))
    AssertEqual(StartSSH(node_name, ' && '.join(cmds)).wait(), 0)

  # Get device paths
  cmd = ['gnt-instance', 'activate-disks', instance['name']]
  output = qa_utils.GetCommandOutput(master['primary'], sq(cmd))
  devpath = []
  for line in output.splitlines():
    (_, _, tmpdevpath) = line.split(':')
    devpath.append(tmpdevpath)

  # Get drbd device paths
  cmd = ['gnt-instance', 'info', instance['name']]
  output = qa_utils.GetCommandOutput(master['primary'], sq(cmd))
  pattern = (r'\s+-\s+type:\s+drbd,\s+.*$'
             r'\s+primary:\s+(/dev/drbd\d+)\s+')
  drbddevs = re.findall(pattern, output, re.M)

  halted_disks = []
  try:
    # Deactivate disks
    cmds = []
    for name in node2disk[[node2_full, node_full][int(onmaster)]]:
      halted_disks.append(name)
      cmds.append(sq(["echo", "offline"]) + " >%s" % _GetDiskStatePath(name))
    AssertEqual(StartSSH([node2, node][int(onmaster)]['primary'],
                         ' && '.join(cmds)).wait(), 0)

    # Write something to the disks and give some time to notice the problem
    cmds = []
    for disk in devpath:
      cmds.append(sq(["dd", "count=1", "bs=512", "conv=notrunc",
                      "if=%s" % disk, "of=%s" % disk]))
    for _ in (0, 1, 2):
      AssertEqual(StartSSH(node['primary'], ' && '.join(cmds)).wait(), 0)
      time.sleep(3)

    for name in drbddevs:
      cmd = ['drbdsetup', name, 'show']
      AssertEqual(StartSSH(node['primary'], sq(cmd)).wait(), 0)

    # For manual checks
    cmd = ['gnt-instance', 'info', instance['name']]
    AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

  finally:
    # Activate disks again
    cmds = []
    for name in halted_disks:
      cmds.append(sq(["echo", "running"]) + " >%s" % _GetDiskStatePath(name))
    AssertEqual(StartSSH([node2, node][int(onmaster)]['primary'],
                         '; '.join(cmds)).wait(), 0)

  if onmaster:
    for name in drbddevs:
      cmd = ['drbdsetup', name, 'detach']
      AssertEqual(StartSSH(node['primary'], sq(cmd)).wait(), 0)
  else:
    for name in drbddevs:
      cmd = ['drbdsetup', name, 'disconnect']
      AssertEqual(StartSSH(node2['primary'], sq(cmd)).wait(), 0)

  # Make sure disks are up again
  #cmd = ['gnt-instance', 'activate-disks', instance['name']]
  #AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

  # Restart instance
  cmd = ['gnt-instance', 'shutdown', instance['name']]
  AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

  #cmd = ['gnt-instance', 'startup', '--force', instance['name']]
  cmd = ['gnt-instance', 'startup', instance['name']]
  AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

  cmd = ['gnt-cluster', 'verify']
  AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)


def TestInstanceMasterDiskFailure(instance, node, node2):
  """Testing disk failure on master node."""
  print qa_utils.FormatError("Disk failure on primary node cannot be"
                             " tested due to potential crashes.")
  # The following can cause crashes, thus it's disabled until fixed
  #return _TestInstanceDiskFailure(instance, node, node2, True)


def TestInstanceSecondaryDiskFailure(instance, node, node2):
  """Testing disk failure on secondary node."""
  return _TestInstanceDiskFailure(instance, node, node2, False)
