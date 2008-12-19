#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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
import sha
import re
import logging
import tempfile

from ganeti import rpc
from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import config
from ganeti import constants
from ganeti import objects
from ganeti import ssconf


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

  f = open(pub_key, 'r')
  try:
    utils.AddAuthorizedKey(auth_keys, f.read(8192))
  finally:
    f.close()


def _GenerateSelfSignedSslCert(file_name, validity=(365 * 5)):
  """Generates a self-signed SSL certificate.

  @type file_name: str
  @param file_name: Path to output file
  @type validity: int
  @param validity: Validity for certificate in days

  """
  (fd, tmp_file_name) = tempfile.mkstemp(dir=os.path.dirname(file_name))
  try:
    # Set permissions before writing key
    os.chmod(tmp_file_name, 0600)

    result = utils.RunCmd(["openssl", "req", "-new", "-newkey", "rsa:1024",
                           "-days", str(validity), "-nodes", "-x509",
                           "-keyout", tmp_file_name, "-out", tmp_file_name,
                           "-batch"])
    if result.failed:
      raise errors.OpExecError("Could not generate SSL certificate, command"
                               " %s had exitcode %s and error message %s" %
                               (result.cmd, result.exit_code, result.output))

    # Make read-only
    os.chmod(tmp_file_name, 0400)

    os.rename(tmp_file_name, file_name)
  finally:
    utils.RemoveFile(tmp_file_name)


def _InitGanetiServerSetup():
  """Setup the necessary configuration for the initial node daemon.

  This creates the nodepass file containing the shared password for
  the cluster and also generates the SSL certificate.

  """
  _GenerateSelfSignedSslCert(constants.SSL_CERT_FILE)

  # Don't overwrite existing file
  if not os.path.exists(constants.RAPI_CERT_FILE):
    _GenerateSelfSignedSslCert(constants.RAPI_CERT_FILE)

  result = utils.RunCmd([constants.NODE_INITD_SCRIPT, "restart"])

  if result.failed:
    raise errors.OpExecError("Could not start the node daemon, command %s"
                             " had exitcode %s and error %s" %
                             (result.cmd, result.exit_code, result.output))


def InitCluster(cluster_name, mac_prefix, def_bridge,
                master_netdev, file_storage_dir, candidate_pool_size,
                secondary_ip=None, vg_name=None, beparams=None, hvparams=None,
                enabled_hypervisors=None, default_hypervisor=None):
  """Initialise the cluster.

  @type candidate_pool_size: int
  @param candidate_pool_size: master candidate pool size

  """
  # TODO: complete the docstring
  if config.ConfigWriter.IsCluster():
    raise errors.OpPrereqError("Cluster is already initialised")

  hostname = utils.HostInfo()

  if hostname.ip.startswith("127."):
    raise errors.OpPrereqError("This host's IP resolves to the private"
                               " range (%s). Please fix DNS or %s." %
                               (hostname.ip, constants.ETC_HOSTS))

  if not utils.OwnIpAddress(hostname.ip):
    raise errors.OpPrereqError("Inconsistency: this host's name resolves"
                               " to %s,\nbut this ip address does not"
                               " belong to this host."
                               " Aborting." % hostname.ip)

  clustername = utils.HostInfo(cluster_name)

  if utils.TcpPing(clustername.ip, constants.DEFAULT_NODED_PORT,
                   timeout=5):
    raise errors.OpPrereqError("Cluster IP already active. Aborting.")

  if secondary_ip:
    if not utils.IsValidIP(secondary_ip):
      raise errors.OpPrereqError("Invalid secondary ip given")
    if (secondary_ip != hostname.ip and
        not utils.OwnIpAddress(secondary_ip)):
      raise errors.OpPrereqError("You gave %s as secondary IP,"
                                 " but it does not belong to this host." %
                                 secondary_ip)
  else:
    secondary_ip = hostname.ip

  if vg_name is not None:
    # Check if volume group is valid
    vgstatus = utils.CheckVolumeGroupSize(utils.ListVolumeGroups(), vg_name,
                                          constants.MIN_VG_SIZE)
    if vgstatus:
      raise errors.OpPrereqError("Error: %s\nspecify --no-lvm-storage if"
                                 " you are not using lvm" % vgstatus)

  file_storage_dir = os.path.normpath(file_storage_dir)

  if not os.path.isabs(file_storage_dir):
    raise errors.OpPrereqError("The file storage directory you passed is"
                               " not an absolute path.")

  if not os.path.exists(file_storage_dir):
    try:
      os.makedirs(file_storage_dir, 0750)
    except OSError, err:
      raise errors.OpPrereqError("Cannot create file storage directory"
                                 " '%s': %s" %
                                 (file_storage_dir, err))

  if not os.path.isdir(file_storage_dir):
    raise errors.OpPrereqError("The file storage directory '%s' is not"
                               " a directory." % file_storage_dir)

  if not re.match("^[0-9a-z]{2}:[0-9a-z]{2}:[0-9a-z]{2}$", mac_prefix):
    raise errors.OpPrereqError("Invalid mac prefix given '%s'" % mac_prefix)

  result = utils.RunCmd(["ip", "link", "show", "dev", master_netdev])
  if result.failed:
    raise errors.OpPrereqError("Invalid master netdev given (%s): '%s'" %
                               (master_netdev,
                                result.output.strip()))

  if not (os.path.isfile(constants.NODE_INITD_SCRIPT) and
          os.access(constants.NODE_INITD_SCRIPT, os.X_OK)):
    raise errors.OpPrereqError("Init.d script '%s' missing or not"
                               " executable." % constants.NODE_INITD_SCRIPT)

  utils.CheckBEParams(beparams)

  # set up the inter-node password and certificate
  _InitGanetiServerSetup()

  # set up ssh config and /etc/hosts
  f = open(constants.SSH_HOST_RSA_PUB, 'r')
  try:
    sshline = f.read()
  finally:
    f.close()
  sshkey = sshline.split(" ")[1]

  utils.AddHostToEtcHosts(hostname.name)
  _InitSSHSetup()

  # init of cluster config file
  cluster_config = objects.Cluster(
    serial_no=1,
    rsahostkeypub=sshkey,
    highest_used_port=(constants.FIRST_DRBD_PORT - 1),
    mac_prefix=mac_prefix,
    volume_group_name=vg_name,
    default_bridge=def_bridge,
    tcpudp_port_pool=set(),
    master_node=hostname.name,
    master_ip=clustername.ip,
    master_netdev=master_netdev,
    cluster_name=clustername.name,
    file_storage_dir=file_storage_dir,
    enabled_hypervisors=enabled_hypervisors,
    default_hypervisor=default_hypervisor,
    beparams={constants.BEGR_DEFAULT: beparams},
    hvparams=hvparams,
    candidate_pool_size=candidate_pool_size,
    )
  master_node_config = objects.Node(name=hostname.name,
                                    primary_ip=hostname.ip,
                                    secondary_ip=secondary_ip,
                                    serial_no=1,
                                    master_candidate=True,
                                    offline=False,
                                    )

  sscfg = InitConfig(constants.CONFIG_VERSION,
                     cluster_config, master_node_config)
  ssh.WriteKnownHostsFile(sscfg, constants.SSH_KNOWN_HOSTS_FILE)
  cfg = config.ConfigWriter()
  cfg.Update(cfg.GetClusterInfo())

  # start the master ip
  # TODO: Review rpc call from bootstrap
  rpc.RpcRunner.call_node_start_master(hostname.name, True)


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

  @rtype: L{ssconf.SimpleConfigWriter}
  @returns: initialized config instance

  """
  nodes = {
    master_node_config.name: master_node_config,
    }

  config_data = objects.ConfigData(version=version,
                                   cluster=cluster_config,
                                   nodes=nodes,
                                   instances={},
                                   serial_no=1)
  cfg = ssconf.SimpleConfigWriter.FromDict(config_data.ToDict(), cfg_file)
  cfg.Save()

  return cfg


def FinalizeClusterDestroy(master):
  """Execute the last steps of cluster destroy

  This function shuts down all the daemons, completing the destroy
  begun in cmdlib.LUDestroyOpcode.

  """
  result = rpc.RpcRunner.call_node_stop_master(master, True)
  if result.failed or not result.data:
    logging.warning("Could not disable the master role")
  result = rpc.RpcRunner.call_node_leave_cluster(master)
  if result.failed or not result.data:
    logging.warning("Could not shutdown the node daemon and cleanup the node")


def SetupNodeDaemon(cluster_name, node, ssh_key_check):
  """Add a node to the cluster.

  This function must be called before the actual opcode, and will ssh
  to the remote node, copy the needed files, and start ganeti-noded,
  allowing the master to do the rest via normal rpc calls.

  @param cluster_name: the cluster name
  @param node: the name of the new node
  @param ssh_key_check: whether to do a strict key check

  """
  sshrunner = ssh.SshRunner(cluster_name)
  gntpem = utils.ReadFile(constants.SSL_CERT_FILE)
  # in the base64 pem encoding, neither '!' nor '.' are valid chars,
  # so we use this to detect an invalid certificate; as long as the
  # cert doesn't contain this, the here-document will be correctly
  # parsed by the shell sequence below
  if re.search('^!EOF\.', gntpem, re.MULTILINE):
    raise errors.OpExecError("invalid PEM encoding in the SSL certificate")
  if not gntpem.endswith("\n"):
    raise errors.OpExecError("PEM must end with newline")

  # set up inter-node password and certificate and restarts the node daemon
  # and then connect with ssh to set password and start ganeti-noded
  # note that all the below variables are sanitized at this point,
  # either by being constants or by the checks above
  mycommand = ("umask 077 && "
               "cat > '%s' << '!EOF.' && \n"
               "%s!EOF.\n%s restart" %
               (constants.SSL_CERT_FILE, gntpem,
                constants.NODE_INITD_SCRIPT))

  result = sshrunner.Run(node, 'root', mycommand, batch=False,
                         ask_key=ssh_key_check,
                         use_cluster_key=False,
                         strict_host_check=ssh_key_check)
  if result.failed:
    raise errors.OpExecError("Remote command on node %s, error: %s,"
                             " output: %s" %
                             (node, result.fail_reason, result.output))


def MasterFailover():
  """Failover the master node.

  This checks that we are not already the master, and will cause the
  current master to cease being master, and the non-master to become
  new master.

  """
  sstore = ssconf.SimpleStore()

  old_master, new_master = ssconf.GetMasterAndMyself(sstore)
  node_list = sstore.GetNodeList()
  mc_list = sstore.GetMasterCandidates()

  if old_master == new_master:
    raise errors.OpPrereqError("This commands must be run on the node"
                               " where you want the new master to be."
                               " %s is already the master" %
                               old_master)

  if new_master not in mc_list:
    mc_no_master = [name for name in mc_list if name != old_master]
    raise errors.OpPrereqError("This node is not among the nodes marked"
                               " as master candidates. Only these nodes"
                               " can become masters. Current list of"
                               " master candidates is:\n"
                               "%s" % ('\n'.join(mc_no_master)))

  vote_list = GatherMasterVotes(node_list)

  if vote_list:
    voted_master = vote_list[0][0]
    if voted_master is None:
      raise errors.OpPrereqError("Cluster is inconsistent, most nodes did not"
                                 " respond.")
    elif voted_master != old_master:
      raise errors.OpPrereqError("I have wrong configuration, I believe the"
                                 " master is %s but the other nodes voted for"
                                 " %s. Please resync the configuration of"
                                 " this node." % (old_master, voted_master))
  # end checks

  rcode = 0

  logging.info("Setting master to %s, old master: %s", new_master, old_master)

  result = rpc.RpcRunner.call_node_stop_master(old_master, True)
  if result.failed or not result.data:
    logging.error("Could not disable the master role on the old master"
                 " %s, please disable manually", old_master)

  # Here we have a phase where no master should be running

  # instantiate a real config writer, as we now know we have the
  # configuration data
  cfg = config.ConfigWriter()

  cluster_info = cfg.GetClusterInfo()
  cluster_info.master_node = new_master
  # this will also regenerate the ssconf files, since we updated the
  # cluster info
  cfg.Update(cluster_info)

  result = rpc.RpcRunner.call_node_start_master(new_master, True)
  if result.failed or not result.data:
    logging.error("Could not start the master role on the new master"
                  " %s, please check", new_master)
    rcode = 1

  return rcode


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
      node wil be removed if it is in the list
  @rtype: list
  @return: list of (node, votes)

  """
  myself = utils.HostInfo().name
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
    data = nres.data
    if nres.failed or not isinstance(data, (tuple, list)) or len(data) < 3:
      # here the rpc layer should have already logged errors
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
