#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2012, 2013 Google Inc.
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


"""Base class for all hypervisors

The syntax for the _CHECK variables and the contents of the PARAMETERS
dict is the same, see the docstring for L{BaseHypervisor.PARAMETERS}.

@var _FILE_CHECK: stub for file checks, without the required flag
@var _DIR_CHECK: stub for directory checks, without the required flag
@var REQ_FILE_CHECK: mandatory file parameter
@var OPT_FILE_CHECK: optional file parameter
@var REQ_DIR_CHECK: mandatory directory parametr
@var OPT_DIR_CHECK: optional directory parameter
@var NO_CHECK: parameter without any checks at all
@var REQUIRED_CHECK: parameter required to exist (and non-false), but
    without other checks; beware that this can't be used for boolean
    parameters, where you should use NO_CHECK or a custom checker

"""

import os
import re
import logging


from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import utils


def _IsCpuMaskWellFormed(cpu_mask):
  """Verifies if the given single CPU mask is valid

  The single CPU mask should be in the form "a,b,c,d", where each
  letter is a positive number or range.

  """
  try:
    cpu_list = utils.ParseCpuMask(cpu_mask)
  except errors.ParseError, _:
    return False
  return isinstance(cpu_list, list) and len(cpu_list) > 0


def _IsMultiCpuMaskWellFormed(cpu_mask):
  """Verifies if the given multiple CPU mask is valid

  A valid multiple CPU mask is in the form "a:b:c:d", where each
  letter is a single CPU mask.

  """
  try:
    utils.ParseMultiCpuMask(cpu_mask)
  except errors.ParseError, _:
    return False

  return True


# Read the BaseHypervisor.PARAMETERS docstring for the syntax of the
# _CHECK values

# must be a file
_FILE_CHECK = (utils.IsNormAbsPath, "must be an absolute normalized path",
               os.path.isfile, "not found or not a file")

# must be a file or a URL
_FILE_OR_URL_CHECK = (lambda x: utils.IsNormAbsPath(x) or utils.IsUrl(x),
                      "must be an absolute normalized path or a URL",
                      lambda x: os.path.isfile(x) or utils.IsUrl(x),
                      "not found or not a file or URL")

# must be a directory
_DIR_CHECK = (utils.IsNormAbsPath, "must be an absolute normalized path",
              os.path.isdir, "not found or not a directory")

# CPU mask must be well-formed
# TODO: implement node level check for the CPU mask
_CPU_MASK_CHECK = (_IsCpuMaskWellFormed,
                   "CPU mask definition is not well-formed",
                   None, None)

# Multiple CPU mask must be well-formed
_MULTI_CPU_MASK_CHECK = (_IsMultiCpuMaskWellFormed,
                         "Multiple CPU mask definition is not well-formed",
                         None, None)

# Check for validity of port number
_NET_PORT_CHECK = (lambda x: 0 < x < 65535, "invalid port number",
                   None, None)

# Check if number of queues is in safe range
_VIRTIO_NET_QUEUES_CHECK = (lambda x: 0 < x < 9, "invalid number of queues",
                            None, None)

# Check that an integer is non negative
_NONNEGATIVE_INT_CHECK = (lambda x: x >= 0, "cannot be negative", None, None)

# nice wrappers for users
REQ_FILE_CHECK = (True, ) + _FILE_CHECK
OPT_FILE_CHECK = (False, ) + _FILE_CHECK
REQ_FILE_OR_URL_CHECK = (True, ) + _FILE_OR_URL_CHECK
OPT_FILE_OR_URL_CHECK = (False, ) + _FILE_OR_URL_CHECK
REQ_DIR_CHECK = (True, ) + _DIR_CHECK
OPT_DIR_CHECK = (False, ) + _DIR_CHECK
REQ_NET_PORT_CHECK = (True, ) + _NET_PORT_CHECK
OPT_NET_PORT_CHECK = (False, ) + _NET_PORT_CHECK
REQ_VIRTIO_NET_QUEUES_CHECK = (True, ) + _VIRTIO_NET_QUEUES_CHECK
OPT_VIRTIO_NET_QUEUES_CHECK = (False, ) + _VIRTIO_NET_QUEUES_CHECK
REQ_CPU_MASK_CHECK = (True, ) + _CPU_MASK_CHECK
OPT_CPU_MASK_CHECK = (False, ) + _CPU_MASK_CHECK
REQ_MULTI_CPU_MASK_CHECK = (True, ) + _MULTI_CPU_MASK_CHECK
OPT_MULTI_CPU_MASK_CHECK = (False, ) + _MULTI_CPU_MASK_CHECK
REQ_NONNEGATIVE_INT_CHECK = (True, ) + _NONNEGATIVE_INT_CHECK
OPT_NONNEGATIVE_INT_CHECK = (False, ) + _NONNEGATIVE_INT_CHECK

# no checks at all
NO_CHECK = (False, None, None, None, None)

# required, but no other checks
REQUIRED_CHECK = (True, None, None, None, None)

# migration type
MIGRATION_MODE_CHECK = (True, lambda x: x in constants.HT_MIGRATION_MODES,
                        "invalid migration mode", None, None)


def ParamInSet(required, my_set):
  """Builds parameter checker for set membership.

  @type required: boolean
  @param required: whether this is a required parameter
  @type my_set: tuple, list or set
  @param my_set: allowed values set

  """
  fn = lambda x: x in my_set
  err = ("The value must be one of: %s" % utils.CommaJoin(my_set))
  return (required, fn, err, None, None)


def GenerateTapName():
  """Generate a TAP network interface name for a NIC.

  This helper function generates a special TAP network interface
  name for NICs that are meant to be used in instance communication.
  This function checks the existing TAP interfaces in order to find
  a unique name for the new TAP network interface.  The TAP network
  interface names are of the form 'gnt.com.%d', where '%d' is a
  unique number within the node.

  @rtype: string
  @return: TAP network interface name, or the empty string if the
           NIC is not used in instance communication

  """
  result = utils.RunCmd(["ip", "link", "show"])

  if result.failed:
    raise errors.HypervisorError("Failed to list TUN/TAP interfaces")

  idxs = set()

  for line in result.output.splitlines()[0::2]:
    parts = line.split(": ")

    if len(parts) < 2:
      raise errors.HypervisorError("Failed to parse TUN/TAP interfaces")

    r = re.match(r"gnt\.com\.([0-9]+)", parts[1])

    if r is not None:
      idxs.add(int(r.group(1)))

  if idxs:
    idx = max(idxs) + 1
  else:
    idx = 0

  return "gnt.com.%d" % idx


def ConfigureNIC(cmd, instance, seq, nic, tap):
  """Run the network configuration script for a specified NIC

  @type cmd: string
  @param cmd: command to run
  @type instance: instance object
  @param instance: instance we're acting on
  @type seq: int
  @param seq: nic sequence number
  @type nic: nic object
  @param nic: nic we're acting on
  @type tap: str
  @param tap: the host's tap interface this NIC corresponds to

  """
  env = {
    "PATH": "%s:/sbin:/usr/sbin" % os.environ["PATH"],
    "INSTANCE": instance.name,
    "MAC": nic.mac,
    "MODE": nic.nicparams[constants.NIC_MODE],
    "INTERFACE": tap,
    "INTERFACE_INDEX": str(seq),
    "INTERFACE_UUID": nic.uuid,
    "TAGS": " ".join(instance.GetTags()),
  }

  if nic.ip:
    env["IP"] = nic.ip

  if nic.name:
    env["INTERFACE_NAME"] = nic.name

  if nic.nicparams[constants.NIC_LINK]:
    env["LINK"] = nic.nicparams[constants.NIC_LINK]

  if constants.NIC_VLAN in nic.nicparams:
    env["VLAN"] = nic.nicparams[constants.NIC_VLAN]

  if nic.network:
    n = objects.Network.FromDict(nic.netinfo)
    env.update(n.HooksDict())

  if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
    env["BRIDGE"] = nic.nicparams[constants.NIC_LINK]

  result = utils.RunCmd(cmd, env=env)
  if result.failed:
    raise errors.HypervisorError("Failed to configure interface %s: %s;"
                                 " network configuration script output: %s" %
                                 (tap, result.fail_reason, result.output))


class HvInstanceState(object):
  RUNNING = 0
  SHUTDOWN = 1

  @staticmethod
  def IsRunning(s):
    return s == HvInstanceState.RUNNING

  @staticmethod
  def IsShutdown(s):
    return s == HvInstanceState.SHUTDOWN


class BaseHypervisor(object):
  """Abstract virtualisation technology interface

  The goal is that all aspects of the virtualisation technology are
  abstracted away from the rest of code.

  @cvar PARAMETERS: a dict of parameter name: check type; the check type is
      a five-tuple containing:
          - the required flag (boolean)
          - a function to check for syntax, that will be used in
            L{CheckParameterSyntax}, in the master daemon process
          - an error message for the above function
          - a function to check for parameter validity on the remote node,
            in the L{ValidateParameters} function
          - an error message for the above function
  @type CAN_MIGRATE: boolean
  @cvar CAN_MIGRATE: whether this hypervisor can do migration (either
      live or non-live)

  """
  PARAMETERS = {}
  ANCILLARY_FILES = []
  ANCILLARY_FILES_OPT = []
  CAN_MIGRATE = False

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to start
    @type block_devices: list of tuples (disk_object, link_name, drive_uri)
    @param block_devices: blockdevices assigned to this instance
    @type startup_paused: bool
    @param startup_paused: if instance should be paused at startup
    """
    raise NotImplementedError

  def VerifyInstance(self, instance):  # pylint: disable=R0201,W0613
    """Verify if running instance (config) is in correct state.

    @type instance: L{objects.Instance}
    @param instance: instance to verify

    @return: bool, if instance in correct state
    """
    return True

  def RestoreInstance(self, instance, block_devices):
    """Fixup running instance's (config) state.

    @type instance: L{objects.Instance}
    @param instance: instance to restore
    @type block_devices: list of tuples (disk_object, link_name, drive_uri)
    @param block_devices: blockdevices assigned to this instance
    """
    pass

  def StopInstance(self, instance, force=False, retry=False, name=None,
                   timeout=None):
    """Stop an instance

    @type instance: L{objects.Instance}
    @param instance: instance to stop
    @type force: boolean
    @param force: whether to do a "hard" stop (destroy)
    @type retry: boolean
    @param retry: whether this is just a retry call
    @type name: string or None
    @param name: if this parameter is passed, the the instance object
        should not be used (will be passed as None), and the shutdown
        must be done by name only
    @type timeout: int or None
    @param timeout: if the parameter is not None, a soft shutdown operation will
        be killed after the specified number of seconds. A hard (forced)
        shutdown cannot have a timeout
    @raise errors.HypervisorError: when a parameter is not valid or
        the instance failed to be stopped

    """
    raise NotImplementedError

  def CleanupInstance(self, instance_name):
    """Cleanup after a stopped instance

    This is an optional method, used by hypervisors that need to cleanup after
    an instance has been stopped.

    @type instance_name: string
    @param instance_name: instance name to cleanup after

    """
    pass

  def RebootInstance(self, instance):
    """Reboot an instance."""
    raise NotImplementedError

  def ListInstances(self, hvparams=None):
    """Get the list of running instances."""
    raise NotImplementedError

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: hvparams to be used with this instance

    @rtype: (string, string, int, int, HvInstanceState, int)
    @return: tuple (name, id, memory, vcpus, state, times)

    """
    raise NotImplementedError

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameter

    @rtype: (string, string, int, int, HvInstanceState, int)
    @return: list of tuples (name, id, memory, vcpus, state, times)

    """
    raise NotImplementedError

  def GetNodeInfo(self, hvparams=None):
    """Return information about the node.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters

    @return: a dict with at least the following keys (memory values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available
          - cpu_total: total number of CPUs
          - cpu_dom0: number of CPUs used by the node OS
          - cpu_nodes: number of NUMA domains
          - cpu_sockets: number of physical CPU sockets

    """
    raise NotImplementedError

  @classmethod
  def GetInstanceConsole(cls, instance, primary_node, node_group,
                         hvparams, beparams):
    """Return information for connecting to the console of an instance.

    """
    raise NotImplementedError

  @classmethod
  def GetAncillaryFiles(cls):
    """Return a list of ancillary files to be copied to all nodes as ancillary
    configuration files.

    @rtype: (list of absolute paths, list of absolute paths)
    @return: (all files, optional files)

    """
    # By default we return a member variable, so that if an hypervisor has just
    # a static list of files it doesn't have to override this function.
    assert set(cls.ANCILLARY_FILES).issuperset(cls.ANCILLARY_FILES_OPT), \
      "Optional ancillary files must be a subset of ancillary files"

    return (cls.ANCILLARY_FILES, cls.ANCILLARY_FILES_OPT)

  def Verify(self, hvparams=None):
    """Verify the hypervisor.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be verified against

    @return: Problem description if something is wrong, C{None} otherwise

    """
    raise NotImplementedError

  @staticmethod
  def VersionsSafeForMigration(src, target):
    """Decide if migration between those version is likely to suceed.

    Given two versions of a hypervisor, give a guess whether live migration
    from the one version to the other version is likely to succeed. The current

    """
    if src == target:
      return True

    return False

  def MigrationInfo(self, instance): # pylint: disable=R0201,W0613
    """Get instance information to perform a migration.

    By default assume no information is needed.

    @type instance: L{objects.Instance}
    @param instance: instance to be migrated
    @rtype: string/data (opaque)
    @return: instance migration information - serialized form

    """
    return ""

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    By default assume no preparation is needed.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string/data (opaque)
    @param info: migration information, from the source node
    @type target: string
    @param target: target host (usually ip), on this node

    """
    pass

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    raise NotImplementedError

  def FinalizeMigrationDst(self, instance, info, success):
    """Finalize the instance migration on the target node.

    Should finalize or revert any preparation done to accept the instance.
    Since by default we do no preparation, we also don't have anything to do

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being finalized
    @type info: string/data (opaque)
    @param info: migration information, from the source node
    @type success: boolean
    @param success: whether the migration was a success or a failure

    """
    pass

  def MigrateInstance(self, cluster_name, instance, target, live):
    """Migrate an instance.

    @type cluster_name: string
    @param cluster_name: name of the cluster
    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: hostname (usually ip) of the target node
    @type live: boolean
    @param live: whether to do a live or non-live migration

    """
    raise NotImplementedError

  def FinalizeMigrationSource(self, instance, success, live):
    """Finalize the instance migration on the source node.

    @type instance: L{objects.Instance}
    @param instance: the instance that was migrated
    @type success: bool
    @param success: whether the migration succeeded or not
    @type live: bool
    @param live: whether the user requested a live migration or not

    """
    pass

  def GetMigrationStatus(self, instance):
    """Get the migration status

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    raise NotImplementedError

  def _InstanceStartupMemory(self, instance):
    """Get the correct startup memory for an instance

    This function calculates how much memory an instance should be started
    with, making sure it's a value between the minimum and the maximum memory,
    but also trying to use no more than the current free memory on the node.

    @type instance: L{objects.Instance}
    @param instance: the instance that is being started
    @rtype: integer
    @return: memory the instance should be started with

    """
    free_memory = self.GetNodeInfo(hvparams=instance.hvparams)["memory_free"]
    max_start_mem = min(instance.beparams[constants.BE_MAXMEM], free_memory)
    start_mem = max(instance.beparams[constants.BE_MINMEM], max_start_mem)
    return start_mem

  @classmethod
  def _IsParamValueUnspecified(cls, param_value):
    """Check if the parameter value is a kind of value meaning unspecified.

    This function checks if the parameter value is a kind of value meaning
    unspecified.

    @type param_value: any
    @param param_value: the parameter value that needs to be checked
    @rtype: bool
    @return: True if the parameter value is a kind of value meaning unspecified,
      False otherwise

    """
    return param_value is None \
      or isinstance(param_value, basestring) and param_value == ""

  @classmethod
  def CheckParameterSyntax(cls, hvparams):
    """Check the given parameters for validity.

    This should check the passed set of parameters for
    validity. Classes should extend, not replace, this function.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    for key in hvparams:
      if key not in cls.PARAMETERS:
        raise errors.HypervisorError("Parameter '%s' is not supported" % key)

    # cheap tests that run on the master, should not access the world
    for name, (required, check_fn, errstr, _, _) in cls.PARAMETERS.items():
      if name not in hvparams:
        raise errors.HypervisorError("Parameter '%s' is missing" % name)
      value = hvparams[name]
      if not required and cls._IsParamValueUnspecified(value):
        continue
      if cls._IsParamValueUnspecified(value):
        raise errors.HypervisorError("Parameter '%s' is required but"
                                     " is currently not defined" % (name, ))
      if check_fn is not None and not check_fn(value):
        raise errors.HypervisorError("Parameter '%s' fails syntax"
                                     " check: %s (current value: '%s')" %
                                     (name, errstr, value))

  @classmethod
  def ValidateParameters(cls, hvparams):
    """Check the given parameters for validity.

    This should check the passed set of parameters for
    validity. Classes should extend, not replace, this function.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    for name, (required, _, _, check_fn, errstr) in cls.PARAMETERS.items():
      value = hvparams[name]
      if not required and cls._IsParamValueUnspecified(value):
        continue
      if check_fn is not None and not check_fn(value):
        raise errors.HypervisorError("Parameter '%s' fails"
                                     " validation: %s (current value: '%s')" %
                                     (name, errstr, value))

  @classmethod
  def PowercycleNode(cls, hvparams=None):
    """Hard powercycle a node using hypervisor specific methods.

    This method should hard powercycle the node, using whatever
    methods the hypervisor provides. Note that this means that all
    instances running on the node must be stopped too.

    @type hvparams: dict of strings
    @param hvparams: hypervisor params to be used on this node

    """
    raise NotImplementedError

  @staticmethod
  def GetLinuxNodeInfo(meminfo="/proc/meminfo", cpuinfo="/proc/cpuinfo"):
    """For linux systems, return actual OS information.

    This is an abstraction for all non-hypervisor-based classes, where
    the node actually sees all the memory and CPUs via the /proc
    interface and standard commands. The other case if for example
    xen, where you only see the hardware resources via xen-specific
    tools.

    @param meminfo: name of the file containing meminfo
    @type meminfo: string
    @param cpuinfo: name of the file containing cpuinfo
    @type cpuinfo: string
    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available
          - cpu_total: total number of CPUs
          - cpu_dom0: number of CPUs used by the node OS
          - cpu_nodes: number of NUMA domains
          - cpu_sockets: number of physical CPU sockets

    """
    try:
      data = utils.ReadFile(meminfo).splitlines()
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to list node info: %s" % (err,))

    result = {}
    sum_free = 0
    try:
      for line in data:
        splitfields = line.split(":", 1)

        if len(splitfields) > 1:
          key = splitfields[0].strip()
          val = splitfields[1].strip()
          if key == "MemTotal":
            result["memory_total"] = int(val.split()[0]) / 1024
          elif key in ("MemFree", "Buffers", "Cached"):
            sum_free += int(val.split()[0]) / 1024
          elif key == "Active":
            result["memory_dom0"] = int(val.split()[0]) / 1024
    except (ValueError, TypeError), err:
      raise errors.HypervisorError("Failed to compute memory usage: %s" %
                                   (err,))
    result["memory_free"] = sum_free

    cpu_total = 0
    try:
      fh = open(cpuinfo)
      try:
        cpu_total = len(re.findall(r"(?m)^processor\s*:\s*[0-9]+\s*$",
                                   fh.read()))
      finally:
        fh.close()
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to list node info: %s" % (err,))
    result["cpu_total"] = cpu_total
    # We assume that the node OS can access all the CPUs
    result["cpu_dom0"] = cpu_total
    # FIXME: export correct data here
    result["cpu_nodes"] = 1
    result["cpu_sockets"] = 1

    return result

  @classmethod
  def LinuxPowercycle(cls):
    """Linux-specific powercycle method.

    """
    try:
      fd = os.open("/proc/sysrq-trigger", os.O_WRONLY)
      try:
        os.write(fd, "b")
      finally:
        fd.close()
    except OSError:
      logging.exception("Can't open the sysrq-trigger file")
      result = utils.RunCmd(["reboot", "-n", "-f"])
      if not result:
        logging.error("Can't run shutdown: %s", result.output)

  @staticmethod
  def _FormatVerifyResults(msgs):
    """Formats the verification results, given a list of errors.

    @param msgs: list of errors, possibly empty
    @return: overall problem description if something is wrong,
        C{None} otherwise

    """
    if msgs:
      return "; ".join(msgs)
    else:
      return None

  # pylint: disable=R0201,W0613
  def HotAddDevice(self, instance, dev_type, device, extra, seq):
    """Hot-add a device.

    """
    raise errors.HotplugError("Hotplug is not supported by this hypervisor")

  # pylint: disable=R0201,W0613
  def HotDelDevice(self, instance, dev_type, device, extra, seq):
    """Hot-del a device.

    """
    raise errors.HotplugError("Hotplug is not supported by this hypervisor")

  # pylint: disable=R0201,W0613
  def HotModDevice(self, instance, dev_type, device, extra, seq):
    """Hot-mod a device.

    """
    raise errors.HotplugError("Hotplug is not supported by this hypervisor")

  # pylint: disable=R0201,W0613
  def VerifyHotplugSupport(self, instance, action, dev_type):
    """Verifies that hotplug is supported.

    Given the target device and hotplug action checks if hotplug is
    actually supported.

    @type instance: L{objects.Instance}
    @param instance: the instance object
    @type action: string
    @param action: one of the supported hotplug commands
    @type dev_type: string
    @param dev_type: one of the supported device types to hotplug
    @raise errors.HotplugError: if hotplugging is not supported

    """
    raise errors.HotplugError("Hotplug is not supported.")

  def HotplugSupported(self, instance):
    """Checks if hotplug is supported.

    By default is not. Currently only KVM hypervisor supports it.

    """
    raise errors.HotplugError("Hotplug is not supported by this hypervisor")
