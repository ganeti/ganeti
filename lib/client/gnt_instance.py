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

"""Instance related commands"""

# pylint: disable-msg=W0401,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-instance

import itertools
import simplejson
import logging
from cStringIO import StringIO

from ganeti.cli import *
from ganeti import opcodes
from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import errors
from ganeti import netutils
from ganeti import ssh
from ganeti import objects


_SHUTDOWN_CLUSTER = "cluster"
_SHUTDOWN_NODES_BOTH = "nodes"
_SHUTDOWN_NODES_PRI = "nodes-pri"
_SHUTDOWN_NODES_SEC = "nodes-sec"
_SHUTDOWN_NODES_BOTH_BY_TAGS = "nodes-by-tags"
_SHUTDOWN_NODES_PRI_BY_TAGS = "nodes-pri-by-tags"
_SHUTDOWN_NODES_SEC_BY_TAGS = "nodes-sec-by-tags"
_SHUTDOWN_INSTANCES = "instances"
_SHUTDOWN_INSTANCES_BY_TAGS = "instances-by-tags"

_SHUTDOWN_NODES_TAGS_MODES = (
    _SHUTDOWN_NODES_BOTH_BY_TAGS,
    _SHUTDOWN_NODES_PRI_BY_TAGS,
    _SHUTDOWN_NODES_SEC_BY_TAGS)


_VALUE_TRUE = "true"

#: default list of options for L{ListInstances}
_LIST_DEF_FIELDS = [
  "name", "hypervisor", "os", "pnode", "status", "oper_ram",
  ]


def _ExpandMultiNames(mode, names, client=None):
  """Expand the given names using the passed mode.

  For _SHUTDOWN_CLUSTER, all instances will be returned. For
  _SHUTDOWN_NODES_PRI/SEC, all instances having those nodes as
  primary/secondary will be returned. For _SHUTDOWN_NODES_BOTH, all
  instances having those nodes as either primary or secondary will be
  returned. For _SHUTDOWN_INSTANCES, the given instances will be
  returned.

  @param mode: one of L{_SHUTDOWN_CLUSTER}, L{_SHUTDOWN_NODES_BOTH},
      L{_SHUTDOWN_NODES_PRI}, L{_SHUTDOWN_NODES_SEC} or
      L{_SHUTDOWN_INSTANCES}
  @param names: a list of names; for cluster, it must be empty,
      and for node and instance it must be a list of valid item
      names (short names are valid as usual, e.g. node1 instead of
      node1.example.com)
  @rtype: list
  @return: the list of names after the expansion
  @raise errors.ProgrammerError: for unknown selection type
  @raise errors.OpPrereqError: for invalid input parameters

  """
  # pylint: disable-msg=W0142

  if client is None:
    client = GetClient()
  if mode == _SHUTDOWN_CLUSTER:
    if names:
      raise errors.OpPrereqError("Cluster filter mode takes no arguments",
                                 errors.ECODE_INVAL)
    idata = client.QueryInstances([], ["name"], False)
    inames = [row[0] for row in idata]

  elif mode in (_SHUTDOWN_NODES_BOTH,
                _SHUTDOWN_NODES_PRI,
                _SHUTDOWN_NODES_SEC) + _SHUTDOWN_NODES_TAGS_MODES:
    if mode in _SHUTDOWN_NODES_TAGS_MODES:
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
    if mode in (_SHUTDOWN_NODES_BOTH, _SHUTDOWN_NODES_BOTH_BY_TAGS):
      inames = pri_names + sec_names
    elif mode in (_SHUTDOWN_NODES_PRI, _SHUTDOWN_NODES_PRI_BY_TAGS):
      inames = pri_names
    elif mode in (_SHUTDOWN_NODES_SEC, _SHUTDOWN_NODES_SEC_BY_TAGS):
      inames = sec_names
    else:
      raise errors.ProgrammerError("Unhandled shutdown type")
  elif mode == _SHUTDOWN_INSTANCES:
    if not names:
      raise errors.OpPrereqError("No instance names passed",
                                 errors.ECODE_INVAL)
    idata = client.QueryInstances(names, ["name"], False)
    inames = [row[0] for row in idata]
  elif mode == _SHUTDOWN_INSTANCES_BY_TAGS:
    if not names:
      raise errors.OpPrereqError("No instance tags passed",
                                 errors.ECODE_INVAL)
    idata = client.QueryInstances([], ["name", "tags"], False)
    inames = [row[0] for row in idata if set(row[1]).intersection(names)]
  else:
    raise errors.OpPrereqError("Unknown mode '%s'" % mode, errors.ECODE_INVAL)

  return inames


def _ConfirmOperation(inames, text, extra=""):
  """Ask the user to confirm an operation on a list of instances.

  This function is used to request confirmation for doing an operation
  on a given list of instances.

  @type inames: list
  @param inames: the list of names that we display when
      we ask for confirmation
  @type text: str
  @param text: the operation that the user should confirm
      (e.g. I{shutdown} or I{startup})
  @rtype: boolean
  @return: True or False depending on user's confirmation.

  """
  count = len(inames)
  msg = ("The %s will operate on %d instances.\n%s"
         "Do you want to continue?" % (text, count, extra))
  affected = ("\nAffected instances:\n" +
              "\n".join(["  %s" % name for name in inames]))

  choices = [('y', True, 'Yes, execute the %s' % text),
             ('n', False, 'No, abort the %s' % text)]

  if count > 20:
    choices.insert(1, ('v', 'v', 'View the list of affected instances'))
    ask = msg
  else:
    ask = msg + affected

  choice = AskUser(ask, choices)
  if choice == 'v':
    choices.pop(1)
    choice = AskUser(msg + affected, choices)
  return choice


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
  # TODO: change LUQueryInstances to that it actually returns None
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
      opts.multi_mode = _SHUTDOWN_INSTANCES
    cl = GetClient()
    inames = _ExpandMultiNames(opts.multi_mode, args, client=cl)
    if not inames:
      raise errors.OpPrereqError("Selection filter does not match"
                                 " any instances", errors.ECODE_INVAL)
    multi_on = opts.multi_mode != _SHUTDOWN_INSTANCES or len(inames) > 1
    if not (opts.force_multi or not multi_on
            or _ConfirmOperation(inames, operation)):
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
                               "snodes"],
                              (lambda value: ",".join(str(item)
                                                      for item in value),
                               False))

  return GenericList(constants.QR_INSTANCE, selected_fields, args, opts.units,
                     opts.separator, not opts.no_headers,
                     format_override=fmtoverride)


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

  This is just a wrapper over GenericInstanceCreate.

  """
  return GenericInstanceCreate(constants.INSTANCE_CREATE, opts, args)


def BatchCreate(opts, args):
  """Create instances using a definition file.

  This function reads a json file with instances defined
  in the form::

    {"instance-name":{
      "disk_size": [20480],
      "template": "drbd",
      "backend": {
        "memory": 512,
        "vcpus": 1 },
      "os": "debootstrap",
      "primary_node": "firstnode",
      "secondary_node": "secondnode",
      "iallocator": "dumb"}
    }

  Note that I{primary_node} and I{secondary_node} have precedence over
  I{iallocator}.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain one element, the json filename
  @rtype: int
  @return: the desired exit code

  """
  _DEFAULT_SPECS = {"disk_size": [20 * 1024],
                    "backend": {},
                    "iallocator": None,
                    "primary_node": None,
                    "secondary_node": None,
                    "nics": None,
                    "start": True,
                    "ip_check": True,
                    "name_check": True,
                    "hypervisor": None,
                    "hvparams": {},
                    "file_storage_dir": None,
                    "force_variant": False,
                    "file_driver": 'loop'}

  def _PopulateWithDefaults(spec):
    """Returns a new hash combined with default values."""
    mydict = _DEFAULT_SPECS.copy()
    mydict.update(spec)
    return mydict

  def _Validate(spec):
    """Validate the instance specs."""
    # Validate fields required under any circumstances
    for required_field in ('os', 'template'):
      if required_field not in spec:
        raise errors.OpPrereqError('Required field "%s" is missing.' %
                                   required_field, errors.ECODE_INVAL)
    # Validate special fields
    if spec['primary_node'] is not None:
      if (spec['template'] in constants.DTS_NET_MIRROR and
          spec['secondary_node'] is None):
        raise errors.OpPrereqError('Template requires secondary node, but'
                                   ' there was no secondary provided.',
                                   errors.ECODE_INVAL)
    elif spec['iallocator'] is None:
      raise errors.OpPrereqError('You have to provide at least a primary_node'
                                 ' or an iallocator.',
                                 errors.ECODE_INVAL)

    if (spec['hvparams'] and
        not isinstance(spec['hvparams'], dict)):
      raise errors.OpPrereqError('Hypervisor parameters must be a dict.',
                                 errors.ECODE_INVAL)

  json_filename = args[0]
  try:
    instance_data = simplejson.loads(utils.ReadFile(json_filename))
  except Exception, err: # pylint: disable-msg=W0703
    ToStderr("Can't parse the instance definition file: %s" % str(err))
    return 1

  if not isinstance(instance_data, dict):
    ToStderr("The instance definition file is not in dict format.")
    return 1

  jex = JobExecutor(opts=opts)

  # Iterate over the instances and do:
  #  * Populate the specs with default value
  #  * Validate the instance specs
  i_names = utils.NiceSort(instance_data.keys()) # pylint: disable-msg=E1103
  for name in i_names:
    specs = instance_data[name]
    specs = _PopulateWithDefaults(specs)
    _Validate(specs)

    hypervisor = specs['hypervisor']
    hvparams = specs['hvparams']

    disks = []
    for elem in specs['disk_size']:
      try:
        size = utils.ParseUnit(elem)
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid disk size '%s' for"
                                   " instance %s: %s" %
                                   (elem, name, err), errors.ECODE_INVAL)
      disks.append({"size": size})

    utils.ForceDictType(specs['backend'], constants.BES_PARAMETER_TYPES)
    utils.ForceDictType(hvparams, constants.HVS_PARAMETER_TYPES)

    tmp_nics = []
    for field in ('ip', 'mac', 'mode', 'link', 'bridge'):
      if field in specs:
        if not tmp_nics:
          tmp_nics.append({})
        tmp_nics[0][field] = specs[field]

    if specs['nics'] is not None and tmp_nics:
      raise errors.OpPrereqError("'nics' list incompatible with using"
                                 " individual nic fields as well",
                                 errors.ECODE_INVAL)
    elif specs['nics'] is not None:
      tmp_nics = specs['nics']
    elif not tmp_nics:
      tmp_nics = [{}]

    op = opcodes.OpCreateInstance(instance_name=name,
                                  disks=disks,
                                  disk_template=specs['template'],
                                  mode=constants.INSTANCE_CREATE,
                                  os_type=specs['os'],
                                  force_variant=specs["force_variant"],
                                  pnode=specs['primary_node'],
                                  snode=specs['secondary_node'],
                                  nics=tmp_nics,
                                  start=specs['start'],
                                  ip_check=specs['ip_check'],
                                  name_check=specs['name_check'],
                                  wait_for_sync=True,
                                  iallocator=specs['iallocator'],
                                  hypervisor=hypervisor,
                                  hvparams=hvparams,
                                  beparams=specs['backend'],
                                  file_storage_dir=specs['file_storage_dir'],
                                  file_driver=specs['file_driver'])

    jex.QueueJob(name, op)
  # we never want to wait, just show the submitted job IDs
  jex.WaitOrShow(False)

  return 0


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
    opts.multi_mode = _SHUTDOWN_INSTANCES

  inames = _ExpandMultiNames(opts.multi_mode, args)
  if not inames:
    raise errors.OpPrereqError("Selection filter does not match any instances",
                               errors.ECODE_INVAL)

  # second, if requested, ask for an OS
  if opts.select_os is True:
    op = opcodes.OpDiagnoseOS(output_fields=["name", "variants"], names=[])
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

    choices.append(('x', 'exit', 'Exit gnt-instance reinstall'))
    selected = AskUser("Enter OS template number (or x to abort):",
                       choices)

    if selected == 'exit':
      ToStderr("User aborted reinstall, exiting")
      return 1

    os_name = selected
  else:
    os_name = opts.os

  # third, get confirmation: multi-reinstall requires --force-multi,
  # single-reinstall either --force or --force-multi (--force-multi is
  # a stronger --force)
  multi_on = opts.multi_mode != _SHUTDOWN_INSTANCES or len(inames) > 1
  if multi_on:
    warn_msg = "Note: this will remove *all* data for the below instances!\n"
    if not (opts.force_multi or
            _ConfirmOperation(inames, "reinstall", extra=warn_msg)):
      return 1
  else:
    if not (opts.force or opts.force_multi):
      usertext = ("This will reinstall the instance %s and remove"
                  " all data. Continue?") % inames[0]
      if not AskUser(usertext):
        return 1

  jex = JobExecutor(verbose=multi_on, opts=opts)
  for instance_name in inames:
    op = opcodes.OpReinstallInstance(instance_name=instance_name,
                                     os_type=os_name,
                                     force_variant=opts.force_variant,
                                     osparams=opts.osparams)
    jex.QueueJob(instance_name, op)

  jex.WaitOrShow(not opts.submit_only)
  return 0


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

  op = opcodes.OpRemoveInstance(instance_name=instance_name,
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
  if not opts.name_check:
    if not AskUser("As you disabled the check of the DNS entry, please verify"
                   " that '%s' is a FQDN. Continue?" % args[1]):
      return 1

  op = opcodes.OpRenameInstance(instance_name=args[0],
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
  op = opcodes.OpActivateInstanceDisks(instance_name=instance_name,
                                       ignore_size=opts.ignore_size)
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
  op = opcodes.OpDeactivateInstanceDisks(instance_name=instance_name)
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
  if opts.disks:
    try:
      opts.disks = [int(v) for v in opts.disks.split(",")]
    except (ValueError, TypeError), err:
      ToStderr("Invalid disks value: %s" % str(err))
      return 1
  else:
    opts.disks = []

  op = opcodes.OpRecreateInstanceDisks(instance_name=instance_name,
                                       disks=opts.disks)
  SubmitOrSend(op, opts)
  return 0


def GrowDisk(opts, args):
  """Grow an instance's disks.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain two elements, the instance name
      whose disks we grow and the disk name, e.g. I{sda}
  @rtype: int
  @return: the desired exit code

  """
  instance = args[0]
  disk = args[1]
  try:
    disk = int(disk)
  except (TypeError, ValueError), err:
    raise errors.OpPrereqError("Invalid disk index: %s" % str(err),
                               errors.ECODE_INVAL)
  amount = utils.ParseUnit(args[2])
  op = opcodes.OpGrowDisk(instance_name=instance, disk=disk, amount=amount,
                          wait_for_sync=opts.wait_for_sync)
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
  op = opcodes.OpStartupInstance(instance_name=name,
                                 force=opts.force,
                                 ignore_offline_nodes=opts.ignore_offline)
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
  return opcodes.OpRebootInstance(instance_name=name,
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
  return opcodes.OpShutdownInstance(instance_name=name,
                                    timeout=opts.timeout,
                                    ignore_offline_nodes=opts.ignore_offline)


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
    except (TypeError, ValueError), err:
      raise errors.OpPrereqError("Invalid disk index passed: %s" % str(err),
                                 errors.ECODE_INVAL)
  cnt = [opts.on_primary, opts.on_secondary, opts.auto,
         new_2ndary is not None, iallocator is not None].count(True)
  if cnt != 1:
    raise errors.OpPrereqError("One and only one of the -p, -s, -a, -n and -i"
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

  op = opcodes.OpReplaceDisks(instance_name=args[0], disks=disks,
                              remote_node=new_2ndary, mode=mode,
                              iallocator=iallocator,
                              early_release=opts.early_release)
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
  force = opts.force

  if not force:
    _EnsureInstancesExist(cl, [instance_name])

    usertext = ("Failover will happen to image %s."
                " This requires a shutdown of the instance. Continue?" %
                (instance_name,))
    if not AskUser(usertext):
      return 1

  op = opcodes.OpFailoverInstance(instance_name=instance_name,
                                  ignore_consistency=opts.ignore_consistency,
                                  shutdown_timeout=opts.shutdown_timeout)
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

  op = opcodes.OpMigrateInstance(instance_name=instance_name, mode=mode,
                                 cleanup=opts.cleanup)
  SubmitOpCode(op, cl=cl, opts=opts)
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

  op = opcodes.OpMoveInstance(instance_name=instance_name,
                              target_node=opts.node,
                              shutdown_timeout=opts.shutdown_timeout)
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

  op = opcodes.OpConnectConsole(instance_name=instance_name)

  cl = GetClient()
  try:
    cluster_name = cl.QueryConfigValues(["cluster_name"])[0]
    console_data = SubmitOpCode(op, opts=opts, cl=cl)
  finally:
    # Ensure client connection is closed while external commands are run
    cl.Close()

  del cl

  return _DoConsole(objects.InstanceConsole.FromDict(console_data),
                    opts.show_command, cluster_name)


def _DoConsole(console, show_command, cluster_name, feedback_fn=ToStdout,
               _runcmd_fn=utils.RunCmd):
  """Acts based on the result of L{opcodes.OpConnectConsole}.

  @type console: L{objects.InstanceConsole}
  @param console: Console object
  @type show_command: bool
  @param show_command: Whether to just display commands
  @type cluster_name: string
  @param cluster_name: Cluster name as retrieved from master daemon

  """
  assert console.Validate()

  if console.kind == constants.CONS_MESSAGE:
    feedback_fn(console.message)
  elif console.kind == constants.CONS_VNC:
    feedback_fn("Instance %s has VNC listening on %s:%s (display %s),"
                " URL <vnc://%s:%s/>",
                console.instance, console.host, console.port,
                console.display, console.host, console.port)
  elif console.kind == constants.CONS_SSH:
    # Convert to string if not already one
    if isinstance(console.command, basestring):
      cmd = console.command
    else:
      cmd = utils.ShellQuoteArgs(console.command)

    srun = ssh.SshRunner(cluster_name=cluster_name)
    ssh_cmd = srun.BuildCmd(console.host, console.user, cmd,
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


def _FormatLogicalID(dev_type, logical_id, roman):
  """Formats the logical_id of a disk.

  """
  if dev_type == constants.LD_DRBD8:
    node_a, node_b, port, minor_a, minor_b, key = logical_id
    data = [
      ("nodeA", "%s, minor=%s" % (node_a, compat.TryToRoman(minor_a,
                                                            convert=roman))),
      ("nodeB", "%s, minor=%s" % (node_b, compat.TryToRoman(minor_b,
                                                            convert=roman))),
      ("port", compat.TryToRoman(port, convert=roman)),
      ("auth key", key),
      ]
  elif dev_type == constants.LD_LV:
    vg_name, lv_name = logical_id
    data = ["%s/%s" % (vg_name, lv_name)]
  else:
    data = [str(logical_id)]

  return data


def _FormatBlockDevInfo(idx, top_level, dev, static, roman):
  """Show block device information.

  This is only used by L{ShowInstanceConfig}, but it's too big to be
  left for an inline definition.

  @type idx: int
  @param idx: the index of the current disk
  @type top_level: boolean
  @param top_level: if this a top-level disk?
  @type dev: dict
  @param dev: dictionary with disk information
  @type static: boolean
  @param static: wheter the device information doesn't contain
      runtime information but only static data
  @type roman: boolean
  @param roman: whether to try to use roman integers
  @return: a list of either strings, tuples or lists
      (which should be formatted at a higher indent level)

  """
  def helper(dtype, status):
    """Format one line for physical device status.

    @type dtype: str
    @param dtype: a constant from the L{constants.LDS_BLOCK} set
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
    if dtype in (constants.LD_DRBD8, ):
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
    elif dtype == constants.LD_LV:
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
    nice_size = utils.FormatUnit(dev["size"], "h")
  else:
    nice_size = dev["size"]
  d1 = ["- %s: %s, size %s" % (txt, dev["dev_type"], nice_size)]
  data = []
  if top_level:
    data.append(("access mode", dev["mode"]))
  if dev["logical_id"] is not None:
    try:
      l_id = _FormatLogicalID(dev["dev_type"], dev["logical_id"], roman)
    except ValueError:
      l_id = [str(dev["logical_id"])]
    if len(l_id) == 1:
      data.append(("logical_id", l_id[0]))
    else:
      data.extend(l_id)
  elif dev["physical_id"] is not None:
    data.append("physical_id:")
    data.append([dev["physical_id"]])
  if not static:
    data.append(("on primary", helper(dev["dev_type"], dev["pstatus"])))
  if dev["sstatus"] and not static:
    data.append(("on secondary", helper(dev["dev_type"], dev["sstatus"])))

  if dev["children"]:
    data.append("child devices:")
    for c_idx, child in enumerate(dev["children"]):
      data.append(_FormatBlockDevInfo(c_idx, False, child, static, roman))
  d1.append(data)
  return d1


def _FormatList(buf, data, indent_level):
  """Formats a list of data at a given indent level.

  If the element of the list is:
    - a string, it is simply formatted as is
    - a tuple, it will be split into key, value and the all the
      values in a list will be aligned all at the same start column
    - a list, will be recursively formatted

  @type buf: StringIO
  @param buf: the buffer into which we write the output
  @param data: the list to format
  @type indent_level: int
  @param indent_level: the indent level to format at

  """
  max_tlen = max([len(elem[0]) for elem in data
                 if isinstance(elem, tuple)] or [0])
  for elem in data:
    if isinstance(elem, basestring):
      buf.write("%*s%s\n" % (2*indent_level, "", elem))
    elif isinstance(elem, tuple):
      key, value = elem
      spacer = "%*s" % (max_tlen - len(key), "")
      buf.write("%*s%s:%s %s\n" % (2*indent_level, "", key, spacer, value))
    elif isinstance(elem, list):
      _FormatList(buf, elem, indent_level+1)


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
  op = opcodes.OpQueryInstanceData(instances=args, static=opts.static)
  result = SubmitOpCode(op, opts=opts)
  if not result:
    ToStdout("No instances.")
    return 1

  buf = StringIO()
  retcode = 0
  for instance_name in result:
    instance = result[instance_name]
    buf.write("Instance name: %s\n" % instance["name"])
    buf.write("UUID: %s\n" % instance["uuid"])
    buf.write("Serial number: %s\n" %
              compat.TryToRoman(instance["serial_no"],
                                convert=opts.roman_integers))
    buf.write("Creation time: %s\n" % utils.FormatTime(instance["ctime"]))
    buf.write("Modification time: %s\n" % utils.FormatTime(instance["mtime"]))
    buf.write("State: configured to be %s" % instance["config_state"])
    if not opts.static:
      buf.write(", actual state is %s" % instance["run_state"])
    buf.write("\n")
    ##buf.write("Considered for memory checks in cluster verify: %s\n" %
    ##          instance["auto_balance"])
    buf.write("  Nodes:\n")
    buf.write("    - primary: %s\n" % instance["pnode"])
    buf.write("    - secondaries: %s\n" % utils.CommaJoin(instance["snodes"]))
    buf.write("  Operating system: %s\n" % instance["os"])
    FormatParameterDict(buf, instance["os_instance"], instance["os_actual"],
                        level=2)
    if instance.has_key("network_port"):
      buf.write("  Allocated network port: %s\n" %
                compat.TryToRoman(instance["network_port"],
                                  convert=opts.roman_integers))
    buf.write("  Hypervisor: %s\n" % instance["hypervisor"])

    # custom VNC console information
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
      buf.write("    - console connection: vnc to %s\n" % vnc_console_port)

    FormatParameterDict(buf, instance["hv_instance"], instance["hv_actual"],
                        level=2)
    buf.write("  Hardware:\n")
    buf.write("    - VCPUs: %s\n" %
              compat.TryToRoman(instance["be_actual"][constants.BE_VCPUS],
                                convert=opts.roman_integers))
    buf.write("    - memory: %sMiB\n" %
              compat.TryToRoman(instance["be_actual"][constants.BE_MEMORY],
                                convert=opts.roman_integers))
    buf.write("    - NICs:\n")
    for idx, (ip, mac, mode, link) in enumerate(instance["nics"]):
      buf.write("      - nic/%d: MAC: %s, IP: %s, mode: %s, link: %s\n" %
                (idx, mac, ip, mode, link))
    buf.write("  Disks:\n")

    for idx, device in enumerate(instance["disks"]):
      _FormatList(buf, _FormatBlockDevInfo(idx, True, device, opts.static,
                  opts.roman_integers), 2)

  ToStdout(buf.getvalue().rstrip('\n'))
  return retcode


def SetInstanceParams(opts, args):
  """Modifies an instance.

  All parameters take effect only at the next restart of the instance.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the instance name
  @rtype: int
  @return: the desired exit code

  """
  if not (opts.nics or opts.disks or opts.disk_template or
          opts.hvparams or opts.beparams or opts.os or opts.osparams):
    ToStderr("Please give at least one of the parameters.")
    return 1

  for param in opts.beparams:
    if isinstance(opts.beparams[param], basestring):
      if opts.beparams[param].lower() == "default":
        opts.beparams[param] = constants.VALUE_DEFAULT

  utils.ForceDictType(opts.beparams, constants.BES_PARAMETER_TYPES,
                      allowed_values=[constants.VALUE_DEFAULT])

  for param in opts.hvparams:
    if isinstance(opts.hvparams[param], basestring):
      if opts.hvparams[param].lower() == "default":
        opts.hvparams[param] = constants.VALUE_DEFAULT

  utils.ForceDictType(opts.hvparams, constants.HVS_PARAMETER_TYPES,
                      allowed_values=[constants.VALUE_DEFAULT])

  for idx, (nic_op, nic_dict) in enumerate(opts.nics):
    try:
      nic_op = int(nic_op)
      opts.nics[idx] = (nic_op, nic_dict)
    except (TypeError, ValueError):
      pass

  for idx, (disk_op, disk_dict) in enumerate(opts.disks):
    try:
      disk_op = int(disk_op)
      opts.disks[idx] = (disk_op, disk_dict)
    except (TypeError, ValueError):
      pass
    if disk_op == constants.DDM_ADD:
      if 'size' not in disk_dict:
        raise errors.OpPrereqError("Missing required parameter 'size'",
                                   errors.ECODE_INVAL)
      disk_dict['size'] = utils.ParseUnit(disk_dict['size'])

  if (opts.disk_template and
      opts.disk_template in constants.DTS_NET_MIRROR and
      not opts.node):
    ToStderr("Changing the disk template to a mirrored one requires"
             " specifying a secondary node")
    return 1

  op = opcodes.OpSetInstanceParams(instance_name=args[0],
                                   nics=opts.nics,
                                   disks=opts.disks,
                                   disk_template=opts.disk_template,
                                   remote_node=opts.node,
                                   hvparams=opts.hvparams,
                                   beparams=opts.beparams,
                                   os_name=opts.os,
                                   osparams=opts.osparams,
                                   force_variant=opts.force_variant,
                                   force=opts.force)

  # even if here we process the result, we allow submit only
  result = SubmitOrSend(op, opts)

  if result:
    ToStdout("Modified instance %s", args[0])
    for param, data in result:
      ToStdout(" - %-5s -> %s", param, data)
    ToStdout("Please don't forget that most parameters take effect"
             " only at the next start of the instance.")
  return 0


# multi-instance selection options
m_force_multi = cli_option("--force-multiple", dest="force_multi",
                           help="Do not ask for confirmation when more than"
                           " one instance is affected",
                           action="store_true", default=False)

m_pri_node_opt = cli_option("--primary", dest="multi_mode",
                            help="Filter by nodes (primary only)",
                            const=_SHUTDOWN_NODES_PRI, action="store_const")

m_sec_node_opt = cli_option("--secondary", dest="multi_mode",
                            help="Filter by nodes (secondary only)",
                            const=_SHUTDOWN_NODES_SEC, action="store_const")

m_node_opt = cli_option("--node", dest="multi_mode",
                        help="Filter by nodes (primary and secondary)",
                        const=_SHUTDOWN_NODES_BOTH, action="store_const")

m_clust_opt = cli_option("--all", dest="multi_mode",
                         help="Select all instances in the cluster",
                         const=_SHUTDOWN_CLUSTER, action="store_const")

m_inst_opt = cli_option("--instance", dest="multi_mode",
                        help="Filter by instance name [default]",
                        const=_SHUTDOWN_INSTANCES, action="store_const")

m_node_tags_opt = cli_option("--node-tags", dest="multi_mode",
                             help="Filter by node tag",
                             const=_SHUTDOWN_NODES_BOTH_BY_TAGS,
                             action="store_const")

m_pri_node_tags_opt = cli_option("--pri-node-tags", dest="multi_mode",
                                 help="Filter by primary node tag",
                                 const=_SHUTDOWN_NODES_PRI_BY_TAGS,
                                 action="store_const")

m_sec_node_tags_opt = cli_option("--sec-node-tags", dest="multi_mode",
                                 help="Filter by secondary node tag",
                                 const=_SHUTDOWN_NODES_SEC_BY_TAGS,
                                 action="store_const")

m_inst_tags_opt = cli_option("--tags", dest="multi_mode",
                             help="Filter by instance tag",
                             const=_SHUTDOWN_INSTANCES_BY_TAGS,
                             action="store_const")

# this is defined separately due to readability only
add_opts = [
  NOSTART_OPT,
  OS_OPT,
  FORCE_VARIANT_OPT,
  NO_INSTALL_OPT,
  ]

commands = {
  'add': (
    AddInstance, [ArgHost(min=1, max=1)], COMMON_CREATE_OPTS + add_opts,
    "[...] -t disk-type -n node[:secondary-node] -o os-type <name>",
    "Creates and adds a new instance to the cluster"),
  'batch-create': (
    BatchCreate, [ArgFile(min=1, max=1)], [DRY_RUN_OPT, PRIORITY_OPT],
    "<instances.json>",
    "Create a bunch of instances based on specs in the file."),
  'console': (
    ConnectToInstanceConsole, ARGS_ONE_INSTANCE,
    [SHOWCMD_OPT, PRIORITY_OPT],
    "[--show-cmd] <instance>", "Opens a console on the specified instance"),
  'failover': (
    FailoverInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, IGNORE_CONSIST_OPT, SUBMIT_OPT, SHUTDOWN_TIMEOUT_OPT,
     DRY_RUN_OPT, PRIORITY_OPT],
    "[-f] <instance>", "Stops the instance and starts it on the backup node,"
    " using the remote mirror (only for instances of type drbd)"),
  'migrate': (
    MigrateInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, NONLIVE_OPT, MIGRATION_MODE_OPT, CLEANUP_OPT, DRY_RUN_OPT,
     PRIORITY_OPT],
    "[-f] <instance>", "Migrate instance to its secondary node"
    " (only for instances of type drbd)"),
  'move': (
    MoveInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, SUBMIT_OPT, SINGLE_NODE_OPT, SHUTDOWN_TIMEOUT_OPT,
     DRY_RUN_OPT, PRIORITY_OPT],
    "[-f] <instance>", "Move instance to an arbitrary node"
    " (only for instances of type file and lv)"),
  'info': (
    ShowInstanceConfig, ARGS_MANY_INSTANCES,
    [STATIC_OPT, ALL_OPT, ROMAN_OPT, PRIORITY_OPT],
    "[-s] {--all | <instance>...}",
    "Show information on the specified instance(s)"),
  'list': (
    ListInstances, ARGS_MANY_INSTANCES,
    [NOHDR_OPT, SEP_OPT, USEUNITS_OPT, FIELDS_OPT],
    "[<instance>...]",
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
  'reinstall': (
    ReinstallInstance, [ArgInstance()],
    [FORCE_OPT, OS_OPT, FORCE_VARIANT_OPT, m_force_multi, m_node_opt,
     m_pri_node_opt, m_sec_node_opt, m_clust_opt, m_inst_opt, m_node_tags_opt,
     m_pri_node_tags_opt, m_sec_node_tags_opt, m_inst_tags_opt, SELECT_OS_OPT,
     SUBMIT_OPT, DRY_RUN_OPT, PRIORITY_OPT, OSPARAMS_OPT],
    "[-f] <instance>", "Reinstall a stopped instance"),
  'remove': (
    RemoveInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, SHUTDOWN_TIMEOUT_OPT, IGNORE_FAILURES_OPT, SUBMIT_OPT,
     DRY_RUN_OPT, PRIORITY_OPT],
    "[-f] <instance>", "Shuts down the instance and removes it"),
  'rename': (
    RenameInstance,
    [ArgInstance(min=1, max=1), ArgHost(min=1, max=1)],
    [NOIPCHECK_OPT, NONAMECHECK_OPT, SUBMIT_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance> <new_name>", "Rename the instance"),
  'replace-disks': (
    ReplaceDisks, ARGS_ONE_INSTANCE,
    [AUTO_REPLACE_OPT, DISKIDX_OPT, IALLOCATOR_OPT, EARLY_RELEASE_OPT,
     NEW_SECONDARY_OPT, ON_PRIMARY_OPT, ON_SECONDARY_OPT, SUBMIT_OPT,
     DRY_RUN_OPT, PRIORITY_OPT],
    "[-s|-p|-n NODE|-I NAME] <instance>",
    "Replaces all disks for the instance"),
  'modify': (
    SetInstanceParams, ARGS_ONE_INSTANCE,
    [BACKEND_OPT, DISK_OPT, FORCE_OPT, HVOPTS_OPT, NET_OPT, SUBMIT_OPT,
     DISK_TEMPLATE_OPT, SINGLE_NODE_OPT, OS_OPT, FORCE_VARIANT_OPT,
     OSPARAMS_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance>", "Alters the parameters of an instance"),
  'shutdown': (
    GenericManyOps("shutdown", _ShutdownInstance), [ArgInstance()],
    [m_node_opt, m_pri_node_opt, m_sec_node_opt, m_clust_opt,
     m_node_tags_opt, m_pri_node_tags_opt, m_sec_node_tags_opt,
     m_inst_tags_opt, m_inst_opt, m_force_multi, TIMEOUT_OPT, SUBMIT_OPT,
     DRY_RUN_OPT, PRIORITY_OPT, IGNORE_OFFLINE_OPT],
    "<instance>", "Stops an instance"),
  'startup': (
    GenericManyOps("startup", _StartupInstance), [ArgInstance()],
    [FORCE_OPT, m_force_multi, m_node_opt, m_pri_node_opt, m_sec_node_opt,
     m_node_tags_opt, m_pri_node_tags_opt, m_sec_node_tags_opt,
     m_inst_tags_opt, m_clust_opt, m_inst_opt, SUBMIT_OPT, HVOPTS_OPT,
     BACKEND_OPT, DRY_RUN_OPT, PRIORITY_OPT, IGNORE_OFFLINE_OPT],
    "<instance>", "Starts an instance"),
  'reboot': (
    GenericManyOps("reboot", _RebootInstance), [ArgInstance()],
    [m_force_multi, REBOOT_TYPE_OPT, IGNORE_SECONDARIES_OPT, m_node_opt,
     m_pri_node_opt, m_sec_node_opt, m_clust_opt, m_inst_opt, SUBMIT_OPT,
     m_node_tags_opt, m_pri_node_tags_opt, m_sec_node_tags_opt,
     m_inst_tags_opt, SHUTDOWN_TIMEOUT_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance>", "Reboots an instance"),
  'activate-disks': (
    ActivateDisks, ARGS_ONE_INSTANCE,
    [SUBMIT_OPT, IGNORE_SIZE_OPT, PRIORITY_OPT],
    "<instance>", "Activate an instance's disks"),
  'deactivate-disks': (
    DeactivateDisks, ARGS_ONE_INSTANCE,
    [SUBMIT_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance>", "Deactivate an instance's disks"),
  'recreate-disks': (
    RecreateDisks, ARGS_ONE_INSTANCE,
    [SUBMIT_OPT, DISKIDX_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance>", "Recreate an instance's disks"),
  'grow-disk': (
    GrowDisk,
    [ArgInstance(min=1, max=1), ArgUnknown(min=1, max=1),
     ArgUnknown(min=1, max=1)],
    [SUBMIT_OPT, NWSYNC_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "<instance> <disk> <size>", "Grow an instance's disk"),
  'list-tags': (
    ListTags, ARGS_ONE_INSTANCE, [PRIORITY_OPT],
    "<instance_name>", "List the tags of the given instance"),
  'add-tags': (
    AddTags, [ArgInstance(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT],
    "<instance_name> tag...", "Add tags to the given instance"),
  'remove-tags': (
    RemoveTags, [ArgInstance(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT],
    "<instance_name> tag...", "Remove tags from given instance"),
  }

#: dictionary with aliases for commands
aliases = {
  'start': 'startup',
  'stop': 'shutdown',
  }


def Main():
  return GenericMain(commands, aliases=aliases,
                     override={"tag_type": constants.TAG_INSTANCE})
