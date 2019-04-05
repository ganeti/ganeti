#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""Xen hypervisors

"""

import logging
import errno
import os
import string # pylint: disable=W0402
import shutil
import time
from cStringIO import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti.hypervisor import hv_base
from ganeti import netutils
from ganeti import objects
from ganeti import pathutils


XEND_CONFIG_FILE = utils.PathJoin(pathutils.XEN_CONFIG_DIR, "xend-config.sxp")
XL_CONFIG_FILE = utils.PathJoin(pathutils.XEN_CONFIG_DIR, "xen/xl.conf")
VIF_BRIDGE_SCRIPT = utils.PathJoin(pathutils.XEN_CONFIG_DIR,
                                   "scripts/vif-bridge")
_DOM0_NAME = "Domain-0"
_DISK_LETTERS = string.ascii_lowercase

_FILE_DRIVER_MAP = {
  constants.FD_LOOP: "file",
  constants.FD_BLKTAP: "tap:aio",
  constants.FD_BLKTAP2: "tap2:tapdisk:aio",
  }


def _CreateConfigCpus(cpu_mask):
  """Create a CPU config string for Xen's config file.

  """
  # Convert the string CPU mask to a list of list of int's
  cpu_list = utils.ParseMultiCpuMask(cpu_mask)

  if len(cpu_list) == 1:
    all_cpu_mapping = cpu_list[0]
    if all_cpu_mapping == constants.CPU_PINNING_OFF:
      # If CPU pinning has 1 entry that's "all", then remove the
      # parameter from the config file
      return None
    else:
      # If CPU pinning has one non-all entry, mapping all vCPUS (the entire
      # VM) to one physical CPU, using format 'cpu = "C"'
      return "cpu = \"%s\"" % ",".join(map(str, all_cpu_mapping))
  else:

    def _GetCPUMap(vcpu):
      if vcpu[0] == constants.CPU_PINNING_ALL_VAL:
        cpu_map = constants.CPU_PINNING_ALL_XEN
      else:
        cpu_map = ",".join(map(str, vcpu))
      return "\"%s\"" % cpu_map

    # build the result string in format 'cpus = [ "c", "c", "c" ]',
    # where each c is a physical CPU number, a range, a list, or any
    # combination
    return "cpus = [ %s ]" % ", ".join(map(_GetCPUMap, cpu_list))


def _RunInstanceList(fn, instance_list_errors):
  """Helper function for L{_GetAllInstanceList} to retrieve the list
  of instances from xen.

  @type fn: callable
  @param fn: Function to query xen for the list of instances
  @type instance_list_errors: list
  @param instance_list_errors: Error list
  @rtype: list

  """
  result = fn()
  if result.failed:
    logging.error("Retrieving the instance list from xen failed (%s): %s",
                  result.fail_reason, result.output)
    instance_list_errors.append(result)
    raise utils.RetryAgain()

  # skip over the heading
  return result.stdout.splitlines()


class _InstanceCrashed(errors.GenericError):
  """Instance has reached a violent ending.

  This is raised within the Xen hypervisor only, and should not be seen or used
  outside.

  """


def _ParseInstanceList(lines, include_node):
  """Parses the output of listing instances by xen.

  @type lines: list
  @param lines: Result of retrieving the instance list from xen
  @type include_node: boolean
  @param include_node: If True, return information for Dom0
  @return: list of tuple containing (name, id, memory, vcpus, state, time
    spent)

  """
  result = []

  # Iterate through all lines while ignoring header
  for line in lines[1:]:
    # The format of lines is:
    # Name      ID Mem(MiB) VCPUs State  Time(s)
    # Domain-0   0  3418     4 r-----    266.2
    data = line.split()
    if len(data) != 6:
      raise errors.HypervisorError("Can't parse instance list,"
                                   " line: %s" % line)
    try:
      # TODO: Cleanup this mess - introduce a namedtuple/dict/class
      data[1] = int(data[1])
      data[2] = int(data[2])
      data[3] = int(data[3])
      data[4] = _XenToHypervisorInstanceState(data[4])
      data[5] = float(data[5])
    except (TypeError, ValueError) as err:
      raise errors.HypervisorError("Can't parse instance list,"
                                   " line: %s, error: %s" % (line, err))
    except _InstanceCrashed:
      # The crashed instance can be interpreted as being down, so we omit it
      # from the instance list.
      continue

    # skip the Domain-0 (optional)
    if include_node or data[0] != _DOM0_NAME:
      result.append(data)

  return result


def _InstanceDomID(info):
  """Get instance domain ID from instance info tuple.
  @type info: tuple
  @param info: instance info as parsed by _ParseInstanceList()

  @return: int, instance domain ID
  """
  return info[1]


def _InstanceRuntime(info):
  """Get instance runtime from instance info tuple.
  @type info: tuple
  @param info: instance info as parsed by _ParseInstanceList()

  @return: float value of instance runtime
  """
  return info[5]


def _GetAllInstanceList(fn, include_node, delays, timeout):
  """Return the list of instances including running and shutdown.

  See L{_RunInstanceList} and L{_ParseInstanceList} for parameter details.

  """
  instance_list_errors = []
  try:
    lines = utils.Retry(_RunInstanceList, delays, timeout,
                        args=(fn, instance_list_errors))
  except utils.RetryTimeout:
    if instance_list_errors:
      instance_list_result = instance_list_errors.pop()

      errmsg = ("listing instances failed, timeout exceeded (%s): %s" %
                (instance_list_result.fail_reason, instance_list_result.output))
    else:
      errmsg = "listing instances failed"

    raise errors.HypervisorError(errmsg)

  return _ParseInstanceList(lines, include_node)


def _IsInstanceRunning(instance_info):
  """Determine whether an instance is running.

  An instance is running if it is in the following Xen states:
  running, blocked, paused, or dying (about to be destroyed / shutdown).

  For some strange reason, Xen once printed 'rb----' which does not make any
  sense because an instance cannot be both running and blocked.  Fortunately,
  for Ganeti 'running' or 'blocked' is the same as 'running'.

  A state of nothing '------' means that the domain is runnable but it is not
  currently running.  That means it is in the queue behind other domains waiting
  to be scheduled to run.
  http://old-list-archives.xenproject.org/xen-users/2007-06/msg00849.html

  A dying instance is about to be removed, but it is still consuming resources,
  and counts as running.

  @type instance_info: string
  @param instance_info: Information about instance, as supplied by Xen.
  @rtype: bool
  @return: Whether an instance is running.

  """
  allowable_running_prefixes = [
    "r--",
    "rb-",
    "-b-",
    "---",
  ]

  def _RunningWithSuffix(suffix):
    return [x + suffix for x in allowable_running_prefixes]

  # The shutdown suspend ("ss") state is encountered during migration, where
  # the instance is still considered to be running.
  # The shutdown restart ("sr") is probably encountered during restarts - still
  # running.
  # See Xen commit e1475a6693aac8cddc4bdd456548aa05a625556b
  return instance_info in _RunningWithSuffix("---") \
      or instance_info in _RunningWithSuffix("ss-") \
      or instance_info in _RunningWithSuffix("sr-") \
      or instance_info == "-----d"


def _IsInstanceShutdown(instance_info):
  """Determine whether the instance is shutdown.

  An instance is shutdown when a user shuts it down from within, and we do not
  remove domains to be able to detect that.

  The dying state has been added as a precaution, as Xen's status reporting is
  weird.

  """
  return instance_info == "---s--" \
      or instance_info == "---s-d"


def _IgnorePaused(instance_info):
  """Removes information about whether a Xen state is paused from the state.

  As it turns out, an instance can be reported as paused in almost any
  condition. Paused instances can be paused, running instances can be paused for
  scheduling, and any other condition can appear to be paused as a result of
  races or improbable conditions in Xen's status reporting.
  As we do not use Xen's pause commands in any way at the time, we can simply
  ignore the paused field and save ourselves a lot of trouble.

  Should we ever use the pause commands, several samples would be needed before
  we could confirm the domain as paused.

  """
  return instance_info.replace('p', '-')


def _IsCrashed(instance_info):
  """Returns whether an instance is in the crashed Xen state.

  When a horrible misconfiguration happens to a Xen domain, it can crash,
  meaning that it encounters a violent ending. While this state usually flashes
  only temporarily before the domain is restarted, being able to check for it
  allows Ganeti not to act confused and do something about it.

  """
  return instance_info.count('c') > 0


def _XenToHypervisorInstanceState(instance_info):
  """Maps Xen states to hypervisor states.

  @type instance_info: string
  @param instance_info: Information about instance, as supplied by Xen.
  @rtype: L{hv_base.HvInstanceState}

  """
  instance_info = _IgnorePaused(instance_info)

  if _IsCrashed(instance_info):
    raise _InstanceCrashed("Instance detected as crashed, should be omitted")

  if _IsInstanceRunning(instance_info):
    return hv_base.HvInstanceState.RUNNING
  elif _IsInstanceShutdown(instance_info):
    return hv_base.HvInstanceState.SHUTDOWN
  else:
    raise errors.HypervisorError("hv_xen._XenToHypervisorInstanceState:"
                                 " unhandled Xen instance state '%s'" %
                                   instance_info)


def _GetRunningInstanceList(fn, include_node, delays, timeout):
  """Return the list of running instances.

  See L{_GetAllInstanceList} for parameter details.

  """
  instances = _GetAllInstanceList(fn, include_node, delays, timeout)
  return [i for i in instances if hv_base.HvInstanceState.IsRunning(i[4])]


def _GetShutdownInstanceList(fn, include_node, delays, timeout):
  """Return the list of shutdown instances.

  See L{_GetAllInstanceList} for parameter details.

  """
  instances = _GetAllInstanceList(fn, include_node, delays, timeout)
  return [i for i in instances if hv_base.HvInstanceState.IsShutdown(i[4])]


def _ParseNodeInfo(info):
  """Return information about the node.

  @return: a dict with the following keys (memory values in MiB):
        - memory_total: the total memory size on the node
        - memory_free: the available memory on the node for instances
        - nr_cpus: total number of CPUs
        - nr_nodes: in a NUMA system, the number of domains
        - nr_sockets: the number of physical CPU sockets in the node
        - hv_version: the hypervisor version in the form (major, minor)

  """
  result = {}
  cores_per_socket = threads_per_core = nr_cpus = None
  xen_major, xen_minor = None, None
  memory_total = None
  memory_free = None

  for line in info.splitlines():
    fields = line.split(":", 1)

    if len(fields) < 2:
      continue

    (key, val) = [s.strip() for s in fields]

    # Note: in Xen 3, memory has changed to total_memory
    if key in ("memory", "total_memory"):
      memory_total = int(val)
    elif key == "free_memory":
      memory_free = int(val)
    elif key == "nr_cpus":
      nr_cpus = result["cpu_total"] = int(val)
    elif key == "nr_nodes":
      result["cpu_nodes"] = int(val)
    elif key == "cores_per_socket":
      cores_per_socket = int(val)
    elif key == "threads_per_core":
      threads_per_core = int(val)
    elif key == "xen_major":
      xen_major = int(val)
    elif key == "xen_minor":
      xen_minor = int(val)

  if None not in [cores_per_socket, threads_per_core, nr_cpus]:
    result["cpu_sockets"] = nr_cpus // (cores_per_socket * threads_per_core)

  if memory_free is not None:
    result["memory_free"] = memory_free

  if memory_total is not None:
    result["memory_total"] = memory_total

  if not (xen_major is None or xen_minor is None):
    result[constants.HV_NODEINFO_KEY_VERSION] = (xen_major, xen_minor)

  return result


def _MergeInstanceInfo(info, instance_list):
  """Updates node information from L{_ParseNodeInfo} with instance info.

  @type info: dict
  @param info: Result from L{_ParseNodeInfo}
  @type instance_list: list of tuples
  @param instance_list: list of instance information; one tuple per instance
  @rtype: dict

  """
  total_instmem = 0

  for (name, _, mem, vcpus, _, _) in instance_list:
    if name == _DOM0_NAME:
      info["memory_dom0"] = mem
      info["cpu_dom0"] = vcpus

    # Include Dom0 in total memory usage
    total_instmem += mem

  memory_free = info.get("memory_free")
  memory_total = info.get("memory_total")

  # Calculate memory used by hypervisor
  if None not in [memory_total, memory_free, total_instmem]:
    info["memory_hv"] = memory_total - memory_free - total_instmem

  return info


def _GetNodeInfo(info, instance_list):
  """Combines L{_MergeInstanceInfo} and L{_ParseNodeInfo}.

  @type instance_list: list of tuples
  @param instance_list: list of instance information; one tuple per instance

  """
  return _MergeInstanceInfo(_ParseNodeInfo(info), instance_list)


def _GetConfigFileDiskData(block_devices, blockdev_prefix,
                           _letters=_DISK_LETTERS):
  """Get disk directives for Xen config file.

  This method builds the xen config disk directive according to the
  given disk_template and block_devices.

  @param block_devices: list of tuples (cfdev, rldev):
      - cfdev: dict containing ganeti config disk part
      - rldev: ganeti.block.bdev.BlockDev object
  @param blockdev_prefix: a string containing blockdevice prefix,
                          e.g. "sd" for /dev/sda

  @return: string containing disk directive for xen instance config file

  """
  if len(block_devices) > len(_letters):
    raise errors.HypervisorError("Too many disks")

  disk_data = []

  for sd_suffix, (cfdev, dev_path, _) in zip(_letters, block_devices):
    sd_name = blockdev_prefix + sd_suffix

    if cfdev.mode == constants.DISK_RDWR:
      mode = "w"
    else:
      mode = "r"

    if cfdev.dev_type in constants.DTS_FILEBASED:
      driver = _FILE_DRIVER_MAP[cfdev.logical_id[0]]
    else:
      driver = "phy"

    disk_data.append("'%s:%s,%s,%s'" % (driver, dev_path, sd_name, mode))

  return disk_data


def _QuoteCpuidField(data):
  """Add quotes around the CPUID field only if necessary.

  Xen CPUID fields come in two shapes: LIBXL strings, which need quotes around
  them, and lists of XEND strings, which don't.

  @param data: Either type of parameter.
  @return: The quoted version thereof.

  """
  return "'%s'" % data if data.startswith("host") else data


def _ConfigureNIC(instance, seq, nic, tap):
  """Run the network configuration script for a specified NIC

  See L{hv_base.ConfigureNIC}.

  @type instance: instance object
  @param instance: instance we're acting on
  @type seq: int
  @param seq: nic sequence number
  @type nic: nic object
  @param nic: nic we're acting on
  @type tap: str
  @param tap: the host's tap interface this NIC corresponds to

  """
  hv_base.ConfigureNIC(pathutils.XEN_IFUP_OS, instance, seq, nic, tap)


class XenHypervisor(hv_base.BaseHypervisor):
  """Xen generic hypervisor interface

  This is the Xen base class used for both Xen PVM and HVM. It contains
  all the functionality that is identical for both.

  """
  CAN_MIGRATE = True
  REBOOT_RETRY_COUNT = 60
  REBOOT_RETRY_INTERVAL = 10
  _ROOT_DIR = pathutils.RUN_DIR + "/xen-hypervisor"
  # contains NICs' info
  _NICS_DIR = _ROOT_DIR + "/nic"
  # contains the pidfiles of socat processes used to migrate instaces under xl
  _MIGRATION_DIR = _ROOT_DIR + "/migration"
  _DIRS = [_ROOT_DIR, _NICS_DIR, _MIGRATION_DIR]

  _INSTANCE_LIST_DELAYS = (0.3, 1.5, 1.0)
  _INSTANCE_LIST_TIMEOUT = 5

  ANCILLARY_FILES = [
    XEND_CONFIG_FILE,
    XL_CONFIG_FILE,
    VIF_BRIDGE_SCRIPT,
    ]
  ANCILLARY_FILES_OPT = [
    XEND_CONFIG_FILE,
    XL_CONFIG_FILE,
    ]

  def __init__(self, _cfgdir=None, _run_cmd_fn=None, _cmd=None):
    hv_base.BaseHypervisor.__init__(self)

    if _cfgdir is None:
      self._cfgdir = pathutils.XEN_CONFIG_DIR
    else:
      self._cfgdir = _cfgdir

    if _run_cmd_fn is None:
      self._run_cmd_fn = utils.RunCmd
    else:
      self._run_cmd_fn = _run_cmd_fn

    self._cmd = _cmd

  @staticmethod
  def _GetCommandFromHvparams(hvparams):
    """Returns the Xen command extracted from the given hvparams.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters

    """
    if hvparams is None or constants.HV_XEN_CMD not in hvparams:
      raise errors.HypervisorError("Cannot determine xen command.")
    else:
      return hvparams[constants.HV_XEN_CMD]

  def _GetCommand(self, hvparams):
    """Returns Xen command to use.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters

    """
    if self._cmd is None:
      cmd = XenHypervisor._GetCommandFromHvparams(hvparams)
    else:
      cmd = self._cmd

    if cmd not in constants.KNOWN_XEN_COMMANDS:
      raise errors.ProgrammerError("Unknown Xen command '%s'" % cmd)

    return cmd

  def _RunXen(self, args, hvparams, timeout=None):
    """Wrapper around L{utils.process.RunCmd} to run Xen command.

    @type hvparams: dict of strings
    @param hvparams: dictionary of hypervisor params
    @type timeout: int or None
    @param timeout: if a timeout (in seconds) is specified, the command will be
                    terminated after that number of seconds.
    @see: L{utils.process.RunCmd}

    """
    cmd = []

    if timeout is not None:
      cmd.extend(["timeout", str(timeout)])

    cmd.extend([self._GetCommand(hvparams)])
    cmd.extend(args)

    return self._run_cmd_fn(cmd)

  def _ConfigFileName(self, instance_name):
    """Get the config file name for an instance.

    @param instance_name: instance name
    @type instance_name: str
    @return: fully qualified path to instance config file
    @rtype: str

    """
    return utils.PathJoin(self._cfgdir, instance_name)

  @classmethod
  def _EnsureDirs(cls, extra_dirs=None):
    """Makes sure that the directories needed by the hypervisor exist.

    @type extra_dirs: list of string or None
    @param extra_dirs: Additional directories which ought to exist.

    """
    if extra_dirs is None:
      extra_dirs = []
    dirs = [(dname, constants.RUN_DIRS_MODE) for dname in
            (cls._DIRS + extra_dirs)]
    utils.EnsureDirs(dirs)

  @classmethod
  def _WriteNICInfoFile(cls, instance, idx, nic):
    """Write the Xen config file for the instance.

    This version of the function just writes the config file from static data.

    """
    instance_name = instance.name
    cls._EnsureDirs(extra_dirs=[cls._InstanceNICDir(instance_name)])

    cfg_file = cls._InstanceNICFile(instance_name, idx)
    data = StringIO()

    data.write("TAGS=\"%s\"\n" % r"\ ".join(instance.GetTags()))
    if nic.netinfo:
      netinfo = objects.Network.FromDict(nic.netinfo)
      for k, v in netinfo.HooksDict().items():
        data.write("%s=\"%s\"\n" % (k, v))

    data.write("MAC=%s\n" % nic.mac)
    if nic.ip:
      data.write("IP=%s\n" % nic.ip)
    data.write("INTERFACE_INDEX=%s\n" % str(idx))
    if nic.name:
      data.write("INTERFACE_NAME=%s\n" % nic.name)
    data.write("INTERFACE_UUID=%s\n" % nic.uuid)
    data.write("MODE=%s\n" % nic.nicparams[constants.NIC_MODE])
    data.write("LINK=%s\n" % nic.nicparams[constants.NIC_LINK])
    data.write("VLAN=%s\n" % nic.nicparams[constants.NIC_VLAN])

    try:
      utils.WriteFile(cfg_file, data=data.getvalue())
    except EnvironmentError as err:
      raise errors.HypervisorError("Cannot write Xen instance configuration"
                                   " file %s: %s" % (cfg_file, err))

  @staticmethod
  def VersionsSafeForMigration(src, target):
    """Decide if migration is likely to suceed for hypervisor versions.

    Given two versions of a hypervisor, give a guess whether live migration
    from the one version to the other version is likely to succeed. For Xen,
    the heuristics is, that an increase by one on the second digit is OK. This
    fits with the current numbering scheme.

    @type src: list or tuple
    @type target: list or tuple
    @rtype: bool
    """
    if src == target:
      return True

    if len(src) < 2 or len(target) < 2:
      return False

    return src[0] == target[0] and target[1] in [src[1], src[1] + 1]

  @classmethod
  def _InstanceNICDir(cls, instance_name):
    """Returns the directory holding the tap device files for a given instance.

    """
    return utils.PathJoin(cls._NICS_DIR, instance_name)

  @classmethod
  def _InstanceNICFile(cls, instance_name, seq):
    """Returns the name of the file containing the tap device for a given NIC

    """
    return utils.PathJoin(cls._InstanceNICDir(instance_name), str(seq))

  @classmethod
  def _InstanceMigrationPidfile(cls, _instance_name):
    """Returns the name of the pid file for a socat process used to migrate.

    """
    #TODO(riba): At the moment, we are using a single pidfile because we
    # use a single port for migrations at the moment. This is because we do not
    # allow more migrations, so dynamic port selection and the needed port
    # modifications are not needed.
    # The _instance_name parameter has been left here for future use.
    return utils.PathJoin(cls._MIGRATION_DIR, constants.XL_MIGRATION_PIDFILE)

  @classmethod
  def _GetConfig(cls, instance, startup_memory, block_devices):
    """Build Xen configuration for an instance.

    """
    raise NotImplementedError

  def _WriteNicConfig(self, config, instance, hvp):
    vif_data = []

    # only XenHvmHypervisor has these hvparams
    nic_type = hvp.get(constants.HV_NIC_TYPE, None)
    vif_type = hvp.get(constants.HV_VIF_TYPE, None)
    nic_type_str = ""
    if nic_type or vif_type:
      if nic_type is None:
        if vif_type:
          nic_type_str = ", type=%s" % vif_type
      elif nic_type == constants.HT_NIC_PARAVIRTUAL:
        nic_type_str = ", type=%s" % constants.HT_HVM_VIF_VIF
      else:
        # parameter 'model' is only valid with type 'ioemu'
        nic_type_str = ", model=%s, type=%s" % \
          (nic_type, constants.HT_HVM_VIF_IOEMU)

    for idx, nic in enumerate(instance.nics):
      nic_args = {}
      nic_args["mac"] = "%s%s" % (nic.mac, nic_type_str)

      if nic.name and \
            nic.name.startswith(constants.INSTANCE_COMMUNICATION_NIC_PREFIX):
        tap = hv_base.GenerateTapName()
        nic_args["vifname"] = tap
        nic_args["script"] = pathutils.XEN_VIF_METAD_SETUP
        nic.name = tap
      else:
        ip = getattr(nic, "ip", None)
        if ip is not None:
          nic_args["ip"] = ip

        if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
          nic_args["bridge"] = nic.nicparams[constants.NIC_LINK]
        elif nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_OVS:
          nic_args["bridge"] = nic.nicparams[constants.NIC_LINK]
          if nic.nicparams[constants.NIC_VLAN]:
            nic_args["bridge"] += nic.nicparams[constants.NIC_VLAN]

        if hvp[constants.HV_VIF_SCRIPT]:
          nic_args["script"] = hvp[constants.HV_VIF_SCRIPT]

      nic_str = ", ".join(["%s=%s" % p for p in nic_args.items()])
      vif_data.append("'%s'" % (nic_str, ))
      self._WriteNICInfoFile(instance, idx, nic)

    config.write("vif = [%s]\n" % ",".join(vif_data))

  def _WriteConfigFile(self, instance_name, data):
    """Write the Xen config file for the instance.

    This version of the function just writes the config file from static data.

    """
    # just in case it exists
    utils.RemoveFile(utils.PathJoin(self._cfgdir, "auto", instance_name))

    cfg_file = self._ConfigFileName(instance_name)
    try:
      utils.WriteFile(cfg_file, data=data)
    except EnvironmentError as err:
      raise errors.HypervisorError("Cannot write Xen instance configuration"
                                   " file %s: %s" % (cfg_file, err))

  def _ReadConfigFile(self, instance_name):
    """Returns the contents of the instance config file.

    """
    filename = self._ConfigFileName(instance_name)

    try:
      file_content = utils.ReadFile(filename)
    except EnvironmentError as err:
      raise errors.HypervisorError("Failed to load Xen config file: %s" % err)

    return file_content

  def _RemoveConfigFile(self, instance_name):
    """Remove the xen configuration file.

    """
    utils.RemoveFile(self._ConfigFileName(instance_name))
    try:
      shutil.rmtree(self._InstanceNICDir(instance_name))
    except OSError as err:
      if err.errno != errno.ENOENT:
        raise

  def _StashConfigFile(self, instance_name):
    """Move the Xen config file to the log directory and return its new path.

    """
    old_filename = self._ConfigFileName(instance_name)
    base = ("%s-%s" %
            (instance_name, utils.TimestampForFilename()))
    new_filename = utils.PathJoin(pathutils.LOG_XEN_DIR, base)
    utils.RenameFile(old_filename, new_filename)
    return new_filename

  def _GetInstanceList(self, include_node, hvparams):
    """Wrapper around module level L{_GetAllInstanceList}.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be used on this node

    """
    return _GetAllInstanceList(lambda: self._RunXen(["list"], hvparams),
                               include_node, delays=self._INSTANCE_LIST_DELAYS,
                               timeout=self._INSTANCE_LIST_TIMEOUT)

  def ListInstances(self, hvparams=None):
    """Get the list of running instances.

    @type hvparams: dict of strings
    @param hvparams: the instance's hypervisor params

    @rtype: list of strings
    @return: names of running instances

    """
    instance_list = _GetRunningInstanceList(
      lambda: self._RunXen(["list"], hvparams),
      False, delays=self._INSTANCE_LIST_DELAYS,
      timeout=self._INSTANCE_LIST_TIMEOUT)
    return [info[0] for info in instance_list]

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: the instance's hypervisor params

    @return: tuple (name, id, memory, vcpus, stat, times)

    """
    instance_list = self._GetInstanceList(instance_name == _DOM0_NAME, hvparams)

    for data in instance_list:
      if data[0] == instance_name:
        return data

    return None

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters

    @rtype: (string, string, int, int, HypervisorInstanceState, int)
    @return: list of tuples (name, id, memory, vcpus, state, times)

    """
    return self._GetInstanceList(False, hvparams)

  def _MakeConfigFile(self, instance, startup_memory, block_devices):
    """Gather configuration details and write to disk.

    See L{_GetConfig} for arguments.

    """
    buf = StringIO()
    buf.write("# Automatically generated by Ganeti. Do not edit!\n")
    buf.write("\n")
    buf.write(self._GetConfig(instance, startup_memory, block_devices))
    buf.write("\n")

    self._WriteConfigFile(instance.name, buf.getvalue())

  def VerifyInstance(self, instance):
    """Verify if running instance (configuration) is in correct state.

    @type instance: L{objects.Instance}
    @param instance: instance to verify

    @return: bool, if instance in correct state
    """
    config_file = utils.PathJoin(self._cfgdir, "auto", instance.name)
    return os.path.exists(config_file)

  def RestoreInstance(self, instance, block_devices):
    """Fixup running instance's state.

    @type instance: L{objects.Instance}
    @param instance: instance to restore
    @type block_devices: list of tuples (disk_object, link_name, drive_uri)
    @param block_devices: blockdevices assigned to this instance
    """
    startup_memory = self._InstanceStartupMemory(instance)
    self._MakeConfigFile(instance, startup_memory, block_devices)

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to start
    @type block_devices: list of tuples (cfdev, rldev)
      - cfdev: dict containing ganeti config disk part
      - rldev: ganeti.block.bdev.BlockDev object
    @param block_devices: blockdevices assigned to this instance
    @type startup_paused: bool
    @param startup_paused: if instance should be paused at startup
    """
    startup_memory = self._InstanceStartupMemory(instance)

    self._MakeConfigFile(instance, startup_memory, block_devices)

    cmd = ["create"]
    if startup_paused:
      cmd.append("-p")
    cmd.append(self._ConfigFileName(instance.name))

    result = self._RunXen(cmd, instance.hvparams)
    if result.failed:
      # Move the Xen configuration file to the log directory to avoid
      # leaving a stale config file behind.
      stashed_config = self._StashConfigFile(instance.name)
      raise errors.HypervisorError("Failed to start instance %s: %s (%s). Moved"
                                   " config file to %s" %
                                   (instance.name, result.fail_reason,
                                    result.output, stashed_config))

    for nic_seq, nic in enumerate(instance.nics):
      if nic.name and nic.name.startswith("gnt.com."):
        _ConfigureNIC(instance, nic_seq, nic, nic.name)

  def StopInstance(self, instance, force=False, retry=False, name=None,
                   timeout=None):
    """Stop an instance.

    A soft shutdown can be interrupted. A hard shutdown tries forever.

    """
    assert(timeout is None or force is not None)

    if name is None:
      name = instance.name

    return self._StopInstance(name, force, instance.hvparams, timeout)

  def _ShutdownInstance(self, name, hvparams, timeout):
    """Shutdown an instance if the instance is running.

    The '-w' flag waits for shutdown to complete which avoids the need
    to poll in the case where we want to destroy the domain
    immediately after shutdown.

    @type name: string
    @param name: name of the instance to stop
    @type hvparams: dict of string
    @param hvparams: hypervisor parameters of the instance
    @type timeout: int or None
    @param timeout: a timeout after which the shutdown command should be killed,
                    or None for no timeout

    """
    info = self.GetInstanceInfo(name, hvparams=hvparams)

    if info is None or hv_base.HvInstanceState.IsShutdown(info[4]):
      logging.info("Failed to shutdown instance %s, not running", name)
      return None

    return self._RunXen(["shutdown", "-w", name], hvparams, timeout)

  def _DestroyInstance(self, name, hvparams):
    """Destroy an instance if the instance exists.

    @type name: string
    @param name: name of the instance to destroy
    @type hvparams: dict of string
    @param hvparams: hypervisor parameters of the instance

    """
    instance_info = self.GetInstanceInfo(name, hvparams=hvparams)

    if instance_info is None:
      logging.info("Failed to destroy instance %s, does not exist", name)
      return None

    return self._RunXen(["destroy", name], hvparams)

  # Destroy a domain only if necessary
  #
  # This method checks if the domain has already been destroyed before
  # issuing the 'destroy' command.  This step is necessary to handle
  # domains created by other versions of Ganeti.  For example, an
  # instance created with 2.10 will be destroy by the
  # '_ShutdownInstance', thus not requiring an additional destroy,
  # which would cause an error if issued.  See issue 619.
  def _DestroyInstanceIfAlive(self, name, hvparams):
    instance_info = self.GetInstanceInfo(name, hvparams=hvparams)

    if instance_info is None:
      raise errors.HypervisorError("Failed to destroy instance %s, already"
                                   " destroyed" % name)
    else:
      self._DestroyInstance(name, hvparams)

  def _RenameInstance(self, old_name, new_name, hvparams):
    """Rename an instance (domain).

    @type old_name: string
    @param old_name: current name of the instance
    @type new_name: string
    @param new_name: future (requested) name of the instace
    @type hvparams: dict of string
    @param hvparams: hypervisor parameters of the instance

    """
    return self._RunXen(["rename", old_name, new_name], hvparams)

  def _StopInstance(self, name, force, hvparams, timeout):
    """Stop an instance.

    @type name: string
    @param name: name of the instance to destroy

    @type force: boolean
    @param force: whether to do a "hard" stop (destroy)

    @type hvparams: dict of string
    @param hvparams: hypervisor parameters of the instance

    @type timeout: int or None
    @param timeout: a timeout after which the shutdown command should be killed,
                    or None for no timeout

    """
    instance_info = self.GetInstanceInfo(name, hvparams=hvparams)

    if instance_info is None:
      raise errors.HypervisorError("Failed to shutdown instance %s,"
                                   " not running" % name)

    if not force:
      self._ShutdownInstance(name, hvparams, timeout)

    # TODO: Xen does always destroy the instnace after trying a gracefull
    # shutdown. That means doing another attempt with force=True will not make
    # any difference. This differs in behaviour from other hypervisors and
    # should be cleaned up.
    result = self._DestroyInstanceIfAlive(name, hvparams)
    if result is not None and result.failed and \
          self.GetInstanceInfo(name, hvparams=hvparams) is not None:
      raise errors.HypervisorError("Failed to stop instance %s: %s, %s" %
                                   (name, result.fail_reason, result.output))

    # Remove configuration file if stopping/starting instance was successful
    self._RemoveConfigFile(name)

  def RebootInstance(self, instance):
    """Reboot an instance.

    """
    ini_info = self.GetInstanceInfo(instance.name, hvparams=instance.hvparams)

    if ini_info is None:
      raise errors.HypervisorError("Failed to reboot instance %s,"
                                   " not running" % instance.name)

    result = self._RunXen(["reboot", instance.name], instance.hvparams)
    if result.failed:
      raise errors.HypervisorError("Failed to reboot instance %s: %s, %s" %
                                   (instance.name, result.fail_reason,
                                    result.output))

    def _CheckInstance():
      new_info = self.GetInstanceInfo(instance.name, hvparams=instance.hvparams)

      # check if the domain ID has changed or the run time has decreased
      if (new_info is not None and
          (_InstanceDomID(new_info) != _InstanceDomID(ini_info) or (
              _InstanceRuntime(new_info) < _InstanceRuntime(ini_info)))):
        return

      raise utils.RetryAgain()

    try:
      utils.Retry(_CheckInstance, self.REBOOT_RETRY_INTERVAL,
                  self.REBOOT_RETRY_INTERVAL * self.REBOOT_RETRY_COUNT)
    except utils.RetryTimeout:
      raise errors.HypervisorError("Failed to reboot instance %s: instance"
                                   " did not reboot in the expected interval" %
                                   (instance.name, ))

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    result = self._RunXen(["mem-set", instance.name, mem], instance.hvparams)
    if result.failed:
      raise errors.HypervisorError("Failed to balloon instance %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))

    # Update configuration file
    cmd = ["sed", "-ie", "s/^memory.*$/memory = %s/" % mem]
    cmd.append(self._ConfigFileName(instance.name))

    result = utils.RunCmd(cmd)
    if result.failed:
      raise errors.HypervisorError("Failed to update memory for %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))

  def GetNodeInfo(self, hvparams=None):
    """Return information about the node.

    @see: L{_GetNodeInfo} and L{_ParseNodeInfo}

    """
    result = self._RunXen(["info"], hvparams)
    if result.failed:
      logging.error("Can't retrieve xen hypervisor information (%s): %s",
                    result.fail_reason, result.output)
      return None

    instance_list = self._GetInstanceList(True, hvparams)
    return _GetNodeInfo(result.stdout, instance_list)

  @classmethod
  def GetInstanceConsole(cls, instance, primary_node, node_group,
                         hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    xen_cmd = XenHypervisor._GetCommandFromHvparams(hvparams)
    ndparams = node_group.FillND(primary_node)
    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_SSH,
                                   host=primary_node.name,
                                   port=ndparams.get(constants.ND_SSH_PORT),
                                   user=constants.SSH_CONSOLE_USER,
                                   command=[pathutils.XEN_CONSOLE_WRAPPER,
                                            xen_cmd, instance.name])

  def Verify(self, hvparams=None):
    """Verify the hypervisor.

    For Xen, this verifies that the xend process is running.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be verified against

    @return: Problem description if something is wrong, C{None} otherwise

    """
    if hvparams is None:
      return "Could not verify the hypervisor, because no hvparams were" \
             " provided."

    if constants.HV_XEN_CMD in hvparams:
      xen_cmd = hvparams[constants.HV_XEN_CMD]
      try:
        self._CheckToolstack(xen_cmd)
      except errors.HypervisorError:
        return "The configured xen toolstack '%s' is not available on this" \
               " node." % xen_cmd

    result = self._RunXen(["info"], hvparams)
    if result.failed:
      return "Retrieving information from xen failed: %s, %s" % \
        (result.fail_reason, result.output)

    return None

  def MigrationInfo(self, instance):
    """Get instance information to perform a migration.

    @type instance: L{objects.Instance}
    @param instance: instance to be migrated
    @rtype: string
    @return: content of the xen config file

    """
    return self._ReadConfigFile(instance.name)

  def _UseMigrationDaemon(self, hvparams):
    """Whether to start a socat daemon when accepting an instance.

    @rtype: bool

    """
    return self._GetCommand(hvparams) == constants.XEN_CMD_XL

  @classmethod
  def _KillMigrationDaemon(cls, instance):
    """Kills the migration daemon if present.

    """
    pidfile = cls._InstanceMigrationPidfile(instance.name)
    read_pid = utils.ReadPidFile(pidfile)

    # There is no pidfile, hence nothing for us to do
    if read_pid == 0:
      return

    if utils.IsProcessAlive(read_pid):
      # If the process is alive, let's make sure we are killing the right one
      cmdline = ' '.join(utils.GetProcCmdline(read_pid))
      if cmdline.count("xl migrate-receive") > 0:
        utils.KillProcess(read_pid)

    # By this point the process is not running, whether killed or initially
    # nonexistent, so it is safe to remove the pidfile.
    utils.RemoveFile(pidfile)

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string
    @param info: content of the xen config file on the source node
    @type target: string
    @param target: target host (usually ip), on this node

    """
    if self._UseMigrationDaemon(instance.hvparams):
      port = instance.hvparams[constants.HV_MIGRATION_PORT]

      # Make sure there is somewhere to put the pidfile.
      XenHypervisor._EnsureDirs()
      pidfile = XenHypervisor._InstanceMigrationPidfile(instance.name)

      # And try and kill a previous daemon
      XenHypervisor._KillMigrationDaemon(instance)

      listening_arg = "TCP-LISTEN:%d,bind=%s,reuseaddr" % (port, target)
      socat_pid = utils.StartDaemon(["socat", "-b524288", listening_arg,
                                     "SYSTEM:'xl migrate-receive'"],
                                     pidfile=pidfile)

      # Wait for a while to make sure the socat process has successfully started
      # listening
      time.sleep(1)
      if not utils.IsProcessAlive(socat_pid):
        raise errors.HypervisorError("Could not start receiving socat process"
                                     " on port %d: check if port is available" %
                                     port)

  def FinalizeMigrationDst(self, instance, config, success):
    """Finalize an instance migration.

    Write a config file if the instance is running on the destination node
    regardles if we think the migration succeeded or not. This will cover cases,
    when the migration succeeded but due to a timeout on the source node we
    think it failed. If we think the migration failed and there is an unstarted
    domain, clean it up.

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being finalized
    @type config: string
    @param config: content of the xen config file from the source node
    @type success: boolean
    @param success: whether the master node thinks the migration succeeded

    """

    # We should recreate the config file if the domain is present and running,
    # regardless if we think the migration succeeded or not.
    info = self.GetInstanceInfo(instance.name, hvparams=instance.hvparams)
    if info and _InstanceRuntime(info) != 0:
      self._WriteConfigFile(instance.name, config)

    if not success:
      if self._UseMigrationDaemon(instance.hvparams):
        XenHypervisor._KillMigrationDaemon(instance)

      # Fix the common failure when the domain was created but never started:
      # this happens if the memory transfer didn't complete and the instance
      # is running on the source node.
      if info and _InstanceRuntime(info) == 0:
        self._DestroyInstance(instance.name, instance.hvparams)

  def MigrateInstance(self, _cluster_name, instance, target, live):
    """Migrate an instance to a target node.

    The migration will not be attempted if the instance is not
    currently running.

    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: ip address of the target node
    @type live: boolean
    @param live: perform a live migration

    """
    port = instance.hvparams[constants.HV_MIGRATION_PORT]

    return self._MigrateInstance(instance.name, target, port, live,
                                 instance.hvparams)

  def _MigrateInstance(self, instance_name, target, port, live, hvparams,
                       _ping_fn=netutils.TcpPing):
    """Migrate an instance to a target node.

    @see: L{MigrateInstance} for details

    """
    if hvparams is None:
      raise errors.HypervisorError("No hvparams provided.")

    if self.GetInstanceInfo(instance_name, hvparams=hvparams) is None:
      raise errors.HypervisorError("Instance not running, cannot migrate")

    cmd = self._GetCommand(hvparams)

    args = ["migrate"]

    if cmd == constants.XEN_CMD_XM:
      # Try and see if xm is listening on the specified port
      if not _ping_fn(target, port, live_port_needed=True):
        raise errors.HypervisorError("Remote host %s not listening on port"
                                     " %s, cannot migrate" % (target, port))

      args.extend(["-p", "%d" % port])
      if live:
        args.append("-l")

    elif cmd == constants.XEN_CMD_XL:
      # Rather than using SSH, use socat as Ganeti cannot guarantee the presence
      # of usable SSH keys as of 2.13
      args.extend([
        "-s", constants.XL_SOCAT_CMD % (target, port),
        "-C", self._ConfigFileName(instance_name),
        ])

    else:
      raise errors.HypervisorError("Unsupported Xen command: %s" % cmd)

    args.extend([instance_name, target])

    result = self._RunXen(args, hvparams)
    if result.failed:
      raise errors.HypervisorError("Failed to migrate instance %s: %s" %
                                   (instance_name, result.output))

  def FinalizeMigrationSource(self, instance, success, _):
    """Finalize the instance migration on the source node.

    @type instance: L{objects.Instance}
    @param instance: the instance that was migrated
    @type success: bool
    @param success: whether the master thinks the migration succeeded

    """
    # pylint: disable=W0613
    if success:
      # Remove old xen file after migration succeeded
      # Note that _RemoveConfigFile silently succeeds if the file is already
      # deleted, that makes this function idempotent
      try:
        self._RemoveConfigFile(instance.name)
      except EnvironmentError:
        logging.exception("Failure while removing instance config file")
    else:
      # Cleanup the most common failure case when the source instance fails
      # to freeze and remains running renamed:
      # XM: renamed to 'migrating-${oldname}'
      # XL: renamed to '${oldname}--migratedaway'

      temp_name, info = None, None
      for n in ['migrating-' + instance.name, instance.name + '--migratedaway']:
        info = self.GetInstanceInfo(n, hvparams=instance.hvparams)
        if info:
          temp_name = n
          break

      if info:
        self._RenameInstance(temp_name, instance.name, instance.hvparams)

  def GetMigrationStatus(self, instance):
    """Get the migration status

    As MigrateInstance for Xen is still blocking, if this method is called it
    means that MigrateInstance has completed successfully. So we can safely
    assume that the migration was successful and notify this fact to the client.

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    return objects.MigrationStatus(status=constants.HV_MIGRATION_COMPLETED)

  def PowercycleNode(self, hvparams=None):
    """Xen-specific powercycle.

    This first does a Linux reboot (which triggers automatically a Xen
    reboot), and if that fails it tries to do a Xen reboot. The reason
    we don't try a Xen reboot first is that the xen reboot launches an
    external command which connects to the Xen hypervisor, and that
    won't work in case the root filesystem is broken and/or the xend
    daemon is not working.

    @type hvparams: dict of strings
    @param hvparams: hypervisor params to be used on this node

    """
    try:
      self.LinuxPowercycle()
    finally:
      xen_cmd = self._GetCommand(hvparams)
      utils.RunCmd([xen_cmd, "debug", "R"])

  def _CheckToolstack(self, xen_cmd):
    """Check whether the given toolstack is available on the node.

    @type xen_cmd: string
    @param xen_cmd: xen command (e.g. 'xm' or 'xl')

    """
    binary_found = self._CheckToolstackBinary(xen_cmd)
    if not binary_found:
      raise errors.HypervisorError("No '%s' binary found on node." % xen_cmd)
    elif xen_cmd == constants.XEN_CMD_XL:
      if not self._CheckToolstackXlConfigured():
        raise errors.HypervisorError("Toolstack '%s' is not enabled on this"
                                     "node." % xen_cmd)

  def _CheckToolstackBinary(self, xen_cmd):
    """Checks whether the xen command's binary is found on the machine.

    """
    if xen_cmd not in constants.KNOWN_XEN_COMMANDS:
      raise errors.HypervisorError("Unknown xen command '%s'." % xen_cmd)
    result = self._run_cmd_fn(["which", xen_cmd])
    return not result.failed

  def _CheckToolstackXlConfigured(self):
    """Checks whether xl is enabled on an xl-capable node.

    @rtype: bool
    @returns: C{True} if 'xl' is enabled, C{False} otherwise

    """
    result = self._run_cmd_fn([constants.XEN_CMD_XL, "help"])
    if not result.failed:
      return True
    elif result.failed:
      if "toolstack" in result.stderr:
        return False
      # xl fails for some other reason than the toolstack
      else:
        raise errors.HypervisorError("Cannot run xen ('%s'). Error: %s."
                                     % (constants.XEN_CMD_XL, result.stderr))


def WriteXenConfigEvents(config, hvp):
  config.write("on_poweroff = 'preserve'\n")
  if hvp[constants.HV_REBOOT_BEHAVIOR] == constants.INSTANCE_REBOOT_ALLOWED:
    config.write("on_reboot = 'restart'\n")
  else:
    config.write("on_reboot = 'destroy'\n")
  config.write("on_crash = 'restart'\n")


class XenPvmHypervisor(XenHypervisor):
  """Xen PVM hypervisor interface"""

  PARAMETERS = {
    constants.HV_USE_BOOTLOADER: hv_base.NO_CHECK,
    constants.HV_BOOTLOADER_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_BOOTLOADER_ARGS: hv_base.NO_CHECK,
    constants.HV_KERNEL_PATH: hv_base.REQ_FILE_CHECK,
    constants.HV_INITRD_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_ROOT_PATH: hv_base.NO_CHECK,
    constants.HV_KERNEL_ARGS: hv_base.NO_CHECK,
    constants.HV_MIGRATION_PORT: hv_base.REQ_NET_PORT_CHECK,
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    # TODO: Add a check for the blockdev prefix (matching [a-z:] or similar).
    constants.HV_BLOCKDEV_PREFIX: hv_base.NO_CHECK,
    constants.HV_REBOOT_BEHAVIOR:
      hv_base.ParamInSet(True, constants.REBOOT_BEHAVIORS),
    constants.HV_CPU_MASK: hv_base.OPT_MULTI_CPU_MASK_CHECK,
    constants.HV_CPU_CAP: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    constants.HV_CPU_WEIGHT:
      (False, lambda x: 0 < x < 65536, "invalid weight", None, None),
    constants.HV_VIF_SCRIPT: hv_base.OPT_FILE_CHECK,
    constants.HV_XEN_CMD:
      hv_base.ParamInSet(True, constants.KNOWN_XEN_COMMANDS),
    constants.HV_XEN_CPUID: hv_base.NO_CHECK,
    constants.HV_SOUNDHW: hv_base.NO_CHECK,
    }

  def _GetConfig(self, instance, startup_memory, block_devices):
    """Write the Xen config file for the instance.

    """
    hvp = instance.hvparams
    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")

    # if bootloader is True, use bootloader instead of kernel and ramdisk
    # parameters.
    if hvp[constants.HV_USE_BOOTLOADER]:
      # bootloader handling
      bootloader_path = hvp[constants.HV_BOOTLOADER_PATH]
      if bootloader_path:
        config.write("bootloader = '%s'\n" % bootloader_path)
      else:
        raise errors.HypervisorError("Bootloader enabled, but missing"
                                     " bootloader path")

      bootloader_args = hvp[constants.HV_BOOTLOADER_ARGS]
      if bootloader_args:
        config.write("bootargs = '%s'\n" % bootloader_args)
    else:
      # kernel handling
      kpath = hvp[constants.HV_KERNEL_PATH]
      config.write("kernel = '%s'\n" % kpath)

      # initrd handling
      initrd_path = hvp[constants.HV_INITRD_PATH]
      if initrd_path:
        config.write("ramdisk = '%s'\n" % initrd_path)

    # rest of the settings
    config.write("memory = %d\n" % startup_memory)
    config.write("maxmem = %d\n" % instance.beparams[constants.BE_MAXMEM])
    config.write("vcpus = %d\n" % instance.beparams[constants.BE_VCPUS])
    cpu_pinning = _CreateConfigCpus(hvp[constants.HV_CPU_MASK])
    if cpu_pinning:
      config.write("%s\n" % cpu_pinning)
    cpu_cap = hvp[constants.HV_CPU_CAP]
    if cpu_cap:
      config.write("cpu_cap=%d\n" % cpu_cap)
    cpu_weight = hvp[constants.HV_CPU_WEIGHT]
    if cpu_weight:
      config.write("cpu_weight=%d\n" % cpu_weight)

    config.write("name = '%s'\n" % instance.name)

    self._WriteNicConfig(config, instance, hvp)

    disk_data = \
      _GetConfigFileDiskData(block_devices, hvp[constants.HV_BLOCKDEV_PREFIX])
    config.write("disk = [%s]\n" % ",".join(disk_data))

    if hvp[constants.HV_ROOT_PATH]:
      config.write("root = '%s'\n" % hvp[constants.HV_ROOT_PATH])

    WriteXenConfigEvents(config, hvp)
    config.write("extra = '%s'\n" % hvp[constants.HV_KERNEL_ARGS])

    cpuid = hvp[constants.HV_XEN_CPUID]
    if cpuid:
      config.write("cpuid = %s\n" % _QuoteCpuidField(cpuid))

    if hvp[constants.HV_SOUNDHW]:
      config.write("soundhw = '%s'\n" % hvp[constants.HV_SOUNDHW])

    return config.getvalue()


class XenHvmHypervisor(XenHypervisor):
  """Xen HVM hypervisor interface"""

  ANCILLARY_FILES = XenHypervisor.ANCILLARY_FILES + [
    pathutils.VNC_PASSWORD_FILE,
    ]
  ANCILLARY_FILES_OPT = XenHypervisor.ANCILLARY_FILES_OPT + [
    pathutils.VNC_PASSWORD_FILE,
    ]

  PARAMETERS = {
    constants.HV_ACPI: hv_base.NO_CHECK,
    constants.HV_BOOT_ORDER: (True, ) +
      (lambda x: x and len(x.strip("acdn")) == 0,
       "Invalid boot order specified, must be one or more of [acdn]",
       None, None),
    constants.HV_CDROM_IMAGE_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_DISK_TYPE:
      hv_base.ParamInSet(True, constants.HT_HVM_VALID_DISK_TYPES),
    constants.HV_NIC_TYPE:
      hv_base.ParamInSet(True, constants.HT_HVM_VALID_NIC_TYPES),
    constants.HV_PAE: hv_base.NO_CHECK,
    constants.HV_VNC_BIND_ADDRESS:
      (False, netutils.IP4Address.IsValid,
       "VNC bind address is not a valid IP address", None, None),
    constants.HV_KERNEL_PATH: hv_base.REQ_FILE_CHECK,
    constants.HV_DEVICE_MODEL: hv_base.REQ_FILE_CHECK,
    constants.HV_VNC_PASSWORD_FILE: hv_base.REQ_FILE_CHECK,
    constants.HV_MIGRATION_PORT: hv_base.REQ_NET_PORT_CHECK,
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    constants.HV_USE_LOCALTIME: hv_base.NO_CHECK,
    # TODO: Add a check for the blockdev prefix (matching [a-z:] or similar).
    constants.HV_BLOCKDEV_PREFIX: hv_base.NO_CHECK,
    # Add PCI passthrough
    constants.HV_PASSTHROUGH: hv_base.NO_CHECK,
    constants.HV_REBOOT_BEHAVIOR:
      hv_base.ParamInSet(True, constants.REBOOT_BEHAVIORS),
    constants.HV_CPU_MASK: hv_base.OPT_MULTI_CPU_MASK_CHECK,
    constants.HV_CPU_CAP: hv_base.NO_CHECK,
    constants.HV_CPU_WEIGHT:
      (False, lambda x: 0 < x < 65535, "invalid weight", None, None),
    constants.HV_VIF_TYPE:
      hv_base.ParamInSet(False, constants.HT_HVM_VALID_VIF_TYPES),
    constants.HV_VIF_SCRIPT: hv_base.OPT_FILE_CHECK,
    constants.HV_VIRIDIAN: hv_base.NO_CHECK,
    constants.HV_XEN_CMD:
      hv_base.ParamInSet(True, constants.KNOWN_XEN_COMMANDS),
    constants.HV_XEN_CPUID: hv_base.NO_CHECK,
    constants.HV_SOUNDHW: hv_base.NO_CHECK,
    }

  def _GetConfig(self, instance, startup_memory, block_devices):
    """Create a Xen 3.1 HVM config file.

    """
    hvp = instance.hvparams

    config = StringIO()

    # kernel handling
    kpath = hvp[constants.HV_KERNEL_PATH]
    config.write("kernel = '%s'\n" % kpath)

    config.write("builder = 'hvm'\n")
    config.write("memory = %d\n" % startup_memory)
    config.write("maxmem = %d\n" % instance.beparams[constants.BE_MAXMEM])
    config.write("vcpus = %d\n" % instance.beparams[constants.BE_VCPUS])
    cpu_pinning = _CreateConfigCpus(hvp[constants.HV_CPU_MASK])
    if cpu_pinning:
      config.write("%s\n" % cpu_pinning)
    cpu_cap = hvp[constants.HV_CPU_CAP]
    if cpu_cap:
      config.write("cpu_cap=%d\n" % cpu_cap)
    cpu_weight = hvp[constants.HV_CPU_WEIGHT]
    if cpu_weight:
      config.write("cpu_weight=%d\n" % cpu_weight)

    config.write("name = '%s'\n" % instance.name)
    if hvp[constants.HV_PAE]:
      config.write("pae = 1\n")
    else:
      config.write("pae = 0\n")
    if hvp[constants.HV_ACPI]:
      config.write("acpi = 1\n")
    else:
      config.write("acpi = 0\n")
    if hvp[constants.HV_VIRIDIAN]:
      config.write("viridian = 1\n")
    else:
      config.write("viridian = 0\n")

    config.write("apic = 1\n")
    config.write("device_model = '%s'\n" % hvp[constants.HV_DEVICE_MODEL])
    config.write("boot = '%s'\n" % hvp[constants.HV_BOOT_ORDER])
    config.write("sdl = 0\n")
    config.write("usb = 1\n")
    config.write("usbdevice = 'tablet'\n")
    config.write("vnc = 1\n")
    if hvp[constants.HV_VNC_BIND_ADDRESS] is None:
      config.write("vnclisten = '%s'\n" % constants.VNC_DEFAULT_BIND_ADDRESS)
    else:
      config.write("vnclisten = '%s'\n" % hvp[constants.HV_VNC_BIND_ADDRESS])

    if instance.network_port > constants.VNC_BASE_PORT:
      display = instance.network_port - constants.VNC_BASE_PORT
      config.write("vncdisplay = %s\n" % display)
      config.write("vncunused = 0\n")
    else:
      config.write("# vncdisplay = 1\n")
      config.write("vncunused = 1\n")

    vnc_pwd_file = hvp[constants.HV_VNC_PASSWORD_FILE]
    try:
      password = utils.ReadFile(vnc_pwd_file)
    except EnvironmentError as err:
      raise errors.HypervisorError("Failed to open VNC password file %s: %s" %
                                   (vnc_pwd_file, err))

    config.write("vncpasswd = '%s'\n" % password.rstrip())

    config.write("serial = 'pty'\n")
    if hvp[constants.HV_USE_LOCALTIME]:
      config.write("localtime = 1\n")

    self._WriteNicConfig(config, instance, hvp)

    disk_data = \
      _GetConfigFileDiskData(block_devices, hvp[constants.HV_BLOCKDEV_PREFIX])

    iso_path = hvp[constants.HV_CDROM_IMAGE_PATH]
    if iso_path:
      iso = "'file:%s,hdc:cdrom,r'" % iso_path
      disk_data.append(iso)

    config.write("disk = [%s]\n" % (",".join(disk_data)))
    # Add PCI passthrough
    pci_pass_arr = []
    pci_pass = hvp[constants.HV_PASSTHROUGH]
    if pci_pass:
      pci_pass_arr = pci_pass.split(";")
      config.write("pci = %s\n" % pci_pass_arr)

    WriteXenConfigEvents(config, hvp)

    cpuid = hvp[constants.HV_XEN_CPUID]
    if cpuid:
      config.write("cpuid = %s\n" % _QuoteCpuidField(cpuid))

    if hvp[constants.HV_SOUNDHW]:
      config.write("soundhw = '%s'\n" % hvp[constants.HV_SOUNDHW])

    return config.getvalue()
