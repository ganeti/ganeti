#
#

# Copyright (C) 2006, 2007, 2008, 2010, 2011, 2012 Google Inc.
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


"""Functions to bootstrap a new cluster.

"""

import os
import os.path
import re
import logging
import time

from ganeti.cmdlib import cluster
import ganeti.rpc.node as rpc
from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import config
from ganeti import constants
from ganeti import objects
from ganeti import ssconf
from ganeti import serializer
from ganeti import hypervisor
from ganeti.storage import drbd
from ganeti.storage import filestorage
from ganeti import netutils
from ganeti import luxi
from ganeti import jstore
from ganeti import pathutils
from ganeti import runtime
from ganeti import vcluster


# ec_id for InitConfig's temporary reservation manager
_INITCONF_ECID = "initconfig-ecid"

#: After how many seconds daemon must be responsive
_DAEMON_READY_TIMEOUT = 10.0


def GenerateHmacKey(file_name):
  """Writes a new HMAC key.

  @type file_name: str
  @param file_name: Path to output file

  """
  utils.WriteFile(file_name, data="%s\n" % utils.GenerateSecret(), mode=0o400,
                  backup=True)


# pylint: disable=R0913
def GenerateClusterCrypto(new_cluster_cert, new_rapi_cert, new_spice_cert,
                          new_confd_hmac_key, new_cds, new_client_cert,
                          master_name,
                          rapi_cert_pem=None, spice_cert_pem=None,
                          spice_cacert_pem=None, cds=None,
                          nodecert_file=pathutils.NODED_CERT_FILE,
                          clientcert_file=pathutils.NODED_CLIENT_CERT_FILE,
                          rapicert_file=pathutils.RAPI_CERT_FILE,
                          spicecert_file=pathutils.SPICE_CERT_FILE,
                          spicecacert_file=pathutils.SPICE_CACERT_FILE,
                          hmackey_file=pathutils.CONFD_HMAC_KEY,
                          cds_file=pathutils.CLUSTER_DOMAIN_SECRET_FILE):
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
  @type new_client_cert: bool
  @param new_client_cert: Whether to generate a new client certificate
  @type master_name: string
  @param master_name: FQDN of the master node
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
  # pylint: disable=R0913
  # noded SSL certificate
  utils.GenerateNewSslCert(
    new_cluster_cert, nodecert_file, 1,
    "Generating new cluster certificate at %s" % nodecert_file)

  # If the cluster certificate was renewed, the client cert has to be
  # renewed and resigned.
  if new_cluster_cert or new_client_cert:
    utils.GenerateNewClientSslCert(clientcert_file, nodecert_file,
                                   master_name)

  # confd HMAC key
  if new_confd_hmac_key or not os.path.exists(hmackey_file):
    logging.debug("Writing new confd HMAC key to %s", hmackey_file)
    GenerateHmacKey(hmackey_file)

  if rapi_cert_pem:
    # Assume rapi_pem contains a valid PEM-formatted certificate and key
    logging.debug("Writing RAPI certificate at %s", rapicert_file)
    utils.WriteFile(rapicert_file, data=rapi_cert_pem, backup=True)

  else:
    utils.GenerateNewSslCert(
      new_rapi_cert, rapicert_file, 1,
      "Generating new RAPI certificate at %s" % rapicert_file)

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
    (_, cert_pem) = utils.GenerateSelfSignedSslCert(spicecert_file, 1)

    # Self-signed certificate -> the public certificate is also the CA public
    # certificate
    logging.debug("Writing the public certificate to %s",
                  spicecert_file)
    utils.io.WriteFile(spicecacert_file, mode=0o400, data=cert_pem)

  # Cluster domain secret
  if cds:
    logging.debug("Writing cluster domain secret to %s", cds_file)
    utils.WriteFile(cds_file, data=cds, backup=True)

  elif new_cds or not os.path.exists(cds_file):
    logging.debug("Generating new cluster domain secret at %s", cds_file)
    GenerateHmacKey(cds_file)


def _InitGanetiServerSetup(master_name, cfg):
  """Setup the necessary configuration for the initial node daemon.

  This creates the nodepass file containing the shared password for
  the cluster, generates the SSL certificate and starts the node daemon.

  @type master_name: str
  @param master_name: Name of the master node
  @type cfg: ConfigWriter
  @param cfg: the configuration writer

  """
  # Generate cluster secrets
  GenerateClusterCrypto(True, False, False, False, False, False, master_name)

  # Add the master's SSL certificate digest to the configuration.
  master_uuid = cfg.GetMasterNode()
  master_digest = utils.GetCertificateDigest()
  cfg.AddNodeToCandidateCerts(master_uuid, master_digest)
  cfg.Update(cfg.GetClusterInfo(), logging.error)
  ssconf.WriteSsconfFiles(cfg.GetSsconfValues())

  if not os.path.exists(
      os.path.join(pathutils.DATA_DIR,
                   "%s%s" % (constants.SSCONF_FILEPREFIX,
                             constants.SS_MASTER_CANDIDATES_CERTS))):
    raise errors.OpExecError("Ssconf file for master candidate certificates"
                             " was not written.")

  if not os.path.exists(pathutils.NODED_CERT_FILE):
    raise errors.OpExecError("The server certficate was not created properly.")

  if not os.path.exists(pathutils.NODED_CLIENT_CERT_FILE):
    raise errors.OpExecError("The client certificate was not created"
                             " properly.")

  # set up the inter-node password and certificate
  result = utils.RunCmd([pathutils.DAEMON_UTIL, "start", constants.NODED])
  if result.failed:
    raise errors.OpExecError("Could not start the node daemon, command %s"
                             " had exitcode %s and error %s" %
                             (result.cmd, result.exit_code, result.output))

  _WaitForNodeDaemon(master_name)


def _WaitForNodeDaemon(node_name):
  """Wait for node daemon to become responsive.

  """
  def _CheckNodeDaemon():
    # Pylint bug <http://www.logilab.org/ticket/35642>
    # pylint: disable=E1101
    result = rpc.BootstrapRunner().call_version([node_name])[node_name]
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


def _WaitForSshDaemon(hostname, port):
  """Wait for SSH daemon to become responsive.

  """
  family = ssconf.SimpleStore().GetPrimaryIPFamily()
  hostip = netutils.GetHostname(name=hostname, family=family).ip

  def _CheckSshDaemon():
    if netutils.TcpPing(hostip, port, timeout=1.0, live_port_needed=True):
      logging.debug("SSH daemon on %s:%s (IP address %s) has become"
                    " responsive", hostname, port, hostip)
    else:
      raise utils.RetryAgain()

  try:
    utils.Retry(_CheckSshDaemon, 1.0, _DAEMON_READY_TIMEOUT)
  except utils.RetryTimeout:
    raise errors.OpExecError("SSH daemon on %s:%s (IP address %s) didn't"
                             " become responsive within %s seconds" %
                             (hostname, port, hostip, _DAEMON_READY_TIMEOUT))


def _InitFileStorageDir(file_storage_dir):
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
      os.makedirs(file_storage_dir, 0o750)
    except OSError as err:
      raise errors.OpPrereqError("Cannot create file storage directory"
                                 " '%s': %s" % (file_storage_dir, err),
                                 errors.ECODE_ENVIRON)

  if not os.path.isdir(file_storage_dir):
    raise errors.OpPrereqError("The file storage directory '%s' is not"
                               " a directory." % file_storage_dir,
                               errors.ECODE_ENVIRON)

  return file_storage_dir


def _PrepareFileBasedStorage(
    enabled_disk_templates, file_storage_dir,
    default_dir, file_disk_template, _storage_path_acceptance_fn,
    init_fn=_InitFileStorageDir, acceptance_fn=None):
  """Checks if a file-base storage type is enabled and inits the dir.

  @type enabled_disk_templates: list of string
  @param enabled_disk_templates: list of enabled disk templates
  @type file_storage_dir: string
  @param file_storage_dir: the file storage directory
  @type default_dir: string
  @param default_dir: default file storage directory when C{file_storage_dir}
      is 'None'
  @type file_disk_template: string
  @param file_disk_template: a disk template whose storage type is 'ST_FILE',
      'ST_SHARED_FILE' or 'ST_GLUSTER'
  @type _storage_path_acceptance_fn: function
  @param _storage_path_acceptance_fn: checks whether the given file-based
      storage directory is acceptable
  @see: C{cluster.CheckFileBasedStoragePathVsEnabledDiskTemplates} for details

  @rtype: string
  @returns: the name of the actual file storage directory

  """
  assert (file_disk_template in utils.storage.GetDiskTemplatesOfStorageTypes(
            constants.ST_FILE, constants.ST_SHARED_FILE, constants.ST_GLUSTER
         ))

  if file_storage_dir is None:
    file_storage_dir = default_dir
  if not acceptance_fn:
    acceptance_fn = \
        lambda path: filestorage.CheckFileStoragePathAcceptance(
            path, exact_match_ok=True)

  _storage_path_acceptance_fn(logging.warning, file_storage_dir,
                              enabled_disk_templates)

  file_storage_enabled = file_disk_template in enabled_disk_templates
  if file_storage_enabled:
    try:
      acceptance_fn(file_storage_dir)
    except errors.FileStoragePathError as e:
      raise errors.OpPrereqError(str(e))
    result_file_storage_dir = init_fn(file_storage_dir)
  else:
    result_file_storage_dir = file_storage_dir
  return result_file_storage_dir


def _PrepareFileStorage(
    enabled_disk_templates, file_storage_dir, init_fn=_InitFileStorageDir,
    acceptance_fn=None):
  """Checks if file storage is enabled and inits the dir.

  @see: C{_PrepareFileBasedStorage}

  """
  return _PrepareFileBasedStorage(
      enabled_disk_templates, file_storage_dir,
      pathutils.DEFAULT_FILE_STORAGE_DIR, constants.DT_FILE,
      cluster.CheckFileStoragePathVsEnabledDiskTemplates,
      init_fn=init_fn, acceptance_fn=acceptance_fn)


def _PrepareSharedFileStorage(
    enabled_disk_templates, file_storage_dir, init_fn=_InitFileStorageDir,
    acceptance_fn=None):
  """Checks if shared file storage is enabled and inits the dir.

  @see: C{_PrepareFileBasedStorage}

  """
  return _PrepareFileBasedStorage(
      enabled_disk_templates, file_storage_dir,
      pathutils.DEFAULT_SHARED_FILE_STORAGE_DIR, constants.DT_SHARED_FILE,
      cluster.CheckSharedFileStoragePathVsEnabledDiskTemplates,
      init_fn=init_fn, acceptance_fn=acceptance_fn)


def _PrepareGlusterStorage(
    enabled_disk_templates, file_storage_dir, init_fn=_InitFileStorageDir,
    acceptance_fn=None):
  """Checks if gluster storage is enabled and inits the dir.

  @see: C{_PrepareFileBasedStorage}

  """
  return _PrepareFileBasedStorage(
      enabled_disk_templates, file_storage_dir,
      pathutils.DEFAULT_GLUSTER_STORAGE_DIR, constants.DT_GLUSTER,
      cluster.CheckGlusterStoragePathVsEnabledDiskTemplates,
      init_fn=init_fn, acceptance_fn=acceptance_fn)


def _InitCheckEnabledDiskTemplates(enabled_disk_templates):
  """Checks the sanity of the enabled disk templates.

  """
  if not enabled_disk_templates:
    raise errors.OpPrereqError("Enabled disk templates list must contain at"
                               " least one member", errors.ECODE_INVAL)
  invalid_disk_templates = \
    set(enabled_disk_templates) - constants.DISK_TEMPLATES
  if invalid_disk_templates:
    raise errors.OpPrereqError("Enabled disk templates list contains invalid"
                               " entries: %s" % invalid_disk_templates,
                               errors.ECODE_INVAL)


def _RestrictIpolicyToEnabledDiskTemplates(ipolicy, enabled_disk_templates):
  """Restricts the ipolicy's disk templates to the enabled ones.

  This function clears the ipolicy's list of allowed disk templates from the
  ones that are not enabled by the cluster.

  @type ipolicy: dict
  @param ipolicy: the instance policy
  @type enabled_disk_templates: list of string
  @param enabled_disk_templates: the list of cluster-wide enabled disk
    templates

  """
  assert constants.IPOLICY_DTS in ipolicy
  allowed_disk_templates = ipolicy[constants.IPOLICY_DTS]
  restricted_disk_templates = list(set(allowed_disk_templates)
                                   .intersection(set(enabled_disk_templates)))
  ipolicy[constants.IPOLICY_DTS] = restricted_disk_templates


def _InitCheckDrbdHelper(drbd_helper, drbd_enabled):
  """Checks the DRBD usermode helper.

  @type drbd_helper: string
  @param drbd_helper: name of the DRBD usermode helper that the system should
    use

  """
  if not drbd_enabled:
    return

  if drbd_helper is not None:
    try:
      curr_helper = drbd.DRBD8.GetUsermodeHelper()
    except errors.BlockDeviceError as err:
      raise errors.OpPrereqError("Error while checking drbd helper"
                                 " (disable drbd with --enabled-disk-templates"
                                 " if you are not using drbd): %s" % str(err),
                                 errors.ECODE_ENVIRON)
    if drbd_helper != curr_helper:
      raise errors.OpPrereqError("Error: requiring %s as drbd helper but %s"
                                 " is the current helper" % (drbd_helper,
                                                             curr_helper),
                                 errors.ECODE_INVAL)


def InitCluster(cluster_name, mac_prefix, # pylint: disable=R0913, R0914
                master_netmask, master_netdev, file_storage_dir,
                shared_file_storage_dir, gluster_storage_dir,
                candidate_pool_size, ssh_key_type, ssh_key_bits,
                secondary_ip=None, vg_name=None, beparams=None, nicparams=None,
                ndparams=None, hvparams=None, diskparams=None,
                enabled_hypervisors=None, modify_etc_hosts=True,
                modify_ssh_setup=True, maintain_node_health=False,
                drbd_helper=None, uid_pool=None, default_iallocator=None,
                default_iallocator_params=None, primary_ip_version=None,
                ipolicy=None, prealloc_wipe_disks=False,
                use_external_mip_script=False, hv_state=None, disk_state=None,
                enabled_disk_templates=None, install_image=None,
                zeroing_image=None, compression_tools=None,
                enabled_user_shutdown=False):
  """Initialise the cluster.

  @type candidate_pool_size: int
  @param candidate_pool_size: master candidate pool size

  @type enabled_disk_templates: list of string
  @param enabled_disk_templates: list of disk_templates to be used in this
    cluster

  @type enabled_user_shutdown: bool
  @param enabled_user_shutdown: whether user shutdown is enabled cluster
                                wide

  """
  # TODO: complete the docstring
  if config.ConfigWriter.IsCluster():
    raise errors.OpPrereqError("Cluster is already initialised",
                               errors.ECODE_STATE)

  data_dir = vcluster.AddNodePrefix(pathutils.DATA_DIR)
  queue_dir = vcluster.AddNodePrefix(pathutils.QUEUE_DIR)
  archive_dir = vcluster.AddNodePrefix(pathutils.JOB_QUEUE_ARCHIVE_DIR)
  for ddir in [queue_dir, data_dir, archive_dir]:
    if os.path.isdir(ddir):
      for entry in os.listdir(ddir):
        if not os.path.isdir(os.path.join(ddir, entry)):
          raise errors.OpPrereqError(
            "%s contains non-directory entries like %s. Remove left-overs of an"
            " old cluster before initialising a new one" % (ddir, entry),
            errors.ECODE_STATE)

  if not enabled_hypervisors:
    raise errors.OpPrereqError("Enabled hypervisors list must contain at"
                               " least one member", errors.ECODE_INVAL)
  invalid_hvs = set(enabled_hypervisors) - constants.HYPER_TYPES
  if invalid_hvs:
    raise errors.OpPrereqError("Enabled hypervisors contains invalid"
                               " entries: %s" % invalid_hvs,
                               errors.ECODE_INVAL)

  _InitCheckEnabledDiskTemplates(enabled_disk_templates)

  try:
    ipcls = netutils.IPAddress.GetClassFromIpVersion(primary_ip_version)
  except errors.ProgrammerError:
    raise errors.OpPrereqError("Invalid primary ip version: %d." %
                               primary_ip_version, errors.ECODE_INVAL)

  hostname = netutils.GetHostname(family=ipcls.family)
  if not ipcls.IsValid(hostname.ip):
    raise errors.OpPrereqError("This host's IP (%s) is not a valid IPv%d"
                               " address." % (hostname.ip, primary_ip_version),
                               errors.ECODE_INVAL)

  if ipcls.IsLoopback(hostname.ip):
    raise errors.OpPrereqError("This host's IP (%s) resolves to a loopback"
                               " address. Please fix DNS or %s." %
                               (hostname.ip, pathutils.ETC_HOSTS),
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
                                  (master_netmask, primary_ip_version),
                                 errors.ECODE_INVAL)
  else:
    master_netmask = ipcls.iplen

  if vg_name:
    # Check if volume group is valid
    vgstatus = utils.CheckVolumeGroupSize(utils.ListVolumeGroups(), vg_name,
                                          constants.MIN_VG_SIZE)
    if vgstatus:
      raise errors.OpPrereqError("Error: %s" % vgstatus, errors.ECODE_INVAL)

  drbd_enabled = constants.DT_DRBD8 in enabled_disk_templates
  _InitCheckDrbdHelper(drbd_helper, drbd_enabled)

  logging.debug("Stopping daemons (if any are running)")
  result = utils.RunCmd([pathutils.DAEMON_UTIL, "stop-all"])
  if result.failed:
    raise errors.OpExecError("Could not stop daemons, command %s"
                             " had exitcode %s and error '%s'" %
                             (result.cmd, result.exit_code, result.output))

  file_storage_dir = _PrepareFileStorage(enabled_disk_templates,
                                         file_storage_dir)
  shared_file_storage_dir = _PrepareSharedFileStorage(enabled_disk_templates,
                                                      shared_file_storage_dir)
  gluster_storage_dir = _PrepareGlusterStorage(enabled_disk_templates,
                                               gluster_storage_dir)

  if not re.match("^[0-9a-z]{2}:[0-9a-z]{2}:[0-9a-z]{2}$", mac_prefix):
    raise errors.OpPrereqError("Invalid mac prefix given '%s'" % mac_prefix,
                               errors.ECODE_INVAL)

  if not nicparams.get('mode', None) == constants.NIC_MODE_OVS:
    # Do not do this check if mode=openvswitch, since the openvswitch is not
    # created yet
    result = utils.RunCmd(["ip", "link", "show", "dev", master_netdev])
    if result.failed:
      raise errors.OpPrereqError("Invalid master netdev given (%s): '%s'" %
                                 (master_netdev,
                                  result.output.strip()), errors.ECODE_INVAL)

  dirs = [(pathutils.RUN_DIR, constants.RUN_DIRS_MODE)]
  utils.EnsureDirs(dirs)

  objects.UpgradeBeParams(beparams)
  utils.ForceDictType(beparams, constants.BES_PARAMETER_TYPES)
  utils.ForceDictType(nicparams, constants.NICS_PARAMETER_TYPES)

  objects.NIC.CheckParameterSyntax(nicparams)

  full_ipolicy = objects.FillIPolicy(constants.IPOLICY_DEFAULTS, ipolicy)
  _RestrictIpolicyToEnabledDiskTemplates(full_ipolicy, enabled_disk_templates)

  if ndparams is not None:
    utils.ForceDictType(ndparams, constants.NDS_PARAMETER_TYPES)
  else:
    ndparams = dict(constants.NDC_DEFAULTS)

  # This is ugly, as we modify the dict itself
  # FIXME: Make utils.ForceDictType pure functional or write a wrapper
  # around it
  if hv_state:
    for hvname, hvs_data in hv_state.items():
      utils.ForceDictType(hvs_data, constants.HVSTS_PARAMETER_TYPES)
      hv_state[hvname] = objects.Cluster.SimpleFillHvState(hvs_data)
  else:
    hv_state = dict((hvname, constants.HVST_DEFAULTS)
                    for hvname in enabled_hypervisors)

  # FIXME: disk_state has no default values yet
  if disk_state:
    for storage, ds_data in disk_state.items():
      if storage not in constants.DS_VALID_TYPES:
        raise errors.OpPrereqError("Invalid storage type in disk state: %s" %
                                   storage, errors.ECODE_INVAL)
      for ds_name, state in ds_data.items():
        utils.ForceDictType(state, constants.DSS_PARAMETER_TYPES)
        ds_data[ds_name] = objects.Cluster.SimpleFillDiskState(state)

  # hvparams is a mapping of hypervisor->hvparams dict
  for hv_name, hv_params in hvparams.items():
    utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
    hv_class = hypervisor.GetHypervisor(hv_name)
    hv_class.CheckParameterSyntax(hv_params)

  # diskparams is a mapping of disk-template->diskparams dict
  for template, dt_params in diskparams.items():
    param_keys = set(dt_params.keys())
    default_param_keys = set(constants.DISK_DT_DEFAULTS[template].keys())
    if param_keys > default_param_keys:
      unknown_params = param_keys - default_param_keys
      raise errors.OpPrereqError("Invalid parameters for disk template %s:"
                                 " %s" % (template,
                                          utils.CommaJoin(unknown_params)),
                                 errors.ECODE_INVAL)
    utils.ForceDictType(dt_params, constants.DISK_DT_TYPES)
    if template == constants.DT_DRBD8 and vg_name is not None:
      # The default METAVG value is equal to the VG name set at init time,
      # if provided
      dt_params[constants.DRBD_DEFAULT_METAVG] = vg_name

  try:
    utils.VerifyDictOptions(diskparams, constants.DISK_DT_DEFAULTS)
  except errors.OpPrereqError as err:
    raise errors.OpPrereqError("While verify diskparam options: %s" % err,
                               errors.ECODE_INVAL)

  # set up ssh config and /etc/hosts
  rsa_sshkey = ""
  dsa_sshkey = ""
  if os.path.isfile(pathutils.SSH_HOST_RSA_PUB):
    sshline = utils.ReadFile(pathutils.SSH_HOST_RSA_PUB)
    rsa_sshkey = sshline.split(" ")[1]
  if os.path.isfile(pathutils.SSH_HOST_DSA_PUB):
    sshline = utils.ReadFile(pathutils.SSH_HOST_DSA_PUB)
    dsa_sshkey = sshline.split(" ")[1]
  if not rsa_sshkey and not dsa_sshkey:
    raise errors.OpPrereqError("Failed to find SSH public keys",
                               errors.ECODE_ENVIRON)

  if modify_etc_hosts:
    utils.AddHostToEtcHosts(hostname.name, hostname.ip)

  if modify_ssh_setup:
    ssh.InitSSHSetup(ssh_key_type, ssh_key_bits)

  if default_iallocator is not None:
    alloc_script = utils.FindFile(default_iallocator,
                                  constants.IALLOCATOR_SEARCH_PATH,
                                  os.path.isfile)
    if alloc_script is None:
      raise errors.OpPrereqError("Invalid default iallocator script '%s'"
                                 " specified" % default_iallocator,
                                 errors.ECODE_INVAL)
  else:
    # default to htools
    if utils.FindFile(constants.IALLOC_HAIL,
                      constants.IALLOCATOR_SEARCH_PATH,
                      os.path.isfile):
      default_iallocator = constants.IALLOC_HAIL

  # check if we have all the users we need
  try:
    runtime.GetEnts()
  except errors.ConfigurationError as err:
    raise errors.OpPrereqError("Required system user/group missing: %s" %
                               err, errors.ECODE_ENVIRON)

  candidate_certs = {}

  now = time.time()

  if compression_tools is not None:
    cluster.CheckCompressionTools(compression_tools)

  initial_dc_config = dict(active=True,
                           interval=int(constants.MOND_TIME_INTERVAL * 1e6))
  data_collectors = dict(
      (name, initial_dc_config.copy())
      for name in constants.DATA_COLLECTOR_NAMES)

  # init of cluster config file
  cluster_config = objects.Cluster(
    serial_no=1,
    rsahostkeypub=rsa_sshkey,
    dsahostkeypub=dsa_sshkey,
    highest_used_port=(constants.FIRST_DRBD_PORT - 1),
    mac_prefix=mac_prefix,
    volume_group_name=vg_name,
    tcpudp_port_pool=set(),
    master_ip=clustername.ip,
    master_netmask=master_netmask,
    master_netdev=master_netdev,
    cluster_name=clustername.name,
    file_storage_dir=file_storage_dir,
    shared_file_storage_dir=shared_file_storage_dir,
    gluster_storage_dir=gluster_storage_dir,
    enabled_hypervisors=enabled_hypervisors,
    beparams={constants.PP_DEFAULT: beparams},
    nicparams={constants.PP_DEFAULT: nicparams},
    ndparams=ndparams,
    hvparams=hvparams,
    diskparams=diskparams,
    candidate_pool_size=candidate_pool_size,
    modify_etc_hosts=modify_etc_hosts,
    modify_ssh_setup=modify_ssh_setup,
    uid_pool=uid_pool,
    ctime=now,
    mtime=now,
    maintain_node_health=maintain_node_health,
    data_collectors=data_collectors,
    drbd_usermode_helper=drbd_helper,
    default_iallocator=default_iallocator,
    default_iallocator_params=default_iallocator_params,
    primary_ip_family=ipcls.family,
    prealloc_wipe_disks=prealloc_wipe_disks,
    use_external_mip_script=use_external_mip_script,
    ipolicy=full_ipolicy,
    hv_state_static=hv_state,
    disk_state_static=disk_state,
    enabled_disk_templates=enabled_disk_templates,
    candidate_certs=candidate_certs,
    osparams={},
    osparams_private_cluster={},
    install_image=install_image,
    zeroing_image=zeroing_image,
    compression_tools=compression_tools,
    enabled_user_shutdown=enabled_user_shutdown,
    ssh_key_type=ssh_key_type,
    ssh_key_bits=ssh_key_bits,
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
  ssh.WriteKnownHostsFile(cfg, pathutils.SSH_KNOWN_HOSTS_FILE)
  cfg.Update(cfg.GetClusterInfo(), logging.error)
  ssconf.WriteSsconfFiles(cfg.GetSsconfValues())

  master_uuid = cfg.GetMasterNode()
  if modify_ssh_setup:
    ssh.InitPubKeyFile(master_uuid, ssh_key_type)
  # set up the inter-node password and certificate
  _InitGanetiServerSetup(hostname.name, cfg)

  logging.debug("Starting daemons")
  result = utils.RunCmd([pathutils.DAEMON_UTIL, "start-all"])
  if result.failed:
    raise errors.OpExecError("Could not start daemons, command %s"
                             " had exitcode %s and error %s" %
                             (result.cmd, result.exit_code, result.output))

  _WaitForMasterDaemon()


def InitConfig(version, cluster_config, master_node_config,
               cfg_file=pathutils.CLUSTER_CONF_FILE):
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
  cluster_config.master_node = master_node_config.uuid
  nodes = {
    master_node_config.uuid: master_node_config,
    }
  default_nodegroup = objects.NodeGroup(
    uuid=uuid_generator.Generate([], utils.NewUUID, _INITCONF_ECID),
    name=constants.INITIAL_NODE_GROUP_NAME,
    members=[master_node_config.uuid],
    diskparams={},
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
                                   networks={},
                                   disks={},
                                   filters={},
                                   serial_no=1,
                                   ctime=now, mtime=now)
  utils.WriteFile(cfg_file,
                  data=serializer.Dump(config_data.ToDict()),
                  mode=0o600)


def FinalizeClusterDestroy(master_uuid):
  """Execute the last steps of cluster destroy

  This function shuts down all the daemons, completing the destroy
  begun in cmdlib.LUDestroyOpcode.

  """
  livelock = utils.livelock.LiveLock("bootstrap_destroy")
  cfg = config.GetConfig(None, livelock)
  modify_ssh_setup = cfg.GetClusterInfo().modify_ssh_setup
  runner = rpc.BootstrapRunner()

  master_name = cfg.GetNodeName(master_uuid)

  master_params = cfg.GetMasterNetworkParameters()
  master_params.uuid = master_uuid
  ems = cfg.GetUseExternalMipScript()
  result = runner.call_node_deactivate_master_ip(master_name, master_params,
                                                 ems)

  msg = result.fail_msg
  if msg:
    logging.warning("Could not disable the master IP: %s", msg)

  result = runner.call_node_stop_master(master_name)
  msg = result.fail_msg
  if msg:
    logging.warning("Could not disable the master role: %s", msg)

  result = runner.call_node_leave_cluster(master_name, modify_ssh_setup)
  msg = result.fail_msg
  if msg:
    logging.warning("Could not shutdown the node daemon and cleanup"
                    " the node: %s", msg)


def SetupNodeDaemon(opts, cluster_name, node, ssh_port):
  """Add a node to the cluster.

  This function must be called before the actual opcode, and will ssh
  to the remote node, copy the needed files, and start ganeti-noded,
  allowing the master to do the rest via normal rpc calls.

  @param cluster_name: the cluster name
  @param node: the name of the new node
  @param ssh_port: the SSH port of the new node

  """
  data = {
    constants.NDS_CLUSTER_NAME: cluster_name,
    constants.NDS_NODE_DAEMON_CERTIFICATE:
      utils.ReadFile(pathutils.NODED_CERT_FILE),
    constants.NDS_SSCONF: ssconf.SimpleStore().ReadAll(),
    constants.NDS_START_NODE_DAEMON: True,
    constants.NDS_NODE_NAME: node,
    }

  ssh.RunSshCmdWithStdin(cluster_name, node, pathutils.NODE_DAEMON_SETUP,
                         ssh_port, data,
                         debug=opts.debug, verbose=opts.verbose,
                         use_cluster_key=True, ask_key=opts.ssh_key_check,
                         strict_host_check=opts.ssh_key_check,
                         ensure_version=True)

  _WaitForSshDaemon(node, ssh_port)
  _WaitForNodeDaemon(node)


def MasterFailover(no_voting=False):
  """Failover the master node.

  This checks that we are not already the master, and will cause the
  current master to cease being master, and the non-master to become
  new master.

  Note: The call to MasterFailover from lib/client/gnt_cluster.py checks that
  a majority of nodes are healthy and responding before calling this. If this
  function is called from somewhere else, the caller should also verify that a
  majority of nodes are healthy.

  @type no_voting: boolean
  @param no_voting: force the operation without remote nodes agreement
                      (dangerous)

  @returns: the pair of an exit code and warnings to display
  """
  sstore = ssconf.SimpleStore()

  old_master, new_master = ssconf.GetMasterAndMyself(sstore)
  node_names = sstore.GetNodeList()
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
                               "%s" % ("\n".join(mc_no_master)),
                               errors.ECODE_STATE)

  if not no_voting:
    vote_list = _GatherMasterVotes(node_names)
    if vote_list:
      voted_master = vote_list[0][0]
      if voted_master != old_master:
        raise errors.OpPrereqError("I have a wrong configuration, I believe"
                                   " the master is %s but the other nodes"
                                   " voted %s. Please resync the configuration"
                                   " of this node." %
                                   (old_master, voted_master),
                                   errors.ECODE_STATE)
  # end checks

  rcode = 0
  warnings = []

  logging.info("Setting master to %s, old master: %s", new_master, old_master)

  try:
    # Forcefully start WConfd so that we can access the configuration
    result = utils.RunCmd([pathutils.DAEMON_UTIL,
                           "start", constants.WCONFD, "--force-node",
                           "--no-voting", "--yes-do-it"])
    if result.failed:
      raise errors.OpPrereqError("Could not start the configuration daemon,"
                                 " command %s had exitcode %s and error %s" %
                                 (result.cmd, result.exit_code, result.output),
                                 errors.ECODE_NOENT)

    # instantiate a real config writer, as we now know we have the
    # configuration data
    livelock = utils.livelock.LiveLock("bootstrap_failover")
    cfg = config.GetConfig(None, livelock, accept_foreign=True)

    old_master_node = cfg.GetNodeInfoByName(old_master)
    if old_master_node is None:
      raise errors.OpPrereqError("Could not find old master node '%s' in"
                                 " cluster configuration." % old_master,
                                 errors.ECODE_NOENT)

    cluster_info = cfg.GetClusterInfo()
    new_master_node = cfg.GetNodeInfoByName(new_master)
    if new_master_node is None:
      raise errors.OpPrereqError("Could not find new master node '%s' in"
                                 " cluster configuration." % new_master,
                                 errors.ECODE_NOENT)

    cluster_info.master_node = new_master_node.uuid
    # this will also regenerate the ssconf files, since we updated the
    # cluster info
    cfg.Update(cluster_info, logging.error)

    # if cfg.Update worked, then it means the old master daemon won't be
    # able now to write its own config file (we rely on locking in both
    # backend.UploadFile() and ConfigWriter._Write(); hence the next
    # step is to kill the old master

    logging.info("Stopping the master daemon on node %s", old_master)

    runner = rpc.BootstrapRunner()
    master_params = cfg.GetMasterNetworkParameters()
    master_params.uuid = old_master_node.uuid
    ems = cfg.GetUseExternalMipScript()
    result = runner.call_node_deactivate_master_ip(old_master,
                                                   master_params, ems)

    msg = result.fail_msg
    if msg:
      warning = "Could not disable the master IP: %s" % (msg,)
      logging.warning("%s", warning)
      warnings.append(warning)

    result = runner.call_node_stop_master(old_master)
    msg = result.fail_msg
    if msg:
      warning = ("Could not disable the master role on the old master"
                 " %s, please disable manually: %s" % (old_master, msg))
      logging.error("%s", warning)
      warnings.append(warning)
  except errors.ConfigurationError as err:
    logging.error("Error while trying to set the new master: %s",
                  str(err))
    return 1, warnings
  finally:
    # stop WConfd again:
    result = utils.RunCmd([pathutils.DAEMON_UTIL, "stop", constants.WCONFD])
    if result.failed:
      warning = ("Could not stop the configuration daemon,"
                 " command %s had exitcode %s and error %s"
                 % (result.cmd, result.exit_code, result.output))
      logging.error("%s", warning)
      rcode = 1

  logging.info("Checking master IP non-reachability...")

  master_ip = sstore.GetMasterIP()
  total_timeout = 30

  # Here we have a phase where no master should be running
  def _check_ip(expected):
    if netutils.TcpPing(master_ip, constants.DEFAULT_NODED_PORT) != expected:
      raise utils.RetryAgain()

  try:
    utils.Retry(_check_ip, (1, 1.5, 5), total_timeout, args=[False])
  except utils.RetryTimeout:
    warning = ("The master IP is still reachable after %s seconds,"
               " continuing but activating the master IP on the current"
               " node will probably fail" % total_timeout)
    logging.warning("%s", warning)
    warnings.append(warning)
    rcode = 1

  if jstore.CheckDrainFlag():
    logging.info("Undraining job queue")
    jstore.SetDrainFlag(False)

  logging.info("Starting the master daemons on the new master")

  result = rpc.BootstrapRunner().call_node_start_master_daemons(new_master,
                                                                no_voting)
  msg = result.fail_msg
  if msg:
    logging.error("Could not start the master role on the new master"
                  " %s, please check: %s", new_master, msg)
    rcode = 1

  # Finally verify that the new master managed to set up the master IP
  # and warn if it didn't.
  try:
    utils.Retry(_check_ip, (1, 1.5, 5), total_timeout, args=[True])
  except utils.RetryTimeout:
    warning = ("The master IP did not come up within %s seconds; the"
               " cluster should still be working and reachable via %s,"
               " but not via the master IP address"
               % (total_timeout, new_master))
    logging.warning("%s", warning)
    warnings.append(warning)
    rcode = 1

  logging.info("Master failed over from %s to %s", old_master, new_master)
  return rcode, warnings


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


def _GatherMasterVotes(node_names):
  """Check the agreement on who is the master.

  This function will return a list of (node, number of votes), ordered
  by the number of votes.

  Note that the sum of votes is the number of nodes this machine
  knows, whereas the number of entries in the list could be different
  (if some nodes vote for another master).

  @type node_names: list
  @param node_names: the list of nodes to query for master info
  @rtype: list
  @return: list of (node, votes)

  """
  if not node_names:
    # no nodes
    return []
  results = rpc.BootstrapRunner().call_master_node_name(node_names)
  if not isinstance(results, dict):
    # this should not happen (unless internal error in rpc)
    logging.critical("Can't complete rpc call, aborting master startup")
    return [(None, len(node_names))]

  votes = {}
  for (node_name, nres) in results.items():
    msg = nres.fail_msg
    if msg:
      logging.warning("Error contacting node %s: %s", node_name, msg)
      continue
    node = nres.payload
    if not node:
      logging.warning(('Expected a Node, encountered a None. Skipping this'
                       ' voting result.'))
    if node not in votes:
      votes[node] = 1
    else:
      votes[node] += 1

  vote_list = list(votes.items())
  vote_list.sort(key=lambda x: x[1], reverse=True)
  return vote_list


def MajorityHealthy(ignore_offline_nodes=False):
  """Check if the majority of nodes is healthy

  Gather master votes from all nodes known to this node;
  return True if a strict majority of nodes is reachable and
  has some opinion on which node is master. Note that this will
  not guarantee any node to win an election but it ensures that
  a standard master-failover is still possible.

  @return: tuple of (boolean, [str]); the first is if a majority of nodes are
    healthy, the second is a list of the node names that are not considered
    healthy.
  """
  if ignore_offline_nodes:
    node_names = ssconf.SimpleStore().GetOnlineNodeList()
  else:
    node_names = ssconf.SimpleStore().GetNodeList()

  node_count = len(node_names)
  vote_list = _GatherMasterVotes(node_names)

  if not vote_list:
    logging.warning(('Voting list was None; cannot determine if a majority of '
                     'nodes are healthy'))
    return (False, node_names)

  total_votes = sum([count for (node, count) in vote_list if node is not None])
  majority_healthy = 2 * total_votes > node_count

  # The list of nodes that did not vote is calculated to provide useful
  # debugging information to the client.
  voting_nodes = [node for (node, _) in vote_list]
  nonvoting_nodes = [node for node in node_names if node not in voting_nodes]

  logging.info("Total %d nodes, %d votes: %s", node_count, total_votes,
               vote_list)

  return (majority_healthy, nonvoting_nodes)
