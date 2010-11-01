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


"""Instance related QA tests.

"""

import re
import time

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertEqual, AssertNotEqual, AssertIn, StartSSH


def _GetDiskStatePath(disk):
  return "/sys/block/%s/device/state" % disk


def _GetGenericAddParameters():
  params = ['-B', '%s=%s' % (constants.BE_MEMORY, qa_config.get('mem'))]
  for idx, size in enumerate(qa_config.get('disk')):
    params.extend(["--disk", "%s:size=%s" % (idx, size)])
  return params


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

    _CheckSsconfInstanceList(instance["name"])

    return instance
  except:
    qa_config.ReleaseInstance(instance)
    raise


def TestInstanceAddWithPlainDisk(node):
  """gnt-instance add -t plain"""
  return _DiskTest(node['primary'], 'plain')


def TestInstanceAddWithDrbdDisk(node, node2):
  """gnt-instance add -t drbd"""
  return _DiskTest("%s:%s" % (node['primary'], node2['primary']),
                   'drbd')


def TestInstanceRemove(instance):
  """gnt-instance remove"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'remove', '-f', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  qa_config.ReleaseInstance(instance)


def TestInstanceStartup(instance):
  """gnt-instance startup"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'startup', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceShutdown(instance):
  """gnt-instance shutdown"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'shutdown', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceReboot(instance):
  """gnt-instance reboot"""
  master = qa_config.GetMasterNode()

  options = qa_config.get('options', {})
  reboot_types = options.get("reboot-types", constants.REBOOT_TYPES)

  for rtype in reboot_types:
    cmd = ['gnt-instance', 'reboot', '--type=%s' % rtype, instance['name']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceReinstall(instance):
  """gnt-instance reinstall"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'reinstall', '-f', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def _ReadSsconfInstanceList():
  """Reads ssconf_instance_list from the master node.

  """
  master = qa_config.GetMasterNode()

  cmd = ["cat", utils.PathJoin(constants.DATA_DIR,
                               "ssconf_%s" % constants.SS_INSTANCE_LIST)]

  return qa_utils.GetCommandOutput(master["primary"],
                                   utils.ShellQuoteArgs(cmd)).splitlines()


def _CheckSsconfInstanceList(instance):
  """Checks if a certain instance is in the ssconf instance list.

  @type instance: string
  @param instance: Instance name

  """
  AssertIn(qa_utils.ResolveInstanceName(instance),
           _ReadSsconfInstanceList())


def TestInstanceRename(instance, rename_target):
  """gnt-instance rename"""
  master = qa_config.GetMasterNode()

  rename_source = instance['name']

  for name1, name2 in [(rename_source, rename_target),
                       (rename_target, rename_source)]:
    _CheckSsconfInstanceList(name1)
    cmd = ['gnt-instance', 'rename', name1, name2]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
    _CheckSsconfInstanceList(name2)


def TestInstanceFailover(instance):
  """gnt-instance failover"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'failover', '--force', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  # ... and back
  cmd = ['gnt-instance', 'failover', '--force', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceMigrate(instance):
  """gnt-instance migrate"""
  master = qa_config.GetMasterNode()

  cmd = ["gnt-instance", "migrate", "--force", instance["name"]]
  AssertEqual(StartSSH(master["primary"],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  # ... and back
  cmd = ["gnt-instance", "migrate", "--force", instance["name"]]
  AssertEqual(StartSSH(master["primary"],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceInfo(instance):
  """gnt-instance info"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'info', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceModify(instance):
  """gnt-instance modify"""
  master = qa_config.GetMasterNode()

  # Assume /sbin/init exists on all systems
  test_kernel = "/sbin/init"
  test_initrd = test_kernel

  orig_memory = qa_config.get('mem')
  orig_bridge = qa_config.get('bridge', 'xen-br0')
  args = [
    ["-B", "%s=128" % constants.BE_MEMORY],
    ["-B", "%s=%s" % (constants.BE_MEMORY, orig_memory)],
    ["-B", "%s=2" % constants.BE_VCPUS],
    ["-B", "%s=1" % constants.BE_VCPUS],
    ["-B", "%s=%s" % (constants.BE_VCPUS, constants.VALUE_DEFAULT)],

    ["-H", "%s=%s" % (constants.HV_KERNEL_PATH, test_kernel)],
    ["-H", "%s=%s" % (constants.HV_KERNEL_PATH, constants.VALUE_DEFAULT)],
    ["-H", "%s=%s" % (constants.HV_INITRD_PATH, test_initrd)],
    ["-H", "no_%s" % (constants.HV_INITRD_PATH, )],
    ["-H", "%s=%s" % (constants.HV_INITRD_PATH, constants.VALUE_DEFAULT)],

    # TODO: bridge tests
    #["--bridge", "xen-br1"],
    #["--bridge", orig_bridge],

    # TODO: Do these tests only with xen-hvm
    #["-H", "%s=acn" % constants.HV_BOOT_ORDER],
    #["-H", "%s=%s" % (constants.HV_BOOT_ORDER, constants.VALUE_DEFAULT)],
    ]
  for alist in args:
    cmd = ['gnt-instance', 'modify'] + alist + [instance['name']]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

  # check no-modify
  cmd = ['gnt-instance', 'modify', instance['name']]
  AssertNotEqual(StartSSH(master['primary'],
                          utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceConvertDisk(instance, snode):
  """gnt-instance modify -t"""
  master = qa_config.GetMasterNode()
  cmd = ['gnt-instance', 'modify', '-t', 'plain', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)
  cmd = ['gnt-instance', 'modify', '-t', 'drbd', '-n', snode['primary'],
         instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceList():
  """gnt-instance list"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'list']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceConsole(instance):
  """gnt-instance console"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'console', '--show-cmd', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestReplaceDisks(instance, pnode, snode, othernode):
  """gnt-instance replace-disks"""
  master = qa_config.GetMasterNode()

  def buildcmd(args):
    cmd = ['gnt-instance', 'replace-disks']
    cmd.extend(args)
    cmd.append(instance["name"])
    return cmd

  cmd = buildcmd(["-p"])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  cmd = buildcmd(["-s"])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  cmd = buildcmd(["--new-secondary=%s" % othernode["primary"]])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  # Restore
  cmd = buildcmd(["--new-secondary=%s" % snode["primary"]])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceExport(instance, node):
  """gnt-backup export -n ..."""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-backup', 'export', '-n', node['primary'], instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  return qa_utils.ResolveInstanceName(instance["name"])


def TestInstanceExportWithRemove(instance, node):
  """gnt-backup export --remove-instance"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-backup', 'export', '-n', node['primary'], "--remove-instance",
         instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceExportNoTarget(instance):
  """gnt-backup export (without target node, should fail)"""
  master = qa_config.GetMasterNode()

  cmd = ["gnt-backup", "export", instance["name"]]
  AssertNotEqual(StartSSH(master['primary'],
                          utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceImport(node, newinst, expnode, name):
  """gnt-backup import"""
  master = qa_config.GetMasterNode()

  cmd = (['gnt-backup', 'import',
          '--disk-template=plain',
          '--no-ip-check',
          '--net', '0:mac=generate',
          '--src-node=%s' % expnode['primary'],
          '--src-dir=%s/%s' % (constants.EXPORT_DIR, name),
          '--node=%s' % node['primary']] +
         _GetGenericAddParameters())
  cmd.append(newinst['name'])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


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

  instance_full = qa_utils.ResolveInstanceName(instance["name"])
  node_full = qa_utils.ResolveNodeName(node)
  node2_full = qa_utils.ResolveNodeName(node2)

  print qa_utils.FormatInfo("Getting physical disk names")
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

  print qa_utils.FormatInfo("Checking whether nodes have ability to stop"
                            " disks")
  for node_name, disks in node2disk.iteritems():
    cmds = []
    for disk in disks:
      cmds.append(sq(["test", "-f", _GetDiskStatePath(disk)]))
    AssertEqual(StartSSH(node_name, ' && '.join(cmds)).wait(), 0)

  print qa_utils.FormatInfo("Getting device paths")
  cmd = ['gnt-instance', 'activate-disks', instance['name']]
  output = qa_utils.GetCommandOutput(master['primary'], sq(cmd))
  devpath = []
  for line in output.splitlines():
    (_, _, tmpdevpath) = line.split(':')
    devpath.append(tmpdevpath)
  print devpath

  print qa_utils.FormatInfo("Getting drbd device paths")
  cmd = ['gnt-instance', 'info', instance['name']]
  output = qa_utils.GetCommandOutput(master['primary'], sq(cmd))
  pattern = (r'\s+-\s+sd[a-z]+,\s+type:\s+drbd8?,\s+.*$'
             r'\s+primary:\s+(/dev/drbd\d+)\s+')
  drbddevs = re.findall(pattern, output, re.M)
  print drbddevs

  halted_disks = []
  try:
    print qa_utils.FormatInfo("Deactivating disks")
    cmds = []
    for name in node2disk[[node2_full, node_full][int(onmaster)]]:
      halted_disks.append(name)
      cmds.append(sq(["echo", "offline"]) + " >%s" % _GetDiskStatePath(name))
    AssertEqual(StartSSH([node2, node][int(onmaster)]['primary'],
                         ' && '.join(cmds)).wait(), 0)

    print qa_utils.FormatInfo("Write to disks and give some time to notice"
                              " to notice the problem")
    cmds = []
    for disk in devpath:
      cmds.append(sq(["dd", "count=1", "bs=512", "conv=notrunc",
                      "if=%s" % disk, "of=%s" % disk]))
    for _ in (0, 1, 2):
      AssertEqual(StartSSH(node['primary'], ' && '.join(cmds)).wait(), 0)
      time.sleep(3)

    print qa_utils.FormatInfo("Debugging info")
    for name in drbddevs:
      cmd = ['drbdsetup', name, 'show']
      AssertEqual(StartSSH(node['primary'], sq(cmd)).wait(), 0)

    cmd = ['gnt-instance', 'info', instance['name']]
    AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

  finally:
    print qa_utils.FormatInfo("Activating disks again")
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

  # TODO
  #cmd = ['vgs']
  #AssertEqual(StartSSH([node2, node][int(onmaster)]['primary'],
  #                     sq(cmd)).wait(), 0)

  print qa_utils.FormatInfo("Making sure disks are up again")
  cmd = ['gnt-instance', 'replace-disks', instance['name']]
  AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

  print qa_utils.FormatInfo("Restarting instance")
  cmd = ['gnt-instance', 'shutdown', instance['name']]
  AssertEqual(StartSSH(master['primary'], sq(cmd)).wait(), 0)

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
