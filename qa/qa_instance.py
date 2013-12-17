#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
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

import os
import re

from ganeti import utils
from ganeti import constants
from ganeti import query
from ganeti import pathutils

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertCommand, AssertEqual
from qa_utils import InstanceCheck, INST_DOWN, INST_UP, FIRST_ARG, RETURN_VALUE
from qa_instance_utils import CheckSsconfInstanceList, \
                              CreateInstanceDrbd8, \
                              CreateInstanceByDiskTemplate, \
                              CreateInstanceByDiskTemplateOneNode, \
                              GetGenericAddParameters


def _GetDiskStatePath(disk):
  return "/sys/block/%s/device/state" % disk


def GetInstanceInfo(instance):
  """Return information about the actual state of an instance.

  @type instance: string
  @param instance: the instance name
  @return: a dictionary with the following keys:
      - "nodes": instance nodes, a list of strings
      - "volumes": instance volume IDs, a list of strings
      - "drbd-minors": DRBD minors used by the instance, a dictionary where
        keys are nodes, and values are lists of integers (or an empty
        dictionary for non-DRBD instances)
      - "disk-template": instance disk template
      - "storage-type": storage type associated with the instance disk template

  """
  node_elem = r"([^,()]+)(?:\s+\([^)]+\))?"
  # re_nodelist matches a list of nodes returned by gnt-instance info, e.g.:
  #  node1.fqdn
  #  node2.fqdn,node3.fqdn
  #  node4.fqdn (group mygroup, group UUID 01234567-abcd-0123-4567-0123456789ab)
  # FIXME This works with no more than 2 secondaries
  re_nodelist = re.compile(node_elem + "(?:," + node_elem + ")?$")

  info = qa_utils.GetObjectInfo(["gnt-instance", "info", instance])[0]
  nodes = []
  for nodeinfo in info["Nodes"]:
    if "primary" in nodeinfo:
      nodes.append(nodeinfo["primary"])
    elif "secondaries" in nodeinfo:
      nodestr = nodeinfo["secondaries"]
      if nodestr:
        m = re_nodelist.match(nodestr)
        if m:
          nodes.extend(filter(None, m.groups()))
        else:
          nodes.append(nodestr)

  disk_template = info["Disk template"]
  if not disk_template:
    raise qa_error.Error("Can't get instance disk template")
  storage_type = constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template]

  re_drbdnode = re.compile(r"^([^\s,]+),\s+minor=([0-9]+)$")
  vols = []
  drbd_min = {}
  for (count, diskinfo) in enumerate(info["Disks"]):
    (dtype, _) = diskinfo["disk/%s" % count].split(",", 1)
    if dtype == constants.DT_DRBD8:
      for child in diskinfo["child devices"]:
        vols.append(child["logical_id"])
      for key in ["nodeA", "nodeB"]:
        m = re_drbdnode.match(diskinfo[key])
        if not m:
          raise qa_error.Error("Cannot parse DRBD info: %s" % diskinfo[key])
        node = m.group(1)
        minor = int(m.group(2))
        minorlist = drbd_min.setdefault(node, [])
        minorlist.append(minor)
    elif dtype == constants.DT_PLAIN:
      vols.append(diskinfo["logical_id"])

  assert nodes
  assert len(nodes) < 2 or vols
  return {
    "nodes": nodes,
    "volumes": vols,
    "drbd-minors": drbd_min,
    "disk-template": disk_template,
    "storage-type": storage_type,
    }


def _DestroyInstanceDisks(instance):
  """Remove all the backend disks of an instance.

  This is used to simulate HW errors (dead nodes, broken disks...); the
  configuration of the instance is not affected.
  @type instance: dictionary
  @param instance: the instance

  """
  info = GetInstanceInfo(instance.name)
  # FIXME: destruction/removal should be part of the disk class
  if info["storage-type"] == constants.ST_LVM_VG:
    vols = info["volumes"]
    for node in info["nodes"]:
      AssertCommand(["lvremove", "-f"] + vols, node=node)
  elif info["storage-type"] in (constants.ST_FILE, constants.ST_SHARED_FILE):
    # Note that this works for both file and sharedfile, and this is intended.
    storage_dir = qa_config.get("file-storage-dir",
                                pathutils.DEFAULT_FILE_STORAGE_DIR)
    idir = os.path.join(storage_dir, instance.name)
    for node in info["nodes"]:
      AssertCommand(["rm", "-rf", idir], node=node)
  elif info["storage-type"] == constants.ST_DISKLESS:
    pass


def _GetInstanceField(instance, field):
  """Get the value of a field of an instance.

  @type instance: string
  @param instance: Instance name
  @type field: string
  @param field: Name of the field
  @rtype: string

  """
  master = qa_config.GetMasterNode()
  infocmd = utils.ShellQuoteArgs(["gnt-instance", "list", "--no-headers",
                                  "--units", "m", "-o", field, instance])
  return qa_utils.GetCommandOutput(master.primary, infocmd).strip()


def _GetBoolInstanceField(instance, field):
  """Get the Boolean value of a field of an instance.

  @type instance: string
  @param instance: Instance name
  @type field: string
  @param field: Name of the field
  @rtype: bool

  """
  info_out = _GetInstanceField(instance, field)
  if info_out == "Y":
    return True
  elif info_out == "N":
    return False
  else:
    raise qa_error.Error("Field %s of instance %s has a non-Boolean value:"
                         " %s" % (field, instance, info_out))


def _GetNumInstanceField(instance, field):
  """Get a numeric value of a field of an instance.

  @type instance: string
  @param instance: Instance name
  @type field: string
  @param field: Name of the field
  @rtype: int or float

  """
  info_out = _GetInstanceField(instance, field)
  try:
    ret = int(info_out)
  except ValueError:
    try:
      ret = float(info_out)
    except ValueError:
      raise qa_error.Error("Field %s of instance %s has a non-numeric value:"
                           " %s" % (field, instance, info_out))
  return ret


def GetInstanceSpec(instance, spec):
  """Return the current spec for the given parameter.

  @type instance: string
  @param instance: Instance name
  @type spec: string
  @param spec: one of the supported parameters: "memory-size", "cpu-count",
      "disk-count", "disk-size", "nic-count"
  @rtype: tuple
  @return: (minspec, maxspec); minspec and maxspec can be different only for
      memory and disk size

  """
  specmap = {
    "memory-size": ["be/minmem", "be/maxmem"],
    "cpu-count": ["vcpus"],
    "disk-count": ["disk.count"],
    "disk-size": ["disk.size/ "],
    "nic-count": ["nic.count"],
    }
  # For disks, first we need the number of disks
  if spec == "disk-size":
    (numdisk, _) = GetInstanceSpec(instance, "disk-count")
    fields = ["disk.size/%s" % k for k in range(0, numdisk)]
  else:
    assert spec in specmap, "%s not in %s" % (spec, specmap)
    fields = specmap[spec]
  values = [_GetNumInstanceField(instance, f) for f in fields]
  return (min(values), max(values))


def IsFailoverSupported(instance):
  return instance.disk_template in constants.DTS_MIRRORED


def IsMigrationSupported(instance):
  return instance.disk_template in constants.DTS_MIRRORED


def IsDiskReplacingSupported(instance):
  return instance.disk_template == constants.DT_DRBD8


def IsDiskSupported(instance):
  return instance.disk_template != constants.DT_DISKLESS


def TestInstanceAddWithPlainDisk(nodes, fail=False):
  """gnt-instance add -t plain"""
  if constants.DT_PLAIN in qa_config.GetEnabledDiskTemplates():
    instance = CreateInstanceByDiskTemplateOneNode(nodes, constants.DT_PLAIN,
                                                    fail=fail)
    if not fail:
      qa_utils.RunInstanceCheck(instance, True)
    return instance


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddWithDrbdDisk(nodes):
  """gnt-instance add -t drbd"""
  if constants.DT_DRBD8 in qa_config.GetEnabledDiskTemplates():
    return CreateInstanceDrbd8(nodes)


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddFile(nodes):
  """gnt-instance add -t file"""
  assert len(nodes) == 1
  if constants.DT_FILE in qa_config.GetEnabledDiskTemplates():
    return CreateInstanceByDiskTemplateOneNode(nodes, constants.DT_FILE)


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddSharedFile(nodes):
  """gnt-instance add -t sharedfile"""
  assert len(nodes) == 1
  if constants.DT_SHARED_FILE in qa_config.GetEnabledDiskTemplates():
    return CreateInstanceByDiskTemplateOneNode(nodes, constants.DT_SHARED_FILE)


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddDiskless(nodes):
  """gnt-instance add -t diskless"""
  assert len(nodes) == 1
  if constants.DT_DISKLESS in qa_config.GetEnabledDiskTemplates():
    return CreateInstanceByDiskTemplateOneNode(nodes, constants.DT_DISKLESS)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceRemove(instance):
  """gnt-instance remove"""
  AssertCommand(["gnt-instance", "remove", "-f", instance.name])


@InstanceCheck(INST_DOWN, INST_UP, FIRST_ARG)
def TestInstanceStartup(instance):
  """gnt-instance startup"""
  AssertCommand(["gnt-instance", "startup", instance.name])


@InstanceCheck(INST_UP, INST_DOWN, FIRST_ARG)
def TestInstanceShutdown(instance):
  """gnt-instance shutdown"""
  AssertCommand(["gnt-instance", "shutdown", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceReboot(instance):
  """gnt-instance reboot"""
  options = qa_config.get("options", {})
  reboot_types = options.get("reboot-types", constants.REBOOT_TYPES)
  name = instance.name
  for rtype in reboot_types:
    AssertCommand(["gnt-instance", "reboot", "--type=%s" % rtype, name])

  AssertCommand(["gnt-instance", "shutdown", name])
  qa_utils.RunInstanceCheck(instance, False)
  AssertCommand(["gnt-instance", "reboot", name])

  master = qa_config.GetMasterNode()
  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_RUNNING)


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceReinstall(instance):
  """gnt-instance reinstall"""
  if instance.disk_template == constants.DT_DISKLESS:
    print qa_utils.FormatInfo("Test not supported for diskless instances")
    return

  AssertCommand(["gnt-instance", "reinstall", "-f", instance.name])

  # Test with non-existant OS definition
  AssertCommand(["gnt-instance", "reinstall", "-f",
                 "--os-type=NonExistantOsForQa",
                 instance.name],
                fail=True)


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceRenameAndBack(rename_source, rename_target):
  """gnt-instance rename

  This must leave the instance with the original name, not the target
  name.

  """
  CheckSsconfInstanceList(rename_source)

  # first do a rename to a different actual name, expecting it to fail
  qa_utils.AddToEtcHosts(["meeeeh-not-exists", rename_target])
  try:
    AssertCommand(["gnt-instance", "rename", rename_source, rename_target],
                  fail=True)
    CheckSsconfInstanceList(rename_source)
  finally:
    qa_utils.RemoveFromEtcHosts(["meeeeh-not-exists", rename_target])

  info = GetInstanceInfo(rename_source)

  # Check instance volume tags correctly updated. Note that this check is lvm
  # specific, so we skip it for non-lvm-based instances.
  # FIXME: This will need updating when instances will be able to have
  # different disks living on storage pools with etherogeneous storage types.
  # FIXME: This check should be put inside the disk/storage class themselves,
  # rather than explicitly called here.
  if info["storage-type"] == constants.ST_LVM_VG:
    # In the lvm world we can check for tags on the logical volume
    tags_cmd = ("lvs -o tags --noheadings %s | grep " %
                (" ".join(info["volumes"]), ))
  else:
    # Other storage types don't have tags, so we use an always failing command,
    # to make sure it never gets executed
    tags_cmd = "false"

  # and now rename instance to rename_target...
  AssertCommand(["gnt-instance", "rename", rename_source, rename_target])
  CheckSsconfInstanceList(rename_target)
  qa_utils.RunInstanceCheck(rename_source, False)
  qa_utils.RunInstanceCheck(rename_target, False)

  # NOTE: tags might not be the exactly as the instance name, due to
  # charset restrictions; hence the test might be flaky
  if (rename_source != rename_target and
      info["storage-type"] == constants.ST_LVM_VG):
    for node in info["nodes"]:
      AssertCommand(tags_cmd + rename_source, node=node, fail=True)
      AssertCommand(tags_cmd + rename_target, node=node, fail=False)

  # and back
  AssertCommand(["gnt-instance", "rename", rename_target, rename_source])
  CheckSsconfInstanceList(rename_source)
  qa_utils.RunInstanceCheck(rename_target, False)

  if (rename_source != rename_target and
      info["storage-type"] == constants.ST_LVM_VG):
    for node in info["nodes"]:
      AssertCommand(tags_cmd + rename_source, node=node, fail=False)
      AssertCommand(tags_cmd + rename_target, node=node, fail=True)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceFailover(instance):
  """gnt-instance failover"""
  if not IsFailoverSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support failover, skipping"
                              " test")
    return

  cmd = ["gnt-instance", "failover", "--force", instance.name]

  # failover ...
  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)

  # ... and back
  AssertCommand(cmd)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceMigrate(instance, toggle_always_failover=True):
  """gnt-instance migrate"""
  if not IsMigrationSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support migration, skipping"
                              " test")
    return

  cmd = ["gnt-instance", "migrate", "--force", instance.name]
  af_par = constants.BE_ALWAYS_FAILOVER
  af_field = "be/" + constants.BE_ALWAYS_FAILOVER
  af_init_val = _GetBoolInstanceField(instance.name, af_field)

  # migrate ...
  AssertCommand(cmd)
  # TODO: Verify the choice between failover and migration
  qa_utils.RunInstanceCheck(instance, True)

  # ... and back (possibly with always_failover toggled)
  if toggle_always_failover:
    AssertCommand(["gnt-instance", "modify", "-B",
                   ("%s=%s" % (af_par, not af_init_val)),
                   instance.name])
  AssertCommand(cmd)
  # TODO: Verify the choice between failover and migration
  qa_utils.RunInstanceCheck(instance, True)
  if toggle_always_failover:
    AssertCommand(["gnt-instance", "modify", "-B",
                   ("%s=%s" % (af_par, af_init_val)), instance.name])

  # TODO: Split into multiple tests
  AssertCommand(["gnt-instance", "shutdown", instance.name])
  qa_utils.RunInstanceCheck(instance, False)
  AssertCommand(cmd, fail=True)
  AssertCommand(["gnt-instance", "migrate", "--force", "--allow-failover",
                 instance.name])
  AssertCommand(["gnt-instance", "start", instance.name])
  AssertCommand(cmd)
  # @InstanceCheck enforces the check that the instance is running
  qa_utils.RunInstanceCheck(instance, True)

  AssertCommand(["gnt-instance", "modify", "-B",
                 ("%s=%s" %
                  (constants.BE_ALWAYS_FAILOVER, constants.VALUE_TRUE)),
                 instance.name])

  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)
  # TODO: Verify that a failover has been done instead of a migration

  # TODO: Verify whether the default value is restored here (not hardcoded)
  AssertCommand(["gnt-instance", "modify", "-B",
                 ("%s=%s" %
                  (constants.BE_ALWAYS_FAILOVER, constants.VALUE_FALSE)),
                 instance.name])

  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)


def TestInstanceInfo(instance):
  """gnt-instance info"""
  AssertCommand(["gnt-instance", "info", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModify(instance):
  """gnt-instance modify"""
  default_hv = qa_config.GetDefaultHypervisor()

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

    # TODO: bridge tests
    #["--bridge", "xen-br1"],
    #["--bridge", orig_bridge],
    ]

  if default_hv == constants.HT_XEN_PVM:
    args.extend([
      ["-H", "%s=%s" % (constants.HV_INITRD_PATH, test_initrd)],
      ["-H", "no_%s" % (constants.HV_INITRD_PATH, )],
      ["-H", "%s=%s" % (constants.HV_INITRD_PATH, constants.VALUE_DEFAULT)],
      ])
  elif default_hv == constants.HT_XEN_HVM:
    args.extend([
      ["-H", "%s=acn" % constants.HV_BOOT_ORDER],
      ["-H", "%s=%s" % (constants.HV_BOOT_ORDER, constants.VALUE_DEFAULT)],
      ])
  elif default_hv == constants.HT_KVM and \
    qa_config.TestEnabled("instance-device-hotplug"):
    args.extend([
      ["--net", "-1:add", "--hotplug"],
      ["--net", "-1:modify,mac=aa:bb:cc:dd:ee:ff", "--hotplug", "--force"],
      ["--net", "-1:remove", "--hotplug"],
      ["--disk", "-1:add,size=1G", "--hotplug"],
      ["--disk", "-1:remove", "--hotplug"],
      ])

  for alist in args:
    AssertCommand(["gnt-instance", "modify"] + alist + [instance.name])

  # check no-modify
  AssertCommand(["gnt-instance", "modify", instance.name], fail=True)

  # Marking offline while instance is running must fail...
  AssertCommand(["gnt-instance", "modify", "--offline", instance.name],
                 fail=True)

  # ...while making it online is ok, and should work
  AssertCommand(["gnt-instance", "modify", "--online", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModifyPrimaryAndBack(instance, currentnode, othernode):
  """gnt-instance modify --new-primary

  This will leave the instance on its original primary node, not other node.

  """
  if instance.disk_template != constants.DT_FILE:
    print qa_utils.FormatInfo("Test only supported for the file disk template")
    return

  cluster_name = qa_config.get("name")

  name = instance.name
  current = currentnode.primary
  other = othernode.primary

  filestorage = qa_config.get("file-storage-dir",
                              pathutils.DEFAULT_FILE_STORAGE_DIR)
  disk = os.path.join(filestorage, name)

  AssertCommand(["gnt-instance", "modify", "--new-primary=%s" % other, name],
                fail=True)
  AssertCommand(["gnt-instance", "shutdown", name])
  AssertCommand(["scp", "-oGlobalKnownHostsFile=%s" %
                 pathutils.SSH_KNOWN_HOSTS_FILE,
                 "-oCheckHostIp=no", "-oStrictHostKeyChecking=yes",
                 "-oHashKnownHosts=no", "-oHostKeyAlias=%s" % cluster_name,
                 "-r", disk, "%s:%s" % (other, filestorage)], node=current)
  AssertCommand(["gnt-instance", "modify", "--new-primary=%s" % other, name])
  AssertCommand(["gnt-instance", "startup", name])

  # and back
  AssertCommand(["gnt-instance", "shutdown", name])
  AssertCommand(["rm", "-rf", disk], node=other)
  AssertCommand(["gnt-instance", "modify", "--new-primary=%s" % current, name])
  AssertCommand(["gnt-instance", "startup", name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceStoppedModify(instance):
  """gnt-instance modify (stopped instance)"""
  name = instance.name

  # Instance was not marked offline; try marking it online once more
  AssertCommand(["gnt-instance", "modify", "--online", name])

  # Mark instance as offline
  AssertCommand(["gnt-instance", "modify", "--offline", name])

  # When the instance is offline shutdown should only work with --force,
  # while start should never work
  AssertCommand(["gnt-instance", "shutdown", name], fail=True)
  AssertCommand(["gnt-instance", "shutdown", "--force", name])
  AssertCommand(["gnt-instance", "start", name], fail=True)
  AssertCommand(["gnt-instance", "start", "--force", name], fail=True)

  # Also do offline to offline
  AssertCommand(["gnt-instance", "modify", "--offline", name])

  # And online again
  AssertCommand(["gnt-instance", "modify", "--online", name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceConvertDiskToPlain(instance, inodes):
  """gnt-instance modify -t"""
  name = instance.name

  template = instance.disk_template
  if template != constants.DT_DRBD8:
    print qa_utils.FormatInfo("Unsupported template %s, skipping conversion"
                              " test" % template)
    return

  assert len(inodes) == 2
  AssertCommand(["gnt-instance", "modify", "-t", constants.DT_PLAIN, name])
  AssertCommand(["gnt-instance", "modify", "-t", constants.DT_DRBD8,
                 "-n", inodes[1].primary, name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModifyDisks(instance):
  """gnt-instance modify --disk"""
  if not IsDiskSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support disks, skipping test")
    return

  disk_conf = qa_config.GetDiskOptions()[-1]
  size = disk_conf.get("size")
  name = instance.name
  build_cmd = lambda arg: ["gnt-instance", "modify", "--disk", arg, name]
  if qa_config.AreSpindlesSupported():
    spindles = disk_conf.get("spindles")
    spindles_supported = True
  else:
    # Any number is good for spindles in this case
    spindles = 1
    spindles_supported = False
  AssertCommand(build_cmd("add:size=%s,spindles=%s" % (size, spindles)),
                fail=not spindles_supported)
  AssertCommand(build_cmd("add:size=%s" % size),
                fail=spindles_supported)
  # Exactly one of the above commands has succeded, so we need one remove
  AssertCommand(build_cmd("remove"))


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceGrowDisk(instance):
  """gnt-instance grow-disk"""
  if instance.disk_template == constants.DT_DISKLESS:
    print qa_utils.FormatInfo("Test not supported for diskless instances")
    return

  name = instance.name
  disks = qa_config.GetDiskOptions()
  all_size = [d.get("size") for d in disks]
  all_grow = [d.get("growth") for d in disks]

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


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceDeviceNames(instance):
  if instance.disk_template == constants.DT_DISKLESS:
    print qa_utils.FormatInfo("Test not supported for diskless instances")
    return

  name = instance.name
  for dev_type in ["disk", "net"]:
    if dev_type == "disk":
      options = ",size=512M"
      if qa_config.AreSpindlesSupported():
        options += ",spindles=1"
    else:
      options = ""
    # succeed in adding a device named 'test_device'
    AssertCommand(["gnt-instance", "modify",
                   "--%s=-1:add,name=test_device%s" % (dev_type, options),
                   name])
    # succeed in removing the 'test_device'
    AssertCommand(["gnt-instance", "modify",
                   "--%s=test_device:remove" % dev_type,
                   name])
    # fail to add two devices with the same name
    AssertCommand(["gnt-instance", "modify",
                   "--%s=-1:add,name=test_device%s" % (dev_type, options),
                   "--%s=-1:add,name=test_device%s" % (dev_type, options),
                   name], fail=True)
    # fail to add a device with invalid name
    AssertCommand(["gnt-instance", "modify",
                   "--%s=-1:add,name=2%s" % (dev_type, options),
                   name], fail=True)
  # Rename disks
  disks = qa_config.GetDiskOptions()
  disk_names = [d.get("name") for d in disks]
  for idx, disk_name in enumerate(disk_names):
    # Refer to disk by idx
    AssertCommand(["gnt-instance", "modify",
                   "--disk=%s:modify,name=renamed" % idx,
                   name])
    # Refer to by name and rename to original name
    AssertCommand(["gnt-instance", "modify",
                   "--disk=renamed:modify,name=%s" % disk_name,
                   name])
  if len(disks) >= 2:
    # fail in renaming to disks to the same name
    AssertCommand(["gnt-instance", "modify",
                   "--disk=0:modify,name=same_name",
                   "--disk=1:modify,name=same_name",
                   name], fail=True)


def TestInstanceList():
  """gnt-instance list"""
  qa_utils.GenericQueryTest("gnt-instance", query.INSTANCE_FIELDS.keys())


def TestInstanceListFields():
  """gnt-instance list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-instance", query.INSTANCE_FIELDS.keys())


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceConsole(instance):
  """gnt-instance console"""
  AssertCommand(["gnt-instance", "console", "--show-cmd", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestReplaceDisks(instance, curr_nodes, other_nodes):
  """gnt-instance replace-disks"""
  def buildcmd(args):
    cmd = ["gnt-instance", "replace-disks"]
    cmd.extend(args)
    cmd.append(instance.name)
    return cmd

  if not IsDiskReplacingSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support disk replacing,"
                              " skipping test")
    return

  # Currently all supported templates have one primary and one secondary node
  assert len(curr_nodes) == 2
  snode = curr_nodes[1]
  assert len(other_nodes) == 1
  othernode = other_nodes[0]

  options = qa_config.get("options", {})
  use_ialloc = options.get("use-iallocators", True)
  for data in [
    ["-p"],
    ["-s"],
    # A placeholder; the actual command choice depends on use_ialloc
    None,
    # Restore the original secondary
    ["--new-secondary=%s" % snode.primary],
    ]:
    if data is None:
      if use_ialloc:
        data = ["-I", constants.DEFAULT_IALLOCATOR_SHORTCUT]
      else:
        data = ["--new-secondary=%s" % othernode.primary]
    AssertCommand(buildcmd(data))

  AssertCommand(buildcmd(["-a"]))
  AssertCommand(["gnt-instance", "stop", instance.name])
  AssertCommand(buildcmd(["-a"]), fail=True)
  AssertCommand(["gnt-instance", "activate-disks", instance.name])
  AssertCommand(["gnt-instance", "activate-disks", "--wait-for-sync",
                 instance.name])
  AssertCommand(buildcmd(["-a"]))
  AssertCommand(["gnt-instance", "start", instance.name])


def _AssertRecreateDisks(cmdargs, instance, fail=False, check=True,
                         destroy=True):
  """Execute gnt-instance recreate-disks and check the result

  @param cmdargs: Arguments (instance name excluded)
  @param instance: Instance to operate on
  @param fail: True if the command is expected to fail
  @param check: If True and fail is False, check that the disks work
  @prama destroy: If True, destroy the old disks first

  """
  if destroy:
    _DestroyInstanceDisks(instance)
  AssertCommand((["gnt-instance", "recreate-disks"] + cmdargs +
                 [instance.name]), fail)
  if not fail and check:
    # Quick check that the disks are there
    AssertCommand(["gnt-instance", "activate-disks", instance.name])
    AssertCommand(["gnt-instance", "activate-disks", "--wait-for-sync",
                   instance.name])
    AssertCommand(["gnt-instance", "deactivate-disks", instance.name])


def _BuildRecreateDisksOpts(en_disks, with_spindles, with_growth,
                            spindles_supported):
  if with_spindles:
    if spindles_supported:
      if with_growth:
        build_spindles_opt = (lambda disk:
                              ",spindles=%s" %
                              (disk["spindles"] + disk["spindles-growth"]))
      else:
        build_spindles_opt = (lambda disk:
                              ",spindles=%s" % disk["spindles"])
    else:
      build_spindles_opt = (lambda _: ",spindles=1")
  else:
    build_spindles_opt = (lambda _: "")
  if with_growth:
    build_size_opt = (lambda disk:
                      "size=%s" % (utils.ParseUnit(disk["size"]) +
                                   utils.ParseUnit(disk["growth"])))
  else:
    build_size_opt = (lambda disk: "size=%s" % disk["size"])
  build_disk_opt = (lambda (idx, disk):
                    "--disk=%s:%s%s" % (idx, build_size_opt(disk),
                                        build_spindles_opt(disk)))
  return map(build_disk_opt, en_disks)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRecreateDisks(instance, inodes, othernodes):
  """gnt-instance recreate-disks

  @param instance: Instance to work on
  @param inodes: List of the current nodes of the instance
  @param othernodes: list/tuple of nodes where to temporarily recreate disks

  """
  options = qa_config.get("options", {})
  use_ialloc = options.get("use-iallocators", True)
  other_seq = ":".join([n.primary for n in othernodes])
  orig_seq = ":".join([n.primary for n in inodes])
  # These fail because the instance is running
  _AssertRecreateDisks(["-n", other_seq], instance, fail=True, destroy=False)
  if use_ialloc:
    _AssertRecreateDisks(["-I", "hail"], instance, fail=True, destroy=False)
  else:
    _AssertRecreateDisks(["-n", other_seq], instance, fail=True, destroy=False)
  AssertCommand(["gnt-instance", "stop", instance.name])
  # Disks exist: this should fail
  _AssertRecreateDisks([], instance, fail=True, destroy=False)
  # Unsupported spindles parameters: fail
  if not qa_config.AreSpindlesSupported():
    _AssertRecreateDisks(["--disk=0:spindles=2"], instance,
                         fail=True, destroy=False)
  # Recreate disks in place
  _AssertRecreateDisks([], instance)
  # Move disks away
  if use_ialloc:
    _AssertRecreateDisks(["-I", "hail"], instance)
    # Move disks somewhere else
    _AssertRecreateDisks(["-I", constants.DEFAULT_IALLOCATOR_SHORTCUT],
                         instance)
  else:
    _AssertRecreateDisks(["-n", other_seq], instance)
  # Move disks back
  _AssertRecreateDisks(["-n", orig_seq], instance)
  # Recreate resized disks
  # One of the two commands fails because either spindles are given when they
  # should not or vice versa
  alldisks = qa_config.GetDiskOptions()
  spindles_supported = qa_config.AreSpindlesSupported()
  disk_opts = _BuildRecreateDisksOpts(enumerate(alldisks), True, True,
                                      spindles_supported)
  _AssertRecreateDisks(disk_opts, instance, destroy=True,
                       fail=not spindles_supported)
  disk_opts = _BuildRecreateDisksOpts(enumerate(alldisks), False, True,
                                      spindles_supported)
  _AssertRecreateDisks(disk_opts, instance, destroy=False,
                       fail=spindles_supported)
  # Recreate the disks one by one (with the original size)
  for (idx, disk) in enumerate(alldisks):
    # Only the first call should destroy all the disk
    destroy = (idx == 0)
    # Again, one of the two commands is expected to fail
    disk_opts = _BuildRecreateDisksOpts([(idx, disk)], True, False,
                                        spindles_supported)
    _AssertRecreateDisks(disk_opts, instance, destroy=destroy, check=False,
                         fail=not spindles_supported)
    disk_opts = _BuildRecreateDisksOpts([(idx, disk)], False, False,
                                        spindles_supported)
    _AssertRecreateDisks(disk_opts, instance, destroy=False, check=False,
                         fail=spindles_supported)
  # This and InstanceCheck decoration check that the disks are working
  AssertCommand(["gnt-instance", "reinstall", "-f", instance.name])
  AssertCommand(["gnt-instance", "start", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceExport(instance, node):
  """gnt-backup export -n ..."""
  name = instance.name
  # Export does not work for file-based templates, thus we skip the test
  if instance.disk_template in [constants.DT_FILE, constants.DT_SHARED_FILE]:
    return
  AssertCommand(["gnt-backup", "export", "-n", node.primary, name])
  return qa_utils.ResolveInstanceName(name)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceExportWithRemove(instance, node):
  """gnt-backup export --remove-instance"""
  AssertCommand(["gnt-backup", "export", "-n", node.primary,
                 "--remove-instance", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceExportNoTarget(instance):
  """gnt-backup export (without target node, should fail)"""
  AssertCommand(["gnt-backup", "export", instance.name], fail=True)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceImport(newinst, node, expnode, name):
  """gnt-backup import"""
  templ = constants.DT_PLAIN
  if not qa_config.IsTemplateSupported(templ):
    return
  cmd = (["gnt-backup", "import",
          "--disk-template=%s" % templ,
          "--no-ip-check",
          "--src-node=%s" % expnode.primary,
          "--src-dir=%s/%s" % (pathutils.EXPORT_DIR, name),
          "--node=%s" % node.primary] +
         GetGenericAddParameters(newinst, templ,
                                  force_mac=constants.VALUE_GENERATE))
  cmd.append(newinst.name)
  AssertCommand(cmd)
  newinst.SetDiskTemplate(templ)


def TestBackupList(expnode):
  """gnt-backup list"""
  AssertCommand(["gnt-backup", "list", "--node=%s" % expnode.primary])

  qa_utils.GenericQueryTest("gnt-backup", query.EXPORT_FIELDS.keys(),
                            namefield=None, test_unknown=False)


def TestBackupListFields():
  """gnt-backup list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-backup", query.EXPORT_FIELDS.keys())


def TestRemoveInstanceOfflineNode(instance, snode, set_offline, set_online):
  """gnt-instance remove with an off-line node

  @param instance: instance
  @param snode: secondary node, to be set offline
  @param set_offline: function to call to set the node off-line
  @param set_online: function to call to set the node on-line

  """
  info = GetInstanceInfo(instance.name)
  set_offline(snode)
  try:
    TestInstanceRemove(instance)
  finally:
    set_online(snode)

  # Clean up the disks on the offline node, if necessary
  if instance.disk_template not in constants.DTS_EXT_MIRROR:
    # FIXME: abstract the cleanup inside the disks
    if info["storage-type"] == constants.ST_LVM_VG:
      for minor in info["drbd-minors"][snode.primary]:
        # DRBD 8.3 syntax comes first, then DRBD 8.4 syntax. The 8.4 syntax
        # relies on the fact that we always create a resources for each minor,
        # and that this resources is always named resource{minor}.
        # As 'drbdsetup 0 down' does return success (even though that's invalid
        # syntax), we always have to perform both commands and ignore the
        # output.
        drbd_shutdown_cmd = \
          "(drbdsetup %d down >/dev/null 2>&1;" \
          " drbdsetup down resource%d >/dev/null 2>&1) || /bin/true" % \
            (minor, minor)
        AssertCommand(drbd_shutdown_cmd, node=snode)
      AssertCommand(["lvremove", "-f"] + info["volumes"], node=snode)
    elif info["storage-type"] == constants.ST_FILE:
      filestorage = qa_config.get("file-storage-dir",
                                  pathutils.DEFAULT_FILE_STORAGE_DIR)
      disk = os.path.join(filestorage, instance.name)
      AssertCommand(["rm", "-rf", disk], node=snode)


def TestInstanceCreationRestrictedByDiskTemplates():
  """Test adding instances for disabled disk templates."""
  if qa_config.TestEnabled("cluster-exclusive-storage"):
    # These tests are valid only for non-exclusive storage
    return

  enabled_disk_templates = qa_config.GetEnabledDiskTemplates()
  nodes = qa_config.AcquireManyNodes(2)

  # Setup the cluster with the enabled_disk_templates
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % ",".join(enabled_disk_templates),
     "--ipolicy-disk-templates=%s" % ",".join(enabled_disk_templates)],
    fail=False)

  # Test instance creation for enabled disk templates
  for disk_template in enabled_disk_templates:
    instance = CreateInstanceByDiskTemplate(nodes, disk_template, fail=False)
    TestInstanceRemove(instance)
    instance.Release()

  # Test that instance creation fails for disabled disk templates
  disabled_disk_templates = list(constants.DISK_TEMPLATES
                                 - set(enabled_disk_templates))
  for disk_template in disabled_disk_templates:
    instance = CreateInstanceByDiskTemplate(nodes, disk_template, fail=True)

  # Test instance creation for after disabling enabled disk templates
  if (len(enabled_disk_templates) > 1):
    # Partition the disk templates, enable them separately and check if the
    # disabled ones cannot be used by instances.
    middle = len(enabled_disk_templates) / 2
    templates1 = enabled_disk_templates[:middle]
    templates2 = enabled_disk_templates[middle:]

    for (enabled, disabled) in [(templates1, templates2),
                                (templates2, templates1)]:
      AssertCommand(["gnt-cluster", "modify",
                     "--enabled-disk-templates=%s" % ",".join(enabled),
                     "--ipolicy-disk-templates=%s" % ",".join(enabled)],
                    fail=False)
      for disk_template in disabled:
        CreateInstanceByDiskTemplate(nodes, disk_template, fail=True)
  elif (len(enabled_disk_templates) == 1):
    # If only one disk template is enabled in the QA config, we have to enable
    # some other templates in order to test if the disabling the only enabled
    # disk template prohibits creating instances of that template.
    other_disk_templates = list(
                             set([constants.DT_DISKLESS, constants.DT_BLOCK]) -
                             set(enabled_disk_templates))
    AssertCommand(["gnt-cluster", "modify",
                   "--enabled-disk-templates=%s" %
                     ",".join(other_disk_templates),
                   "--ipolicy-disk-templates=%s" %
                     ",".join(other_disk_templates)],
                  fail=False)
    CreateInstanceByDiskTemplate(nodes, enabled_disk_templates[0], fail=True)
  else:
    raise qa_error.Error("Please enable at least one disk template"
                         " in your QA setup.")

  # Restore initially enabled disk templates
  AssertCommand(["gnt-cluster", "modify",
                 "--enabled-disk-templates=%s" %
                   ",".join(enabled_disk_templates),
                 "--ipolicy-disk-templates=%s" %
                   ",".join(enabled_disk_templates)],
                 fail=False)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def _TestInstanceUserDown(instance, master, hv_shutdown_fn):
  # Shutdown instance in Xen and bring instance status to 'USER_down'
  hv_shutdown_fn()

  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", instance.name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_USERDOWN)

  # Fail to bring instance status to 'running'
  AssertCommand(["gnt-instance", "start", instance.name], fail=True)

  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", instance.name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_USERDOWN)

  # Bring instance status to 'ADMIN_down'
  AssertCommand(["gnt-instance", "shutdown", instance.name])

  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", instance.name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_ADMINDOWN)

  # Bring instance status to 'running'
  AssertCommand(["gnt-instance", "start", instance.name])

  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", instance.name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_RUNNING)

  # Bring instance status to 'ADMIN_down' forcibly
  AssertCommand(["gnt-instance", "shutdown", "-f", instance.name])

  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", instance.name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_ADMINDOWN)

  # Bring instance status to 'running'
  AssertCommand(["gnt-instance", "start", instance.name])

  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", instance.name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_RUNNING)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def _TestInstanceUserDownXen(instance, master):
  primary = _GetInstanceField(instance.name, "pnode")
  fn = lambda: AssertCommand(["xm", "shutdown", "-w", instance.name],
                             fail=False, node=primary)
  _TestInstanceUserDown(instance, master, fn)


# FIXME: User shutdown is not implemented for KVM yet
#
# @InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
# def _TestInstanceUserDownKvm(instance, master):
#   fn = lambda: hv_kvm.KVMHypervisor._StopInstance(None, True, instance.name)
#   _TestInstanceUserDown(instance, master, fn)
#
def _TestInstanceUserDownKvm(_1, _2):
  pass


def TestInstanceUserDown(instance, master):
  """Tests user shutdown"""
  enabled_hypervisors = qa_config.GetEnabledHypervisors()

  for (hv, fn) in [(constants.HT_XEN_PVM, _TestInstanceUserDownXen),
                   (constants.HT_XEN_HVM, _TestInstanceUserDownXen),
                   (constants.HT_KVM, _TestInstanceUserDownKvm)]:
    if hv in enabled_hypervisors:
      fn(instance, master)
    else:
      print "%s hypervisor is not enabled, skipping test for this hypervisor" \
          % hv


available_instance_tests = [
  ("instance-add-plain-disk", constants.DT_PLAIN,
   TestInstanceAddWithPlainDisk, 1),
  ("instance-add-drbd-disk", constants.DT_DRBD8,
   TestInstanceAddWithDrbdDisk, 2),
  ("instance-add-diskless", constants.DT_DISKLESS,
   TestInstanceAddDiskless, 1),
  ("instance-add-file", constants.DT_FILE,
   TestInstanceAddFile, 1),
  ("instance-add-shared-file", constants.DT_SHARED_FILE,
   TestInstanceAddSharedFile, 1),
  ]
