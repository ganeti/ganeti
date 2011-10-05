#
#

# Copyright (C) 2006, 2007, 2008, 2010, 2011 Google Inc.
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


"""Functions to bootstrap a new cluster.

"""

import os
import os.path
import re
import logging
import time

from ganeti import rpc
from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import config
from ganeti import constants
from ganeti import objects
from ganeti import ssconf
from ganeti import serializer
from ganeti import hypervisor
from ganeti import bdev
from ganeti import netutils
from ganeti import backend
from ganeti import luxi
from ganeti import jstore


# ec_id for InitConfig's temporary reservation manager
_INITCONF_ECID = "initconfig-ecid"

#: After how many seconds daemon must be responsive
_DAEMON_READY_TIMEOUT = 10.0


def _InitSSHSetup():
  """Setup the SSH configuration for the cluster.

  This generates a dsa keypair for root, adds the pub key to the
  permitted hosts and adds the hostkey to its own known hosts.

  """
  priv_key, pub_key, auth_keys = ssh.GetUserFiles(constants.GANETI_RUNAS)

  for name in priv_key, pub_key:
    if os.path.exists(name):
      utils.CreateBackup(name)
    utils.RemoveFile(name)

  result = utils.RunCmd(["ssh-keygen", "-t", "dsa",
                         "-f", priv_key,
                         "-q", "-N", ""])
  if result.failed:
    raise errors.OpExecError("Could not generate ssh keypair, error %s" %
                             result.output)

  utils.AddAuthorizedKey(auth_keys, utils.ReadFile(pub_key))


def GenerateHmacKey(file_name):
  """Writes a new HMAC key.

  @type file_name: str
  @param file_name: Path to output file

  """
  utils.WriteFile(file_name, data="%s\n" % utils.GenerateSecret(), mode=0400,
                  backup=True)


def GenerateClusterCrypto(new_cluster_cert, new_rapi_cert, new_spice_cert,
                          new_confd_hmac_key, new_cds,
                          rapi_cert_pem=None, spice_cert_pem=None,
                          spice_cacert_pem=None, cds=None,
                          nodecert_file=constants.NODED_CERT_FILE,
                          rapicert_file=constants.RAPI_CERT_FILE,
                          spicecert_file=constants.SPICE_CERT_FILE,
                          spicecacert_file=constants.SPICE_CACERT_FILE,
                          hmackey_file=constants.CONFD_HMAC_KEY,
                          cds_file=constants.CLUSTER_DOMAIN_SECRET_FILE):
  """Updates the cluster certificates, keys and secrets.

  @type new_cluster_cert: bool
  @param new_cluster_cert: Whether to generate a new cluster certificate
  @type new_rapi_cert: bool
  @param new_rapi_cert: Whether to generate a new RAPI certificate
  @type new_spice_cert: bool
  @param new_spice_cert: Whether to generate a new SPICE certificate
  @type new_confd_hmac_key: bool
  @param new_confd_hmac_key: Whether to generate a new HMAC key
  @type new_cds: bool
  @param new_cds: Whether to generate a new cluster domain secret
  @type rapi_cert_pem: string
  @param rapi_cert_pem: New RAPI certificate in PEM format
  @type spice_cert_pem: string
  @param spice_cert_pem: New SPICE certificate in PEM format
  @type spice_cacert_pem: string
  @param spice_cacert_pem: Certificate of the CA that signed the SPICE
                           certificate, in PEM format
  @type cds: string
  @param cds: New cluster domain secret
  @type nodecert_file: string
  @param nodecert_file: optional override of the node cert file path
  @type rapicert_file: string
  @param rapicert_file: optional override of the rapi cert file path
  @type spicecert_file: string
  @param spicecert_file: optional override of the spice cert file path
  @type spicecacert_file: string
  @param spicecacert_file: optional override of the spice CA cert file path
  @type hmackey_file: string
  @param hmackey_file: optional override of the hmac key file path

  """
  # noded SSL certificate
  cluster_cert_exists = os.path.exists(nodecert_file)
  if new_cluster_cert or not cluster_cert_exists:
    if cluster_cert_exists:
      utils.CreateBackup(nodecert_file)

    logging.debug("Generating new cluster certificate at %s", nodecert_file)
    utils.GenerateSelfSignedSslCert(nodecert_file)

  # confd HMAC key
  if new_confd_hmac_key or not os.path.exists(hmackey_file):
    logging.debug("Writing new confd HMAC key to %s", hmackey_file)
    GenerateHmacKey(hmackey_file)

  # RAPI
  rapi_cert_exists = os.path.exists(rapicert_file)

  if rapi_cert_pem:
    # Assume rapi_pem contains a valid PEM-formatted certificate and key
    logging.debug("Writing RAPI certificate at %s", rapicert_file)
    utils.WriteFile(rapicert_file, data=rapi_cert_pem, backup=True)

  elif new_rapi_cert or not rapi_cert_exists:
    if rapi_cert_exists:
      utils.CreateBackup(rapicert_file)

    logging.debug("Generating new RAPI certificate at %s", rapicert_file)
    utils.GenerateSelfSignedSslCert(rapicert_file)

  # SPICE
  spice_cert_exists = os.path.exists(spicecert_file)
  spice_cacert_exists = os.path.exists(spicecacert_file)
  if spice_cert_pem:
    # spice_cert_pem implies also spice_cacert_pem
    logging.debug("Writing SPICE certificate at %s", spicecert_file)
    utils.WriteFile(spicecert_file, data=spice_cert_pem, backup=True)
    logging.debug("Writing SPICE CA certificate at %s", spicecacert_file)
    utils.WriteFile(spicecacert_file, data=spice_cacert_pem, backup=True)
  elif new_spice_cert or not spice_cert_exists:
    if spice_cert_exists:
      utils.CreateBackup(spicecert_file)
    if spice_cacert_exists:
      utils.CreateBackup(spicecacert_file)

    logging.debug("Generating new self-signed SPICE certificate at %s",
                  spicecert_file)
    (_, cert_pem) = utils.GenerateSelfSignedSslCert(spicecert_file)

    # Self-signed certificate -> the public certificate is also the CA public
    # certificate
    logging.debug("Writing the public certificate to %s",
                  spicecert_file)
    utils.io.WriteFile(spicecacert_file, mode=0400, data=cert_pem)

  # Cluster domain secret
  if cds:
    logging.debug("Writing cluster domain secret to %s", cds_file)
    utils.WriteFile(cds_file, data=cds, backup=True)

  elif new_cds or not os.path.exists(cds_file):
    logging.debug("Generating new cluster domain secret at %s", cds_file)
    GenerateHmacKey(cds_file)


def _InitGanetiServerSetup(master_name):
  """Setup the necessary configuration for the initial node daemon.

  This creates the nodepass file containing the shared password for
  the cluster, generates the SSL certificate and starts the node daemon.

  @type master_name: str
  @param master_name: Name of the master node

  """
  # Generate cluster secrets
  GenerateClusterCrypto(True, False, False, False, False)

  result = utils.RunCmd([constants.DAEMON_UTIL, "start", constants.NODED])
  if result.failed:
    raise errors.OpExecError("Could not start the node daemon, command %s"
                             " had exitcode %s and error %s" %
                             (result.cmd, result.exit_code, result.output))

  _WaitForNodeDaemon(master_name)


def _WaitForNodeDaemon(node_name):
  """Wait for node daemon to become responsive.

  """
  def _CheckNodeDaemon():
    result = rpc.RpcRunner.call_version([node_name])[node_name]
    if result.fail_msg:
      raise utils.RetryAgain()

  try:
    utils.Retry(_CheckNodeDaemon, 1.0, _DAEMON_READY_TIMEOUT)
  except utils.RetryTimeout:
    raise errors.OpExecError("Node daemon on %s didn't answer queries within"
                             " %s seconds" % (node_name, _DAEMON_READY_TIMEOUT))


def _WaitForMasterDaemon():
  """Wait for master daemon to become responsive.

  """
  def _CheckMasterDaemon():
    try:
      cl = luxi.Client()
      (cluster_name, ) = cl.QueryConfigValues(["cluster_name"])
    except Exception:
      raise utils.RetryAgain()

    logging.debug("Received cluster name %s from master", cluster_name)

  try:
    utils.Retry(_CheckMasterDaemon, 1.0, _DAEMON_READY_TIMEOUT)
  except utils.RetryTimeout:
    raise errors.OpExecError("Master daemon didn't answer queries within"
                             " %s seconds" % _DAEMON_READY_TIMEOUT)


def _InitFileStorage(file_storage_dir):
  """Initialize if needed the file storage.

  @param file_storage_dir: the user-supplied value
  @return: either empty string (if file storage was disabled at build
      time) or the normalized path to the storage directory

  """
  file_storage_dir = os.path.normpath(file_storage_dir)

  if not os.path.isabs(file_storage_dir):
    raise errors.OpPrereqError("File storage directory '%s' is not an absolute"
                               " path" % file_storage_dir, errors.ECODE_INVAL)

  if not os.path.exists(file_storage_dir):
    try:
      os.makedirs(file_storage_dir, 0750)
    except OSError, err:
      raise errors.OpPrereqError("Cannot create file storage directory"
                                 " '%s': %s" % (file_storage_dir, err),
                                 errors.ECODE_ENVIRON)

  if not os.path.isdir(file_storage_dir):
    raise errors.OpPrereqError("The file storage directory '%s' is not"
                               " a directory." % file_storage_dir,
                               errors.ECODE_ENVIRON)
  return file_storage_dir


def InitCluster(cluster_name, mac_prefix, # pylint: disable=R0913
                master_netmask, master_netdev, file_storage_dir,
                shared_file_storage_dir, candidate_pool_size, secondary_ip=None,
                vg_name=None, beparams=None, nicparams=None, ndparams=None,
                hvparams=None, enabled_hypervisors=None, modify_etc_hosts=True,
                modify_ssh_setup=True, maintain_node_health=False,
                drbd_helper=None, uid_pool=None, default_iallocator=None,
                primary_ip_version=None, prealloc_wipe_disks=False):
  """Initialise the cluster.

  @type candidate_pool_size: int
  @param candidate_pool_size: master candidate pool size

  """
  # TODO: complete the docstring
  if config.ConfigWriter.IsCluster():
    raise errors.OpPrereqError("Cluster is already initialised",
                               errors.ECODE_STATE)

  if not enabled_hypervisors:
    raise errors.OpPrereqError("Enabled hypervisors list must contain at"
                               " least one member", errors.ECODE_INVAL)
  invalid_hvs = set(enabled_hypervisors) - constants.HYPER_TYPES
  if invalid_hvs:
    raise errors.OpPrereqError("Enabled hypervisors contains invalid"
                               " entries: %s" % invalid_hvs,
                               errors.ECODE_INVAL)

  try:
    ipcls = netutils.IPAddress.GetClassFromIpVersion(primary_ip_version)
  except errors.ProgrammerError:
    raise errors.OpPrereqError("Invalid primary ip version: %d." %
                               primary_ip_version)

  hostname = netutils.GetHostname(family=ipcls.family)
  if not ipcls.IsValid(hostname.ip):
    raise errors.OpPrereqError("This host's IP (%s) is not a valid IPv%d"
                               " address." % (hostname.ip, primary_ip_version))

  if ipcls.IsLoopback(hostname.ip):
    raise errors.OpPrereqError("This host's IP (%s) resolves to a loopback"
                               " address. Please fix DNS or %s." %
                               (hostname.ip, constants.ETC_HOSTS),
                               errors.ECODE_ENVIRON)

  if not ipcls.Own(hostname.ip):
    raise errors.OpPrereqError("Inconsistency: this host's name resolves"
                               " to %s,\nbut this ip address does not"
                               " belong to this host" %
                               hostname.ip, errors.ECODE_ENVIRON)

  clustername = netutils.GetHostname(name=cluster_name, family=ipcls.family)

  if netutils.TcpPing(clustername.ip, constants.DEFAULT_NODED_PORT, timeout=5):
    raise errors.OpPrereqError("Cluster IP already active",
                               errors.ECODE_NOTUNIQUE)

  if not secondary_ip:
    if primary_ip_version == constants.IP6_VERSION:
      raise errors.OpPrereqError("When using a IPv6 primary address, a valid"
                                 " IPv4 address must be given as secondary",
                                 errors.ECODE_INVAL)
    secondary_ip = hostname.ip

  if not netutils.IP4Address.IsValid(secondary_ip):
    raise errors.OpPrereqError("Secondary IP address (%s) has to be a valid"
                               " IPv4 address." % secondary_ip,
                               errors.ECODE_INVAL)

  if not netutils.IP4Address.Own(secondary_ip):
    raise errors.OpPrereqError("You gave %s as secondary IP,"
                               " but it does not belong to this host." %
                               secondary_ip, errors.ECODE_ENVIRON)

  if master_netmask is not None:
    if not ipcls.ValidateNetmask(master_netmask):
      raise errors.OpPrereqError("CIDR netmask (%s) not valid for IPv%s " %
                                  (master_netmask, primary_ip_version))
  else:
    master_netmask = ipcls.iplen

  if vg_name is not None:
    # Check if volume group is valid
    vgstatus = utils.CheckVolumeGroupSize(utils.ListVolumeGroups(), vg_name,
                                          constants.MIN_VG_SIZE)
    if vgstatus:
      raise errors.OpPrereqError("Error: %s\nspecify --no-lvm-storage if"
                                 " you are not using lvm" % vgstatus,
                                 errors.ECODE_INVAL)

  if drbd_helper is not None:
    try:
      curr_helper = bdev.BaseDRBD.GetUsermodeHelper()
    except errors.BlockDeviceError, err:
      raise errors.OpPrereqError("Error while checking drbd helper"
                                 " (specify --no-drbd-storage if you are not"
                                 " using drbd): %s" % str(err),
                                 errors.ECODE_ENVIRON)
    if drbd_helper != curr_helper:
      raise errors.OpPrereqError("Error: requiring %s as drbd helper but %s"
                                 " is the current helper" % (drbd_helper,
                                                             curr_helper),
                                 errors.ECODE_INVAL)

  if constants.ENABLE_FILE_STORAGE:
    file_storage_dir = _InitFileStorage(file_storage_dir)
  else:
    file_storage_dir = ""

  if constants.ENABLE_SHARED_FILE_STORAGE:
    shared_file_storage_dir = _InitFileStorage(shared_file_storage_dir)
  else:
    shared_file_storage_dir = ""

  if not re.match("^[0-9a-z]{2}:[0-9a-z]{2}:[0-9a-z]{2}$", mac_prefix):
    raise errors.OpPrereqError("Invalid mac prefix given '%s'" % mac_prefix,
                               errors.ECODE_INVAL)

  result = utils.RunCmd(["ip", "link", "show", "dev", master_netdev])
  if result.failed:
    raise errors.OpPrereqError("Invalid master netdev given (%s): '%s'" %
                               (master_netdev,
                                result.output.strip()), errors.ECODE_INVAL)

  dirs = [(constants.RUN_GANETI_DIR, constants.RUN_DIRS_MODE)]
  utils.EnsureDirs(dirs)

  utils.ForceDictType(beparams, constants.BES_PARAMETER_TYPES)
  utils.ForceDictType(nicparams, constants.NICS_PARAMETER_TYPES)
  objects.NIC.CheckParameterSyntax(nicparams)

  if ndparams is not None:
    utils.ForceDictType(ndparams, constants.NDS_PARAMETER_TYPES)
  else:
    ndparams = dict(constants.NDC_DEFAULTS)

  # hvparams is a mapping of hypervisor->hvparams dict
  for hv_name, hv_params in hvparams.iteritems():
    utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
    hv_class = hypervisor.GetHypervisor(hv_name)
    hv_class.CheckParameterSyntax(hv_params)

  # set up ssh config and /etc/hosts
  sshline = utils.ReadFile(constants.SSH_HOST_RSA_PUB)
  sshkey = sshline.split(" ")[1]

  if modify_etc_hosts:
    utils.AddHostToEtcHosts(hostname.name, hostname.ip)

  if modify_ssh_setup:
    _InitSSHSetup()

  if default_iallocator is not None:
    alloc_script = utils.FindFile(default_iallocator,
                                  constants.IALLOCATOR_SEARCH_PATH,
                                  os.path.isfile)
    if alloc_script is None:
      raise errors.OpPrereqError("Invalid default iallocator script '%s'"
                                 " specified" % default_iallocator,
                                 errors.ECODE_INVAL)
  elif constants.HTOOLS:
    # htools was enabled at build-time, we default to it
    if utils.FindFile(constants.IALLOC_HAIL,
                      constants.IALLOCATOR_SEARCH_PATH,
                      os.path.isfile):
      default_iallocator = constants.IALLOC_HAIL

  now = time.time()

  # init of cluster config file
  cluster_config = objects.Cluster(
    serial_no=1,
    rsahostkeypub=sshkey,
    highest_used_port=(constants.FIRST_DRBD_PORT - 1),
    mac_prefix=mac_prefix,
    volume_group_name=vg_name,
    tcpudp_port_pool=set(),
    master_node=hostname.name,
    master_ip=clustername.ip,
    master_netmask=master_netmask,
    master_netdev=master_netdev,
    cluster_name=clustername.name,
    file_storage_dir=file_storage_dir,
    shared_file_storage_dir=shared_file_storage_dir,
    enabled_hypervisors=enabled_hypervisors,
    beparams={constants.PP_DEFAULT: beparams},
    nicparams={constants.PP_DEFAULT: nicparams},
    ndparams=ndparams,
    hvparams=hvparams,
    candidate_pool_size=candidate_pool_size,
    modify_etc_hosts=modify_etc_hosts,
    modify_ssh_setup=modify_ssh_setup,
    uid_pool=uid_pool,
    ctime=now,
    mtime=now,
    maintain_node_health=maintain_node_health,
    drbd_usermode_helper=drbd_helper,
    default_iallocator=default_iallocator,
    primary_ip_family=ipcls.family,
    prealloc_wipe_disks=prealloc_wipe_disks,
    )
  master_node_config = objects.Node(name=hostname.name,
                                    primary_ip=hostname.ip,
                                    secondary_ip=secondary_ip,
                                    serial_no=1,
                                    master_candidate=True,
                                    offline=False, drained=False,
                                    ctime=now, mtime=now,
                                    )
  InitConfig(constants.CONFIG_VERSION, cluster_config, master_node_config)
  cfg = config.ConfigWriter(offline=True)
  ssh.WriteKnownHostsFile(cfg, constants.SSH_KNOWN_HOSTS_FILE)
  cfg.Update(cfg.GetClusterInfo(), logging.error)
  backend.WriteSsconfFiles(cfg.GetSsconfValues())

  # set up the inter-node password and certificate
  _InitGanetiServerSetup(hostname.name)

  logging.debug("Starting daemons")
  result = utils.RunCmd([constants.DAEMON_UTIL, "start-all"])
  if result.failed:
    raise errors.OpExecError("Could not start daemons, command %s"
                             " had exitcode %s and error %s" %
                             (result.cmd, result.exit_code, result.output))

  _WaitForMasterDaemon()


def InitConfig(version, cluster_config, master_node_config,
               cfg_file=constants.CLUSTER_CONF_FILE):
  """Create the initial cluster configuration.

  It will contain the current node, which will also be the master
  node, and no instances.

  @type version: int
  @param version: configuration version
  @type cluster_config: L{objects.Cluster}
  @param cluster_config: cluster configuration
  @type master_node_config: L{objects.Node}
  @param master_node_config: master node configuration
  @type cfg_file: string
  @param cfg_file: configuration file path

  """
  uuid_generator = config.TemporaryReservationManager()
  cluster_config.uuid = uuid_generator.Generate([], utils.NewUUID,
                                                _INITCONF_ECID)
  master_node_config.uuid = uuid_generator.Generate([], utils.NewUUID,
                                                    _INITCONF_ECID)
  nodes = {
    master_node_config.name: master_node_config,
    }
  default_nodegroup = objects.NodeGroup(
    uuid=uuid_generator.Generate([], utils.NewUUID, _INITCONF_ECID),
    name=constants.INITIAL_NODE_GROUP_NAME,
    members=[master_node_config.name],
    )
  nodegroups = {
    default_nodegroup.uuid: default_nodegroup,
    }
  now = time.time()
  config_data = objects.ConfigData(version=version,
                                   cluster=cluster_config,
                                   nodegroups=nodegroups,
                                   nodes=nodes,
                                   instances={},
                                   serial_no=1,
                                   ctime=now, mtime=now)
  utils.WriteFile(cfg_file,
                  data=serializer.Dump(config_data.ToDict()),
                  mode=0600)


def FinalizeClusterDestroy(master):
  """Execute the last steps of cluster destroy

  This function shuts down all the daemons, completing the destroy
  begun in cmdlib.LUDestroyOpcode.

  """
  cfg = config.ConfigWriter()
  modify_ssh_setup = cfg.GetClusterInfo().modify_ssh_setup
  result = rpc.RpcRunner.call_node_stop_master(master)
  msg = result.fail_msg
  if msg:
    logging.warning("Could not disable the master role: %s", msg)
  result = rpc.RpcRunner.call_node_leave_cluster(master, modify_ssh_setup)
  msg = result.fail_msg
  if msg:
    logging.warning("Could not shutdown the node daemon and cleanup"
                    " the node: %s", msg)


def SetupNodeDaemon(cluster_name, node, ssh_key_check):
  """Add a node to the cluster.

  This function must be called before the actual opcode, and will ssh
  to the remote node, copy the needed files, and start ganeti-noded,
  allowing the master to do the rest via normal rpc calls.

  @param cluster_name: the cluster name
  @param node: the name of the new node
  @param ssh_key_check: whether to do a strict key check

  """
  family = ssconf.SimpleStore().GetPrimaryIPFamily()
  sshrunner = ssh.SshRunner(cluster_name,
                            ipv6=(family == netutils.IP6Address.family))

  bind_address = constants.IP4_ADDRESS_ANY
  if family == netutils.IP6Address.family:
    bind_address = constants.IP6_ADDRESS_ANY

  # set up inter-node password and certificate and restarts the node daemon
  # and then connect with ssh to set password and start ganeti-noded
  # note that all the below variables are sanitized at this point,
  # either by being constants or by the checks above
  sshrunner.CopyFileToNode(node, constants.NODED_CERT_FILE)
  sshrunner.CopyFileToNode(node, constants.RAPI_CERT_FILE)
  sshrunner.CopyFileToNode(node, constants.SPICE_CERT_FILE)
  sshrunner.CopyFileToNode(node, constants.SPICE_CACERT_FILE)
  sshrunner.CopyFileToNode(node, constants.CONFD_HMAC_KEY)
  mycommand = ("%s stop-all; %s start %s -b %s" %
               (constants.DAEMON_UTIL, constants.DAEMON_UTIL, constants.NODED,
                utils.ShellQuote(bind_address)))

  result = sshrunner.Run(node, 'root', mycommand, batch=False,
                         ask_key=ssh_key_check,
                         use_cluster_key=True,
                         strict_host_check=ssh_key_check)
  if result.failed:
    raise errors.OpExecError("Remote command on node %s, error: %s,"
                             " output: %s" %
                             (node, result.fail_reason, result.output))

  _WaitForNodeDaemon(node)


def MasterFailover(no_voting=False):
  """Failover the master node.

  This checks that we are not already the master, and will cause the
  current master to cease being master, and the non-master to become
  new master.

  @type no_voting: boolean
  @param no_voting: force the operation without remote nodes agreement
                      (dangerous)

  """
  sstore = ssconf.SimpleStore()

  old_master, new_master = ssconf.GetMasterAndMyself(sstore)
  node_list = sstore.GetNodeList()
  mc_list = sstore.GetMasterCandidates()

  if old_master == new_master:
    raise errors.OpPrereqError("This commands must be run on the node"
                               " where you want the new master to be."
                               " %s is already the master" %
                               old_master, errors.ECODE_INVAL)

  if new_master not in mc_list:
    mc_no_master = [name for name in mc_list if name != old_master]
    raise errors.OpPrereqError("This node is not among the nodes marked"
                               " as master candidates. Only these nodes"
                               " can become masters. Current list of"
                               " master candidates is:\n"
                               "%s" % ('\n'.join(mc_no_master)),
                               errors.ECODE_STATE)

  if not no_voting:
    vote_list = GatherMasterVotes(node_list)

    if vote_list:
      voted_master = vote_list[0][0]
      if voted_master is None:
        raise errors.OpPrereqError("Cluster is inconsistent, most nodes did"
                                   " not respond.", errors.ECODE_ENVIRON)
      elif voted_master != old_master:
        raise errors.OpPrereqError("I have a wrong configuration, I believe"
                                   " the master is %s but the other nodes"
                                   " voted %s. Please resync the configuration"
                                   " of this node." %
                                   (old_master, voted_master),
                                   errors.ECODE_STATE)
  # end checks

  rcode = 0

  logging.info("Setting master to %s, old master: %s", new_master, old_master)

  try:
    # instantiate a real config writer, as we now know we have the
    # configuration data
    cfg = config.ConfigWriter(accept_foreign=True)

    cluster_info = cfg.GetClusterInfo()
    cluster_info.master_node = new_master
    # this will also regenerate the ssconf files, since we updated the
    # cluster info
    cfg.Update(cluster_info, logging.error)
  except errors.ConfigurationError, err:
    logging.error("Error while trying to set the new master: %s",
                  str(err))
    return 1

  # if cfg.Update worked, then it means the old master daemon won't be
  # able now to write its own config file (we rely on locking in both
  # backend.UploadFile() and ConfigWriter._Write(); hence the next
  # step is to kill the old master

  logging.info("Stopping the master daemon on node %s", old_master)

  result = rpc.RpcRunner.call_node_stop_master(old_master)
  msg = result.fail_msg
  if msg:
    logging.error("Could not disable the master role on the old master"
                 " %s, please disable manually: %s", old_master, msg)

  logging.info("Checking master IP non-reachability...")

  master_ip = sstore.GetMasterIP()
  total_timeout = 30

  # Here we have a phase where no master should be running
  def _check_ip():
    if netutils.TcpPing(master_ip, constants.DEFAULT_NODED_PORT):
      raise utils.RetryAgain()

  try:
    utils.Retry(_check_ip, (1, 1.5, 5), total_timeout)
  except utils.RetryTimeout:
    logging.warning("The master IP is still reachable after %s seconds,"
                    " continuing but activating the master on the current"
                    " node will probably fail", total_timeout)

  if jstore.CheckDrainFlag():
    logging.info("Undraining job queue")
    jstore.SetDrainFlag(False)

  logging.info("Starting the master daemons on the new master")

  result = rpc.RpcRunner.call_node_start_master_daemons(new_master, no_voting)
  msg = result.fail_msg
  if msg:
    logging.error("Could not start the master role on the new master"
                  " %s, please check: %s", new_master, msg)
    rcode = 1

  logging.info("Master failed over from %s to %s", old_master, new_master)
  return rcode


def GetMaster():
  """Returns the current master node.

  This is a separate function in bootstrap since it's needed by
  gnt-cluster, and instead of importing directly ssconf, it's better
  to abstract it in bootstrap, where we do use ssconf in other
  functions too.

  """
  sstore = ssconf.SimpleStore()

  old_master, _ = ssconf.GetMasterAndMyself(sstore)

  return old_master


def GatherMasterVotes(node_list):
  """Check the agreement on who is the master.

  This function will return a list of (node, number of votes), ordered
  by the number of votes. Errors will be denoted by the key 'None'.

  Note that the sum of votes is the number of nodes this machine
  knows, whereas the number of entries in the list could be different
  (if some nodes vote for another master).

  We remove ourselves from the list since we know that (bugs aside)
  since we use the same source for configuration information for both
  backend and boostrap, we'll always vote for ourselves.

  @type node_list: list
  @param node_list: the list of nodes to query for master info; the current
      node will be removed if it is in the list
  @rtype: list
  @return: list of (node, votes)

  """
  myself = netutils.Hostname.GetSysName()
  try:
    node_list.remove(myself)
  except ValueError:
    pass
  if not node_list:
    # no nodes left (eventually after removing myself)
    return []
  results = rpc.RpcRunner.call_master_info(node_list)
  if not isinstance(results, dict):
    # this should not happen (unless internal error in rpc)
    logging.critical("Can't complete rpc call, aborting master startup")
    return [(None, len(node_list))]
  votes = {}
  for node in results:
    nres = results[node]
    data = nres.payload
    msg = nres.fail_msg
    fail = False
    if msg:
      logging.warning("Error contacting node %s: %s", node, msg)
      fail = True
    # for now we accept both length 3, 4 and 5 (data[3] is primary ip version
    # and data[4] is the master netmask)
    elif not isinstance(data, (tuple, list)) or len(data) < 3:
      logging.warning("Invalid data received from node %s: %s", node, data)
      fail = True
    if fail:
      if None not in votes:
        votes[None] = 0
      votes[None] += 1
      continue
    master_node = data[2]
    if master_node not in votes:
      votes[master_node] = 0
    votes[master_node] += 1

  vote_list = [v for v in votes.items()]
  # sort first on number of votes then on name, since we want None
  # sorted later if we have the half of the nodes not responding, and
  # half voting all for the same master
  vote_list.sort(key=lambda x: (x[1], x[0]), reverse=True)

  return vote_list
