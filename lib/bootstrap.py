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

from ganeti import rpc
from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import config
from ganeti import constants
from ganeti import ssconf


def _InitSSHSetup(node):
  """Setup the SSH configuration for the cluster.


  This generates a dsa keypair for root, adds the pub key to the
  permitted hosts and adds the hostkey to its own known hosts.

  Args:
    node: the name of this host as a fqdn

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


def _InitGanetiServerSetup(ss):
  """Setup the necessary configuration for the initial node daemon.

  This creates the nodepass file containing the shared password for
  the cluster and also generates the SSL certificate.

  Args:
    ss: A WritableSimpleStore

  """
  # Create pseudo random password
  randpass = sha.new(os.urandom(64)).hexdigest()
  # and write it into sstore
  ss.SetKey(ss.SS_NODED_PASS, randpass)

  result = utils.RunCmd(["openssl", "req", "-new", "-newkey", "rsa:1024",
                         "-days", str(365*5), "-nodes", "-x509",
                         "-keyout", constants.SSL_CERT_FILE,
                         "-out", constants.SSL_CERT_FILE, "-batch"])
  if result.failed:
    raise errors.OpExecError("could not generate server ssl cert, command"
                             " %s had exitcode %s and error message %s" %
                             (result.cmd, result.exit_code, result.output))

  os.chmod(constants.SSL_CERT_FILE, 0400)

  result = utils.RunCmd([constants.NODE_INITD_SCRIPT, "restart"])

  if result.failed:
    raise errors.OpExecError("Could not start the node daemon, command %s"
                             " had exitcode %s and error %s" %
                             (result.cmd, result.exit_code, result.output))


def InitCluster(cluster_name, hypervisor_type, mac_prefix, def_bridge,
                master_netdev, file_storage_dir,
                secondary_ip=None,
                vg_name=None):
  """Initialise the cluster.

  """
  if config.ConfigWriter.IsCluster():
    raise errors.OpPrereqError("Cluster is already initialised")

  if hypervisor_type == constants.HT_XEN_HVM31:
    if not os.path.exists(constants.VNC_PASSWORD_FILE):
      raise errors.OpPrereqError("Please prepare the cluster VNC"
                                 "password file %s" %
                                 constants.VNC_PASSWORD_FILE)

  hostname = utils.HostInfo()

  if hostname.ip.startswith("127."):
    raise errors.OpPrereqError("This host's IP resolves to the private"
                               " range (%s). Please fix DNS or %s." %
                               (hostname.ip, constants.ETC_HOSTS))

  if not utils.TcpPing(hostname.ip, constants.DEFAULT_NODED_PORT,
                       source=constants.LOCALHOST_IP_ADDRESS):
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
        (not utils.TcpPing(secondary_ip, constants.DEFAULT_NODED_PORT,
                           source=constants.LOCALHOST_IP_ADDRESS))):
      raise errors.OpPrereqError("You gave %s as secondary IP,"
                                 " but it does not belong to this host." %
                                 secondary_ip)

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

  if hypervisor_type not in constants.HYPER_TYPES:
    raise errors.OpPrereqError("Invalid hypervisor type given '%s'" %
                               hypervisor_type)

  result = utils.RunCmd(["ip", "link", "show", "dev", master_netdev])
  if result.failed:
    raise errors.OpPrereqError("Invalid master netdev given (%s): '%s'" %
                               (master_netdev,
                                result.output.strip()))

  if not (os.path.isfile(constants.NODE_INITD_SCRIPT) and
          os.access(constants.NODE_INITD_SCRIPT, os.X_OK)):
    raise errors.OpPrereqError("Init.d script '%s' missing or not"
                               " executable." % constants.NODE_INITD_SCRIPT)

  # set up the simple store
  ss = ssconf.WritableSimpleStore()
  ss.SetKey(ss.SS_HYPERVISOR, hypervisor_type)
  ss.SetKey(ss.SS_MASTER_NODE, hostname.name)
  ss.SetKey(ss.SS_MASTER_IP, clustername.ip)
  ss.SetKey(ss.SS_MASTER_NETDEV, master_netdev)
  ss.SetKey(ss.SS_CLUSTER_NAME, clustername.name)
  ss.SetKey(ss.SS_FILE_STORAGE_DIR, file_storage_dir)
  ss.SetKey(ss.SS_CONFIG_VERSION, constants.CONFIG_VERSION)

  # set up the inter-node password and certificate
  _InitGanetiServerSetup(ss)

  # set up ssh config and /etc/hosts
  f = open(constants.SSH_HOST_RSA_PUB, 'r')
  try:
    sshline = f.read()
  finally:
    f.close()
  sshkey = sshline.split(" ")[1]

  utils.AddHostToEtcHosts(hostname.name)
  _InitSSHSetup(hostname.name)

  # init of cluster config file
  cfg = config.ConfigWriter()
  cfg.InitConfig(hostname.name, hostname.ip, secondary_ip, sshkey,
                 mac_prefix, vg_name, def_bridge)

  ssh.WriteKnownHostsFile(cfg, ss, constants.SSH_KNOWN_HOSTS_FILE)

  # start the master ip
  # TODO: Review rpc call from bootstrap
  rpc.call_node_start_master(hostname.name, True)


def SetupNodeDaemon(node):
  """Add a node to the cluster.

  This function must be called before the actual opcode, and will ssh
  to the remote node, copy the needed files, and start ganeti-noded,
  allowing the master to do the rest via normal rpc calls.

  Args:
    node: fully qualified domain name for the new node

  """
  ss = ssconf.SimpleStore()
  sshrunner = ssh.SshRunner(ss)
  gntpass = ss.GetNodeDaemonPassword()
  if not re.match('^[a-zA-Z0-9.]{1,64}$', gntpass):
    raise errors.OpExecError("ganeti password corruption detected")
  f = open(constants.SSL_CERT_FILE)
  try:
    gntpem = f.read(8192)
  finally:
    f.close()
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
               "echo '%s' > '%s' && "
               "cat > '%s' << '!EOF.' && \n"
               "%s!EOF.\n%s restart" %
               (gntpass, ss.KeyToFilename(ss.SS_NODED_PASS),
                constants.SSL_CERT_FILE, gntpem,
                constants.NODE_INITD_SCRIPT))

  result = sshrunner.Run(node, 'root', mycommand, batch=False, ask_key=True)
  if result.failed:
    raise errors.OpExecError("Remote command on node %s, error: %s,"
                             " output: %s" %
                             (node, result.fail_reason, result.output))

  return 0


def MasterFailover():
  """Failover the master node.

  This checks that we are not already the master, and will cause the
  current master to cease being master, and the non-master to become
  new master.

  """
  ss = ssconf.WritableSimpleStore()

  new_master = utils.HostInfo().name
  old_master = ss.GetMasterNode()

  if old_master == new_master:
    raise errors.OpPrereqError("This commands must be run on the node"
                               " where you want the new master to be."
                               " %s is already the master" %
                               old_master)
  # end checks

  rcode = 0

  logging.info("setting master to %s, old master: %s", new_master, old_master)

  if not rpc.call_node_stop_master(old_master, True):
    logging.error("could disable the master role on the old master"
                 " %s, please disable manually", old_master)

  ss.SetKey(ss.SS_MASTER_NODE, new_master)

  cfg = config.ConfigWriter()

  if not rpc.call_upload_file(cfg.GetNodeList(),
                              ss.KeyToFilename(ss.SS_MASTER_NODE)):
    logging.error("could not distribute the new simple store master file"
                  " to the other nodes, please check.")

  if not rpc.call_node_start_master(new_master, True):
    logging.error("could not start the master role on the new master"
                  " %s, please check", new_master)
    rcode = 1

  return rcode
