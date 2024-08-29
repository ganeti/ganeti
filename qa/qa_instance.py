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


"""Instance related QA tests.

"""

import os
import re
import time
import yaml

from ganeti import utils
from ganeti import constants
from ganeti import pathutils
from ganeti import query
from ganeti.netutils import IP4Address

from qa import qa_config
from qa import qa_daemon
from qa import qa_utils
from qa import qa_error

from qa_filters import stdout_of
from qa_utils import AssertCommand, AssertEqual, AssertIn
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
      - "hypervisor-parameters": all hypervisor parameters for this instance

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
          nodes.extend([n for n in m.groups() if n])
        else:
          nodes.append(nodestr)

  re_drbdnode = re.compile(r"^([^\s,]+),\s+minor=([0-9]+)$")
  vols = []
  drbd_min = {}
  dtypes = []
  for (count, diskinfo) in enumerate(info["Disks"]):
    (dtype, _) = diskinfo["disk/%s" % count].split(",", 1)
    dtypes.append(dtype)
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

  # TODO remove and modify calling sites
  disk_template = utils.GetDiskTemplateString(dtypes)
  storage_type = constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template]

  hvparams = {}
  # make sure to not iterate on hypervisors w/o parameters (e.g. fake HV)
  if isinstance(info["Hypervisor parameters"], dict):
    for param, value in info["Hypervisor parameters"].items():
      if type(value) == str and value.startswith("default ("):
          result = re.search(r'^default \((.*)\)$', value)
          try:
              value = yaml.load(result.group(1), Loader=yaml.SafeLoader)
          except yaml.YAMLError:
              value = ''
      hvparams[param] = value

  assert nodes
  assert len(nodes) < 2 or vols
  return {
    "nodes": nodes,
    "volumes": vols,
    "drbd-minors": drbd_min,
    "disk-template": disk_template,
    "storage-type": storage_type,
    "hypervisor-parameters": hvparams,
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


def _GetInstanceFields(instance, fields):
  """Get the value of one or more fields of an instance.

  @type instance: string
  @param instance: instance name

  @type field: list of string
  @param field: name of the fields

  @rtype: list of string
  @return: value of the fields

  """
  master = qa_config.GetMasterNode()
  infocmd = utils.ShellQuoteArgs(["gnt-instance", "list", "--no-headers",
                                  "--separator=:", "--units", "m", "-o",
                                  ",".join(fields), instance])
  return tuple(qa_utils.GetCommandOutput(master.primary, infocmd)
               .strip()
               .split(":"))


def _GetInstanceField(instance, field):
  """Get the value of a field of an instance.

  @type instance: string
  @param instance: Instance name
  @type field: string
  @param field: Name of the field
  @rtype: string

  """
  return _GetInstanceFields(instance, [field])[0]


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


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddRADOSBlockDevice(nodes):
  """gnt-instance add -t rbd"""
  assert len(nodes) == 1
  if constants.DT_RBD in qa_config.GetEnabledDiskTemplates():
    return CreateInstanceByDiskTemplateOneNode(nodes, constants.DT_RBD)


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddGluster(nodes):
  """gnt-instance add -t gluster"""
  assert len(nodes) == 1
  if constants.DT_GLUSTER in qa_config.GetEnabledDiskTemplates():
    return CreateInstanceByDiskTemplateOneNode(nodes, constants.DT_GLUSTER)


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
    print(qa_utils.FormatInfo("Test not supported for diskless instances"))
    return

  qa_storage = qa_config.get("qa-storage")

  if qa_storage is None:
    print(qa_utils.FormatInfo("Test not supported because the additional QA"
                              " storage is not available"))
  else:
    # Reinstall with OS image from QA storage
    url = "%s/busybox.img" % qa_storage
    AssertCommand(["gnt-instance", "reinstall",
                   "--os-parameters", "os-image=" + url,
                   "-f", instance.name])

    # Reinstall with OS image as local file on the node
    pnode = _GetInstanceField(instance.name, "pnode")

    cmd = ("wget -O busybox.img %s &> /dev/null &&"
           " echo $(pwd)/busybox.img") % url
    image = qa_utils.GetCommandOutput(pnode, cmd).strip()

    AssertCommand(["gnt-instance", "reinstall",
                   "--os-parameters", "os-image=" + image,
                   "-f", instance.name])

  # Reinstall non existing local file
  AssertCommand(["gnt-instance", "reinstall",
                 "--os-parameters", "os-image=NonExistantOsForQa",
                 "-f", instance.name], fail=True)

  # Reinstall non existing URL
  AssertCommand(["gnt-instance", "reinstall",
                 "--os-parameters", "os-image=http://NonExistantOsForQa",
                 "-f", instance.name], fail=True)

  # Reinstall using OS scripts
  AssertCommand(["gnt-instance", "reinstall", "-f", instance.name])

  # Test with non-existant OS definition
  AssertCommand(["gnt-instance", "reinstall", "-f",
                 "--os-type=NonExistantOsForQa",
                 instance.name],
                fail=True)

  # Test with existing OS but invalid variant
  AssertCommand(["gnt-instance", "reinstall", "-f", "-o", "debootstrap+ola",
                 instance.name],
                fail=True)

  # Test with existing OS but invalid variant
  AssertCommand(["gnt-instance", "reinstall", "-f", "-o", "debian-image+ola",
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
    AssertCommand(["gnt-instance", "rename", "--name-check",
                  rename_source, rename_target], fail=True)
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
  AssertCommand(["gnt-instance", "rename", "--name-check", rename_source,
                rename_target])
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
  AssertCommand(["gnt-instance", "rename", "--name-check", rename_target,
                rename_source])
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
    print(qa_utils.FormatInfo("Instance doesn't support failover, skipping"
                              " test"))
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
    print(qa_utils.FormatInfo("Instance doesn't support migration, skipping"
                              " test"))
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


def _TestKVMHotplug(instance, instance_info):
  """Tests hotplug modification commands, noting that they

  """
  args_to_try = [
    ["--net", "-1:add"],
    ["--net", "-1:modify,mac=aa:bb:cc:dd:ee:ff", "--force"],
    ["--net", "-1:remove"]
  ]
  if instance_info["hypervisor-parameters"]["disk_type"] != \
          constants.HT_DISK_IDE:
    # hotplugging disks is not supported for IDE-type disks
    args_to_try.append(["--disk", "-1:add,size=1G"])
    args_to_try.append(["--disk", "-1:remove"])

  for alist in args_to_try:
    _, stdout, stderr = \
      AssertCommand(["gnt-instance", "modify"] + alist + [instance.name])
    if "failed" in stdout or "failed" in stderr:
      raise qa_error.Error("Hotplugging command failed; please check output"
                           " for further information")


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModify(instance):
  """gnt-instance modify"""
  default_hv = qa_config.GetDefaultHypervisor()

  # Assume /sbin/init exists on all systems
  test_kernel = "/sbin/init"
  test_initrd = test_kernel

  instance_info = GetInstanceInfo(instance.name)

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

    # TODO: bridge tests
    #["--bridge", "xen-br1"],
    #["--bridge", orig_bridge],
    ]

  # Not all hypervisors support kernel_path(e.g, LXC)
  if default_hv in (constants.HT_XEN_PVM,
                    constants.HT_XEN_HVM,
                    constants.HT_KVM):
    args.extend([
      ["-H", "%s=%s" % (constants.HV_KERNEL_PATH, test_kernel)],
      ["-H", "%s=%s" % (constants.HV_KERNEL_PATH, constants.VALUE_DEFAULT)],
      ])

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
    qa_config.TestEnabled("instance-device-hotplug") and \
    instance_info["hypervisor-parameters"]["acpi"]:
    _TestKVMHotplug(instance, instance_info)
  elif default_hv == constants.HT_LXC:
    args.extend([
      ["-H", "%s=0" % constants.HV_CPU_MASK],
      ["-H", "%s=%s" % (constants.HV_CPU_MASK, constants.VALUE_DEFAULT)],
      ["-H", "%s=0" % constants.HV_LXC_NUM_TTYS],
      ["-H", "%s=%s" % (constants.HV_LXC_NUM_TTYS, constants.VALUE_DEFAULT)],
      ])

  url = "http://example.com/busybox.img"
  args.extend([
      ["--os-parameters", "os-image=" + url],
      ["--os-parameters", "os-image=default"]
      ])

  for alist in args:
    AssertCommand(["gnt-instance", "modify"] + alist + [instance.name])

  # check no-modify
  AssertCommand(["gnt-instance", "modify", instance.name], fail=True)

  # Marking offline while instance is running must fail...
  AssertCommand(["gnt-instance", "modify", "--offline", instance.name],
                 fail=True)

  # ...while making it online fails too (needs to be offline first)
  AssertCommand(["gnt-instance", "modify", "--online", instance.name],
                 fail=True)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModifyPrimaryAndBack(instance, currentnode, othernode):
  """gnt-instance modify --new-primary

  This will leave the instance on its original primary node, not other node.

  """
  if instance.disk_template != constants.DT_FILE:
    print(qa_utils.FormatInfo("Test only supported for the file disk template"))
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
def TestInstanceConvertDiskTemplate(instance, requested_conversions):
  """gnt-instance modify -t"""
  def _BuildConvertCommand(disk_template, node):
    cmd = ["gnt-instance", "modify", "-t", disk_template]
    if disk_template == constants.DT_DRBD8:
      cmd.extend(["-n", node])
    cmd.append(name)
    return cmd

  if len(requested_conversions) < 2:
    print(qa_utils.FormatInfo("You must specify more than one convertible"
                              " disk templates in order to test the conversion"
                              " feature"))
    return

  name = instance.name

  template = instance.disk_template
  if template in constants.DTS_NOT_CONVERTIBLE_FROM:
    print(qa_utils.FormatInfo("Unsupported template %s, skipping conversion"
                              " test" % template))
    return

  inodes = qa_config.AcquireManyNodes(2)
  master = qa_config.GetMasterNode()

  snode = inodes[0].primary
  if master.primary == snode:
    snode = inodes[1].primary

  enabled_disk_templates = qa_config.GetEnabledDiskTemplates()

  for templ in requested_conversions:
    if (templ == template or
        templ not in enabled_disk_templates or
        templ in constants.DTS_NOT_CONVERTIBLE_TO):
      continue
    AssertCommand(_BuildConvertCommand(templ, snode))

  # Before we return, convert to the original template
  AssertCommand(_BuildConvertCommand(template, snode))


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModifyDisks(instance):
  """gnt-instance modify --disk"""
  if not IsDiskSupported(instance):
    print(qa_utils.FormatInfo("Instance doesn't support disks, skipping test"))
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
    print(qa_utils.FormatInfo("Test not supported for diskless instances"))
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
    print(qa_utils.FormatInfo("Test not supported for diskless instances"))
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
  qa_utils.GenericQueryTest("gnt-instance", list(query.INSTANCE_FIELDS))


def TestInstanceListFields():
  """gnt-instance list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-instance", list(query.INSTANCE_FIELDS))


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
    print(qa_utils.FormatInfo("Instance doesn't support disk replacing,"
                              " skipping test"))
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
  build_disk_opt = (lambda idx_dsk:
                    "--disk=%s:%s%s" % (idx_dsk[0], build_size_opt(idx_dsk[1]),
                                        build_spindles_opt(idx_dsk[1])))
  return [build_disk_opt(d) for d in en_disks]


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
  options = ["gnt-backup", "export", "-n", node.primary]

  # For files and shared files, the --long-sleep option should be used
  if instance.disk_template in [constants.DT_FILE, constants.DT_SHARED_FILE]:
    options.append("--long-sleep")

  AssertCommand(options + [name])
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

  qa_utils.GenericQueryTest("gnt-backup", list(query.EXPORT_FIELDS),
                            namefield=None, test_unknown=False)


def TestBackupListFields():
  """gnt-backup list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-backup", list(query.EXPORT_FIELDS))


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
    middle = len(enabled_disk_templates) // 2
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


def _AssertInstance(instance, status, admin_state, admin_state_source):
  x, y, z = \
      _GetInstanceFields(instance.name,
                         ["status", "admin_state", "admin_state_source"])

  AssertEqual(x, status)
  AssertEqual(y, admin_state)
  AssertEqual(z, admin_state_source)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def _TestInstanceUserDown(instance, hv_shutdown_fn):
  """Test different combinations of user shutdown"""

  # 1. User shutdown
  # 2. Instance start
  hv_shutdown_fn()

  _AssertInstance(instance,
                  constants.INSTST_USERDOWN,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  AssertCommand(["gnt-instance", "start", instance.name])

  _AssertInstance(instance,
                  constants.INSTST_RUNNING,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  # 1. User shutdown
  # 2. Watcher cleanup
  # 3. Instance start
  hv_shutdown_fn()

  _AssertInstance(instance,
                  constants.INSTST_USERDOWN,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  qa_daemon.RunWatcherDaemon()

  _AssertInstance(instance,
                  constants.INSTST_USERDOWN,
                  constants.ADMINST_DOWN,
                  constants.USER_SOURCE)

  AssertCommand(["gnt-instance", "start", instance.name])

  _AssertInstance(instance,
                  constants.INSTST_RUNNING,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  # 1. User shutdown
  # 2. Watcher cleanup
  # 3. Instance stop
  # 4. Instance start
  hv_shutdown_fn()

  _AssertInstance(instance,
                  constants.INSTST_USERDOWN,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  qa_daemon.RunWatcherDaemon()

  _AssertInstance(instance,
                  constants.INSTST_USERDOWN,
                  constants.ADMINST_DOWN,
                  constants.USER_SOURCE)

  AssertCommand(["gnt-instance", "shutdown", instance.name])

  _AssertInstance(instance,
                  constants.INSTST_ADMINDOWN,
                  constants.ADMINST_DOWN,
                  constants.ADMIN_SOURCE)

  AssertCommand(["gnt-instance", "start", instance.name])

  _AssertInstance(instance,
                  constants.INSTST_RUNNING,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  # 1. User shutdown
  # 2. Instance stop
  # 3. Instance start
  hv_shutdown_fn()

  _AssertInstance(instance,
                  constants.INSTST_USERDOWN,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)

  AssertCommand(["gnt-instance", "shutdown", instance.name])

  _AssertInstance(instance,
                  constants.INSTST_ADMINDOWN,
                  constants.ADMINST_DOWN,
                  constants.ADMIN_SOURCE)

  AssertCommand(["gnt-instance", "start", instance.name])

  _AssertInstance(instance,
                  constants.INSTST_RUNNING,
                  constants.ADMINST_UP,
                  constants.ADMIN_SOURCE)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def _TestInstanceUserDownXen(instance):
  primary = _GetInstanceField(instance.name, "pnode")
  fn = lambda: AssertCommand(["xl", "shutdown", "-w", instance.name],
                             node=primary)

  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=true"])
  _TestInstanceUserDown(instance, fn)
  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=false"])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def _TestInstanceUserDownKvm(instance):
  def _StopKVMInstance():
    AssertCommand("pkill -f \"\\-name %s\"" % instance.name, node=primary)
    time.sleep(10)

  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=true"])
  AssertCommand(["gnt-instance", "modify", "-H", "user_shutdown=true",
                 instance.name])

  # The instance needs to reboot not because the 'user_shutdown'
  # parameter was modified but because the KVM daemon need to be
  # started, given that the instance was first created with user
  # shutdown disabled.
  AssertCommand(["gnt-instance", "reboot", instance.name])

  primary = _GetInstanceField(instance.name, "pnode")
  _TestInstanceUserDown(instance, _StopKVMInstance)

  AssertCommand(["gnt-instance", "modify", "-H", "user_shutdown=false",
                 instance.name])
  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=false"])


def TestInstanceUserDown(instance):
  """Tests user shutdown"""
  enabled_hypervisors = qa_config.GetEnabledHypervisors()

  for (hv, fn) in [(constants.HT_XEN_PVM, _TestInstanceUserDownXen),
                   (constants.HT_XEN_HVM, _TestInstanceUserDownXen),
                   (constants.HT_KVM, _TestInstanceUserDownKvm)]:
    if hv in enabled_hypervisors:
      qa_daemon.TestPauseWatcher()
      fn(instance)
      qa_daemon.TestResumeWatcher()
    else:
      print("%s hypervisor is not enabled, skipping test for this hypervisor" \
          % hv)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceCommunication(instance, master):
  """Tests instance communication via 'gnt-instance modify'"""

  # Enable instance communication network at the cluster level
  network_name = "mynetwork"

  cmd = ["gnt-cluster", "modify",
         "--instance-communication-network=%s" % network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  print(result_output)

  # Enable instance communication mechanism for this instance
  AssertCommand(["gnt-instance", "modify", "-c", "yes", instance.name])

  # Reboot instance for changes to NIC to take effect
  AssertCommand(["gnt-instance", "reboot", instance.name])

  # Check if the instance is properly configured for instance
  # communication.
  nic_name = "%s%s" % (constants.INSTANCE_COMMUNICATION_NIC_PREFIX,
                       instance.name)

  ## Check the output of 'gnt-instance list'
  nic_names = _GetInstanceField(instance.name, "nic.names")
  nic_names = [x.strip(" '") for x in nic_names.strip("[]").split(",")]

  AssertIn(nic_name, nic_names,
           msg="Looking for instance communication TAP interface")

  nic_n = nic_names.index(nic_name)

  nic_ip = _GetInstanceField(instance.name, "nic.ip/%d" % nic_n)
  nic_network = _GetInstanceField(instance.name, "nic.network.name/%d" % nic_n)
  nic_mode = _GetInstanceField(instance.name, "nic.mode/%d" % nic_n)

  AssertEqual(IP4Address.InNetwork(constants.INSTANCE_COMMUNICATION_NETWORK4,
                                   nic_ip),
              True,
              msg="Checking if NIC's IP if part of the expected network")

  AssertEqual(network_name, nic_network,
              msg="Checking if NIC's network name matches the expected value")

  AssertEqual(constants.INSTANCE_COMMUNICATION_NETWORK_MODE, nic_mode,
              msg="Checking if NIC's mode name matches the expected value")

  ## Check the output of 'ip route'
  cmd = ["ip", "route", "show", nic_ip]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  result = result_output.split()

  AssertEqual(len(result), 5, msg="Checking if the IP route is established")

  route_ip = result[0]
  route_dev = result[1]
  route_tap = result[2]
  route_scope = result[3]
  route_link = result[4]

  AssertEqual(route_ip, nic_ip,
              msg="Checking if IP route shows the expected IP")
  AssertEqual(route_dev, "dev",
              msg="Checking if IP route shows the expected device")
  AssertEqual(route_scope, "scope",
              msg="Checking if IP route shows the expected scope")
  AssertEqual(route_link, "link",
              msg="Checking if IP route shows the expected link-level scope")

  ## Check the output of 'ip address'
  cmd = ["ip", "address", "show", "dev", route_tap]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  result = result_output.splitlines()

  AssertEqual(len(result), 3,
              msg="Checking if the IP address is established")

  result = result.pop().split()

  AssertEqual(len(result), 7,
              msg="Checking if the IP address has the expected value")

  address_ip = result[1]
  address_netmask = result[3]

  AssertEqual(address_ip, "169.254.169.254/32",
              msg="Checking if the TAP interface has the expected IP")
  AssertEqual(address_netmask, "169.254.255.255",
              msg="Checking if the TAP interface has the expected netmask")

  # Disable instance communication mechanism for this instance
  AssertCommand(["gnt-instance", "modify", "-c", "no", instance.name])

  # Reboot instance for changes to NIC to take effect
  AssertCommand(["gnt-instance", "reboot", instance.name])

  # Disable instance communication network at cluster level
  cmd = ["gnt-cluster", "modify",
         "--instance-communication-network=%s" % network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  print(result_output)


def _TestRedactionOfSecretOsParams(node, cmd, secret_keys):
  """Tests redaction of secret os parameters

  """
  AssertCommand(["gnt-cluster", "modify", "--max-running-jobs", "1"])
  debug_delay_id = int(stdout_of(["gnt-debug", "delay", "--print-jobid",
                       "--submit", "300"]))
  cmd_jid = int(stdout_of(cmd))
  job_file_abspath = "%s/job-%s" % (pathutils.QUEUE_DIR, cmd_jid)
  job_file = qa_utils.MakeNodePath(node, job_file_abspath)

  for k in secret_keys:
    grep_cmd = ["grep", "\"%s\":\"<redacted>\"" % k, job_file]
    AssertCommand(grep_cmd)

  AssertCommand(["gnt-job", "cancel", "--kill", "--yes-do-it",
                str(debug_delay_id)])
  AssertCommand(["gnt-cluster", "modify", "--max-running-jobs", "20"])
  AssertCommand(["gnt-job", "wait", str(cmd_jid)])


def TestInstanceAddOsParams():
  """Tests instance add with secret os parameters"""

  if not qa_config.IsTemplateSupported(constants.DT_PLAIN):
    return

  master = qa_config.GetMasterNode()
  instance = qa_config.AcquireInstance()

  secret_keys = ["param1", "param2"]
  cmd = (["gnt-instance", "add",
          "--os-type=%s" % qa_config.get("os"),
          "--disk-template=%s" % constants.DT_PLAIN,
          "--os-parameters-secret",
          "param1=secret1,param2=secret2",
          "--node=%s" % master.primary] +
          GetGenericAddParameters(instance, constants.DT_PLAIN))
  cmd.append("--submit")
  cmd.append("--print-jobid")
  cmd.append(instance.name)

  _TestRedactionOfSecretOsParams(master.primary, cmd, secret_keys)

  TestInstanceRemove(instance)
  instance.Release()


def TestSecretOsParams():
  """Tests secret os parameter transmission"""

  master = qa_config.GetMasterNode()
  secret_keys = ["param1", "param2"]
  cmd = (["gnt-debug", "test-osparams", "--os-parameters-secret",
         "param1=secret1,param2=secret2", "--submit", "--print-jobid"])
  _TestRedactionOfSecretOsParams(master.primary, cmd, secret_keys)

  cmd_output = stdout_of(["gnt-debug", "test-osparams",
                         "--os-parameters-secret",
                         "param1=secret1,param2=secret2"])
  AssertIn("\'param1\': \'secret1\'", cmd_output)
  AssertIn("\'param2\': \'secret2\'", cmd_output)


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
  ("instance-add-rbd", constants.DT_RBD,
   TestInstanceAddRADOSBlockDevice, 1),
  ("instance-add-gluster", constants.DT_GLUSTER,
   TestInstanceAddGluster, 1),
  ]
