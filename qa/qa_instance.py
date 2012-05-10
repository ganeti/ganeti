#
#

# Copyright (C) 2007, 2011, 2012 Google Inc.
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
from ganeti import query

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertIn, AssertCommand, AssertEqual
from qa_utils import InstanceCheck, INST_DOWN, INST_UP, FIRST_ARG, RETURN_VALUE


def _GetDiskStatePath(disk):
  return "/sys/block/%s/device/state" % disk


def _GetGenericAddParameters():
  params = ["-B"]
  params.append("%s=%s,%s=%s" % (constants.BE_MINMEM,
                                 qa_config.get(constants.BE_MINMEM),
                                 constants.BE_MAXMEM,
                                 qa_config.get(constants.BE_MAXMEM)))
  for idx, size in enumerate(qa_config.get("disk")):
    params.extend(["--disk", "%s:size=%s" % (idx, size)])
  return params


def _DiskTest(node, disk_template):
  instance = qa_config.AcquireInstance()
  try:
    cmd = (["gnt-instance", "add",
            "--os-type=%s" % qa_config.get("os"),
            "--disk-template=%s" % disk_template,
            "--node=%s" % node] +
           _GetGenericAddParameters())
    cmd.append(instance["name"])

    AssertCommand(cmd)

    _CheckSsconfInstanceList(instance["name"])

    return instance
  except:
    qa_config.ReleaseInstance(instance)
    raise


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddWithPlainDisk(node):
  """gnt-instance add -t plain"""
  return _DiskTest(node["primary"], "plain")


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddWithDrbdDisk(node, node2):
  """gnt-instance add -t drbd"""
  return _DiskTest("%s:%s" % (node["primary"], node2["primary"]),
                   "drbd")


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceRemove(instance):
  """gnt-instance remove"""
  AssertCommand(["gnt-instance", "remove", "-f", instance["name"]])

  qa_config.ReleaseInstance(instance)


@InstanceCheck(INST_DOWN, INST_UP, FIRST_ARG)
def TestInstanceStartup(instance):
  """gnt-instance startup"""
  AssertCommand(["gnt-instance", "startup", instance["name"]])


@InstanceCheck(INST_UP, INST_DOWN, FIRST_ARG)
def TestInstanceShutdown(instance):
  """gnt-instance shutdown"""
  AssertCommand(["gnt-instance", "shutdown", instance["name"]])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceReboot(instance):
  """gnt-instance reboot"""
  options = qa_config.get("options", {})
  reboot_types = options.get("reboot-types", constants.REBOOT_TYPES)
  name = instance["name"]
  for rtype in reboot_types:
    AssertCommand(["gnt-instance", "reboot", "--type=%s" % rtype, name])

  AssertCommand(["gnt-instance", "shutdown", name])
  qa_utils.RunInstanceCheck(instance, False)
  AssertCommand(["gnt-instance", "reboot", name])

  master = qa_config.GetMasterNode()
  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", name]
  result_output = qa_utils.GetCommandOutput(master["primary"],
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_RUNNING)


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceReinstall(instance):
  """gnt-instance reinstall"""
  AssertCommand(["gnt-instance", "reinstall", "-f", instance["name"]])


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


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceRenameAndBack(rename_source, rename_target):
  """gnt-instance rename

  This must leave the instance with the original name, not the target
  name.

  """
  _CheckSsconfInstanceList(rename_source)

  # first do a rename to a different actual name, expecting it to fail
  qa_utils.AddToEtcHosts(["meeeeh-not-exists", rename_target])
  try:
    AssertCommand(["gnt-instance", "rename", rename_source, rename_target],
                  fail=True)
    _CheckSsconfInstanceList(rename_source)
  finally:
    qa_utils.RemoveFromEtcHosts(["meeeeh-not-exists", rename_target])

  # and now rename instance to rename_target...
  AssertCommand(["gnt-instance", "rename", rename_source, rename_target])
  _CheckSsconfInstanceList(rename_target)
  qa_utils.RunInstanceCheck(rename_source, False)
  qa_utils.RunInstanceCheck(rename_target, True)

  # and back
  AssertCommand(["gnt-instance", "rename", rename_target, rename_source])
  _CheckSsconfInstanceList(rename_source)
  qa_utils.RunInstanceCheck(rename_target, False)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceFailover(instance):
  """gnt-instance failover"""
  cmd = ["gnt-instance", "failover", "--force", instance["name"]]

  # failover ...
  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)

  # ... and back
  AssertCommand(cmd)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceMigrate(instance):
  """gnt-instance migrate"""
  cmd = ["gnt-instance", "migrate", "--force", instance["name"]]

  # migrate ...
  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)

  # ... and back
  AssertCommand(cmd)

  # TODO: Split into multiple tests
  AssertCommand(["gnt-instance", "shutdown", instance["name"]])
  qa_utils.RunInstanceCheck(instance, False)
  AssertCommand(cmd, fail=True)
  AssertCommand(["gnt-instance", "migrate", "--force", "--allow-failover",
                 instance["name"]])
  AssertCommand(["gnt-instance", "start", instance["name"]])
  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)

  AssertCommand(["gnt-instance", "modify", "-B",
                 ("%s=%s" %
                  (constants.BE_ALWAYS_FAILOVER, constants.VALUE_TRUE)),
                 instance["name"]])

  AssertCommand(cmd, fail=True)
  qa_utils.RunInstanceCheck(instance, True)
  AssertCommand(["gnt-instance", "migrate", "--force", "--allow-failover",
                 instance["name"]])

  # TODO: Verify whether the default value is restored here (not hardcoded)
  AssertCommand(["gnt-instance", "modify", "-B",
                 ("%s=%s" %
                  (constants.BE_ALWAYS_FAILOVER, constants.VALUE_FALSE)),
                 instance["name"]])

  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)


def TestInstanceInfo(instance):
  """gnt-instance info"""
  AssertCommand(["gnt-instance", "info", instance["name"]])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModify(instance):
  """gnt-instance modify"""
  # Assume /sbin/init exists on all systems
  test_kernel = "/sbin/init"
  test_initrd = test_kernel

  orig_maxmem = qa_config.get(constants.BE_MAXMEM)
  orig_minmem = qa_config.get(constants.BE_MINMEM)
  #orig_bridge = qa_config.get("bridge", "xen-br0")
  args = [
    ["-B", "%s=128" % constants.BE_MINMEM],
    ["-B", "%s=128" % constants.BE_MAXMEM],
    ["-B", "%s=%s,%s=%s" % (constants.BE_MINMEM, orig_minmem,
                            constants.BE_MAXMEM, orig_maxmem)],
    ["-B", "%s=2" % constants.BE_VCPUS],
    ["-B", "%s=1" % constants.BE_VCPUS],
    ["-B", "%s=%s" % (constants.BE_VCPUS, constants.VALUE_DEFAULT)],
    ["-B", "%s=%s" % (constants.BE_ALWAYS_FAILOVER, constants.VALUE_TRUE)],
    ["-B", "%s=%s" % (constants.BE_ALWAYS_FAILOVER, constants.VALUE_DEFAULT)],

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
    AssertCommand(["gnt-instance", "modify"] + alist + [instance["name"]])

  # check no-modify
  AssertCommand(["gnt-instance", "modify", instance["name"]], fail=True)

  # Marking offline/online while instance is running must fail
  for arg in ["--online", "--offline"]:
    AssertCommand(["gnt-instance", "modify", arg, instance["name"]], fail=True)


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceStoppedModify(instance):
  """gnt-instance modify (stopped instance)"""
  name = instance["name"]

  # Instance was not marked offline; try marking it online once more
  AssertCommand(["gnt-instance", "modify", "--online", name])

  # Mark instance as offline
  AssertCommand(["gnt-instance", "modify", "--offline", name])

  # And online again
  AssertCommand(["gnt-instance", "modify", "--online", name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceConvertDisk(instance, snode):
  """gnt-instance modify -t"""
  name = instance["name"]
  AssertCommand(["gnt-instance", "modify", "-t", "plain", name])
  AssertCommand(["gnt-instance", "modify", "-t", "drbd",
                 "-n", snode["primary"], name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceGrowDisk(instance):
  """gnt-instance grow-disk"""
  name = instance["name"]
  all_size = qa_config.get("disk")
  all_grow = qa_config.get("disk-growth")
  if not all_grow:
    # missing disk sizes but instance grow disk has been enabled,
    # let's set fixed/nomimal growth
    all_grow = ["128M" for _ in all_size]
  for idx, (size, grow) in enumerate(zip(all_size, all_grow)):
    # succeed in grow by amount
    AssertCommand(["gnt-instance", "grow-disk", name, str(idx), grow])
    # fail in grow to the old size
    AssertCommand(["gnt-instance", "grow-disk", "--absolute", name, str(idx),
                   size], fail=True)
    # succeed to grow to old size + 2 * growth
    int_size = utils.ParseUnit(size)
    int_grow = utils.ParseUnit(grow)
    AssertCommand(["gnt-instance", "grow-disk", "--absolute", name, str(idx),
                   str(int_size + 2 * int_grow)])


def TestInstanceList():
  """gnt-instance list"""
  qa_utils.GenericQueryTest("gnt-instance", query.INSTANCE_FIELDS.keys())


def TestInstanceListFields():
  """gnt-instance list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-instance", query.INSTANCE_FIELDS.keys())


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceConsole(instance):
  """gnt-instance console"""
  AssertCommand(["gnt-instance", "console", "--show-cmd", instance["name"]])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestReplaceDisks(instance, pnode, snode, othernode):
  """gnt-instance replace-disks"""
  # pylint: disable=W0613
  # due to unused pnode arg
  # FIXME: should be removed from the function completely
  def buildcmd(args):
    cmd = ["gnt-instance", "replace-disks"]
    cmd.extend(args)
    cmd.append(instance["name"])
    return cmd

  for data in [
    ["-p"],
    ["-s"],
    ["--new-secondary=%s" % othernode["primary"]],
    # and restore
    ["--new-secondary=%s" % snode["primary"]],
    ]:
    AssertCommand(buildcmd(data))

  AssertCommand(buildcmd(["-a"]))
  AssertCommand(["gnt-instance", "stop", instance["name"]])
  AssertCommand(buildcmd(["-a"]), fail=True)
  AssertCommand(["gnt-instance", "activate-disks", instance["name"]])
  AssertCommand(buildcmd(["-a"]))
  AssertCommand(["gnt-instance", "start", instance["name"]])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceExport(instance, node):
  """gnt-backup export -n ..."""
  name = instance["name"]
  AssertCommand(["gnt-backup", "export", "-n", node["primary"], name])
  return qa_utils.ResolveInstanceName(name)


@InstanceCheck(INST_UP, None, FIRST_ARG)
def TestInstanceExportWithRemove(instance, node):
  """gnt-backup export --remove-instance"""
  AssertCommand(["gnt-backup", "export", "-n", node["primary"],
                 "--remove-instance", instance["name"]])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceExportNoTarget(instance):
  """gnt-backup export (without target node, should fail)"""
  AssertCommand(["gnt-backup", "export", instance["name"]], fail=True)


@InstanceCheck(None, INST_UP, FIRST_ARG)
def TestInstanceImport(newinst, node, expnode, name):
  """gnt-backup import"""
  cmd = (["gnt-backup", "import",
          "--disk-template=plain",
          "--no-ip-check",
          "--net", "0:mac=generate",
          "--src-node=%s" % expnode["primary"],
          "--src-dir=%s/%s" % (constants.EXPORT_DIR, name),
          "--node=%s" % node["primary"]] +
         _GetGenericAddParameters())
  cmd.append(newinst["name"])
  AssertCommand(cmd)


def TestBackupList(expnode):
  """gnt-backup list"""
  AssertCommand(["gnt-backup", "list", "--node=%s" % expnode["primary"]])

  qa_utils.GenericQueryTest("gnt-backup", query.EXPORT_FIELDS.keys(),
                            namefield=None, test_unknown=False)


def TestBackupListFields():
  """gnt-backup list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-backup", query.EXPORT_FIELDS.keys())


def _TestInstanceDiskFailure(instance, node, node2, onmaster):
  """Testing disk failure."""
  master = qa_config.GetMasterNode()
  sq = utils.ShellQuoteArgs

  instance_full = qa_utils.ResolveInstanceName(instance["name"])
  node_full = qa_utils.ResolveNodeName(node)
  node2_full = qa_utils.ResolveNodeName(node2)

  print qa_utils.FormatInfo("Getting physical disk names")
  cmd = ["gnt-node", "volumes", "--separator=|", "--no-headers",
         "--output=node,phys,instance",
         node["primary"], node2["primary"]]
  output = qa_utils.GetCommandOutput(master["primary"], sq(cmd))

  # Get physical disk names
  re_disk = re.compile(r"^/dev/([a-z]+)\d+$")
  node2disk = {}
  for line in output.splitlines():
    (node_name, phys, inst) = line.split("|")
    if inst == instance_full:
      if node_name not in node2disk:
        node2disk[node_name] = []

      m = re_disk.match(phys)
      if not m:
        raise qa_error.Error("Unknown disk name format: %s" % phys)

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
    AssertCommand(" && ".join(cmds), node=node_name)

  print qa_utils.FormatInfo("Getting device paths")
  cmd = ["gnt-instance", "activate-disks", instance["name"]]
  output = qa_utils.GetCommandOutput(master["primary"], sq(cmd))
  devpath = []
  for line in output.splitlines():
    (_, _, tmpdevpath) = line.split(":")
    devpath.append(tmpdevpath)
  print devpath

  print qa_utils.FormatInfo("Getting drbd device paths")
  cmd = ["gnt-instance", "info", instance["name"]]
  output = qa_utils.GetCommandOutput(master["primary"], sq(cmd))
  pattern = (r"\s+-\s+sd[a-z]+,\s+type:\s+drbd8?,\s+.*$"
             r"\s+primary:\s+(/dev/drbd\d+)\s+")
  drbddevs = re.findall(pattern, output, re.M)
  print drbddevs

  halted_disks = []
  try:
    print qa_utils.FormatInfo("Deactivating disks")
    cmds = []
    for name in node2disk[[node2_full, node_full][int(onmaster)]]:
      halted_disks.append(name)
      cmds.append(sq(["echo", "offline"]) + " >%s" % _GetDiskStatePath(name))
    AssertCommand(" && ".join(cmds), node=[node2, node][int(onmaster)])

    print qa_utils.FormatInfo("Write to disks and give some time to notice"
                              " to notice the problem")
    cmds = []
    for disk in devpath:
      cmds.append(sq(["dd", "count=1", "bs=512", "conv=notrunc",
                      "if=%s" % disk, "of=%s" % disk]))
    for _ in (0, 1, 2):
      AssertCommand(" && ".join(cmds), node=node)
      time.sleep(3)

    print qa_utils.FormatInfo("Debugging info")
    for name in drbddevs:
      AssertCommand(["drbdsetup", name, "show"], node=node)

    AssertCommand(["gnt-instance", "info", instance["name"]])

  finally:
    print qa_utils.FormatInfo("Activating disks again")
    cmds = []
    for name in halted_disks:
      cmds.append(sq(["echo", "running"]) + " >%s" % _GetDiskStatePath(name))
    AssertCommand("; ".join(cmds), node=[node2, node][int(onmaster)])

  if onmaster:
    for name in drbddevs:
      AssertCommand(["drbdsetup", name, "detach"], node=node)
  else:
    for name in drbddevs:
      AssertCommand(["drbdsetup", name, "disconnect"], node=node2)

  # TODO
  #AssertCommand(["vgs"], [node2, node][int(onmaster)])

  print qa_utils.FormatInfo("Making sure disks are up again")
  AssertCommand(["gnt-instance", "replace-disks", instance["name"]])

  print qa_utils.FormatInfo("Restarting instance")
  AssertCommand(["gnt-instance", "shutdown", instance["name"]])
  AssertCommand(["gnt-instance", "startup", instance["name"]])

  AssertCommand(["gnt-cluster", "verify"])


def TestInstanceMasterDiskFailure(instance, node, node2):
  """Testing disk failure on master node."""
  # pylint: disable=W0613
  # due to unused args
  print qa_utils.FormatError("Disk failure on primary node cannot be"
                             " tested due to potential crashes.")
  # The following can cause crashes, thus it's disabled until fixed
  #return _TestInstanceDiskFailure(instance, node, node2, True)


def TestInstanceSecondaryDiskFailure(instance, node, node2):
  """Testing disk failure on secondary node."""
  return _TestInstanceDiskFailure(instance, node, node2, False)
