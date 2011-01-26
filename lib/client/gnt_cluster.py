#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Cluster related commands"""

# pylint: disable-msg=W0401,W0613,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0613: Unused argument, since all functions follow the same API
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-cluster

import os.path
import time
import OpenSSL

from ganeti.cli import *
from ganeti import opcodes
from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import bootstrap
from ganeti import ssh
from ganeti import objects
from ganeti import uidpool
from ganeti import compat


@UsesRPC
def InitCluster(opts, args):
  """Initialize the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the desired
      cluster name
  @rtype: int
  @return: the desired exit code

  """
  if not opts.lvm_storage and opts.vg_name:
    ToStderr("Options --no-lvm-storage and --vg-name conflict.")
    return 1

  vg_name = opts.vg_name
  if opts.lvm_storage and not opts.vg_name:
    vg_name = constants.DEFAULT_VG

  if not opts.drbd_storage and opts.drbd_helper:
    ToStderr("Options --no-drbd-storage and --drbd-usermode-helper conflict.")
    return 1

  drbd_helper = opts.drbd_helper
  if opts.drbd_storage and not opts.drbd_helper:
    drbd_helper = constants.DEFAULT_DRBD_HELPER

  master_netdev = opts.master_netdev
  if master_netdev is None:
    master_netdev = constants.DEFAULT_BRIDGE

  hvlist = opts.enabled_hypervisors
  if hvlist is None:
    hvlist = constants.DEFAULT_ENABLED_HYPERVISOR
  hvlist = hvlist.split(",")

  hvparams = dict(opts.hvparams)
  beparams = opts.beparams
  nicparams = opts.nicparams

  # prepare beparams dict
  beparams = objects.FillDict(constants.BEC_DEFAULTS, beparams)
  utils.ForceDictType(beparams, constants.BES_PARAMETER_TYPES)

  # prepare nicparams dict
  nicparams = objects.FillDict(constants.NICC_DEFAULTS, nicparams)
  utils.ForceDictType(nicparams, constants.NICS_PARAMETER_TYPES)

  # prepare ndparams dict
  if opts.ndparams is None:
    ndparams = dict(constants.NDC_DEFAULTS)
  else:
    ndparams = objects.FillDict(constants.NDC_DEFAULTS, opts.ndparams)
    utils.ForceDictType(ndparams, constants.NDS_PARAMETER_TYPES)

  # prepare hvparams dict
  for hv in constants.HYPER_TYPES:
    if hv not in hvparams:
      hvparams[hv] = {}
    hvparams[hv] = objects.FillDict(constants.HVC_DEFAULTS[hv], hvparams[hv])
    utils.ForceDictType(hvparams[hv], constants.HVS_PARAMETER_TYPES)

  if opts.candidate_pool_size is None:
    opts.candidate_pool_size = constants.MASTER_POOL_SIZE_DEFAULT

  if opts.mac_prefix is None:
    opts.mac_prefix = constants.DEFAULT_MAC_PREFIX

  uid_pool = opts.uid_pool
  if uid_pool is not None:
    uid_pool = uidpool.ParseUidPool(uid_pool)

  if opts.prealloc_wipe_disks is None:
    opts.prealloc_wipe_disks = False

  try:
    primary_ip_version = int(opts.primary_ip_version)
  except (ValueError, TypeError), err:
    ToStderr("Invalid primary ip version value: %s" % str(err))
    return 1

  bootstrap.InitCluster(cluster_name=args[0],
                        secondary_ip=opts.secondary_ip,
                        vg_name=vg_name,
                        mac_prefix=opts.mac_prefix,
                        master_netdev=master_netdev,
                        file_storage_dir=opts.file_storage_dir,
                        enabled_hypervisors=hvlist,
                        hvparams=hvparams,
                        beparams=beparams,
                        nicparams=nicparams,
                        ndparams=ndparams,
                        candidate_pool_size=opts.candidate_pool_size,
                        modify_etc_hosts=opts.modify_etc_hosts,
                        modify_ssh_setup=opts.modify_ssh_setup,
                        maintain_node_health=opts.maintain_node_health,
                        drbd_helper=drbd_helper,
                        uid_pool=uid_pool,
                        default_iallocator=opts.default_iallocator,
                        primary_ip_version=primary_ip_version,
                        prealloc_wipe_disks=opts.prealloc_wipe_disks,
                        )
  op = opcodes.OpClusterPostInit()
  SubmitOpCode(op, opts=opts)
  return 0


@UsesRPC
def DestroyCluster(opts, args):
  """Destroy the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  if not opts.yes_do_it:
    ToStderr("Destroying a cluster is irreversible. If you really want"
             " destroy this cluster, supply the --yes-do-it option.")
    return 1

  op = opcodes.OpClusterDestroy()
  master = SubmitOpCode(op, opts=opts)
  # if we reached this, the opcode didn't fail; we can proceed to
  # shutdown all the daemons
  bootstrap.FinalizeClusterDestroy(master)
  return 0


def RenameCluster(opts, args):
  """Rename the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the new cluster name
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  (cluster_name, ) = cl.QueryConfigValues(["cluster_name"])

  new_name = args[0]
  if not opts.force:
    usertext = ("This will rename the cluster from '%s' to '%s'. If you are"
                " connected over the network to the cluster name, the"
                " operation is very dangerous as the IP address will be"
                " removed from the node and the change may not go through."
                " Continue?") % (cluster_name, new_name)
    if not AskUser(usertext):
      return 1

  op = opcodes.OpClusterRename(name=new_name)
  result = SubmitOpCode(op, opts=opts, cl=cl)

  if result:
    ToStdout("Cluster renamed from '%s' to '%s'", cluster_name, result)

  return 0


def RedistributeConfig(opts, args):
  """Forces push of the cluster configuration.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: empty list
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpClusterRedistConf()
  SubmitOrSend(op, opts)
  return 0


def ShowClusterVersion(opts, args):
  """Write version of ganeti software to the standard output.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  result = cl.QueryClusterInfo()
  ToStdout("Software version: %s", result["software_version"])
  ToStdout("Internode protocol: %s", result["protocol_version"])
  ToStdout("Configuration format: %s", result["config_version"])
  ToStdout("OS api version: %s", result["os_api_version"])
  ToStdout("Export interface: %s", result["export_version"])
  return 0


def ShowClusterMaster(opts, args):
  """Write name of master node to the standard output.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  master = bootstrap.GetMaster()
  ToStdout(master)
  return 0


def _PrintGroupedParams(paramsdict, level=1, roman=False):
  """Print Grouped parameters (be, nic, disk) by group.

  @type paramsdict: dict of dicts
  @param paramsdict: {group: {param: value, ...}, ...}
  @type level: int
  @param level: Level of indention

  """
  indent = "  " * level
  for item, val in sorted(paramsdict.items()):
    if isinstance(val, dict):
      ToStdout("%s- %s:", indent, item)
      _PrintGroupedParams(val, level=level + 1, roman=roman)
    elif roman and isinstance(val, int):
      ToStdout("%s  %s: %s", indent, item, compat.TryToRoman(val))
    else:
      ToStdout("%s  %s: %s", indent, item, val)


def ShowClusterConfig(opts, args):
  """Shows cluster information.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  result = cl.QueryClusterInfo()

  ToStdout("Cluster name: %s", result["name"])
  ToStdout("Cluster UUID: %s", result["uuid"])

  ToStdout("Creation time: %s", utils.FormatTime(result["ctime"]))
  ToStdout("Modification time: %s", utils.FormatTime(result["mtime"]))

  ToStdout("Master node: %s", result["master"])

  ToStdout("Architecture (this node): %s (%s)",
           result["architecture"][0], result["architecture"][1])

  if result["tags"]:
    tags = utils.CommaJoin(utils.NiceSort(result["tags"]))
  else:
    tags = "(none)"

  ToStdout("Tags: %s", tags)

  ToStdout("Default hypervisor: %s", result["default_hypervisor"])
  ToStdout("Enabled hypervisors: %s",
           utils.CommaJoin(result["enabled_hypervisors"]))

  ToStdout("Hypervisor parameters:")
  _PrintGroupedParams(result["hvparams"])

  ToStdout("OS-specific hypervisor parameters:")
  _PrintGroupedParams(result["os_hvp"])

  ToStdout("OS parameters:")
  _PrintGroupedParams(result["osparams"])

  ToStdout("Hidden OSes: %s", utils.CommaJoin(result["hidden_os"]))
  ToStdout("Blacklisted OSes: %s", utils.CommaJoin(result["blacklisted_os"]))

  ToStdout("Cluster parameters:")
  ToStdout("  - candidate pool size: %s",
            compat.TryToRoman(result["candidate_pool_size"],
                              convert=opts.roman_integers))
  ToStdout("  - master netdev: %s", result["master_netdev"])
  ToStdout("  - lvm volume group: %s", result["volume_group_name"])
  if result["reserved_lvs"]:
    reserved_lvs = utils.CommaJoin(result["reserved_lvs"])
  else:
    reserved_lvs = "(none)"
  ToStdout("  - lvm reserved volumes: %s", reserved_lvs)
  ToStdout("  - drbd usermode helper: %s", result["drbd_usermode_helper"])
  ToStdout("  - file storage path: %s", result["file_storage_dir"])
  ToStdout("  - maintenance of node health: %s",
           result["maintain_node_health"])
  ToStdout("  - uid pool: %s",
            uidpool.FormatUidPool(result["uid_pool"],
                                  roman=opts.roman_integers))
  ToStdout("  - default instance allocator: %s", result["default_iallocator"])
  ToStdout("  - primary ip version: %d", result["primary_ip_version"])
  ToStdout("  - preallocation wipe disks: %s", result["prealloc_wipe_disks"])

  ToStdout("Default node parameters:")
  _PrintGroupedParams(result["ndparams"], roman=opts.roman_integers)

  ToStdout("Default instance parameters:")
  _PrintGroupedParams(result["beparams"], roman=opts.roman_integers)

  ToStdout("Default nic parameters:")
  _PrintGroupedParams(result["nicparams"], roman=opts.roman_integers)

  return 0


def ClusterCopyFile(opts, args):
  """Copy a file from master to some nodes.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the path of
      the file to be copied
  @rtype: int
  @return: the desired exit code

  """
  filename = args[0]
  if not os.path.exists(filename):
    raise errors.OpPrereqError("No such filename '%s'" % filename,
                               errors.ECODE_INVAL)

  cl = GetClient()

  cluster_name = cl.QueryConfigValues(["cluster_name"])[0]

  results = GetOnlineNodes(nodes=opts.nodes, cl=cl, filter_master=True,
                           secondary_ips=opts.use_replication_network)

  srun = ssh.SshRunner(cluster_name=cluster_name)
  for node in results:
    if not srun.CopyFileToNode(node, filename):
      ToStderr("Copy of file %s to node %s failed", filename, node)

  return 0


def RunClusterCommand(opts, args):
  """Run a command on some nodes.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain the command to be run and its arguments
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  command = " ".join(args)

  nodes = GetOnlineNodes(nodes=opts.nodes, cl=cl)

  cluster_name, master_node = cl.QueryConfigValues(["cluster_name",
                                                    "master_node"])

  srun = ssh.SshRunner(cluster_name=cluster_name)

  # Make sure master node is at list end
  if master_node in nodes:
    nodes.remove(master_node)
    nodes.append(master_node)

  for name in nodes:
    result = srun.Run(name, "root", command)
    ToStdout("------------------------------------------------")
    ToStdout("node: %s", name)
    ToStdout("%s", result.output)
    ToStdout("return code = %s", result.exit_code)

  return 0


def VerifyCluster(opts, args):
  """Verify integrity of cluster, performing various test on nodes.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  skip_checks = []
  if opts.skip_nplusone_mem:
    skip_checks.append(constants.VERIFY_NPLUSONE_MEM)
  op = opcodes.OpClusterVerify(skip_checks=skip_checks,
                               verbose=opts.verbose,
                               error_codes=opts.error_codes,
                               debug_simulate_errors=opts.simulate_errors)
  if SubmitOpCode(op, opts=opts):
    return 0
  else:
    return 1


def VerifyDisks(opts, args):
  """Verify integrity of cluster disks.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  op = opcodes.OpClusterVerifyDisks()
  result = SubmitOpCode(op, opts=opts, cl=cl)
  if not isinstance(result, (list, tuple)) or len(result) != 3:
    raise errors.ProgrammerError("Unknown result type for OpClusterVerifyDisks")

  bad_nodes, instances, missing = result

  retcode = constants.EXIT_SUCCESS

  if bad_nodes:
    for node, text in bad_nodes.items():
      ToStdout("Error gathering data on node %s: %s",
               node, utils.SafeEncode(text[-400:]))
      retcode |= 1
      ToStdout("You need to fix these nodes first before fixing instances")

  if instances:
    for iname in instances:
      if iname in missing:
        continue
      op = opcodes.OpInstanceActivateDisks(instance_name=iname)
      try:
        ToStdout("Activating disks for instance '%s'", iname)
        SubmitOpCode(op, opts=opts, cl=cl)
      except errors.GenericError, err:
        nret, msg = FormatError(err)
        retcode |= nret
        ToStderr("Error activating disks for instance %s: %s", iname, msg)

  if missing:
    (vg_name, ) = cl.QueryConfigValues(["volume_group_name"])

    for iname, ival in missing.iteritems():
      all_missing = compat.all(x[0] in bad_nodes for x in ival)
      if all_missing:
        ToStdout("Instance %s cannot be verified as it lives on"
                 " broken nodes", iname)
      else:
        ToStdout("Instance %s has missing logical volumes:", iname)
        ival.sort()
        for node, vol in ival:
          if node in bad_nodes:
            ToStdout("\tbroken node %s /dev/%s/%s", node, vg_name, vol)
          else:
            ToStdout("\t%s /dev/%s/%s", node, vg_name, vol)

    ToStdout("You need to run replace_disks for all the above"
             " instances, if this message persist after fixing nodes.")
    retcode |= 1

  return retcode


def RepairDiskSizes(opts, args):
  """Verify sizes of cluster disks.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: optional list of instances to restrict check to
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpClusterRepairDiskSizes(instances=args)
  SubmitOpCode(op, opts=opts)


@UsesRPC
def MasterFailover(opts, args):
  """Failover the master node.

  This command, when run on a non-master node, will cause the current
  master to cease being master, and the non-master to become new
  master.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  if opts.no_voting:
    usertext = ("This will perform the failover even if most other nodes"
                " are down, or if this node is outdated. This is dangerous"
                " as it can lead to a non-consistent cluster. Check the"
                " gnt-cluster(8) man page before proceeding. Continue?")
    if not AskUser(usertext):
      return 1

  return bootstrap.MasterFailover(no_voting=opts.no_voting)


def MasterPing(opts, args):
  """Checks if the master is alive.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  try:
    cl = GetClient()
    cl.QueryClusterInfo()
    return 0
  except Exception: # pylint: disable-msg=W0703
    return 1


def SearchTags(opts, args):
  """Searches the tags on all the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the tag pattern
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpTagsSearch(pattern=args[0])
  result = SubmitOpCode(op, opts=opts)
  if not result:
    return 1
  result = list(result)
  result.sort()
  for path, tag in result:
    ToStdout("%s %s", path, tag)


def _RenewCrypto(new_cluster_cert, new_rapi_cert, rapi_cert_filename,
                 new_confd_hmac_key, new_cds, cds_filename,
                 force):
  """Renews cluster certificates, keys and secrets.

  @type new_cluster_cert: bool
  @param new_cluster_cert: Whether to generate a new cluster certificate
  @type new_rapi_cert: bool
  @param new_rapi_cert: Whether to generate a new RAPI certificate
  @type rapi_cert_filename: string
  @param rapi_cert_filename: Path to file containing new RAPI certificate
  @type new_confd_hmac_key: bool
  @param new_confd_hmac_key: Whether to generate a new HMAC key
  @type new_cds: bool
  @param new_cds: Whether to generate a new cluster domain secret
  @type cds_filename: string
  @param cds_filename: Path to file containing new cluster domain secret
  @type force: bool
  @param force: Whether to ask user for confirmation

  """
  if new_rapi_cert and rapi_cert_filename:
    ToStderr("Only one of the --new-rapi-certficate and --rapi-certificate"
             " options can be specified at the same time.")
    return 1

  if new_cds and cds_filename:
    ToStderr("Only one of the --new-cluster-domain-secret and"
             " --cluster-domain-secret options can be specified at"
             " the same time.")
    return 1

  if rapi_cert_filename:
    # Read and verify new certificate
    try:
      rapi_cert_pem = utils.ReadFile(rapi_cert_filename)

      OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                      rapi_cert_pem)
    except Exception, err: # pylint: disable-msg=W0703
      ToStderr("Can't load new RAPI certificate from %s: %s" %
               (rapi_cert_filename, str(err)))
      return 1

    try:
      OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, rapi_cert_pem)
    except Exception, err: # pylint: disable-msg=W0703
      ToStderr("Can't load new RAPI private key from %s: %s" %
               (rapi_cert_filename, str(err)))
      return 1

  else:
    rapi_cert_pem = None

  if cds_filename:
    try:
      cds = utils.ReadFile(cds_filename)
    except Exception, err: # pylint: disable-msg=W0703
      ToStderr("Can't load new cluster domain secret from %s: %s" %
               (cds_filename, str(err)))
      return 1
  else:
    cds = None

  if not force:
    usertext = ("This requires all daemons on all nodes to be restarted and"
                " may take some time. Continue?")
    if not AskUser(usertext):
      return 1

  def _RenewCryptoInner(ctx):
    ctx.feedback_fn("Updating certificates and keys")
    bootstrap.GenerateClusterCrypto(new_cluster_cert, new_rapi_cert,
                                    new_confd_hmac_key,
                                    new_cds,
                                    rapi_cert_pem=rapi_cert_pem,
                                    cds=cds)

    files_to_copy = []

    if new_cluster_cert:
      files_to_copy.append(constants.NODED_CERT_FILE)

    if new_rapi_cert or rapi_cert_pem:
      files_to_copy.append(constants.RAPI_CERT_FILE)

    if new_confd_hmac_key:
      files_to_copy.append(constants.CONFD_HMAC_KEY)

    if new_cds or cds:
      files_to_copy.append(constants.CLUSTER_DOMAIN_SECRET_FILE)

    if files_to_copy:
      for node_name in ctx.nonmaster_nodes:
        ctx.feedback_fn("Copying %s to %s" %
                        (", ".join(files_to_copy), node_name))
        for file_name in files_to_copy:
          ctx.ssh.CopyFileToNode(node_name, file_name)

  RunWhileClusterStopped(ToStdout, _RenewCryptoInner)

  ToStdout("All requested certificates and keys have been replaced."
           " Running \"gnt-cluster verify\" now is recommended.")

  return 0


def RenewCrypto(opts, args):
  """Renews cluster certificates, keys and secrets.

  """
  return _RenewCrypto(opts.new_cluster_cert,
                      opts.new_rapi_cert,
                      opts.rapi_cert,
                      opts.new_confd_hmac_key,
                      opts.new_cluster_domain_secret,
                      opts.cluster_domain_secret,
                      opts.force)


def SetClusterParams(opts, args):
  """Modify the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  if not (not opts.lvm_storage or opts.vg_name or
          not opts.drbd_storage or opts.drbd_helper or
          opts.enabled_hypervisors or opts.hvparams or
          opts.beparams or opts.nicparams or opts.ndparams or
          opts.candidate_pool_size is not None or
          opts.uid_pool is not None or
          opts.maintain_node_health is not None or
          opts.add_uids is not None or
          opts.remove_uids is not None or
          opts.default_iallocator is not None or
          opts.reserved_lvs is not None or
          opts.master_netdev is not None or
          opts.prealloc_wipe_disks is not None):
    ToStderr("Please give at least one of the parameters.")
    return 1

  vg_name = opts.vg_name
  if not opts.lvm_storage and opts.vg_name:
    ToStderr("Options --no-lvm-storage and --vg-name conflict.")
    return 1

  if not opts.lvm_storage:
    vg_name = ""

  drbd_helper = opts.drbd_helper
  if not opts.drbd_storage and opts.drbd_helper:
    ToStderr("Options --no-drbd-storage and --drbd-usermode-helper conflict.")
    return 1

  if not opts.drbd_storage:
    drbd_helper = ""

  hvlist = opts.enabled_hypervisors
  if hvlist is not None:
    hvlist = hvlist.split(",")

  # a list of (name, dict) we can pass directly to dict() (or [])
  hvparams = dict(opts.hvparams)
  for hv_params in hvparams.values():
    utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)

  beparams = opts.beparams
  utils.ForceDictType(beparams, constants.BES_PARAMETER_TYPES)

  nicparams = opts.nicparams
  utils.ForceDictType(nicparams, constants.NICS_PARAMETER_TYPES)

  ndparams = opts.ndparams
  if ndparams is not None:
    utils.ForceDictType(ndparams, constants.NDS_PARAMETER_TYPES)

  mnh = opts.maintain_node_health

  uid_pool = opts.uid_pool
  if uid_pool is not None:
    uid_pool = uidpool.ParseUidPool(uid_pool)

  add_uids = opts.add_uids
  if add_uids is not None:
    add_uids = uidpool.ParseUidPool(add_uids)

  remove_uids = opts.remove_uids
  if remove_uids is not None:
    remove_uids = uidpool.ParseUidPool(remove_uids)

  if opts.reserved_lvs is not None:
    if opts.reserved_lvs == "":
      opts.reserved_lvs = []
    else:
      opts.reserved_lvs = utils.UnescapeAndSplit(opts.reserved_lvs, sep=",")

  op = opcodes.OpClusterSetParams(vg_name=vg_name,
                                  drbd_helper=drbd_helper,
                                  enabled_hypervisors=hvlist,
                                  hvparams=hvparams,
                                  os_hvp=None,
                                  beparams=beparams,
                                  nicparams=nicparams,
                                  ndparams=ndparams,
                                  candidate_pool_size=opts.candidate_pool_size,
                                  maintain_node_health=mnh,
                                  uid_pool=uid_pool,
                                  add_uids=add_uids,
                                  remove_uids=remove_uids,
                                  default_iallocator=opts.default_iallocator,
                                  prealloc_wipe_disks=opts.prealloc_wipe_disks,
                                  master_netdev=opts.master_netdev,
                                  reserved_lvs=opts.reserved_lvs)
  SubmitOpCode(op, opts=opts)
  return 0


def QueueOps(opts, args):
  """Queue operations.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the subcommand
  @rtype: int
  @return: the desired exit code

  """
  command = args[0]
  client = GetClient()
  if command in ("drain", "undrain"):
    drain_flag = command == "drain"
    client.SetQueueDrainFlag(drain_flag)
  elif command == "info":
    result = client.QueryConfigValues(["drain_flag"])
    if result[0]:
      val = "set"
    else:
      val = "unset"
    ToStdout("The drain flag is %s" % val)
  else:
    raise errors.OpPrereqError("Command '%s' is not valid." % command,
                               errors.ECODE_INVAL)

  return 0


def _ShowWatcherPause(until):
  if until is None or until < time.time():
    ToStdout("The watcher is not paused.")
  else:
    ToStdout("The watcher is paused until %s.", time.ctime(until))


def WatcherOps(opts, args):
  """Watcher operations.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the subcommand
  @rtype: int
  @return: the desired exit code

  """
  command = args[0]
  client = GetClient()

  if command == "continue":
    client.SetWatcherPause(None)
    ToStdout("The watcher is no longer paused.")

  elif command == "pause":
    if len(args) < 2:
      raise errors.OpPrereqError("Missing pause duration", errors.ECODE_INVAL)

    result = client.SetWatcherPause(time.time() + ParseTimespec(args[1]))
    _ShowWatcherPause(result)

  elif command == "info":
    result = client.QueryConfigValues(["watcher_pause"])
    _ShowWatcherPause(result[0])

  else:
    raise errors.OpPrereqError("Command '%s' is not valid." % command,
                               errors.ECODE_INVAL)

  return 0


commands = {
  'init': (
    InitCluster, [ArgHost(min=1, max=1)],
    [BACKEND_OPT, CP_SIZE_OPT, ENABLED_HV_OPT, GLOBAL_FILEDIR_OPT,
     HVLIST_OPT, MAC_PREFIX_OPT, MASTER_NETDEV_OPT, NIC_PARAMS_OPT,
     NOLVM_STORAGE_OPT, NOMODIFY_ETCHOSTS_OPT, NOMODIFY_SSH_SETUP_OPT,
     SECONDARY_IP_OPT, VG_NAME_OPT, MAINTAIN_NODE_HEALTH_OPT,
     UIDPOOL_OPT, DRBD_HELPER_OPT, NODRBD_STORAGE_OPT,
     DEFAULT_IALLOCATOR_OPT, PRIMARY_IP_VERSION_OPT, PREALLOC_WIPE_DISKS_OPT,
     NODE_PARAMS_OPT],
    "[opts...] <cluster_name>", "Initialises a new cluster configuration"),
  'destroy': (
    DestroyCluster, ARGS_NONE, [YES_DOIT_OPT],
    "", "Destroy cluster"),
  'rename': (
    RenameCluster, [ArgHost(min=1, max=1)],
    [FORCE_OPT, DRY_RUN_OPT],
    "<new_name>",
    "Renames the cluster"),
  'redist-conf': (
    RedistributeConfig, ARGS_NONE, [SUBMIT_OPT, DRY_RUN_OPT, PRIORITY_OPT],
    "", "Forces a push of the configuration file and ssconf files"
    " to the nodes in the cluster"),
  'verify': (
    VerifyCluster, ARGS_NONE,
    [VERBOSE_OPT, DEBUG_SIMERR_OPT, ERROR_CODES_OPT, NONPLUS1_OPT,
     DRY_RUN_OPT, PRIORITY_OPT],
    "", "Does a check on the cluster configuration"),
  'verify-disks': (
    VerifyDisks, ARGS_NONE, [PRIORITY_OPT],
    "", "Does a check on the cluster disk status"),
  'repair-disk-sizes': (
    RepairDiskSizes, ARGS_MANY_INSTANCES, [DRY_RUN_OPT, PRIORITY_OPT],
    "", "Updates mismatches in recorded disk sizes"),
  'master-failover': (
    MasterFailover, ARGS_NONE, [NOVOTING_OPT],
    "", "Makes the current node the master"),
  'master-ping': (
    MasterPing, ARGS_NONE, [],
    "", "Checks if the master is alive"),
  'version': (
    ShowClusterVersion, ARGS_NONE, [],
    "", "Shows the cluster version"),
  'getmaster': (
    ShowClusterMaster, ARGS_NONE, [],
    "", "Shows the cluster master"),
  'copyfile': (
    ClusterCopyFile, [ArgFile(min=1, max=1)],
    [NODE_LIST_OPT, USE_REPL_NET_OPT],
    "[-n node...] <filename>", "Copies a file to all (or only some) nodes"),
  'command': (
    RunClusterCommand, [ArgCommand(min=1)],
    [NODE_LIST_OPT],
    "[-n node...] <command>", "Runs a command on all (or only some) nodes"),
  'info': (
    ShowClusterConfig, ARGS_NONE, [ROMAN_OPT],
    "[--roman]", "Show cluster configuration"),
  'list-tags': (
    ListTags, ARGS_NONE, [], "", "List the tags of the cluster"),
  'add-tags': (
    AddTags, [ArgUnknown()], [TAG_SRC_OPT, PRIORITY_OPT],
    "tag...", "Add tags to the cluster"),
  'remove-tags': (
    RemoveTags, [ArgUnknown()], [TAG_SRC_OPT, PRIORITY_OPT],
    "tag...", "Remove tags from the cluster"),
  'search-tags': (
    SearchTags, [ArgUnknown(min=1, max=1)], [PRIORITY_OPT], "",
    "Searches the tags on all objects on"
    " the cluster for a given pattern (regex)"),
  'queue': (
    QueueOps,
    [ArgChoice(min=1, max=1, choices=["drain", "undrain", "info"])],
    [], "drain|undrain|info", "Change queue properties"),
  'watcher': (
    WatcherOps,
    [ArgChoice(min=1, max=1, choices=["pause", "continue", "info"]),
     ArgSuggest(min=0, max=1, choices=["30m", "1h", "4h"])],
    [],
    "{pause <timespec>|continue|info}", "Change watcher properties"),
  'modify': (
    SetClusterParams, ARGS_NONE,
    [BACKEND_OPT, CP_SIZE_OPT, ENABLED_HV_OPT, HVLIST_OPT, MASTER_NETDEV_OPT,
     NIC_PARAMS_OPT, NOLVM_STORAGE_OPT, VG_NAME_OPT, MAINTAIN_NODE_HEALTH_OPT,
     UIDPOOL_OPT, ADD_UIDS_OPT, REMOVE_UIDS_OPT, DRBD_HELPER_OPT,
     NODRBD_STORAGE_OPT, DEFAULT_IALLOCATOR_OPT, RESERVED_LVS_OPT,
     DRY_RUN_OPT, PRIORITY_OPT, PREALLOC_WIPE_DISKS_OPT, NODE_PARAMS_OPT],
    "[opts...]",
    "Alters the parameters of the cluster"),
  "renew-crypto": (
    RenewCrypto, ARGS_NONE,
    [NEW_CLUSTER_CERT_OPT, NEW_RAPI_CERT_OPT, RAPI_CERT_OPT,
     NEW_CONFD_HMAC_KEY_OPT, FORCE_OPT,
     NEW_CLUSTER_DOMAIN_SECRET_OPT, CLUSTER_DOMAIN_SECRET_OPT],
    "[opts...]",
    "Renews cluster certificates, keys and secrets"),
  }


#: dictionary with aliases for commands
aliases = {
  'masterfailover': 'master-failover',
}


def Main():
  return GenericMain(commands, override={"tag_type": constants.TAG_CLUSTER},
                     aliases=aliases)
