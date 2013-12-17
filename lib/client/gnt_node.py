#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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

"""Node related commands"""

# pylint: disable=W0401,W0613,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0613: Unused argument, since all functions follow the same API
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-node

import itertools
import errno

from ganeti.cli import *
from ganeti import cli
from ganeti import bootstrap
from ganeti import opcodes
from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import pathutils
from ganeti import ssh
from ganeti import compat

from ganeti import confd
from ganeti.confd import client as confd_client

#: default list of field for L{ListNodes}
_LIST_DEF_FIELDS = [
  "name", "dtotal", "dfree",
  "mtotal", "mnode", "mfree",
  "pinst_cnt", "sinst_cnt",
  ]


#: Default field list for L{ListVolumes}
_LIST_VOL_DEF_FIELDS = ["node", "phys", "vg", "name", "size", "instance"]


#: default list of field for L{ListStorage}
_LIST_STOR_DEF_FIELDS = [
  constants.SF_NODE,
  constants.SF_TYPE,
  constants.SF_NAME,
  constants.SF_SIZE,
  constants.SF_USED,
  constants.SF_FREE,
  constants.SF_ALLOCATABLE,
  ]


#: default list of power commands
_LIST_POWER_COMMANDS = ["on", "off", "cycle", "status"]


#: headers (and full field list) for L{ListStorage}
_LIST_STOR_HEADERS = {
  constants.SF_NODE: "Node",
  constants.SF_TYPE: "Type",
  constants.SF_NAME: "Name",
  constants.SF_SIZE: "Size",
  constants.SF_USED: "Used",
  constants.SF_FREE: "Free",
  constants.SF_ALLOCATABLE: "Allocatable",
  }


#: User-facing storage unit types
_USER_STORAGE_TYPE = {
  constants.ST_FILE: "file",
  constants.ST_LVM_PV: "lvm-pv",
  constants.ST_LVM_VG: "lvm-vg",
  constants.ST_SHARED_FILE: "sharedfile",
  }

_STORAGE_TYPE_OPT = \
  cli_option("-t", "--storage-type",
             dest="user_storage_type",
             choices=_USER_STORAGE_TYPE.keys(),
             default=None,
             metavar="STORAGE_TYPE",
             help=("Storage type (%s)" %
                   utils.CommaJoin(_USER_STORAGE_TYPE.keys())))

_REPAIRABLE_STORAGE_TYPES = \
  [st for st, so in constants.VALID_STORAGE_OPERATIONS.iteritems()
   if constants.SO_FIX_CONSISTENCY in so]

_MODIFIABLE_STORAGE_TYPES = constants.MODIFIABLE_STORAGE_FIELDS.keys()

_OOB_COMMAND_ASK = compat.UniqueFrozenset([
  constants.OOB_POWER_OFF,
  constants.OOB_POWER_CYCLE,
  ])

_ENV_OVERRIDE = compat.UniqueFrozenset(["list"])

NONODE_SETUP_OPT = cli_option("--no-node-setup", default=True,
                              action="store_false", dest="node_setup",
                              help=("Do not make initial SSH setup on remote"
                                    " node (needs to be done manually)"))

IGNORE_STATUS_OPT = cli_option("--ignore-status", default=False,
                               action="store_true", dest="ignore_status",
                               help=("Ignore the Node(s) offline status"
                                     " (potentially DANGEROUS)"))


def ConvertStorageType(user_storage_type):
  """Converts a user storage type to its internal name.

  """
  try:
    return _USER_STORAGE_TYPE[user_storage_type]
  except KeyError:
    raise errors.OpPrereqError("Unknown storage type: %s" % user_storage_type,
                               errors.ECODE_INVAL)


def _TryReadFile(path):
  """Tries to read a file.

  If the file is not found, C{None} is returned.

  @type path: string
  @param path: Filename
  @rtype: None or string
  @todo: Consider adding a generic ENOENT wrapper

  """
  try:
    return utils.ReadFile(path)
  except EnvironmentError, err:
    if err.errno == errno.ENOENT:
      return None
    else:
      raise


def _ReadSshKeys(keyfiles, _tostderr_fn=ToStderr):
  """Reads SSH keys according to C{keyfiles}.

  @type keyfiles: dict
  @param keyfiles: Dictionary with keys of L{constants.SSHK_ALL} and two-values
    tuples (private and public key file)
  @rtype: list
  @return: List of three-values tuples (L{constants.SSHK_ALL}, private and
    public key as strings)

  """
  result = []

  for (kind, (private_file, public_file)) in keyfiles.items():
    private_key = _TryReadFile(private_file)
    public_key = _TryReadFile(public_file)

    if public_key and private_key:
      result.append((kind, private_key, public_key))
    elif public_key or private_key:
      _tostderr_fn("Couldn't find a complete set of keys for kind '%s'; files"
                   " '%s' and '%s'", kind, private_file, public_file)

  return result


def _SetupSSH(options, cluster_name, node, ssh_port):
  """Configures a destination node's SSH daemon.

  @param options: Command line options
  @type cluster_name
  @param cluster_name: Cluster name
  @type node: string
  @param node: Destination node name
  @type ssh_port: int
  @param ssh_port: Destination node ssh port

  """
  if options.force_join:
    ToStderr("The \"--force-join\" option is no longer supported and will be"
             " ignored.")

  host_keys = _ReadSshKeys(constants.SSH_DAEMON_KEYFILES)

  (_, root_keyfiles) = \
    ssh.GetAllUserFiles(constants.SSH_LOGIN_USER, mkdir=False, dircheck=False)

  root_keys = _ReadSshKeys(root_keyfiles)

  (_, cert_pem) = \
    utils.ExtractX509Certificate(utils.ReadFile(pathutils.NODED_CERT_FILE))

  data = {
    constants.SSHS_CLUSTER_NAME: cluster_name,
    constants.SSHS_NODE_DAEMON_CERTIFICATE: cert_pem,
    constants.SSHS_SSH_HOST_KEY: host_keys,
    constants.SSHS_SSH_ROOT_KEY: root_keys,
    }

  bootstrap.RunNodeSetupCmd(cluster_name, node, pathutils.PREPARE_NODE_JOIN,
                            options.debug, options.verbose, False,
                            options.ssh_key_check, options.ssh_key_check,
                            ssh_port, data)


@UsesRPC
def AddNode(opts, args):
  """Add a node to the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the new node name
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  query_cl = GetClient(query=True)
  node = netutils.GetHostname(name=args[0]).name
  readd = opts.readd

  # Retrieve relevant parameters of the node group.
  ssh_port = None
  try:
    # Passing [] to QueryGroups means query the default group:
    node_groups = [opts.nodegroup] if opts.nodegroup is not None else []
    output = query_cl.QueryGroups(names=node_groups, fields=["ndp/ssh_port"],
                                  use_locking=False)
    (ssh_port, ) = output[0]
  except (errors.OpPrereqError, errors.OpExecError):
    pass

  try:
    output = query_cl.QueryNodes(names=[node],
                                 fields=["name", "sip", "master",
                                         "ndp/ssh_port"],
                                 use_locking=False)
    node_exists, sip, is_master, ssh_port = output[0]
  except (errors.OpPrereqError, errors.OpExecError):
    node_exists = ""
    sip = None

  if readd:
    if not node_exists:
      ToStderr("Node %s not in the cluster"
               " - please retry without '--readd'", node)
      return 1
    if is_master:
      ToStderr("Node %s is the master, cannot readd", node)
      return 1
  else:
    if node_exists:
      ToStderr("Node %s already in the cluster (as %s)"
               " - please retry with '--readd'", node, node_exists)
      return 1
    sip = opts.secondary_ip

  # read the cluster name from the master
  (cluster_name, ) = cl.QueryConfigValues(["cluster_name"])

  if not readd and opts.node_setup:
    ToStderr("-- WARNING -- \n"
             "Performing this operation is going to replace the ssh daemon"
             " keypair\n"
             "on the target machine (%s) with the ones of the"
             " current one\n"
             "and grant full intra-cluster ssh root access to/from it\n", node)

  if opts.node_setup:
    _SetupSSH(opts, cluster_name, node, ssh_port)

  bootstrap.SetupNodeDaemon(opts, cluster_name, node, ssh_port)

  if opts.disk_state:
    disk_state = utils.FlatToDict(opts.disk_state)
  else:
    disk_state = {}

  hv_state = dict(opts.hv_state)

  op = opcodes.OpNodeAdd(node_name=args[0], secondary_ip=sip,
                         readd=opts.readd, group=opts.nodegroup,
                         vm_capable=opts.vm_capable, ndparams=opts.ndparams,
                         master_capable=opts.master_capable,
                         disk_state=disk_state,
                         hv_state=hv_state)
  SubmitOpCode(op, opts=opts)


def ListNodes(opts, args):
  """List nodes and their properties.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: nodes to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)

  fmtoverride = dict.fromkeys(["pinst_list", "sinst_list", "tags"],
                              (",".join, False))

  cl = GetClient(query=True)

  return GenericList(constants.QR_NODE, selected_fields, args, opts.units,
                     opts.separator, not opts.no_headers,
                     format_override=fmtoverride, verbose=opts.verbose,
                     force_filter=opts.force_filter, cl=cl)


def ListNodeFields(opts, args):
  """List node fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient(query=True)

  return GenericListFields(constants.QR_NODE, args, opts.separator,
                           not opts.no_headers, cl=cl)


def EvacuateNode(opts, args):
  """Relocate all secondary instance from a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  if opts.dst_node is not None:
    ToStderr("New secondary node given (disabling iallocator), hence evacuating"
             " secondary instances only.")
    opts.secondary_only = True
    opts.primary_only = False

  if opts.secondary_only and opts.primary_only:
    raise errors.OpPrereqError("Only one of the --primary-only and"
                               " --secondary-only options can be passed",
                               errors.ECODE_INVAL)
  elif opts.primary_only:
    mode = constants.NODE_EVAC_PRI
  elif opts.secondary_only:
    mode = constants.NODE_EVAC_SEC
  else:
    mode = constants.NODE_EVAC_ALL

  # Determine affected instances
  fields = []

  if not opts.secondary_only:
    fields.append("pinst_list")
  if not opts.primary_only:
    fields.append("sinst_list")

  cl = GetClient()

  qcl = GetClient(query=True)
  result = qcl.QueryNodes(names=args, fields=fields, use_locking=False)
  qcl.Close()

  instances = set(itertools.chain(*itertools.chain(*itertools.chain(result))))

  if not instances:
    # No instances to evacuate
    ToStderr("No instances to evacuate on node(s) %s, exiting.",
             utils.CommaJoin(args))
    return constants.EXIT_SUCCESS

  if not (opts.force or
          AskUser("Relocate instance(s) %s from node(s) %s?" %
                  (utils.CommaJoin(utils.NiceSort(instances)),
                   utils.CommaJoin(args)))):
    return constants.EXIT_CONFIRMATION

  # Evacuate node
  op = opcodes.OpNodeEvacuate(node_name=args[0], mode=mode,
                              remote_node=opts.dst_node,
                              iallocator=opts.iallocator,
                              early_release=opts.early_release)
  result = SubmitOrSend(op, opts, cl=cl)

  # Keep track of submitted jobs
  jex = JobExecutor(cl=cl, opts=opts)

  for (status, job_id) in result[constants.JOB_IDS_KEY]:
    jex.AddJobId(None, status, job_id)

  results = jex.GetResults()
  bad_cnt = len([row for row in results if not row[0]])
  if bad_cnt == 0:
    ToStdout("All instances evacuated successfully.")
    rcode = constants.EXIT_SUCCESS
  else:
    ToStdout("There were %s errors during the evacuation.", bad_cnt)
    rcode = constants.EXIT_FAILURE

  return rcode


def FailoverNode(opts, args):
  """Failover all primary instance on a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  force = opts.force
  selected_fields = ["name", "pinst_list"]

  # these fields are static data anyway, so it doesn't matter, but
  # locking=True should be safer
  qcl = GetClient(query=True)
  result = qcl.QueryNodes(names=args, fields=selected_fields,
                          use_locking=False)
  qcl.Close()
  node, pinst = result[0]

  if not pinst:
    ToStderr("No primary instances on node %s, exiting.", node)
    return 0

  pinst = utils.NiceSort(pinst)

  retcode = 0

  if not force and not AskUser("Fail over instance(s) %s?" %
                               (",".join("'%s'" % name for name in pinst))):
    return 2

  jex = JobExecutor(cl=cl, opts=opts)
  for iname in pinst:
    op = opcodes.OpInstanceFailover(instance_name=iname,
                                    ignore_consistency=opts.ignore_consistency,
                                    iallocator=opts.iallocator)
    jex.QueueJob(iname, op)
  results = jex.GetResults()
  bad_cnt = len([row for row in results if not row[0]])
  if bad_cnt == 0:
    ToStdout("All %d instance(s) failed over successfully.", len(results))
  else:
    ToStdout("There were errors during the failover:\n"
             "%d error(s) out of %d instance(s).", bad_cnt, len(results))
  return retcode


def MigrateNode(opts, args):
  """Migrate all primary instance on a node.

  """
  cl = GetClient()
  force = opts.force
  selected_fields = ["name", "pinst_list"]

  qcl = GetClient(query=True)
  result = qcl.QueryNodes(names=args, fields=selected_fields, use_locking=False)
  qcl.Close()
  ((node, pinst), ) = result

  if not pinst:
    ToStdout("No primary instances on node %s, exiting." % node)
    return 0

  pinst = utils.NiceSort(pinst)

  if not (force or
          AskUser("Migrate instance(s) %s?" %
                  utils.CommaJoin(utils.NiceSort(pinst)))):
    return constants.EXIT_CONFIRMATION

  # this should be removed once --non-live is deprecated
  if not opts.live and opts.migration_mode is not None:
    raise errors.OpPrereqError("Only one of the --non-live and "
                               "--migration-mode options can be passed",
                               errors.ECODE_INVAL)
  if not opts.live: # --non-live passed
    mode = constants.HT_MIGRATION_NONLIVE
  else:
    mode = opts.migration_mode

  op = opcodes.OpNodeMigrate(node_name=args[0], mode=mode,
                             iallocator=opts.iallocator,
                             target_node=opts.dst_node,
                             allow_runtime_changes=opts.allow_runtime_chgs,
                             ignore_ipolicy=opts.ignore_ipolicy)

  result = SubmitOrSend(op, opts, cl=cl)

  # Keep track of submitted jobs
  jex = JobExecutor(cl=cl, opts=opts)

  for (status, job_id) in result[constants.JOB_IDS_KEY]:
    jex.AddJobId(None, status, job_id)

  results = jex.GetResults()
  bad_cnt = len([row for row in results if not row[0]])
  if bad_cnt == 0:
    ToStdout("All instances migrated successfully.")
    rcode = constants.EXIT_SUCCESS
  else:
    ToStdout("There were %s errors during the node migration.", bad_cnt)
    rcode = constants.EXIT_FAILURE

  return rcode


def _FormatNodeInfo(node_info):
  """Format node information for L{cli.PrintGenericInfo()}.

  """
  (name, primary_ip, secondary_ip, pinst, sinst, is_mc, drained, offline,
   master_capable, vm_capable, powered, ndparams, ndparams_custom) = node_info
  info = [
    ("Node name", name),
    ("primary ip", primary_ip),
    ("secondary ip", secondary_ip),
    ("master candidate", is_mc),
    ("drained", drained),
    ("offline", offline),
    ]
  if powered is not None:
    info.append(("powered", powered))
  info.extend([
    ("master_capable", master_capable),
    ("vm_capable", vm_capable),
    ])
  if vm_capable:
    info.extend([
      ("primary for instances",
       [iname for iname in utils.NiceSort(pinst)]),
      ("secondary for instances",
       [iname for iname in utils.NiceSort(sinst)]),
      ])
  info.append(("node parameters",
               FormatParamsDictInfo(ndparams_custom, ndparams)))
  return info


def ShowNodeConfig(opts, args):
  """Show node information.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should either be an empty list, in which case
      we show information about all nodes, or should contain
      a list of nodes to be queried for information
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient(query=True)
  result = cl.QueryNodes(fields=["name", "pip", "sip",
                                 "pinst_list", "sinst_list",
                                 "master_candidate", "drained", "offline",
                                 "master_capable", "vm_capable", "powered",
                                 "ndparams", "custom_ndparams"],
                         names=args, use_locking=False)
  PrintGenericInfo([
    _FormatNodeInfo(node_info)
    for node_info in result
    ])
  return 0


def RemoveNode(opts, args):
  """Remove a node from the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of
      the node to be removed
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpNodeRemove(node_name=args[0])
  SubmitOpCode(op, opts=opts)
  return 0


def PowercycleNode(opts, args):
  """Remove a node from the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of
      the node to be removed
  @rtype: int
  @return: the desired exit code

  """
  node = args[0]
  if (not opts.confirm and
      not AskUser("Are you sure you want to hard powercycle node %s?" % node)):
    return 2

  op = opcodes.OpNodePowercycle(node_name=node, force=opts.force)
  result = SubmitOrSend(op, opts)
  if result:
    ToStderr(result)
  return 0


def PowerNode(opts, args):
  """Change/ask power state of a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of
      the node to be removed
  @rtype: int
  @return: the desired exit code

  """
  command = args.pop(0)

  if opts.no_headers:
    headers = None
  else:
    headers = {"node": "Node", "status": "Status"}

  if command not in _LIST_POWER_COMMANDS:
    ToStderr("power subcommand %s not supported." % command)
    return constants.EXIT_FAILURE

  oob_command = "power-%s" % command

  if oob_command in _OOB_COMMAND_ASK:
    if not args:
      ToStderr("Please provide at least one node for this command")
      return constants.EXIT_FAILURE
    elif not opts.force and not ConfirmOperation(args, "nodes",
                                                 "power %s" % command):
      return constants.EXIT_FAILURE
    assert len(args) > 0

  opcodelist = []
  if not opts.ignore_status and oob_command == constants.OOB_POWER_OFF:
    # TODO: This is a little ugly as we can't catch and revert
    for node in args:
      opcodelist.append(opcodes.OpNodeSetParams(node_name=node, offline=True,
                                                auto_promote=opts.auto_promote))

  opcodelist.append(opcodes.OpOobCommand(node_names=args,
                                         command=oob_command,
                                         ignore_status=opts.ignore_status,
                                         timeout=opts.oob_timeout,
                                         power_delay=opts.power_delay))

  cli.SetGenericOpcodeOpts(opcodelist, opts)

  job_id = cli.SendJob(opcodelist)

  # We just want the OOB Opcode status
  # If it fails PollJob gives us the error message in it
  result = cli.PollJob(job_id)[-1]

  errs = 0
  data = []
  for node_result in result:
    (node_tuple, data_tuple) = node_result
    (_, node_name) = node_tuple
    (data_status, data_node) = data_tuple
    if data_status == constants.RS_NORMAL:
      if oob_command == constants.OOB_POWER_STATUS:
        if data_node[constants.OOB_POWER_STATUS_POWERED]:
          text = "powered"
        else:
          text = "unpowered"
        data.append([node_name, text])
      else:
        # We don't expect data here, so we just say, it was successfully invoked
        data.append([node_name, "invoked"])
    else:
      errs += 1
      data.append([node_name, cli.FormatResultError(data_status, True)])

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=["node", "status"], data=data)

  for line in data:
    ToStdout(line)

  if errs:
    return constants.EXIT_FAILURE
  else:
    return constants.EXIT_SUCCESS


def Health(opts, args):
  """Show health of a node using OOB.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of
      the node to be removed
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpOobCommand(node_names=args, command=constants.OOB_HEALTH,
                            timeout=opts.oob_timeout)
  result = SubmitOpCode(op, opts=opts)

  if opts.no_headers:
    headers = None
  else:
    headers = {"node": "Node", "status": "Status"}

  errs = 0
  data = []
  for node_result in result:
    (node_tuple, data_tuple) = node_result
    (_, node_name) = node_tuple
    (data_status, data_node) = data_tuple
    if data_status == constants.RS_NORMAL:
      data.append([node_name, "%s=%s" % tuple(data_node[0])])
      for item, status in data_node[1:]:
        data.append(["", "%s=%s" % (item, status)])
    else:
      errs += 1
      data.append([node_name, cli.FormatResultError(data_status, True)])

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=["node", "status"], data=data)

  for line in data:
    ToStdout(line)

  if errs:
    return constants.EXIT_FAILURE
  else:
    return constants.EXIT_SUCCESS


def ListVolumes(opts, args):
  """List logical volumes on node(s).

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should either be an empty list, in which case
      we list data for all nodes, or contain a list of nodes
      to display data only for those
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_VOL_DEF_FIELDS)

  op = opcodes.OpNodeQueryvols(nodes=args, output_fields=selected_fields)
  output = SubmitOpCode(op, opts=opts)

  if not opts.no_headers:
    headers = {"node": "Node", "phys": "PhysDev",
               "vg": "VG", "name": "Name",
               "size": "Size", "instance": "Instance"}
  else:
    headers = None

  unitfields = ["size"]

  numfields = ["size"]

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=selected_fields, unitfields=unitfields,
                       numfields=numfields, data=output, units=opts.units)

  for line in data:
    ToStdout(line)

  return 0


def ListStorage(opts, args):
  """List physical volumes on node(s).

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should either be an empty list, in which case
      we list data for all nodes, or contain a list of nodes
      to display data only for those
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_STOR_DEF_FIELDS)

  op = opcodes.OpNodeQueryStorage(nodes=args,
                                  storage_type=opts.user_storage_type,
                                  output_fields=selected_fields)
  output = SubmitOpCode(op, opts=opts)

  if not opts.no_headers:
    headers = {
      constants.SF_NODE: "Node",
      constants.SF_TYPE: "Type",
      constants.SF_NAME: "Name",
      constants.SF_SIZE: "Size",
      constants.SF_USED: "Used",
      constants.SF_FREE: "Free",
      constants.SF_ALLOCATABLE: "Allocatable",
      }
  else:
    headers = None

  unitfields = [constants.SF_SIZE, constants.SF_USED, constants.SF_FREE]
  numfields = [constants.SF_SIZE, constants.SF_USED, constants.SF_FREE]

  # change raw values to nicer strings
  for row in output:
    for idx, field in enumerate(selected_fields):
      val = row[idx]
      if field == constants.SF_ALLOCATABLE:
        if val:
          val = "Y"
        else:
          val = "N"
      row[idx] = str(val)

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=selected_fields, unitfields=unitfields,
                       numfields=numfields, data=output, units=opts.units)

  for line in data:
    ToStdout(line)

  return 0


def ModifyStorage(opts, args):
  """Modify storage volume on a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain 3 items: node name, storage type and volume name
  @rtype: int
  @return: the desired exit code

  """
  (node_name, user_storage_type, volume_name) = args

  storage_type = ConvertStorageType(user_storage_type)

  changes = {}

  if opts.allocatable is not None:
    changes[constants.SF_ALLOCATABLE] = opts.allocatable

  if changes:
    op = opcodes.OpNodeModifyStorage(node_name=node_name,
                                     storage_type=storage_type,
                                     name=volume_name,
                                     changes=changes)
    SubmitOrSend(op, opts)
  else:
    ToStderr("No changes to perform, exiting.")


def RepairStorage(opts, args):
  """Repairs a storage volume on a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain 3 items: node name, storage type and volume name
  @rtype: int
  @return: the desired exit code

  """
  (node_name, user_storage_type, volume_name) = args

  storage_type = ConvertStorageType(user_storage_type)

  op = opcodes.OpRepairNodeStorage(node_name=node_name,
                                   storage_type=storage_type,
                                   name=volume_name,
                                   ignore_consistency=opts.ignore_consistency)
  SubmitOrSend(op, opts)


def SetNodeParams(opts, args):
  """Modifies a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the node name
  @rtype: int
  @return: the desired exit code

  """
  all_changes = [opts.master_candidate, opts.drained, opts.offline,
                 opts.master_capable, opts.vm_capable, opts.secondary_ip,
                 opts.ndparams]
  if (all_changes.count(None) == len(all_changes) and
      not (opts.hv_state or opts.disk_state)):
    ToStderr("Please give at least one of the parameters.")
    return 1

  if opts.disk_state:
    disk_state = utils.FlatToDict(opts.disk_state)
  else:
    disk_state = {}

  hv_state = dict(opts.hv_state)

  op = opcodes.OpNodeSetParams(node_name=args[0],
                               master_candidate=opts.master_candidate,
                               offline=opts.offline,
                               drained=opts.drained,
                               master_capable=opts.master_capable,
                               vm_capable=opts.vm_capable,
                               secondary_ip=opts.secondary_ip,
                               force=opts.force,
                               ndparams=opts.ndparams,
                               auto_promote=opts.auto_promote,
                               powered=opts.node_powered,
                               hv_state=hv_state,
                               disk_state=disk_state)

  # even if here we process the result, we allow submit only
  result = SubmitOrSend(op, opts)

  if result:
    ToStdout("Modified node %s", args[0])
    for param, data in result:
      ToStdout(" - %-5s -> %s", param, data)
  return 0


def RestrictedCommand(opts, args):
  """Runs a remote command on node(s).

  @param opts: Command line options selected by user
  @type args: list
  @param args: Command line arguments
  @rtype: int
  @return: Exit code

  """
  cl = GetClient()

  if len(args) > 1 or opts.nodegroup:
    # Expand node names
    nodes = GetOnlineNodes(nodes=args[1:], cl=cl, nodegroup=opts.nodegroup)
  else:
    raise errors.OpPrereqError("Node group or node names must be given",
                               errors.ECODE_INVAL)

  op = opcodes.OpRestrictedCommand(command=args[0], nodes=nodes,
                                   use_locking=opts.do_locking)
  result = SubmitOrSend(op, opts, cl=cl)

  exit_code = constants.EXIT_SUCCESS

  for (node, (status, text)) in zip(nodes, result):
    ToStdout("------------------------------------------------")
    if status:
      if opts.show_machine_names:
        for line in text.splitlines():
          ToStdout("%s: %s", node, line)
      else:
        ToStdout("Node: %s", node)
        ToStdout(text)
    else:
      exit_code = constants.EXIT_FAILURE
      ToStdout(text)

  return exit_code


class ReplyStatus(object):
  """Class holding a reply status for synchronous confd clients.

  """
  def __init__(self):
    self.failure = True
    self.answer = False


def ListDrbd(opts, args):
  """Modifies a node.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the node name
  @rtype: int
  @return: the desired exit code

  """
  if len(args) != 1:
    ToStderr("Please give one (and only one) node.")
    return constants.EXIT_FAILURE

  if not constants.ENABLE_CONFD:
    ToStderr("Error: this command requires confd support, but it has not"
             " been enabled at build time.")
    return constants.EXIT_FAILURE

  status = ReplyStatus()

  def ListDrbdConfdCallback(reply):
    """Callback for confd queries"""
    if reply.type == confd_client.UPCALL_REPLY:
      answer = reply.server_reply.answer
      reqtype = reply.orig_request.type
      if reqtype == constants.CONFD_REQ_NODE_DRBD:
        if reply.server_reply.status != constants.CONFD_REPL_STATUS_OK:
          ToStderr("Query gave non-ok status '%s': %s" %
                   (reply.server_reply.status,
                    reply.server_reply.answer))
          status.failure = True
          return
        if not confd.HTNodeDrbd(answer):
          ToStderr("Invalid response from server: expected %s, got %s",
                   confd.HTNodeDrbd, answer)
          status.failure = True
        else:
          status.failure = False
          status.answer = answer
      else:
        ToStderr("Unexpected reply %s!?", reqtype)
        status.failure = True

  node = args[0]
  hmac = utils.ReadFile(pathutils.CONFD_HMAC_KEY)
  filter_callback = confd_client.ConfdFilterCallback(ListDrbdConfdCallback)
  counting_callback = confd_client.ConfdCountingCallback(filter_callback)
  cf_client = confd_client.ConfdClient(hmac, [constants.IP4_ADDRESS_LOCALHOST],
                                       counting_callback)
  req = confd_client.ConfdClientRequest(type=constants.CONFD_REQ_NODE_DRBD,
                                        query=node)

  def DoConfdRequestReply(req):
    counting_callback.RegisterQuery(req.rsalt)
    cf_client.SendRequest(req, async=False)
    while not counting_callback.AllAnswered():
      if not cf_client.ReceiveReply():
        ToStderr("Did not receive all expected confd replies")
        break

  DoConfdRequestReply(req)

  if status.failure:
    return constants.EXIT_FAILURE

  fields = ["node", "minor", "instance", "disk", "role", "peer"]
  if opts.no_headers:
    headers = None
  else:
    headers = {"node": "Node", "minor": "Minor", "instance": "Instance",
               "disk": "Disk", "role": "Role", "peer": "PeerNode"}

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=fields, data=sorted(status.answer),
                       numfields=["minor"])
  for line in data:
    ToStdout(line)

  return constants.EXIT_SUCCESS


commands = {
  "add": (
    AddNode, [ArgHost(min=1, max=1)],
    [SECONDARY_IP_OPT, READD_OPT, NOSSH_KEYCHECK_OPT, NODE_FORCE_JOIN_OPT,
     NONODE_SETUP_OPT, VERBOSE_OPT, NODEGROUP_OPT, PRIORITY_OPT,
     CAPAB_MASTER_OPT, CAPAB_VM_OPT, NODE_PARAMS_OPT, HV_STATE_OPT,
     DISK_STATE_OPT],
    "[-s ip] [--readd] [--no-ssh-key-check] [--force-join]"
    " [--no-node-setup] [--verbose] [--network] <node_name>",
    "Add a node to the cluster"),
  "evacuate": (
    EvacuateNode, ARGS_ONE_NODE,
    [FORCE_OPT, IALLOCATOR_OPT, NEW_SECONDARY_OPT, EARLY_RELEASE_OPT,
     PRIORITY_OPT, PRIMARY_ONLY_OPT, SECONDARY_ONLY_OPT] + SUBMIT_OPTS,
    "[-f] {-I <iallocator> | -n <dst>} [-p | -s] [options...] <node>",
    "Relocate the primary and/or secondary instances from a node"),
  "failover": (
    FailoverNode, ARGS_ONE_NODE, [FORCE_OPT, IGNORE_CONSIST_OPT,
                                  IALLOCATOR_OPT, PRIORITY_OPT],
    "[-f] <node>",
    "Stops the primary instances on a node and start them on their"
    " secondary node (only for instances with drbd disk template)"),
  "migrate": (
    MigrateNode, ARGS_ONE_NODE,
    [FORCE_OPT, NONLIVE_OPT, MIGRATION_MODE_OPT, DST_NODE_OPT,
     IALLOCATOR_OPT, PRIORITY_OPT, IGNORE_IPOLICY_OPT,
     NORUNTIME_CHGS_OPT] + SUBMIT_OPTS,
    "[-f] <node>",
    "Migrate all the primary instance on a node away from it"
    " (only for instances of type drbd)"),
  "info": (
    ShowNodeConfig, ARGS_MANY_NODES, [],
    "[<node_name>...]", "Show information about the node(s)"),
  "list": (
    ListNodes, ARGS_MANY_NODES,
    [NOHDR_OPT, SEP_OPT, USEUNITS_OPT, FIELDS_OPT, VERBOSE_OPT,
     FORCE_FILTER_OPT],
    "[nodes...]",
    "Lists the nodes in the cluster. The available fields can be shown using"
    " the \"list-fields\" command (see the man page for details)."
    " The default field list is (in order): %s." %
    utils.CommaJoin(_LIST_DEF_FIELDS)),
  "list-fields": (
    ListNodeFields, [ArgUnknown()],
    [NOHDR_OPT, SEP_OPT],
    "[fields...]",
    "Lists all available fields for nodes"),
  "modify": (
    SetNodeParams, ARGS_ONE_NODE,
    [FORCE_OPT] + SUBMIT_OPTS +
    [MC_OPT, DRAINED_OPT, OFFLINE_OPT,
     CAPAB_MASTER_OPT, CAPAB_VM_OPT, SECONDARY_IP_OPT,
     AUTO_PROMOTE_OPT, DRY_RUN_OPT, PRIORITY_OPT, NODE_PARAMS_OPT,
     NODE_POWERED_OPT, HV_STATE_OPT, DISK_STATE_OPT],
    "<node_name>", "Alters the parameters of a node"),
  "powercycle": (
    PowercycleNode, ARGS_ONE_NODE,
    [FORCE_OPT, CONFIRM_OPT, DRY_RUN_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<node_name>", "Tries to forcefully powercycle a node"),
  "power": (
    PowerNode,
    [ArgChoice(min=1, max=1, choices=_LIST_POWER_COMMANDS),
     ArgNode()],
    SUBMIT_OPTS +
    [AUTO_PROMOTE_OPT, PRIORITY_OPT,
     IGNORE_STATUS_OPT, FORCE_OPT, NOHDR_OPT, SEP_OPT, OOB_TIMEOUT_OPT,
     POWER_DELAY_OPT],
    "on|off|cycle|status [nodes...]",
    "Change power state of node by calling out-of-band helper."),
  "remove": (
    RemoveNode, ARGS_ONE_NODE, [DRY_RUN_OPT, PRIORITY_OPT],
    "<node_name>", "Removes a node from the cluster"),
  "volumes": (
    ListVolumes, [ArgNode()],
    [NOHDR_OPT, SEP_OPT, USEUNITS_OPT, FIELDS_OPT, PRIORITY_OPT],
    "[<node_name>...]", "List logical volumes on node(s)"),
  "list-storage": (
    ListStorage, ARGS_MANY_NODES,
    [NOHDR_OPT, SEP_OPT, USEUNITS_OPT, FIELDS_OPT, _STORAGE_TYPE_OPT,
     PRIORITY_OPT],
    "[<node_name>...]", "List physical volumes on node(s). The available"
    " fields are (see the man page for details): %s." %
    (utils.CommaJoin(_LIST_STOR_HEADERS))),
  "modify-storage": (
    ModifyStorage,
    [ArgNode(min=1, max=1),
     ArgChoice(min=1, max=1, choices=_MODIFIABLE_STORAGE_TYPES),
     ArgFile(min=1, max=1)],
    [ALLOCATABLE_OPT, DRY_RUN_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<node_name> <storage_type> <name>", "Modify storage volume on a node"),
  "repair-storage": (
    RepairStorage,
    [ArgNode(min=1, max=1),
     ArgChoice(min=1, max=1, choices=_REPAIRABLE_STORAGE_TYPES),
     ArgFile(min=1, max=1)],
    [IGNORE_CONSIST_OPT, DRY_RUN_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<node_name> <storage_type> <name>",
    "Repairs a storage volume on a node"),
  "list-tags": (
    ListTags, ARGS_ONE_NODE, [],
    "<node_name>", "List the tags of the given node"),
  "add-tags": (
    AddTags, [ArgNode(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<node_name> tag...", "Add tags to the given node"),
  "remove-tags": (
    RemoveTags, [ArgNode(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<node_name> tag...", "Remove tags from the given node"),
  "health": (
    Health, ARGS_MANY_NODES,
    [NOHDR_OPT, SEP_OPT, PRIORITY_OPT, OOB_TIMEOUT_OPT],
    "[<node_name>...]", "List health of node(s) using out-of-band"),
  "list-drbd": (
    ListDrbd, ARGS_ONE_NODE,
    [NOHDR_OPT, SEP_OPT],
    "[<node_name>]", "Query the list of used DRBD minors on the given node"),
  "restricted-command": (
    RestrictedCommand, [ArgUnknown(min=1, max=1)] + ARGS_MANY_NODES,
    [SYNC_OPT, PRIORITY_OPT] + SUBMIT_OPTS + [SHOW_MACHINE_OPT, NODEGROUP_OPT],
    "<command> <node_name> [<node_name>...]",
    "Executes a restricted command on node(s)"),
  }

#: dictionary with aliases for commands
aliases = {
  "show": "info",
  }


def Main():
  return GenericMain(commands, aliases=aliases,
                     override={"tag_type": constants.TAG_NODE},
                     env_override=_ENV_OVERRIDE)
