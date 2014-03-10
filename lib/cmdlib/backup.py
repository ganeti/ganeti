#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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


"""Logical units dealing with backup operations."""

import urllib2
import OpenSSL
import logging
import math

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import masterd
from ganeti import utils

from ganeti.cmdlib.base import NoHooksLU, LogicalUnit
from ganeti.cmdlib.common import CheckNodeOnline, ExpandNodeUuidAndName
from ganeti.cmdlib.instance_storage import StartInstanceDisks, \
  ShutdownInstanceDisks, TemporaryDisk
from ganeti.cmdlib.instance_utils import GetClusterDomainSecret, \
  BuildInstanceHookEnvByObject, CheckNodeNotDrained, RemoveInstance


class LUBackupPrepare(NoHooksLU):
  """Prepares an instance for an export and returns useful information.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def CheckPrereq(self):
    """Check prerequisites.

    """
    self.instance = self.cfg.GetInstanceInfoByName(self.op.instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, self.instance.primary_node)

    self._cds = GetClusterDomainSecret()

  def Exec(self, feedback_fn):
    """Prepares an instance for an export.

    """
    if self.op.mode == constants.EXPORT_MODE_REMOTE:
      salt = utils.GenerateSecret(8)

      feedback_fn("Generating X509 certificate on %s" %
                  self.cfg.GetNodeName(self.instance.primary_node))
      result = self.rpc.call_x509_cert_create(self.instance.primary_node,
                                              constants.RIE_CERT_VALIDITY)
      result.Raise("Can't create X509 key and certificate on %s" %
                   self.cfg.GetNodeName(result.node))

      (name, cert_pem) = result.payload

      cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                             cert_pem)

      return {
        "handshake": masterd.instance.ComputeRemoteExportHandshake(self._cds),
        "x509_key_name": (name, utils.Sha1Hmac(self._cds, name, salt=salt),
                          salt),
        "x509_ca": utils.SignX509Certificate(cert, self._cds, salt),
        }

    return None


class LUBackupExport(LogicalUnit):
  """Export an instance to an image in the cluster.

  """
  HPATH = "instance-export"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check the arguments.

    """
    self.x509_key_name = self.op.x509_key_name
    self.dest_x509_ca_pem = self.op.destination_x509_ca

    if self.op.mode == constants.EXPORT_MODE_REMOTE:
      if not self.x509_key_name:
        raise errors.OpPrereqError("Missing X509 key name for encryption",
                                   errors.ECODE_INVAL)

      if not self.dest_x509_ca_pem:
        raise errors.OpPrereqError("Missing destination X509 CA",
                                   errors.ECODE_INVAL)

    if self.op.zero_free_space and not self.op.compress:
      raise errors.OpPrereqError("Zeroing free space does not make sense "
                                 "unless compression is used")

    if self.op.zero_free_space and not self.op.shutdown:
      raise errors.OpPrereqError("Unless the instance is shut down, zeroing "
                                 "cannot be used.")

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    # In case we are zeroing, a node lock is required as we will be creating and
    # destroying a disk - allocations should be stopped, but not on the entire
    # cluster
    if self.op.zero_free_space:
      self.recalculate_locks = {locking.LEVEL_NODE: constants.LOCKS_REPLACE}
      self._LockInstancesNodes(primary_only=True)

    # Lock all nodes for local exports
    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      (self.op.target_node_uuid, self.op.target_node) = \
        ExpandNodeUuidAndName(self.cfg, self.op.target_node_uuid,
                              self.op.target_node)
      # FIXME: lock only instance primary and destination node
      #
      # Sad but true, for now we have do lock all nodes, as we don't know where
      # the previous export might be, and in this LU we search for it and
      # remove it from its current node. In the future we could fix this by:
      #  - making a tasklet to search (share-lock all), then create the
      #    new one, then one to remove, after
      #  - removing the removal operation altogether
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

      # Allocations should be stopped while this LU runs with node locks, but
      # it doesn't have to be exclusive
      self.share_locks[locking.LEVEL_NODE_ALLOC] = 1
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def DeclareLocks(self, level):
    """Last minute lock declaration."""
    # All nodes are locked anyway, so nothing to do here.

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on the master, primary node and target node.

    """
    env = {
      "EXPORT_MODE": self.op.mode,
      "EXPORT_NODE": self.op.target_node,
      "EXPORT_DO_SHUTDOWN": self.op.shutdown,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      # TODO: Generic function for boolean env variables
      "REMOVE_INSTANCE": str(bool(self.op.remove_instance)),
      }

    env.update(BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.instance.primary_node]

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      nl.append(self.op.target_node_uuid)

    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance and node names are valid.

    """
    self.instance = self.cfg.GetInstanceInfoByName(self.op.instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, self.instance.primary_node)

    if (self.op.remove_instance and
        self.instance.admin_state == constants.ADMINST_UP and
        not self.op.shutdown):
      raise errors.OpPrereqError("Can not remove instance without shutting it"
                                 " down before", errors.ECODE_STATE)

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      self.dst_node = self.cfg.GetNodeInfo(self.op.target_node_uuid)
      assert self.dst_node is not None

      CheckNodeOnline(self, self.dst_node.uuid)
      CheckNodeNotDrained(self, self.dst_node.uuid)

      self._cds = None
      self.dest_disk_info = None
      self.dest_x509_ca = None

    elif self.op.mode == constants.EXPORT_MODE_REMOTE:
      self.dst_node = None

      if len(self.op.target_node) != len(self.instance.disks):
        raise errors.OpPrereqError(("Received destination information for %s"
                                    " disks, but instance %s has %s disks") %
                                   (len(self.op.target_node),
                                    self.op.instance_name,
                                    len(self.instance.disks)),
                                   errors.ECODE_INVAL)

      cds = GetClusterDomainSecret()

      # Check X509 key name
      try:
        (key_name, hmac_digest, hmac_salt) = self.x509_key_name
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid data for X509 key name: %s" % err,
                                   errors.ECODE_INVAL)

      if not utils.VerifySha1Hmac(cds, key_name, hmac_digest, salt=hmac_salt):
        raise errors.OpPrereqError("HMAC for X509 key name is wrong",
                                   errors.ECODE_INVAL)

      # Load and verify CA
      try:
        (cert, _) = utils.LoadSignedX509Certificate(self.dest_x509_ca_pem, cds)
      except OpenSSL.crypto.Error, err:
        raise errors.OpPrereqError("Unable to load destination X509 CA (%s)" %
                                   (err, ), errors.ECODE_INVAL)

      (errcode, msg) = utils.VerifyX509Certificate(cert, None, None)
      if errcode is not None:
        raise errors.OpPrereqError("Invalid destination X509 CA (%s)" %
                                   (msg, ), errors.ECODE_INVAL)

      self.dest_x509_ca = cert

      # Verify target information
      disk_info = []
      for idx, disk_data in enumerate(self.op.target_node):
        try:
          (host, port, magic) = \
            masterd.instance.CheckRemoteExportDiskInfo(cds, idx, disk_data)
        except errors.GenericError, err:
          raise errors.OpPrereqError("Target info for disk %s: %s" %
                                     (idx, err), errors.ECODE_INVAL)

        disk_info.append((host, port, magic))

      assert len(disk_info) == len(self.op.target_node)
      self.dest_disk_info = disk_info

    else:
      raise errors.ProgrammerError("Unhandled export mode %r" %
                                   self.op.mode)

    # instance disk type verification
    # TODO: Implement export support for file-based disks
    for disk in self.instance.disks:
      if disk.dev_type in constants.DTS_FILEBASED:
        raise errors.OpPrereqError("Export not supported for instances with"
                                   " file-based disks", errors.ECODE_INVAL)

    # Check prerequisites for zeroing
    if self.op.zero_free_space:
      # Check that user shutdown detection has been enabled
      hvparams = self.cfg.GetClusterInfo().FillHV(self.instance)
      if self.instance.hypervisor == constants.HT_KVM and \
         not hvparams.get(constants.HV_KVM_USER_SHUTDOWN, False):
        raise errors.OpPrereqError("Instance shutdown detection must be "
                                   "enabled for zeroing to work")

      # Check that the instance is set to boot from the disk
      if constants.HV_BOOT_ORDER in hvparams and \
         hvparams[constants.HV_BOOT_ORDER] != constants.HT_BO_DISK:
        raise errors.OpPrereqError("Booting from disk must be set for zeroing "
                                   "to work")

      # Check that the zeroing image is set
      if not self.cfg.GetZeroingImage():
        raise errors.OpPrereqError("A zeroing image must be set for zeroing to"
                                   " work")

      if self.op.zeroing_timeout_fixed is None:
        self.op.zeroing_timeout_fixed = constants.HELPER_VM_STARTUP

      if self.op.zeroing_timeout_per_mib is None:
        self.op.zeroing_timeout_per_mib = constants.ZEROING_TIMEOUT_PER_MIB

    else:
      if (self.op.zeroing_timeout_fixed is not None or
          self.op.zeroing_timeout_per_mib is not None):
        raise errors.OpPrereqError("Zeroing timeout options can only be used"
                                   " only with the --zero-free-space option")

  def _CleanupExports(self, feedback_fn):
    """Removes exports of current instance from all other nodes.

    If an instance in a cluster with nodes A..D was exported to node C, its
    exports will be removed from the nodes A, B and D.

    """
    assert self.op.mode != constants.EXPORT_MODE_REMOTE

    node_uuids = self.cfg.GetNodeList()
    node_uuids.remove(self.dst_node.uuid)

    # on one-node clusters nodelist will be empty after the removal
    # if we proceed the backup would be removed because OpBackupQuery
    # substitutes an empty list with the full cluster node list.
    iname = self.instance.name
    if node_uuids:
      feedback_fn("Removing old exports for instance %s" % iname)
      exportlist = self.rpc.call_export_list(node_uuids)
      for node_uuid in exportlist:
        if exportlist[node_uuid].fail_msg:
          continue
        if iname in exportlist[node_uuid].payload:
          msg = self.rpc.call_export_remove(node_uuid, iname).fail_msg
          if msg:
            self.LogWarning("Could not remove older export for instance %s"
                            " on node %s: %s", iname,
                            self.cfg.GetNodeName(node_uuid), msg)

  def _DetermineImageSize(self, image_path, node_uuid):
    """ Determines the size of the specified image.

    @type image_path: string
    @param image_path: The disk path or a URL of an image.
    @type node_uuid: string
    @param node_uuid: If a file path is used,

    @raise OpExecError: If the image does not exist.

    @rtype: int
    @return: The size in MB, rounded up.

    """
    # Check if we are dealing with a URL first
    class _HeadRequest(urllib2.Request):
      def get_method(self):
        return "HEAD"

    if utils.IsUrl(image_path):
      try:
        response = urllib2.urlopen(_HeadRequest(image_path))
      except urllib2.URLError:
        raise errors.OpExecError("Could not retrieve image from given url %s" %
                                 image_path)

      content_length_str = response.info().getheader('content-length')

      if not content_length_str:
        raise errors.OpExecError(
          "Cannot create temporary disk: size of zeroing image at path %s "
          "could not be retrieved through HEAD request" % image_path
        )

      byte_size = int(content_length_str)
    else:
      # We end up here if a file path is used
      result = self.rpc.call_get_file_info(node_uuid, image_path)
      result.Raise("Cannot determine the size of file %s" % image_path)

      success, attributes = result.payload
      if not success:
        raise errors.OpExecError("Could not open file %s" % image_path)
      byte_size = attributes[constants.STAT_SIZE]

    # Finally, the conversion
    return math.ceil(byte_size / 1024. / 1024.)

  def ZeroFreeSpace(self, feedback_fn):
    """Zeroes the free space on a shutdown instance.

    @type feedback_fn: function
    @param feedback_fn: Function used to log progress

    """
    assert self.op.zeroing_timeout_fixed is not None
    assert self.op.zeroing_timeout_per_mib is not None

    zeroing_image = self.cfg.GetZeroingImage()
    src_node_uuid = self.instance.primary_node
    disk_size = self._DetermineImageSize(zeroing_image, src_node_uuid)

    with TemporaryDisk(self, self.instance, disk_size, feedback_fn) as _disk:
      pass

  def Exec(self, feedback_fn):
    """Export an instance to an image in the cluster.

    """
    assert self.op.mode in constants.EXPORT_MODES

    src_node_uuid = self.instance.primary_node

    if self.op.shutdown:
      # shutdown the instance, but not the disks
      feedback_fn("Shutting down instance %s" % self.instance.name)
      result = self.rpc.call_instance_shutdown(src_node_uuid, self.instance,
                                               self.op.shutdown_timeout,
                                               self.op.reason)
      # TODO: Maybe ignore failures if ignore_remove_failures is set
      result.Raise("Could not shutdown instance %s on"
                   " node %s" % (self.instance.name,
                                 self.cfg.GetNodeName(src_node_uuid)))

    if self.op.zero_free_space:
      self.ZeroFreeSpace(feedback_fn)

    activate_disks = not self.instance.disks_active

    if activate_disks:
      # Activate the instance disks if we're exporting a stopped instance
      feedback_fn("Activating disks for %s" % self.instance.name)
      StartInstanceDisks(self, self.instance, None)
      self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

    try:
      helper = masterd.instance.ExportInstanceHelper(self, feedback_fn,
                                                     self.instance)

      helper.CreateSnapshots()
      try:
        if (self.op.shutdown and
            self.instance.admin_state == constants.ADMINST_UP and
            not self.op.remove_instance):
          assert self.instance.disks_active
          feedback_fn("Starting instance %s" % self.instance.name)
          result = self.rpc.call_instance_start(src_node_uuid,
                                                (self.instance, None, None),
                                                False, self.op.reason)
          msg = result.fail_msg
          if msg:
            feedback_fn("Failed to start instance: %s" % msg)
            ShutdownInstanceDisks(self, self.instance)
            raise errors.OpExecError("Could not start instance: %s" % msg)

        if self.op.mode == constants.EXPORT_MODE_LOCAL:
          (fin_resu, dresults) = helper.LocalExport(self.dst_node,
                                                    self.op.compress)
        elif self.op.mode == constants.EXPORT_MODE_REMOTE:
          connect_timeout = constants.RIE_CONNECT_TIMEOUT
          timeouts = masterd.instance.ImportExportTimeouts(connect_timeout)

          (key_name, _, _) = self.x509_key_name

          dest_ca_pem = \
            OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                            self.dest_x509_ca)

          (fin_resu, dresults) = helper.RemoteExport(self.dest_disk_info,
                                                     key_name, dest_ca_pem,
                                                     self.op.compress,
                                                     timeouts)
      finally:
        helper.Cleanup()

      # Check for backwards compatibility
      assert len(dresults) == len(self.instance.disks)
      assert compat.all(isinstance(i, bool) for i in dresults), \
             "Not all results are boolean: %r" % dresults

    finally:
      if activate_disks:
        feedback_fn("Deactivating disks for %s" % self.instance.name)
        ShutdownInstanceDisks(self, self.instance)

    if not (compat.all(dresults) and fin_resu):
      failures = []
      if not fin_resu:
        failures.append("export finalization")
      if not compat.all(dresults):
        fdsk = utils.CommaJoin(idx for (idx, dsk) in enumerate(dresults)
                               if not dsk)
        failures.append("disk export: disk(s) %s" % fdsk)

      raise errors.OpExecError("Export failed, errors in %s" %
                               utils.CommaJoin(failures))

    # At this point, the export was successful, we can cleanup/finish

    # Remove instance if requested
    if self.op.remove_instance:
      feedback_fn("Removing instance %s" % self.instance.name)
      RemoveInstance(self, feedback_fn, self.instance,
                     self.op.ignore_remove_failures)

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      self._CleanupExports(feedback_fn)

    return fin_resu, dresults


class LUBackupRemove(NoHooksLU):
  """Remove exports related to the named instance.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      # We need all nodes to be locked in order for RemoveExport to work, but
      # we don't need to lock the instance itself, as nothing will happen to it
      # (and we can remove exports also for a removed instance)
      locking.LEVEL_NODE: locking.ALL_SET,

      # Removing backups is quick, so blocking allocations is justified
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    # Allocations should be stopped while this LU runs with node locks, but it
    # doesn't have to be exclusive
    self.share_locks[locking.LEVEL_NODE_ALLOC] = 1

  def Exec(self, feedback_fn):
    """Remove any export.

    """
    (_, inst_name) = self.cfg.ExpandInstanceName(self.op.instance_name)
    # If the instance was not found we'll try with the name that was passed in.
    # This will only work if it was an FQDN, though.
    fqdn_warn = False
    if not inst_name:
      fqdn_warn = True
      inst_name = self.op.instance_name

    locked_nodes = self.owned_locks(locking.LEVEL_NODE)
    exportlist = self.rpc.call_export_list(locked_nodes)
    found = False
    for node_uuid in exportlist:
      msg = exportlist[node_uuid].fail_msg
      if msg:
        self.LogWarning("Failed to query node %s (continuing): %s",
                        self.cfg.GetNodeName(node_uuid), msg)
        continue
      if inst_name in exportlist[node_uuid].payload:
        found = True
        result = self.rpc.call_export_remove(node_uuid, inst_name)
        msg = result.fail_msg
        if msg:
          logging.error("Could not remove export for instance %s"
                        " on node %s: %s", inst_name,
                        self.cfg.GetNodeName(node_uuid), msg)

    if fqdn_warn and not found:
      feedback_fn("Export not found. If trying to remove an export belonging"
                  " to a deleted instance please use its Fully Qualified"
                  " Domain Name.")
