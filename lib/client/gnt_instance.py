#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2014 Google Inc.
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

"""Instance related commands"""

# pylint: disable=W0401,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-instance

import copy
import itertools
import json
import logging

from ganeti.cli import *
from ganeti import opcodes
from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import errors
from ganeti import netutils
from ganeti import ssh
from ganeti import objects
from ganeti import ht


_EXPAND_CLUSTER = "cluster"
_EXPAND_NODES_BOTH = "nodes"
_EXPAND_NODES_PRI = "nodes-pri"
_EXPAND_NODES_SEC = "nodes-sec"
_EXPAND_NODES_BOTH_BY_TAGS = "nodes-by-tags"
_EXPAND_NODES_PRI_BY_TAGS = "nodes-pri-by-tags"
_EXPAND_NODES_SEC_BY_TAGS = "nodes-sec-by-tags"
_EXPAND_INSTANCES = "instances"
_EXPAND_INSTANCES_BY_TAGS = "instances-by-tags"

_EXPAND_NODES_TAGS_MODES = compat.UniqueFrozenset([
  _EXPAND_NODES_BOTH_BY_TAGS,
  _EXPAND_NODES_PRI_BY_TAGS,
  _EXPAND_NODES_SEC_BY_TAGS,
  ])

#: default list of options for L{ListInstances}
_LIST_DEF_FIELDS = [
  "name", "hypervisor", "os", "pnode", "status", "oper_ram",
  ]

_MISSING = object()
_ENV_OVERRIDE = compat.UniqueFrozenset(["list"])

_INST_DATA_VAL = ht.TListOf(ht.TDict)


def _ExpandMultiNames(mode, names, client=None):
  """Expand the given names using the passed mode.

  For _EXPAND_CLUSTER, all instances will be returned. For
  _EXPAND_NODES_PRI/SEC, all instances having those nodes as
  primary/secondary will be returned. For _EXPAND_NODES_BOTH, all
  instances having those nodes as either primary or secondary will be
  returned. For _EXPAND_INSTANCES, the given instances will be
  returned.

  @param mode: one of L{_EXPAND_CLUSTER}, L{_EXPAND_NODES_BOTH},
      L{_EXPAND_NODES_PRI}, L{_EXPAND_NODES_SEC} or
      L{_EXPAND_INSTANCES}
  @param names: a list of names; for cluster, it must be empty,
      and for node and instance it must be a list of valid item
      names (short names are valid as usual, e.g. node1 instead of
      node1.example.com)
  @rtype: list
  @return: the list of names after the expansion
  @raise errors.ProgrammerError: for unknown selection type
  @raise errors.OpPrereqError: for invalid input parameters

  """

  if client is None:
    client = GetClient()
  if mode == _EXPAND_CLUSTER:
    if names:
      raise errors.OpPrereqError("Cluster filter mode takes no arguments",
                                 errors.ECODE_INVAL)
    idata = client.QueryInstances([], ["name"], False)
    inames = [row[0] for row in idata]

  elif (mode in _EXPAND_NODES_TAGS_MODES or
        mode in (_EXPAND_NODES_BOTH, _EXPAND_NODES_PRI, _EXPAND_NODES_SEC)):
    if mode in _EXPAND_NODES_TAGS_MODES:
      if not names:
        raise errors.OpPrereqError("No node tags passed", errors.ECODE_INVAL)
      ndata = client.QueryNodes([], ["name", "pinst_list",
                                     "sinst_list", "tags"], False)
      ndata = [row for row in ndata if set(row[3]).intersection(names)]
    else:
      if not names:
        raise errors.OpPrereqError("No node names passed", errors.ECODE_INVAL)
      ndata = client.QueryNodes(names, ["name", "pinst_list", "sinst_list"],
                                False)

    ipri = [row[1] for row in ndata]
    pri_names = list(itertools.chain(*ipri))
    isec = [row[2] for row in ndata]
    sec_names = list(itertools.chain(*isec))
    if mode in (_EXPAND_NODES_BOTH, _EXPAND_NODES_BOTH_BY_TAGS):
      inames = pri_names + sec_names
    elif mode in (_EXPAND_NODES_PRI, _EXPAND_NODES_PRI_BY_TAGS):
      inames = pri_names
    elif mode in (_EXPAND_NODES_SEC, _EXPAND_NODES_SEC_BY_TAGS):
      inames = sec_names
    else:
      raise errors.ProgrammerError("Unhandled shutdown type")
  elif mode == _EXPAND_INSTANCES:
    if not names:
      raise errors.OpPrereqError("No instance names passed",
                                 errors.ECODE_INVAL)
    idata = client.QueryInstances(names, ["name"], False)
    inames = [row[0] for row in idata]
  elif mode == _EXPAND_INSTANCES_BY_TAGS:
    if not names:
      raise errors.OpPrereqError("No instance tags passed",
                                 errors.ECODE_INVAL)
    idata = client.QueryInstances([], ["name", "tags"], False)
    inames = [row[0] for row in idata if set(row[1]).intersection(names)]
  else:
    raise errors.OpPrereqError("Unknown mode '%s'" % mode, errors.ECODE_INVAL)

  return inames


def _EnsureInstancesExist(client, names):
  """Check for and ensure the given instance names exist.

  This function will raise an OpPrereqError in case they don't
  exist. Otherwise it will exit cleanly.

  @type client: L{ganeti.luxi.Client}
  @param client: the client to use for the query
  @type names: list
  @param names: the list of instance names to query
  @raise errors.OpPrereqError: in case any instance is missing

  """
  # TODO: change LUInstanceQuery to that it actually returns None
  # instead of raising an exception, or devise a better mechanism
  result = client.QueryInstances(names, ["name"], False)
  for orig_name, row in zip(names, result):
    if row[0] is None:
      raise errors.OpPrereqError("Instance '%s' does not exist" % orig_name,
                                 errors.ECODE_NOENT)


def GenericManyOps(operation, fn):
  """Generic multi-instance operations.

  The will return a wrapper that processes the options and arguments
  given, and uses the passed function to build the opcode needed for
  the specific operation. Thus all the generic loop/confirmation code
  is abstracted into this function.

  """
  def realfn(opts, args):
    if opts.multi_mode is None:
      opts.multi_mode = _EXPAND_INSTANCES
    cl = GetClient()
    inames = _ExpandMultiNames(opts.multi_mode, args, client=cl)
    if not inames:
      if opts.multi_mode == _EXPAND_CLUSTER:
        ToStdout("Cluster is empty, no instances to shutdown")
        return 0
      raise errors.OpPrereqError("Selection filter does not match"
                                 " any instances", errors.ECODE_INVAL)
    multi_on = opts.multi_mode != _EXPAND_INSTANCES or len(inames) > 1
    if not (opts.force_multi or not multi_on
            or ConfirmOperation(inames, "instances", operation)):
      return 1
    jex = JobExecutor(verbose=multi_on, cl=cl, opts=opts)
    for name in inames:
      op = fn(name, opts)
      jex.QueueJob(name, op)
    results = jex.WaitOrShow(not opts.submit_only)
    rcode = compat.all(row[0] for row in results)
    return int(not rcode)
  return realfn


def ListInstances(opts, args):
  """List instances and their properties.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)

  fmtoverride = dict.fromkeys(["tags", "disk.sizes", "nic.macs", "nic.ips",
                               "nic.modes", "nic.links", "nic.bridges",
                               "nic.networks",
                               "snodes", "snodes.group", "snodes.group.uuid"],
                              (lambda value: ",".join(str(item)
                                                      for item in value),
                               False))

  cl = GetClient()

  return GenericList(constants.QR_INSTANCE, selected_fields, args, opts.units,
                     opts.separator, not opts.no_headers,
                     format_override=fmtoverride, verbose=opts.verbose,
                     force_filter=opts.force_filter, cl=cl)


def ListInstanceFields(opts, args):
  """List instance fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  return GenericListFields(constants.QR_INSTANCE, args, opts.separator,
                           not opts.no_headers)


def AddInstance(opts, args):
  """Add an instance to the cluster.

  This is just a wrapper over L{GenericInstanceCreate}.

  """
  return GenericInstanceCreate(constants.INSTANCE_CREATE, opts, args)


def BatchCreate(opts, args):
  """Create instances using a definition file.

  This function reads a json file with L{opcodes.OpInstanceCreate}
  serialisations.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain one element, the json filename
  @rtype: int
  @return: the desired exit code

  """
  (json_filename,) = args
  cl = GetClient()

  try:
    instance_data = json.loads(utils.ReadFile(json_filename))
  except Exception as err: # pylint: disable=W0703
    ToStderr("Can't parse the instance definition file: %s" % str(err))
    return 1

  if not _INST_DATA_VAL(instance_data):
    ToStderr("The instance definition file is not %s" % _INST_DATA_VAL)
    return 1

  instances = []
  possible_params = set(opcodes.OpInstanceCreate.GetAllSlots())
  for (idx, inst) in enumerate(instance_data):
    unknown = set(inst.keys()) - possible_params

    if unknown:
      # TODO: Suggest closest match for more user friendly experience
      raise errors.OpPrereqError("Unknown fields in definition %s: %s" %
                                 (idx, utils.CommaJoin(unknown)),
                                 errors.ECODE_INVAL)

    op = opcodes.OpInstanceCreate(**inst)
    op.Validate(False)
    instances.append(op)

  op = opcodes.OpInstanceMultiAlloc(iallocator=opts.iallocator,
                                    instances=instances)
  result = SubmitOrSend(op, opts, cl=cl)

  # Keep track of submitted jobs
  jex = JobExecutor(cl=cl, opts=opts)

  for (status, job_id) in result[constants.JOB_IDS_KEY]:
    jex.AddJobId(None, status, job_id)

  results = jex.GetResults()
  bad_cnt = len([row for row in results if not row[0]])
  if bad_cnt == 0:
    ToStdout("All instances created successfully.")
    rcode = constants.EXIT_SUCCESS
  else:
    ToStdout("There were %s errors during the creation.", bad_cnt)
    rcode = constants.EXIT_FAILURE

  return rcode


def ReinstallInstance(opts, args):
  """Reinstall an instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of the
      instance to be reinstalled
  @rtype: int
  @return: the desired exit code

  """
  # first, compute the desired name list
  if opts.multi_mode is None:
    opts.multi_mode = _EXPAND_INSTANCES

  inames = _ExpandMultiNames(opts.multi_mode, args)
  if not inames:
    raise errors.OpPrereqError("Selection filter does not match any instances",
                               errors.ECODE_INVAL)

  # second, if requested, ask for an OS
  if opts.select_os is True:
    op = opcodes.OpOsDiagnose(output_fields=["name", "variants"], names=[])
    result = SubmitOpCode(op, opts=opts)

    if not result:
      ToStdout("Can't get the OS list")
      return 1

    ToStdout("Available OS templates:")
    number = 0
    choices = []
    for (name, variants) in result:
      for entry in CalculateOSNames(name, variants):
        ToStdout("%3s: %s", number, entry)
        choices.append(("%s" % number, entry, entry))
        number += 1

    choices.append(("x", "exit", "Exit gnt-instance reinstall"))
    selected = AskUser("Enter OS template number (or x to abort):",
                       choices)

    if selected == "exit":
      ToStderr("User aborted reinstall, exiting")
      return 1

    os_name = selected
    os_msg = "change the OS to '%s'" % selected
  else:
    os_name = opts.os
    if opts.os is not None:
      os_msg = "change the OS to '%s'" % os_name
    else:
      os_msg = "keep the same OS"

  # third, get confirmation: multi-reinstall requires --force-multi,
  # single-reinstall either --force or --force-multi (--force-multi is
  # a stronger --force)
  multi_on = opts.multi_mode != _EXPAND_INSTANCES or len(inames) > 1
  if multi_on:
    warn_msg = ("Note: this will remove *all* data for the"
                " below instances! It will %s.\n" % os_msg)
    if not (opts.force_multi or
            ConfirmOperation(inames, "instances", "reinstall", extra=warn_msg)):
      return 1
  else:
    if not (opts.force or opts.force_multi):
      usertext = ("This will reinstall the instance '%s' (and %s) which"
                  " removes all data. Continue?") % (inames[0], os_msg)
      if not AskUser(usertext):
        return 1

  jex = JobExecutor(verbose=multi_on, opts=opts)
  for instance_name in inames:
    op = opcodes.OpInstanceReinstall(instance_name=instance_name,
                                     os_type=os_name,
                                     force_variant=opts.force_variant,
                                     osparams=opts.osparams,
                                     osparams_private=opts.osparams_private,
                                     osparams_secret=opts.osparams_secret)
    jex.QueueJob(instance_name, op)

  results = jex.WaitOrShow(not opts.submit_only)

  if compat.all(map(compat.fst, results)):
    return constants.EXIT_SUCCESS
  else:
    return constants.EXIT_FAILURE


def RemoveInstance(opts, args):
  """Remove an instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of
      the instance to be removed
  @rtype: int
  @return: the desired exit code

  """
  instance_name = args[0]
  force = opts.force
  cl = GetClient()

  if not force:
    _EnsureInstancesExist(cl, [instance_name])

    usertext = ("This will remove the volumes of the instance %s"
                " (including mirrors), thus removing all the data"
                " of the instance. Continue?") % instance_name
    if not AskUser(usertext):
      return 1

  op = opcodes.OpInstanceRemove(instance_name=instance_name,
                                ignore_failures=opts.ignore_failures,
                                shutdown_timeout=opts.shutdown_timeout)
  SubmitOrSend(op, opts, cl=cl)
  return 0


def RenameInstance(opts, args):
  """Rename an instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain two elements, the old and the
      new instance names
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpInstanceRename(instance_name=args[0],
                                new_name=args[1],
                                ip_check=opts.ip_check,
                                name_check=opts.name_check)
  result = SubmitOrSend(op, opts)

  if result:
    ToStdout("Instance '%s' renamed to '%s'", args[0], result)

  return 0


def ActivateDisks(opts, args):
  """Activate an instance's disks.

  This serves two purposes:
    - it allows (as long as the instance is not running)
      mounting the disks and modifying them from the node
    - it repairs inactive secondary drbds

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  instance_name = args[0]
  op = opcodes.OpInstanceActivateDisks(instance_name=instance_name,
                                       ignore_size=opts.ignore_size,
                                       wait_for_sync=opts.wait_for_sync)
  disks_info = SubmitOrSend(op, opts)
  for host, iname, nname in disks_info:
    ToStdout("%s:%s:%s", host, iname, nname)
  return 0


def DeactivateDisks(opts, args):
  """Deactivate an instance's disks.

  This function takes the instance name, looks for its primary node
  and the tries to shutdown its block devices on that node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  instance_name = args[0]
  op = opcodes.OpInstanceDeactivateDisks(instance_name=instance_name,
                                         force=opts.force)
  SubmitOrSend(op, opts)
  return 0


def RecreateDisks(opts, args):
  """Recreate an instance's disks.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  instance_name = args[0]

  disks = []

  if opts.disks:
    for didx, ddict in opts.disks:
      didx = int(didx)

      if not ht.TDict(ddict):
        msg = "Invalid disk/%d value: expected dict, got %s" % (didx, ddict)
        raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

      if constants.IDISK_SIZE in ddict:
        try:
          ddict[constants.IDISK_SIZE] = \
            utils.ParseUnit(ddict[constants.IDISK_SIZE])
        except ValueError as err:
          raise errors.OpPrereqError("Invalid disk size for disk %d: %s" %
                                     (didx, err), errors.ECODE_INVAL)

      if constants.IDISK_SPINDLES in ddict:
        try:
          ddict[constants.IDISK_SPINDLES] = \
              int(ddict[constants.IDISK_SPINDLES])
        except ValueError as err:
          raise errors.OpPrereqError("Invalid spindles for disk %d: %s" %
                                     (didx, err), errors.ECODE_INVAL)

      disks.append((didx, ddict))

    # TODO: Verify modifyable parameters (already done in
    # LUInstanceRecreateDisks, but it'd be nice to have in the client)

  if opts.node:
    if opts.iallocator:
      msg = "At most one of either --nodes or --iallocator can be passed"
      raise errors.OpPrereqError(msg, errors.ECODE_INVAL)
    pnode, snode = SplitNodeOption(opts.node)
    nodes = [pnode]
    if snode is not None:
      nodes.append(snode)
  else:
    nodes = []

  op = opcodes.OpInstanceRecreateDisks(instance_name=instance_name,
                                       disks=disks, nodes=nodes,
                                       iallocator=opts.iallocator)
  SubmitOrSend(op, opts)

  return 0


def GrowDisk(opts, args):
  """Grow an instance's disks.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain three elements, the target instance name,
      the target disk id, and the target growth
  @rtype: int
  @return: the desired exit code

  """
  instance = args[0]
  disk = args[1]
  try:
    disk = int(disk)
  except (TypeError, ValueError) as err:
    raise errors.OpPrereqError("Invalid disk index: %s" % str(err),
                               errors.ECODE_INVAL)
  try:
    amount = utils.ParseUnit(args[2])
  except errors.UnitParseError:
    raise errors.OpPrereqError("Can't parse the given amount '%s'" % args[2],
                               errors.ECODE_INVAL)
  op = opcodes.OpInstanceGrowDisk(instance_name=instance,
                                  disk=disk, amount=amount,
                                  wait_for_sync=opts.wait_for_sync,
                                  absolute=opts.absolute,
                                  ignore_ipolicy=opts.ignore_ipolicy
                                  )
  SubmitOrSend(op, opts)
  return 0


def _StartupInstance(name, opts):
  """Startup instances.

  This returns the opcode to start an instance, and its decorator will
  wrap this into a loop starting all desired instances.

  @param name: the name of the instance to act on
  @param opts: the command line options selected by the user
  @return: the opcode needed for the operation

  """
  op = opcodes.OpInstanceStartup(instance_name=name,
                                 force=opts.force,
                                 ignore_offline_nodes=opts.ignore_offline,
                                 no_remember=opts.no_remember,
                                 startup_paused=opts.startup_paused)
  # do not add these parameters to the opcode unless they're defined
  if opts.hvparams:
    op.hvparams = opts.hvparams
  if opts.beparams:
    op.beparams = opts.beparams
  return op


def _RebootInstance(name, opts):
  """Reboot instance(s).

  This returns the opcode to reboot an instance, and its decorator
  will wrap this into a loop rebooting all desired instances.

  @param name: the name of the instance to act on
  @param opts: the command line options selected by the user
  @return: the opcode needed for the operation

  """
  return opcodes.OpInstanceReboot(instance_name=name,
                                  reboot_type=opts.reboot_type,
                                  ignore_secondaries=opts.ignore_secondaries,
                                  shutdown_timeout=opts.shutdown_timeout)


def _ShutdownInstance(name, opts):
  """Shutdown an instance.

  This returns the opcode to shutdown an instance, and its decorator
  will wrap this into a loop shutting down all desired instances.

  @param name: the name of the instance to act on
  @param opts: the command line options selected by the user
  @return: the opcode needed for the operation

  """
  return opcodes.OpInstanceShutdown(instance_name=name,
                                    force=opts.force,
                                    timeout=opts.timeout,
                                    ignore_offline_nodes=opts.ignore_offline,
                                    no_remember=opts.no_remember)


def ReplaceDisks(opts, args):
  """Replace the disks of an instance

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  new_2ndary = opts.dst_node
  iallocator = opts.iallocator
  if opts.disks is None:
    disks = []
  else:
    try:
      disks = [int(i) for i in opts.disks.split(",")]
    except (TypeError, ValueError) as err:
      raise errors.OpPrereqError("Invalid disk index passed: %s" % str(err),
                                 errors.ECODE_INVAL)
  cnt = [opts.on_primary, opts.on_secondary, opts.auto,
         new_2ndary is not None, iallocator is not None].count(True)
  if cnt != 1:
    raise errors.OpPrereqError("One and only one of the -p, -s, -a, -n and -I"
                               " options must be passed", errors.ECODE_INVAL)
  elif opts.on_primary:
    mode = constants.REPLACE_DISK_PRI
  elif opts.on_secondary:
    mode = constants.REPLACE_DISK_SEC
  elif opts.auto:
    mode = constants.REPLACE_DISK_AUTO
    if disks:
      raise errors.OpPrereqError("Cannot specify disks when using automatic"
                                 " mode", errors.ECODE_INVAL)
  elif new_2ndary is not None or iallocator is not None:
    # replace secondary
    mode = constants.REPLACE_DISK_CHG

  op = opcodes.OpInstanceReplaceDisks(instance_name=args[0], disks=disks,
                                      remote_node=new_2ndary, mode=mode,
                                      iallocator=iallocator,
                                      early_release=opts.early_release,
                                      ignore_ipolicy=opts.ignore_ipolicy)
  SubmitOrSend(op, opts)
  return 0


def FailoverInstance(opts, args):
  """Failover an instance.

  The failover is done by shutting it down on its present node and
  starting it on the secondary.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  instance_name = args[0]
  ignore_consistency = opts.ignore_consistency
  force = opts.force
  iallocator = opts.iallocator
  target_node = opts.dst_node

  if iallocator and target_node:
    raise errors.OpPrereqError("Specify either an iallocator (-I), or a target"
                               " node (-n) but not both", errors.ECODE_INVAL)

  if not force:
    _EnsureInstancesExist(cl, [instance_name])

    usertext = ("Failover will happen to image %s."
                " This requires a shutdown of the instance. Continue?" %
                (instance_name,))
    if not AskUser(usertext):
      return 1

  if ignore_consistency:
    usertext = ("To failover instance %s, the source node must be marked"
                " offline first. Is this already the case?") % instance_name
    if not AskUser(usertext):
      return 1

  op = opcodes.OpInstanceFailover(instance_name=instance_name,
                                  ignore_consistency=ignore_consistency,
                                  shutdown_timeout=opts.shutdown_timeout,
                                  iallocator=iallocator,
                                  target_node=target_node,
                                  ignore_ipolicy=opts.ignore_ipolicy)
  SubmitOrSend(op, opts, cl=cl)
  return 0


def MigrateInstance(opts, args):
  """Migrate an instance.

  The migrate is done without shutdown.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  instance_name = args[0]
  force = opts.force
  iallocator = opts.iallocator
  target_node = opts.dst_node

  if iallocator and target_node:
    raise errors.OpPrereqError("Specify either an iallocator (-I), or a target"
                               " node (-n) but not both", errors.ECODE_INVAL)

  if not force:
    _EnsureInstancesExist(cl, [instance_name])

    if opts.cleanup:
      usertext = ("Instance %s will be recovered from a failed migration."
                  " Note that the migration procedure (including cleanup)" %
                  (instance_name,))
    else:
      usertext = ("Instance %s will be migrated. Note that migration" %
                  (instance_name,))
    usertext += (" might impact the instance if anything goes wrong"
                 " (e.g. due to bugs in the hypervisor). Continue?")
    if not AskUser(usertext):
      return 1

  # this should be removed once --non-live is deprecated
  if not opts.live and opts.migration_mode is not None:
    raise errors.OpPrereqError("Only one of the --non-live and "
                               "--migration-mode options can be passed",
                               errors.ECODE_INVAL)
  if not opts.live: # --non-live passed
    mode = constants.HT_MIGRATION_NONLIVE
  else:
    mode = opts.migration_mode

  op = opcodes.OpInstanceMigrate(instance_name=instance_name, mode=mode,
                                 cleanup=opts.cleanup, iallocator=iallocator,
                                 target_node=target_node,
                                 allow_failover=opts.allow_failover,
                                 allow_runtime_changes=opts.allow_runtime_chgs,
                                 ignore_ipolicy=opts.ignore_ipolicy,
                                 ignore_hvversions=opts.ignore_hvversions)
  SubmitOrSend(op, cl=cl, opts=opts)
  return 0


def MoveInstance(opts, args):
  """Move an instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  instance_name = args[0]
  force = opts.force

  if not force:
    usertext = ("Instance %s will be moved."
                " This requires a shutdown of the instance. Continue?" %
                (instance_name,))
    if not AskUser(usertext):
      return 1

  op = opcodes.OpInstanceMove(instance_name=instance_name,
                              target_node=opts.node,
                              compress=opts.compress,
                              shutdown_timeout=opts.shutdown_timeout,
                              ignore_consistency=opts.ignore_consistency,
                              ignore_ipolicy=opts.ignore_ipolicy)
  SubmitOrSend(op, opts, cl=cl)
  return 0


def ConnectToInstanceConsole(opts, args):
  """Connect to the console of an instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  instance_name = args[0]

  cl = GetClient()
  try:
    cluster_name = cl.QueryConfigValues(["cluster_name"])[0]
    idata = cl.QueryInstances([instance_name], ["console", "oper_state"], False)
    if not idata:
      raise errors.OpPrereqError("Instance '%s' does not exist" % instance_name,
                                 errors.ECODE_NOENT)
  finally:
    # Ensure client connection is closed while external commands are run
    cl.Close()

  del cl

  (console_data, oper_state) = idata[0]
  if not console_data:
    if oper_state:
      # Instance is running
      raise errors.OpExecError("Console information for instance %s is"
                               " unavailable" % instance_name)
    else:
      raise errors.OpExecError("Instance %s is not running, can't get console" %
                               instance_name)

  return _DoConsole(objects.InstanceConsole.FromDict(console_data),
                    opts.show_command, cluster_name)


def _DoConsole(console, show_command, cluster_name, feedback_fn=ToStdout,
               _runcmd_fn=utils.RunCmd):
  """Acts based on the result of L{opcodes.OpInstanceConsole}.

  @type console: L{objects.InstanceConsole}
  @param console: Console object
  @type show_command: bool
  @param show_command: Whether to just display commands
  @type cluster_name: string
  @param cluster_name: Cluster name as retrieved from master daemon

  """
  console.Validate()

  if console.kind == constants.CONS_MESSAGE:
    feedback_fn(console.message)
  elif console.kind == constants.CONS_VNC:
    feedback_fn("Instance %s has VNC listening on %s:%s (display %s),"
                " URL <vnc://%s:%s/>",
                console.instance, console.host, console.port,
                console.display, console.host, console.port)
  elif console.kind == constants.CONS_SPICE:
    feedback_fn("Instance %s has SPICE listening on %s:%s", console.instance,
                console.host, console.port)
  elif console.kind == constants.CONS_SSH:
    # Convert to string if not already one
    if isinstance(console.command, str):
      cmd = console.command
    else:
      cmd = utils.ShellQuoteArgs(console.command)

    srun = ssh.SshRunner(cluster_name=cluster_name)
    ssh_cmd = srun.BuildCmd(console.host, console.user, cmd,
                            port=console.port,
                            batch=True, quiet=False, tty=True)

    if show_command:
      feedback_fn(utils.ShellQuoteArgs(ssh_cmd))
    else:
      result = _runcmd_fn(ssh_cmd, interactive=True)
      if result.failed:
        logging.error("Console command \"%s\" failed with reason '%s' and"
                      " output %r", result.cmd, result.fail_reason,
                      result.output)
        raise errors.OpExecError("Connection to console of instance %s failed,"
                                 " please check cluster configuration" %
                                 console.instance)
  else:
    raise errors.GenericError("Unknown console type '%s'" % console.kind)

  return constants.EXIT_SUCCESS


def _FormatDiskDetails(dev_type, dev, roman):
  """Formats the logical_id of a disk.

  """

  if dev_type == constants.DT_DRBD8:
    drbd_info = dev["drbd_info"]
    data = [
      ("nodeA", "%s, minor=%s" %
                (drbd_info["primary_node"],
                 compat.TryToRoman(drbd_info["primary_minor"],
                                   convert=roman))),
      ("nodeB", "%s, minor=%s" %
                (drbd_info["secondary_node"],
                 compat.TryToRoman(drbd_info["secondary_minor"],
                                   convert=roman))),
      ("port", str(compat.TryToRoman(drbd_info["port"], convert=roman))),
      ]
  elif dev_type == constants.DT_PLAIN:
    vg_name, lv_name = dev["logical_id"]
    data = ["%s/%s" % (vg_name, lv_name)]
  else:
    data = [str(dev["logical_id"])]

  return data


def _FormatBlockDevInfo(idx, top_level, dev, roman):
  """Show block device information.

  This is only used by L{ShowInstanceConfig}, but it's too big to be
  left for an inline definition.

  @type idx: int
  @param idx: the index of the current disk
  @type top_level: boolean
  @param top_level: if this a top-level disk?
  @type dev: dict
  @param dev: dictionary with disk information
  @type roman: boolean
  @param roman: whether to try to use roman integers
  @return: a list of either strings, tuples or lists
      (which should be formatted at a higher indent level)

  """
  def helper(dtype, status):
    """Format one line for physical device status.

    @type dtype: str
    @param dtype: a constant from the L{constants.DTS_BLOCK} set
    @type status: tuple
    @param status: a tuple as returned from L{backend.FindBlockDevice}
    @return: the string representing the status

    """
    if not status:
      return "not active"
    txt = ""
    (path, major, minor, syncp, estt, degr, ldisk_status) = status
    if major is None:
      major_string = "N/A"
    else:
      major_string = str(compat.TryToRoman(major, convert=roman))

    if minor is None:
      minor_string = "N/A"
    else:
      minor_string = str(compat.TryToRoman(minor, convert=roman))

    txt += ("%s (%s:%s)" % (path, major_string, minor_string))
    if dtype in (constants.DT_DRBD8, ):
      if syncp is not None:
        sync_text = "*RECOVERING* %5.2f%%," % syncp
        if estt:
          sync_text += " ETA %ss" % compat.TryToRoman(estt, convert=roman)
        else:
          sync_text += " ETA unknown"
      else:
        sync_text = "in sync"
      if degr:
        degr_text = "*DEGRADED*"
      else:
        degr_text = "ok"
      if ldisk_status == constants.LDS_FAULTY:
        ldisk_text = " *MISSING DISK*"
      elif ldisk_status == constants.LDS_UNKNOWN:
        ldisk_text = " *UNCERTAIN STATE*"
      else:
        ldisk_text = ""
      txt += (" %s, status %s%s" % (sync_text, degr_text, ldisk_text))
    elif dtype == constants.DT_PLAIN:
      if ldisk_status == constants.LDS_FAULTY:
        ldisk_text = " *FAILED* (failed drive?)"
      else:
        ldisk_text = ""
      txt += ldisk_text
    return txt

  # the header
  if top_level:
    if dev["iv_name"] is not None:
      txt = dev["iv_name"]
    else:
      txt = "disk %s" % compat.TryToRoman(idx, convert=roman)
  else:
    txt = "child %s" % compat.TryToRoman(idx, convert=roman)
  if isinstance(dev["size"], int):
    nice_size = utils.FormatUnit(dev["size"], "h", roman)
  else:
    nice_size = str(dev["size"])
  data = [(txt, "%s, size %s" % (dev["dev_type"], nice_size))]
  if top_level:
    if dev["spindles"] is not None:
      data.append(("spindles", dev["spindles"]))
    data.append(("access mode", dev["mode"]))
  if dev["logical_id"] is not None:
    try:
      l_id = _FormatDiskDetails(dev["dev_type"], dev, roman)
    except ValueError:
      l_id = [str(dev["logical_id"])]
    if len(l_id) == 1:
      data.append(("logical_id", l_id[0]))
    else:
      data.extend(l_id)

  if dev["pstatus"]:
    data.append(("on primary", helper(dev["dev_type"], dev["pstatus"])))

  if dev["sstatus"]:
    data.append(("on secondary", helper(dev["dev_type"], dev["sstatus"])))

  data.append(("name", dev["name"]))
  data.append(("UUID", dev["uuid"]))

  if dev["children"]:
    data.append(("child devices", [
      _FormatBlockDevInfo(c_idx, False, child, roman)
      for c_idx, child in enumerate(dev["children"])
      ]))
  return data


def _FormatInstanceNicInfo(idx, nic, roman=False):
  """Helper function for L{_FormatInstanceInfo()}"""
  (name, uuid, ip, mac, mode, link, vlan, _, netinfo) = nic
  network_name = None
  if netinfo:
    network_name = netinfo["name"]
  return [
    ("nic/%s" % str(compat.TryToRoman(idx, roman)), ""),
    ("MAC", str(mac)),
    ("IP", str(ip)),
    ("mode", str(mode)),
    ("link", str(link)),
    ("vlan", str(compat.TryToRoman(vlan, roman))),
    ("network", str(network_name)),
    ("UUID", str(uuid)),
    ("name", str(name)),
    ]


def _FormatInstanceNodesInfo(instance):
  """Helper function for L{_FormatInstanceInfo()}"""
  pgroup = ("%s (UUID %s)" %
            (instance["pnode_group_name"], instance["pnode_group_uuid"]))
  secs = utils.CommaJoin(("%s (group %s, group UUID %s)" %
                          (name, group_name, group_uuid))
                         for (name, group_name, group_uuid) in
                           zip(instance["snodes"],
                               instance["snodes_group_names"],
                               instance["snodes_group_uuids"]))
  return [
    [
      ("primary", instance["pnode"]),
      ("group", pgroup),
      ],
    [("secondaries", secs)],
    ]


def _GetVncConsoleInfo(instance):
  """Helper function for L{_FormatInstanceInfo()}"""
  vnc_bind_address = instance["hv_actual"].get(constants.HV_VNC_BIND_ADDRESS,
                                               None)
  if vnc_bind_address:
    port = instance["network_port"]
    display = int(port) - constants.VNC_BASE_PORT
    if display > 0 and vnc_bind_address == constants.IP4_ADDRESS_ANY:
      vnc_console_port = "%s:%s (display %s)" % (instance["pnode"],
                                                 port,
                                                 display)
    elif display > 0 and netutils.IP4Address.IsValid(vnc_bind_address):
      vnc_console_port = ("%s:%s (node %s) (display %s)" %
                           (vnc_bind_address, port,
                            instance["pnode"], display))
    else:
      # vnc bind address is a file
      vnc_console_port = "%s:%s" % (instance["pnode"],
                                    vnc_bind_address)
    ret = "vnc to %s" % vnc_console_port
  else:
    ret = None
  return ret


def _FormatInstanceInfo(instance, roman_integers):
  """Format instance information for L{cli.PrintGenericInfo()}"""
  istate = "configured to be %s" % instance["config_state"]
  if instance["run_state"]:
    istate += ", actual state is %s" % instance["run_state"]
  info = [
    ("Instance name", instance["name"]),
    ("UUID", instance["uuid"]),
    ("Serial number",
     str(compat.TryToRoman(instance["serial_no"], convert=roman_integers))),
    ("Creation time", utils.FormatTime(instance["ctime"])),
    ("Modification time", utils.FormatTime(instance["mtime"])),
    ("State", istate),
    ("Nodes", _FormatInstanceNodesInfo(instance)),
    ("Operating system", instance["os"]),
    ("Operating system parameters",
     FormatParamsDictInfo(instance["os_instance"], instance["os_actual"],
                          roman_integers)),
    ]

  if "network_port" in instance:
    info.append(("Allocated network port",
                 str(compat.TryToRoman(instance["network_port"],
                                       convert=roman_integers))))
  info.append(("Hypervisor", instance["hypervisor"]))
  console = _GetVncConsoleInfo(instance)
  if console:
    info.append(("console connection", console))
  # deprecated "memory" value, kept for one version for compatibility
  # TODO(ganeti 2.7) remove.
  be_actual = copy.deepcopy(instance["be_actual"])
  be_actual["memory"] = be_actual[constants.BE_MAXMEM]
  info.extend([
    ("Hypervisor parameters",
     FormatParamsDictInfo(instance["hv_instance"], instance["hv_actual"],
                          roman_integers)),
    ("Back-end parameters",
     FormatParamsDictInfo(instance["be_instance"], be_actual,
                          roman_integers)),
    ("NICs", [
      _FormatInstanceNicInfo(idx, nic, roman_integers)
      for (idx, nic) in enumerate(instance["nics"])
      ]),
    ("Disk template", instance["disk_template"]),
    ("Disks", [
      _FormatBlockDevInfo(idx, True, device, roman_integers)
      for (idx, device) in enumerate(instance["disks"])
      ]),
    ])
  return info


def ShowInstanceConfig(opts, args):
  """Compute instance run-time status.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: either an empty list, and then we query all
      instances, or should contain a list of instance names
  @rtype: int
  @return: the desired exit code

  """
  if not args and not opts.show_all:
    ToStderr("No instance selected."
             " Please pass in --all if you want to query all instances.\n"
             "Note that this can take a long time on a big cluster.")
    return 1
  elif args and opts.show_all:
    ToStderr("Cannot use --all if you specify instance names.")
    return 1

  retcode = 0
  op = opcodes.OpInstanceQueryData(instances=args, static=opts.static,
                                   use_locking=not opts.static)
  result = SubmitOpCode(op, opts=opts)
  if not result:
    ToStdout("No instances.")
    return 1

  PrintGenericInfo([
    _FormatInstanceInfo(instance, opts.roman_integers)
    for instance in result.values()
    ])
  return retcode


def _ConvertNicDiskModifications(mods):
  """Converts NIC/disk modifications from CLI to opcode.

  When L{opcodes.OpInstanceSetParams} was changed to support adding/removing
  disks at arbitrary indices, its parameter format changed. This function
  converts legacy requests (e.g. "--net add" or "--disk add:size=4G") to the
  newer format and adds support for new-style requests (e.g. "--new 4:add").

  @type mods: list of tuples
  @param mods: Modifications as given by command line parser
  @rtype: list of tuples
  @return: Modifications as understood by L{opcodes.OpInstanceSetParams}

  """
  result = []

  for (identifier, params) in mods:
    if identifier == constants.DDM_ADD:
      # Add item as last item (legacy interface)
      action = constants.DDM_ADD
      identifier = -1
    elif identifier == constants.DDM_ATTACH:
      # Attach item as last item (legacy interface)
      action = constants.DDM_ATTACH
      identifier = -1
    elif identifier == constants.DDM_REMOVE:
      # Remove last item (legacy interface)
      action = constants.DDM_REMOVE
      identifier = -1
    elif identifier == constants.DDM_DETACH:
      # Detach last item (legacy interface)
      action = constants.DDM_DETACH
      identifier = -1
    else:
      # Modifications and adding/attaching/removing/detaching at arbitrary
      # indices
      add = params.pop(constants.DDM_ADD, _MISSING)
      attach = params.pop(constants.DDM_ATTACH, _MISSING)
      remove = params.pop(constants.DDM_REMOVE, _MISSING)
      detach = params.pop(constants.DDM_DETACH, _MISSING)
      modify = params.pop(constants.DDM_MODIFY, _MISSING)

      # Check if the user has requested more than one operation and raise an
      # exception. If no operations have been given, default to modify.
      action = constants.DDM_MODIFY
      ops = {
        constants.DDM_ADD: add,
        constants.DDM_ATTACH: attach,
        constants.DDM_REMOVE: remove,
        constants.DDM_DETACH: detach,
        constants.DDM_MODIFY: modify,
      }
      count = 0
      for op, param in ops.items():
        if param is not _MISSING:
          count += 1
          action = op
      if count > 1:
        raise errors.OpPrereqError(
          "Cannot do more than one of the following operations at the"
          " same time: %s" % ", ".join(ops.keys()),
          errors.ECODE_INVAL)

      assert not (constants.DDMS_VALUES_WITH_MODIFY & set(params.keys()))

    if action in (constants.DDM_REMOVE, constants.DDM_DETACH) and params:
      raise errors.OpPrereqError("Not accepting parameters on removal/detach",
                                 errors.ECODE_INVAL)

    result.append((action, identifier, params))

  return result


def _ParseExtStorageParams(params):
  """Parses the disk params for ExtStorage conversions.

  """
  if params:
    if constants.IDISK_PROVIDER not in params:
      raise errors.OpPrereqError("Missing required parameter '%s' when"
                                 " converting to an ExtStorage disk template" %
                                 constants.IDISK_PROVIDER, errors.ECODE_INVAL)
    else:
      for param in params:
        if (param != constants.IDISK_PROVIDER and
            param in constants.IDISK_PARAMS):
          raise errors.OpPrereqError("Invalid parameter '%s' when converting"
                                     " to an ExtStorage template (it is not"
                                     " allowed modifying existing disk"
                                     " parameters)" % param, errors.ECODE_INVAL)

  return params


def _ParseDiskSizes(mods):
  """Parses disk sizes in parameters.

  """
  for (action, _, params) in mods:
    if params and constants.IDISK_SPINDLES in params:
      params[constants.IDISK_SPINDLES] = \
          int(params[constants.IDISK_SPINDLES])
    if params and constants.IDISK_SIZE in params:
      params[constants.IDISK_SIZE] = \
        utils.ParseUnit(params[constants.IDISK_SIZE])
    elif action == constants.DDM_ADD:
      raise errors.OpPrereqError("Missing required parameter 'size'",
                                 errors.ECODE_INVAL)

  return mods


def SetInstanceParams(opts, args):
  """Modifies an instance.

  All parameters take effect only at the next restart of the instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  if not (opts.nics or opts.disks or opts.disk_template or opts.hvparams or
          opts.beparams or opts.os or opts.osparams or opts.osparams_private
          or opts.offline_inst or opts.online_inst or opts.runtime_mem or
          opts.new_primary_node or opts.instance_communication is not None):
    ToStderr("Please give at least one of the parameters.")
    return 1

  for param in opts.beparams:
    if isinstance(opts.beparams[param], str):
      if opts.beparams[param].lower() == "default":
        opts.beparams[param] = constants.VALUE_DEFAULT

  utils.ForceDictType(opts.beparams, constants.BES_PARAMETER_COMPAT,
                      allowed_values=[constants.VALUE_DEFAULT])

  for param in opts.hvparams:
    if isinstance(opts.hvparams[param], str):
      if opts.hvparams[param].lower() == "default":
        opts.hvparams[param] = constants.VALUE_DEFAULT

  utils.ForceDictType(opts.hvparams, constants.HVS_PARAMETER_TYPES,
                      allowed_values=[constants.VALUE_DEFAULT])
  FixHvParams(opts.hvparams)

  nics = _ConvertNicDiskModifications(opts.nics)
  for action, _, __ in nics:
    if action == constants.DDM_MODIFY and opts.hotplug and not opts.force:
      usertext = ("You are about to hot-modify a NIC. This will be done"
                  " by removing the existing NIC and then adding a new one."
                  " Network connection might be lost. Continue?")
      if not AskUser(usertext):
        return 1

  disks = _ParseDiskSizes(_ConvertNicDiskModifications(opts.disks))

  # verify the user provided parameters for disk template conversions
  if opts.disk_template:
    if (opts.ext_params and
          opts.disk_template != constants.DT_EXT):
      ToStderr("Specifying ExtStorage parameters requires converting"
               " to the '%s' disk template" % constants.DT_EXT)
      return 1
    elif (not opts.ext_params and
          opts.disk_template == constants.DT_EXT):
      ToStderr("Provider option is missing, use either the"
               " '--ext-params' or '-e' option")
      return 1

  if ((opts.file_driver or
       opts.file_storage_dir) and
      not opts.disk_template in constants.DTS_FILEBASED):
    ToStderr("Specifying file-based configuration arguments requires"
             " converting to a file-based disk template")
    return 1

  ext_params = _ParseExtStorageParams(opts.ext_params)

  if opts.offline_inst:
    offline = True
  elif opts.online_inst:
    offline = False
  else:
    offline = None

  instance_comm = opts.instance_communication

  op = opcodes.OpInstanceSetParams(instance_name=args[0],
                                   nics=nics,
                                   disks=disks,
                                   hotplug=opts.hotplug,
                                   disk_template=opts.disk_template,
                                   ext_params=ext_params,
                                   file_driver=opts.file_driver,
                                   file_storage_dir=opts.file_storage_dir,
                                   remote_node=opts.node,
                                   iallocator=opts.iallocator,
                                   pnode=opts.new_primary_node,
                                   hvparams=opts.hvparams,
                                   beparams=opts.beparams,
                                   runtime_mem=opts.runtime_mem,
                                   os_name=opts.os,
                                   osparams=opts.osparams,
                                   osparams_private=opts.osparams_private,
                                   force_variant=opts.force_variant,
                                   force=opts.force,
                                   wait_for_sync=opts.wait_for_sync,
                                   offline=offline,
                                   conflicts_check=opts.conflicts_check,
                                   ignore_ipolicy=opts.ignore_ipolicy,
                                   instance_communication=instance_comm)

  # even if here we process the result, we allow submit only
  result = SubmitOrSend(op, opts)

  if result:
    ToStdout("Modified instance %s", args[0])
    for param, data in result:
      ToStdout(" - %-5s -> %s", param, data)
    ToStdout("Please don't forget that most parameters take effect"
             " only at the next (re)start of the instance initiated by"
             " ganeti; restarting from within the instance will"
             " not be enough.")
    if opts.hvparams:
      ToStdout("Note that changing hypervisor parameters without performing a"
               " restart might lead to a crash while performing a live"
               " migration. This will be addressed in future Ganeti versions.")
  return 0


def ChangeGroup(opts, args):
  """Moves an instance to another group.

  """
  (instance_name, ) = args

  cl = GetClient()

  op = opcodes.OpInstanceChangeGroup(instance_name=instance_name,
                                     iallocator=opts.iallocator,
                                     target_groups=opts.to,
                                     early_release=opts.early_release)
  result = SubmitOrSend(op, opts, cl=cl)

  # Keep track of submitted jobs
  jex = JobExecutor(cl=cl, opts=opts)

  for (status, job_id) in result[constants.JOB_IDS_KEY]:
    jex.AddJobId(None, status, job_id)

  results = jex.GetResults()
  bad_cnt = len([row for row in results if not row[0]])
  if bad_cnt == 0:
    ToStdout("Instance '%s' changed group successfully.", instance_name)
    rcode = constants.EXIT_SUCCESS
  else:
    ToStdout("There were %s errors while changing group of instance '%s'.",
             bad_cnt, instance_name)
    rcode = constants.EXIT_FAILURE

  return rcode


# multi-instance selection options
m_force_multi = cli_option("--force-multiple", dest="force_multi",
                           help="Do not ask for confirmation when more than"
                           " one instance is affected",
                           action="store_true", default=False)

m_pri_node_opt = cli_option("--primary", dest="multi_mode",
                            help="Filter by nodes (primary only)",
                            const=_EXPAND_NODES_PRI, action="store_const")

m_sec_node_opt = cli_option("--secondary", dest="multi_mode",
                            help="Filter by nodes (secondary only)",
                            const=_EXPAND_NODES_SEC, action="store_const")

m_node_opt = cli_option("--node", dest="multi_mode",
                        help="Filter by nodes (primary and secondary)",
                        const=_EXPAND_NODES_BOTH, action="store_const")

m_clust_opt = cli_option("--all", dest="multi_mode",
                         help="Select all instances in the cluster",
                         const=_EXPAND_CLUSTER, action="store_const")

m_inst_opt = cli_option("--instance", dest="multi_mode",
                        help="Filter by instance name [default]",
                        const=_EXPAND_INSTANCES, action="store_const")

m_node_tags_opt = cli_option("--node-tags", dest="multi_mode",
                             help="Filter by node tag",
                             const=_EXPAND_NODES_BOTH_BY_TAGS,
                             action="store_const")

m_pri_node_tags_opt = cli_option("--pri-node-tags", dest="multi_mode",
                                 help="Filter by primary node tag",
                                 const=_EXPAND_NODES_PRI_BY_TAGS,
                                 action="store_const")

m_sec_node_tags_opt = cli_option("--sec-node-tags", dest="multi_mode",
                                 help="Filter by secondary node tag",
                                 const=_EXPAND_NODES_SEC_BY_TAGS,
                                 action="store_const")

m_inst_tags_opt = cli_option("--tags", dest="multi_mode",
                             help="Filter by instance tag",
                             const=_EXPAND_INSTANCES_BY_TAGS,
                             action="store_const")

# this is defined separately due to readability only
add_opts = [
  FORTHCOMING_OPT,
  COMMIT_OPT,
  NOSTART_OPT,
  OS_OPT,
  FORCE_VARIANT_OPT,
  NO_INSTALL_OPT,
  IGNORE_IPOLICY_OPT,
  INSTANCE_COMMUNICATION_OPT,
  HELPER_STARTUP_TIMEOUT_OPT,
  HELPER_SHUTDOWN_TIMEOUT_OPT,
  ]

commands = {
  "add": (
    AddInstance, [ArgHost(min=1, max=1)],
    COMMON_CREATE_OPTS + add_opts,
    "[...] -t disk-type -n node[:secondary-node] -o os-type <instance-name>",
    "Creates and adds a new instance to the cluster"),
  "batch-create": (
    BatchCreate, [ArgFile(min=1, max=1)],
    [DRY_RUN_OPT, PRIORITY_OPT, IALLOCATOR_OPT] + SUBMIT_OPTS,
    "<instances.json>",
    "Create a bunch of instances based on specs in the file."),
  "console": (
    ConnectToInstanceConsole, ARGS_ONE_INSTANCE,
    [SHOWCMD_OPT, PRIORITY_OPT],
    "[--show-cmd] <instance-name>",
    "Opens a console on the specified instance"),
  "failover": (
    FailoverInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, IGNORE_CONSIST_OPT] + SUBMIT_OPTS +
    [SHUTDOWN_TIMEOUT_OPT,
     DRY_RUN_OPT, PRIORITY_OPT, DST_NODE_OPT, IALLOCATOR_OPT,
     IGNORE_IPOLICY_OPT, CLEANUP_OPT],
    "[-f] <instance-name>", "Stops the instance, changes its primary node and"
    " (if it was originally running) starts it on the new node"
    " (the secondary for mirrored instances or any node"
    " for shared storage)."),
  "migrate": (
    MigrateInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, NONLIVE_OPT, MIGRATION_MODE_OPT, CLEANUP_OPT, DRY_RUN_OPT,
     PRIORITY_OPT, DST_NODE_OPT, IALLOCATOR_OPT, ALLOW_FAILOVER_OPT,
     IGNORE_IPOLICY_OPT, IGNORE_HVVERSIONS_OPT, NORUNTIME_CHGS_OPT]
    + SUBMIT_OPTS,
    "[-f] <instance-name>", "Migrate instance to its secondary node"
    " (only for mirrored instances)"),
  "move": (
    MoveInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT] + SUBMIT_OPTS +
    [SINGLE_NODE_OPT, COMPRESS_OPT,
     SHUTDOWN_TIMEOUT_OPT, DRY_RUN_OPT, PRIORITY_OPT, IGNORE_CONSIST_OPT,
     IGNORE_IPOLICY_OPT],
    "[-f] <instance-name>", "Move instance to an arbitrary node"
    " (only for instances of type file and lv)"),
  "info": (
    ShowInstanceConfig, ARGS_MANY_INSTANCES,
    [STATIC_OPT, ALL_OPT, ROMAN_OPT, PRIORITY_OPT],
    "[-s] {--all | <instance-name>...}",
    "Show information on the specified instance(s)"),
  "list": (
    ListInstances, ARGS_MANY_INSTANCES,
    [NOHDR_OPT, SEP_OPT, USEUNITS_OPT, FIELDS_OPT, VERBOSE_OPT,
     FORCE_FILTER_OPT],
    "[<instance-name>...]",
    "Lists the instances and their status. The available fields can be shown"
    " using the \"list-fields\" command (see the man page for details)."
    " The default field list is (in order): %s." %
    utils.CommaJoin(_LIST_DEF_FIELDS),
    ),
  "list-fields": (
    ListInstanceFields, [ArgUnknown()],
    [NOHDR_OPT, SEP_OPT],
    "[fields...]",
    "Lists all available fields for instances"),
  "reinstall": (
    ReinstallInstance, [ArgInstance()],
    [FORCE_OPT, OS_OPT, FORCE_VARIANT_OPT, m_force_multi, m_node_opt,
     m_pri_node_opt, m_sec_node_opt, m_clust_opt, m_inst_opt, m_node_tags_opt,
     m_pri_node_tags_opt, m_sec_node_tags_opt, m_inst_tags_opt, SELECT_OS_OPT]
    + SUBMIT_OPTS + [DRY_RUN_OPT, PRIORITY_OPT, OSPARAMS_OPT,
                     OSPARAMS_PRIVATE_OPT, OSPARAMS_SECRET_OPT],
    "[-f] <instance-name>", "Reinstall a stopped instance"),
  "remove": (
    RemoveInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, SHUTDOWN_TIMEOUT_OPT, IGNORE_FAILURES_OPT] + SUBMIT_OPTS
    + [DRY_RUN_OPT, PRIORITY_OPT],
    "[-f] <instance-name>", "Shuts down the instance and removes it"),
  "rename": (
    RenameInstance,
    [ArgInstance(min=1, max=1), ArgHost(min=1, max=1)],
    [IPCHECK_OPT, NAMECHECK_OPT] + SUBMIT_OPTS
    + [DRY_RUN_OPT, PRIORITY_OPT],
    "<old-name> <new-name>", "Rename the instance"),
  "replace-disks": (
    ReplaceDisks, ARGS_ONE_INSTANCE,
    [AUTO_REPLACE_OPT, DISKIDX_OPT, IALLOCATOR_OPT, EARLY_RELEASE_OPT,
     NEW_SECONDARY_OPT, ON_PRIMARY_OPT, ON_SECONDARY_OPT] + SUBMIT_OPTS
    + [DRY_RUN_OPT, PRIORITY_OPT, IGNORE_IPOLICY_OPT],
    "[-s|-p|-a|-n NODE|-I NAME] <instance-name>",
    "Replaces disks for the instance"),
  "modify": (
    SetInstanceParams, ARGS_ONE_INSTANCE,
    [BACKEND_OPT, DISK_OPT, FORCE_OPT, HVOPTS_OPT, NET_OPT] + SUBMIT_OPTS +
    [DISK_TEMPLATE_OPT, SINGLE_NODE_OPT, IALLOCATOR_OPT,
     OS_OPT, FORCE_VARIANT_OPT,
     OSPARAMS_OPT, OSPARAMS_PRIVATE_OPT, DRY_RUN_OPT, PRIORITY_OPT, NWSYNC_OPT,
     OFFLINE_INST_OPT, ONLINE_INST_OPT, IGNORE_IPOLICY_OPT, RUNTIME_MEM_OPT,
     NOCONFLICTSCHECK_OPT, NEW_PRIMARY_OPT,
     NOHOTPLUG_OPT, INSTANCE_COMMUNICATION_OPT,
     EXT_PARAMS_OPT, FILESTORE_DRIVER_OPT, FILESTORE_DIR_OPT],
    "<instance-name>", "Alters the parameters of an instance"),
  "shutdown": (
    GenericManyOps("shutdown", _ShutdownInstance), [ArgInstance()],
    [FORCE_OPT, m_node_opt, m_pri_node_opt, m_sec_node_opt, m_clust_opt,
     m_node_tags_opt, m_pri_node_tags_opt, m_sec_node_tags_opt,
     m_inst_tags_opt, m_inst_opt, m_force_multi, TIMEOUT_OPT] + SUBMIT_OPTS
    + [DRY_RUN_OPT, PRIORITY_OPT, IGNORE_OFFLINE_OPT, NO_REMEMBER_OPT],
    "<instance-name>...", "Stops one or more instances"),
  "startup": (
    GenericManyOps("startup", _StartupInstance), [ArgInstance()],
    [FORCE_OPT, m_force_multi, m_node_opt, m_pri_node_opt, m_sec_node_opt,
     m_node_tags_opt, m_pri_node_tags_opt, m_sec_node_tags_opt,
     m_inst_tags_opt, m_clust_opt, m_inst_opt] + SUBMIT_OPTS +
    [HVOPTS_OPT,
     BACKEND_OPT, DRY_RUN_OPT, PRIORITY_OPT, IGNORE_OFFLINE_OPT,
     NO_REMEMBER_OPT, STARTUP_PAUSED_OPT],
    "<instance-name>...", "Starts one or more instances"),
  "reboot": (
    GenericManyOps("reboot", _RebootInstance), [ArgInstance()],
    [m_force_multi, REBOOT_TYPE_OPT, IGNORE_SECONDARIES_OPT, m_node_opt,
     m_pri_node_opt, m_sec_node_opt, m_clust_opt, m_inst_opt] + SUBMIT_OPTS +
    [m_node_tags_opt, m_pri_node_tags_opt, m_sec_node_tags_opt,
     m_inst_tags_opt, SHUTDOWN_TIMEOUT_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance-name>...", "Reboots one or more instances"),
  "activate-disks": (
    ActivateDisks, ARGS_ONE_INSTANCE,
    SUBMIT_OPTS + [IGNORE_SIZE_OPT, PRIORITY_OPT, WFSYNC_OPT],
    "<instance-name>", "Activate an instance's disks"),
  "deactivate-disks": (
    DeactivateDisks, ARGS_ONE_INSTANCE,
    [FORCE_OPT] + SUBMIT_OPTS + [DRY_RUN_OPT, PRIORITY_OPT],
    "[-f] <instance-name>", "Deactivate an instance's disks"),
  "recreate-disks": (
    RecreateDisks, ARGS_ONE_INSTANCE,
    SUBMIT_OPTS +
    [DISK_OPT, NODE_PLACEMENT_OPT, DRY_RUN_OPT, PRIORITY_OPT,
     IALLOCATOR_OPT],
    "<instance-name>", "Recreate an instance's disks"),
  "grow-disk": (
    GrowDisk,
    [ArgInstance(min=1, max=1), ArgUnknown(min=1, max=1),
     ArgUnknown(min=1, max=1)],
    SUBMIT_OPTS +
    [NWSYNC_OPT, DRY_RUN_OPT, PRIORITY_OPT, ABSOLUTE_OPT, IGNORE_IPOLICY_OPT],
    "<instance-name> <disk> <size>", "Grow an instance's disk"),
  "change-group": (
    ChangeGroup, ARGS_ONE_INSTANCE,
    [TO_GROUP_OPT, IALLOCATOR_OPT, EARLY_RELEASE_OPT, PRIORITY_OPT]
    + SUBMIT_OPTS,
    "[-I <iallocator>] [--to <group>] <instance-name>",
    "Change group of instance"),
  "list-tags": (
    ListTags, ARGS_ONE_INSTANCE, [],
    "<instance-name>", "List the tags of the given instance"),
  "add-tags": (
    AddTags, [ArgInstance(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<instance-name> <tag>...", "Add tags to the given instance"),
  "remove-tags": (
    RemoveTags, [ArgInstance(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<instance-name> <tag>...", "Remove tags from given instance"),
  }

#: dictionary with aliases for commands
aliases = {
  "start": "startup",
  "stop": "shutdown",
  "show": "info",
  }


def Main():
  return GenericMain(commands, aliases=aliases,
                     override={"tag_type": constants.TAG_INSTANCE},
                     env_override=_ENV_OVERRIDE)
