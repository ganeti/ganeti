#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010 Google Inc.
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


from ganeti import errors
from ganeti import utils
from ganeti import constants


def _IsCpuMaskWellFormed(cpu_mask):
  try:
    cpu_list = utils.ParseCpuMask(cpu_mask)
  except errors.ParseError, _:
    return False
  return isinstance(cpu_list, list) and len(cpu_list) > 0


# Read the BaseHypervisor.PARAMETERS docstring for the syntax of the
# _CHECK values

# must be afile
_FILE_CHECK = (utils.IsNormAbsPath, "must be an absolute normalized path",
              os.path.isfile, "not found or not a file")

# must be a directory
_DIR_CHECK = (utils.IsNormAbsPath, "must be an absolute normalized path",
             os.path.isdir, "not found or not a directory")

# CPU mask must be well-formed
# TODO: implement node level check for the CPU mask
_CPU_MASK_CHECK = (_IsCpuMaskWellFormed,
                   "CPU mask definition is not well-formed",
                   None, None)

# nice wrappers for users
REQ_FILE_CHECK = (True, ) + _FILE_CHECK
OPT_FILE_CHECK = (False, ) + _FILE_CHECK
REQ_DIR_CHECK = (True, ) + _DIR_CHECK
OPT_DIR_CHECK = (False, ) + _DIR_CHECK
NET_PORT_CHECK = (True, lambda x: x > 0 and x < 65535, "invalid port number",
                  None, None)
OPT_CPU_MASK_CHECK = (False, ) + _CPU_MASK_CHECK
REQ_CPU_MASK_CHECK = (True, ) + _CPU_MASK_CHECK

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
  CAN_MIGRATE = False

  def __init__(self):
    pass

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance."""
    raise NotImplementedError

  def StopInstance(self, instance, force=False, retry=False, name=None):
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

  def ListInstances(self):
    """Get the list of running instances."""
    raise NotImplementedError

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name

    @return: tuple (name, id, memory, vcpus, state, times)

    """
    raise NotImplementedError

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    raise NotImplementedError

  def GetNodeInfo(self):
    """Return information about the node.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available

    """
    raise NotImplementedError

  @classmethod
  def GetInstanceConsole(cls, instance, hvparams, beparams):
    """Return information for connecting to the console of an instance.

    """
    raise NotImplementedError

  @classmethod
  def GetAncillaryFiles(cls):
    """Return a list of ancillary files to be copied to all nodes as ancillary
    configuration files.

    @rtype: list of strings
    @return: list of absolute paths of files to ship cluster-wide

    """
    # By default we return a member variable, so that if an hypervisor has just
    # a static list of files it doesn't have to override this function.
    return cls.ANCILLARY_FILES

  def Verify(self):
    """Verify the hypervisor.

    """
    raise NotImplementedError

  def MigrationInfo(self, instance): # pylint: disable-msg=R0201,W0613
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

  def FinalizeMigration(self, instance, info, success):
    """Finalized an instance migration.

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

  def MigrateInstance(self, instance, target, live):
    """Migrate an instance.

    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: hostname (usually ip) of the target node
    @type live: boolean
    @param live: whether to do a live or non-live migration

    """
    raise NotImplementedError

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
      if not required and not value:
        continue
      if not value:
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
      if not required and not value:
        continue
      if check_fn is not None and not check_fn(value):
        raise errors.HypervisorError("Parameter '%s' fails"
                                     " validation: %s (current value: '%s')" %
                                     (name, errstr, value))

  @classmethod
  def PowercycleNode(cls):
    """Hard powercycle a node using hypervisor specific methods.

    This method should hard powercycle the node, using whatever
    methods the hypervisor provides. Note that this means that all
    instances running on the node must be stopped too.

    """
    raise NotImplementedError

  @staticmethod
  def GetLinuxNodeInfo():
    """For linux systems, return actual OS information.

    This is an abstraction for all non-hypervisor-based classes, where
    the node actually sees all the memory and CPUs via the /proc
    interface and standard commands. The other case if for example
    xen, where you only see the hardware resources via xen-specific
    tools.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available

    """
    try:
      data = utils.ReadFile("/proc/meminfo").splitlines()
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
            result["memory_total"] = int(val.split()[0])/1024
          elif key in ("MemFree", "Buffers", "Cached"):
            sum_free += int(val.split()[0])/1024
          elif key == "Active":
            result["memory_dom0"] = int(val.split()[0])/1024
    except (ValueError, TypeError), err:
      raise errors.HypervisorError("Failed to compute memory usage: %s" %
                                   (err,))
    result["memory_free"] = sum_free

    cpu_total = 0
    try:
      fh = open("/proc/cpuinfo")
      try:
        cpu_total = len(re.findall("(?m)^processor\s*:\s*[0-9]+\s*$",
                                   fh.read()))
      finally:
        fh.close()
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to list node info: %s" % (err,))
    result["cpu_total"] = cpu_total
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
