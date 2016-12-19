#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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

"""Logical unit for creating a single instance."""

import logging
import os

import OpenSSL

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti.masterd import iallocator
from ganeti import masterd
from ganeti import netutils
from ganeti import objects
from ganeti import pathutils
from ganeti import utils
from ganeti import serializer

from ganeti.cmdlib.base import LogicalUnit

from ganeti.cmdlib.common import \
  CheckNodeOnline, \
  CheckParamsNotGlobal, \
  IsExclusiveStorageEnabledNode, CheckHVParams, CheckOSParams, \
  ExpandNodeUuidAndName, \
  IsValidDiskAccessModeCombination, \
  CheckDiskTemplateEnabled, CheckIAllocatorOrNode, CheckOSImage
from ganeti.cmdlib.instance_helpervm import RunWithHelperVM
from ganeti.cmdlib.instance_storage import CalculateFileStorageDir, \
  CheckNodesFreeDiskPerVG, CheckRADOSFreeSpace, CheckSpindlesExclusiveStorage, \
  ComputeDiskSizePerVG, CreateDisks, \
  GenerateDiskTemplate, CommitDisks, \
  WaitForSync, ComputeDisks, \
  ImageDisks, WipeDisks
from ganeti.cmdlib.instance_utils import \
  CheckNodeNotDrained, CopyLockList, \
  ReleaseLocks, CheckNodeVmCapable, \
  RemoveDisks, CheckNodeFreeMemory, \
  UpdateMetadata, CheckForConflictingIp, \
  ComputeInstanceCommunicationNIC, \
  ComputeIPolicyInstanceSpecViolation, \
  CheckHostnameSane, CheckOpportunisticLocking, \
  ComputeFullBeParams, ComputeNics, GetClusterDomainSecret, \
  CheckInstanceExistence, CreateInstanceAllocRequest, BuildInstanceHookEnv, \
  NICListToTuple, CheckNicsBridgesExist, CheckCompressionTool
import ganeti.masterd.instance


def _ValidateTrunkVLAN(vlan):
  if not compat.all(vl.isdigit() for vl in vlan[1:].split(':')):
    raise errors.OpPrereqError("Specified VLAN parameter is invalid"
                               " : %s" % vlan, errors.ECODE_INVAL)


class LUInstanceCreate(LogicalUnit):
  """Create an instance.

  """
  HPATH = "instance-add"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def _CheckDiskTemplateValid(self):
    """Checks validity of disk template.

    """
    cluster = self.cfg.GetClusterInfo()
    if self.op.disk_template is None:
      # FIXME: It would be better to take the default disk template from the
      # ipolicy, but for the ipolicy we need the primary node, which we get from
      # the iallocator, which wants the disk template as input. To solve this
      # chicken-and-egg problem, it should be possible to specify just a node
      # group from the iallocator and take the ipolicy from that.
      self.op.disk_template = cluster.enabled_disk_templates[0]
    CheckDiskTemplateEnabled(cluster, self.op.disk_template)

  def _CheckDiskArguments(self):
    """Checks validity of disk-related arguments.

    """
    # check that disk's names are unique and valid
    utils.ValidateDeviceNames("disk", self.op.disks)

    self._CheckDiskTemplateValid()

    # check disks. parameter names and consistent adopt/no-adopt strategy
    has_adopt = has_no_adopt = False
    for disk in self.op.disks:
      if self.op.disk_template != constants.DT_EXT:
        utils.ForceDictType(disk, constants.IDISK_PARAMS_TYPES)
      if constants.IDISK_ADOPT in disk: # pylint: disable=R0102
        has_adopt = True
      else:
        has_no_adopt = True
    if has_adopt and has_no_adopt:
      raise errors.OpPrereqError("Either all disks are adopted or none is",
                                 errors.ECODE_INVAL)
    if has_adopt:
      if self.op.disk_template not in constants.DTS_MAY_ADOPT:
        raise errors.OpPrereqError("Disk adoption is not supported for the"
                                   " '%s' disk template" %
                                   self.op.disk_template,
                                   errors.ECODE_INVAL)
      if self.op.iallocator is not None:
        raise errors.OpPrereqError("Disk adoption not allowed with an"
                                   " iallocator script", errors.ECODE_INVAL)
      if self.op.mode == constants.INSTANCE_IMPORT:
        raise errors.OpPrereqError("Disk adoption not allowed for"
                                   " instance import", errors.ECODE_INVAL)
    else:
      if self.op.disk_template in constants.DTS_MUST_ADOPT:
        raise errors.OpPrereqError("Disk template %s requires disk adoption,"
                                   " but no 'adopt' parameter given" %
                                   self.op.disk_template,
                                   errors.ECODE_INVAL)

    self.adopt_disks = has_adopt

  def _CheckVLANArguments(self):
    """ Check validity of VLANs if given

    """
    for nic in self.op.nics:
      vlan = nic.get(constants.INIC_VLAN, None)
      if vlan:
        if vlan[0] == ".":
          # vlan starting with dot means single untagged vlan,
          # might be followed by trunk (:)
          if not vlan[1:].isdigit():
            _ValidateTrunkVLAN(vlan)
        elif vlan[0] == ":":
          # Trunk - tagged only
          _ValidateTrunkVLAN(vlan)
        elif vlan.isdigit():
          # This is the simplest case. No dots, only single digit
          # -> Create untagged access port, dot needs to be added
          nic[constants.INIC_VLAN] = "." + vlan
        else:
          raise errors.OpPrereqError("Specified VLAN parameter is invalid"
                                       " : %s" % vlan, errors.ECODE_INVAL)

  def CheckArguments(self):
    """Check arguments.

    """
    if self.op.forthcoming and self.op.commit:
      raise errors.OpPrereqError("Forthcoming generation and commiting are"
                                 " mutually exclusive", errors.ECODE_INVAL)

    # do not require name_check to ease forward/backward compatibility
    # for tools
    if self.op.no_install and self.op.start:
      self.LogInfo("No-installation mode selected, disabling startup")
      self.op.start = False
    # validate/normalize the instance name
    self.op.instance_name = \
      netutils.Hostname.GetNormalizedName(self.op.instance_name)

    if self.op.ip_check and not self.op.name_check:
      # TODO: make the ip check more flexible and not depend on the name check
      raise errors.OpPrereqError("Cannot do IP address check without a name"
                                 " check", errors.ECODE_INVAL)

    # instance name verification
    if self.op.name_check:
      self.hostname = CheckHostnameSane(self, self.op.instance_name)
      self.op.instance_name = self.hostname.name
      # used in CheckPrereq for ip ping check
      self.check_ip = self.hostname.ip
    else:
      self.check_ip = None

    # add NIC for instance communication
    if self.op.instance_communication:
      nic_name = ComputeInstanceCommunicationNIC(self.op.instance_name)

      for nic in self.op.nics:
        if nic.get(constants.INIC_NAME, None) == nic_name:
          break
      else:
        self.op.nics.append({constants.INIC_NAME: nic_name,
                             constants.INIC_MAC: constants.VALUE_GENERATE,
                             constants.INIC_IP: constants.NIC_IP_POOL,
                             constants.INIC_NETWORK:
                               self.cfg.GetInstanceCommunicationNetwork()})

    # timeouts for unsafe OS installs
    if self.op.helper_startup_timeout is None:
      self.op.helper_startup_timeout = constants.HELPER_VM_STARTUP

    if self.op.helper_shutdown_timeout is None:
      self.op.helper_shutdown_timeout = constants.HELPER_VM_SHUTDOWN

    # check nics' parameter names
    for nic in self.op.nics:
      utils.ForceDictType(nic, constants.INIC_PARAMS_TYPES)
    # check that NIC's parameters names are unique and valid
    utils.ValidateDeviceNames("NIC", self.op.nics)

    self._CheckVLANArguments()

    self._CheckDiskArguments()
    assert self.op.disk_template is not None

    # file storage checks
    if (self.op.file_driver and
        not self.op.file_driver in constants.FILE_DRIVER):
      raise errors.OpPrereqError("Invalid file driver name '%s'" %
                                 self.op.file_driver, errors.ECODE_INVAL)

    # set default file_driver if unset and required
    if (not self.op.file_driver and
        self.op.disk_template in constants.DTS_FILEBASED):
      self.op.file_driver = constants.FD_DEFAULT

    ### Node/iallocator related checks
    CheckIAllocatorOrNode(self, "iallocator", "pnode")

    if self.op.pnode is not None:
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        if self.op.snode is None:
          raise errors.OpPrereqError("The networked disk templates need"
                                     " a mirror node", errors.ECODE_INVAL)
      elif self.op.snode:
        self.LogWarning("Secondary node will be ignored on non-mirrored disk"
                        " template")
        self.op.snode = None

    CheckOpportunisticLocking(self.op)

    if self.op.mode == constants.INSTANCE_IMPORT:
      # On import force_variant must be True, because if we forced it at
      # initial install, our only chance when importing it back is that it
      # works again!
      self.op.force_variant = True

      if self.op.no_install:
        self.LogInfo("No-installation mode has no effect during import")

      if objects.GetOSImage(self.op.osparams):
        self.LogInfo("OS image has no effect during import")
    elif self.op.mode == constants.INSTANCE_CREATE:
      os_image = CheckOSImage(self.op)

      if self.op.os_type is None and os_image is None:
        raise errors.OpPrereqError("No guest OS or OS image specified",
                                   errors.ECODE_INVAL)

      if self.op.os_type is not None \
            and self.op.os_type in self.cfg.GetClusterInfo().blacklisted_os:
        raise errors.OpPrereqError("Guest OS '%s' is not allowed for"
                                   " installation" % self.op.os_type,
                                   errors.ECODE_STATE)
    elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
      if objects.GetOSImage(self.op.osparams):
        self.LogInfo("OS image has no effect during import")

      self._cds = GetClusterDomainSecret()

      # Check handshake to ensure both clusters have the same domain secret
      src_handshake = self.op.source_handshake
      if not src_handshake:
        raise errors.OpPrereqError("Missing source handshake",
                                   errors.ECODE_INVAL)

      errmsg = masterd.instance.CheckRemoteExportHandshake(self._cds,
                                                           src_handshake)
      if errmsg:
        raise errors.OpPrereqError("Invalid handshake: %s" % errmsg,
                                   errors.ECODE_INVAL)

      # Load and check source CA
      self.source_x509_ca_pem = self.op.source_x509_ca
      if not self.source_x509_ca_pem:
        raise errors.OpPrereqError("Missing source X509 CA",
                                   errors.ECODE_INVAL)

      try:
        (cert, _) = utils.LoadSignedX509Certificate(self.source_x509_ca_pem,
                                                    self._cds)
      except OpenSSL.crypto.Error, err:
        raise errors.OpPrereqError("Unable to load source X509 CA (%s)" %
                                   (err, ), errors.ECODE_INVAL)

      (errcode, msg) = utils.VerifyX509Certificate(cert, None, None)
      if errcode is not None:
        raise errors.OpPrereqError("Invalid source X509 CA (%s)" % (msg, ),
                                   errors.ECODE_INVAL)

      self.source_x509_ca = cert

      src_instance_name = self.op.source_instance_name
      if not src_instance_name:
        raise errors.OpPrereqError("Missing source instance name",
                                   errors.ECODE_INVAL)

      self.source_instance_name = \
        netutils.GetHostname(name=src_instance_name).name

    else:
      raise errors.OpPrereqError("Invalid instance creation mode %r" %
                                 self.op.mode, errors.ECODE_INVAL)

  def ExpandNames(self):
    """ExpandNames for CreateInstance.

    Figure out the right locks for instance creation.

    """
    self.needed_locks = {}

    if self.op.commit:
      (uuid, name) = self.cfg.ExpandInstanceName(self.op.instance_name)
      if name is None:
        raise errors.OpPrereqError("Instance %s unknown" %
                                   self.op.instance_name,
                                   errors.ECODE_INVAL)
      self.op.instance_name = name
      if not self.cfg.GetInstanceInfo(uuid).forthcoming:
        raise errors.OpPrereqError("Instance %s (with uuid %s) not forthcoming"
                                   " but --commit was passed." % (name, uuid),
                                   errors.ECODE_STATE)
      logging.debug("Verified that instance %s with uuid %s is forthcoming",
                    name, uuid)
    else:
      # this is just a preventive check, but someone might still add this
      # instance in the meantime; we check again in CheckPrereq
      CheckInstanceExistence(self, self.op.instance_name)

    self.add_locks[locking.LEVEL_INSTANCE] = self.op.instance_name

    if self.op.commit:
      (uuid, _) = self.cfg.ExpandInstanceName(self.op.instance_name)
      self.needed_locks[locking.LEVEL_NODE] = self.cfg.GetInstanceNodes(uuid)
      logging.debug("Forthcoming instance %s resides on %s", uuid,
                    self.needed_locks[locking.LEVEL_NODE])
    elif self.op.iallocator:
      # TODO: Find a solution to not lock all nodes in the cluster, e.g. by
      # specifying a group on instance creation and then selecting nodes from
      # that group
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

      if self.op.opportunistic_locking:
        self.opportunistic_locks[locking.LEVEL_NODE] = True
        self.opportunistic_locks[locking.LEVEL_NODE_RES] = True
        if self.op.disk_template == constants.DT_DRBD8:
          self.opportunistic_locks_count[locking.LEVEL_NODE] = 2
          self.opportunistic_locks_count[locking.LEVEL_NODE_RES] = 2
    else:
      (self.op.pnode_uuid, self.op.pnode) = \
        ExpandNodeUuidAndName(self.cfg, self.op.pnode_uuid, self.op.pnode)
      nodelist = [self.op.pnode_uuid]
      if self.op.snode is not None:
        (self.op.snode_uuid, self.op.snode) = \
          ExpandNodeUuidAndName(self.cfg, self.op.snode_uuid, self.op.snode)
        nodelist.append(self.op.snode_uuid)
      self.needed_locks[locking.LEVEL_NODE] = nodelist

    # in case of import lock the source node too
    if self.op.mode == constants.INSTANCE_IMPORT:
      src_node = self.op.src_node
      src_path = self.op.src_path

      if src_path is None:
        self.op.src_path = src_path = self.op.instance_name

      if src_node is None:
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        self.op.src_node = None
        if os.path.isabs(src_path):
          raise errors.OpPrereqError("Importing an instance from a path"
                                     " requires a source node option",
                                     errors.ECODE_INVAL)
      else:
        (self.op.src_node_uuid, self.op.src_node) = (_, src_node) = \
          ExpandNodeUuidAndName(self.cfg, self.op.src_node_uuid, src_node)
        if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
          self.needed_locks[locking.LEVEL_NODE].append(self.op.src_node_uuid)
        if not os.path.isabs(src_path):
          self.op.src_path = \
            utils.PathJoin(pathutils.EXPORT_DIR, src_path)

    self.needed_locks[locking.LEVEL_NODE_RES] = \
      CopyLockList(self.needed_locks[locking.LEVEL_NODE])

    # Optimistically acquire shared group locks (we're reading the
    # configuration).  We can't just call GetInstanceNodeGroups, because the
    # instance doesn't exist yet. Therefore we lock all node groups of all
    # nodes we have.
    if self.needed_locks[locking.LEVEL_NODE] == locking.ALL_SET:
      # In the case we lock all nodes for opportunistic allocation, we have no
      # choice than to lock all groups, because they're allocated before nodes.
      # This is sad, but true. At least we release all those we don't need in
      # CheckPrereq later.
      self.needed_locks[locking.LEVEL_NODEGROUP] = locking.ALL_SET
    else:
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        list(self.cfg.GetNodeGroupsFromNodes(
          self.needed_locks[locking.LEVEL_NODE]))
    self.share_locks[locking.LEVEL_NODEGROUP] = 1

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE_RES:
      if self.op.opportunistic_locking:
        self.needed_locks[locking.LEVEL_NODE_RES] = \
          CopyLockList(list(self.owned_locks(locking.LEVEL_NODE)))

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    if self.op.opportunistic_locking:
      # Only consider nodes for which a lock is held
      node_name_whitelist = self.cfg.GetNodeNames(
        set(self.owned_locks(locking.LEVEL_NODE)) &
        set(self.owned_locks(locking.LEVEL_NODE_RES)))
      logging.debug("Trying to allocate on nodes %s", node_name_whitelist)
    else:
      node_name_whitelist = None

    req = CreateInstanceAllocRequest(self.op, self.disks,
                                     self.nics, self.be_full,
                                     node_name_whitelist)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      # When opportunistic locks are used only a temporary failure is generated
      if self.op.opportunistic_locking:
        ecode = errors.ECODE_TEMP_NORES
        self.LogInfo("IAllocator '%s' failed on opportunistically acquired"
                     " nodes: %s", self.op.iallocator, ial.info)
      else:
        ecode = errors.ECODE_NORES

      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 ecode)

    (self.op.pnode_uuid, self.op.pnode) = ExpandNodeUuidAndName(
        self.cfg, None, ial.result[0]) # pylint: disable=E1136
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(ial.result))

    assert req.RequiredNodes() in (1, 2), "Wrong node count from iallocator"

    if req.RequiredNodes() == 2:
      (self.op.snode_uuid, self.op.snode) = ExpandNodeUuidAndName(
          self.cfg, None, ial.result[1]) # pylint: disable=E1136

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "ADD_MODE": self.op.mode,
      }
    if self.op.mode == constants.INSTANCE_IMPORT:
      env["SRC_NODE"] = self.op.src_node
      env["SRC_PATH"] = self.op.src_path
      env["SRC_IMAGES"] = self.src_images

    env.update(BuildInstanceHookEnv(
      name=self.op.instance_name,
      primary_node_name=self.op.pnode,
      secondary_node_names=self.cfg.GetNodeNames(self.secondaries),
      status=self.op.start,
      os_type=self.op.os_type,
      minmem=self.be_full[constants.BE_MINMEM],
      maxmem=self.be_full[constants.BE_MAXMEM],
      vcpus=self.be_full[constants.BE_VCPUS],
      nics=NICListToTuple(self, self.nics),
      disk_template=self.op.disk_template,
      # Note that self.disks here is not a list with objects.Disk
      # but with dicts as returned by ComputeDisks.
      disks=self.disks,
      bep=self.be_full,
      hvp=self.hv_full,
      hypervisor_name=self.op.hypervisor,
      tags=self.op.tags,
      ))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.op.pnode_uuid] + self.secondaries
    return nl, nl

  def _ReadExportInfo(self):
    """Reads the export information from disk.

    It will override the opcode source node and path with the actual
    information, if these two were not specified before.

    @return: the export information

    """
    assert self.op.mode == constants.INSTANCE_IMPORT

    if self.op.src_node_uuid is None:
      locked_nodes = self.owned_locks(locking.LEVEL_NODE)
      exp_list = self.rpc.call_export_list(locked_nodes)
      found = False
      for node_uuid in exp_list:
        if exp_list[node_uuid].fail_msg:
          continue
        if self.op.src_path in exp_list[node_uuid].payload:
          found = True
          self.op.src_node = self.cfg.GetNodeInfo(node_uuid).name
          self.op.src_node_uuid = node_uuid
          self.op.src_path = utils.PathJoin(pathutils.EXPORT_DIR,
                                            self.op.src_path)
          break
      if not found:
        raise errors.OpPrereqError("No export found for relative path %s" %
                                   self.op.src_path, errors.ECODE_INVAL)

    CheckNodeOnline(self, self.op.src_node_uuid)
    result = self.rpc.call_export_info(self.op.src_node_uuid, self.op.src_path)
    result.Raise("No export or invalid export found in dir %s" %
                 self.op.src_path)

    export_info = objects.SerializableConfigParser.Loads(str(result.payload))
    if not export_info.has_section(constants.INISECT_EXP):
      raise errors.ProgrammerError("Corrupted export config",
                                   errors.ECODE_ENVIRON)

    ei_version = export_info.get(constants.INISECT_EXP, "version")
    if int(ei_version) != constants.EXPORT_VERSION:
      raise errors.OpPrereqError("Wrong export version %s (wanted %d)" %
                                 (ei_version, constants.EXPORT_VERSION),
                                 errors.ECODE_ENVIRON)
    return export_info

  def _ReadExportParams(self, einfo):
    """Use export parameters as defaults.

    In case the opcode doesn't specify (as in override) some instance
    parameters, then try to use them from the export information, if
    that declares them.

    """
    self.op.os_type = einfo.get(constants.INISECT_EXP, "os")

    if not self.op.disks:
      disks = []
      # TODO: import the disk iv_name too
      for idx in range(constants.MAX_DISKS):
        if einfo.has_option(constants.INISECT_INS, "disk%d_size" % idx):
          disk_sz = einfo.getint(constants.INISECT_INS, "disk%d_size" % idx)
          disk_name = einfo.get(constants.INISECT_INS, "disk%d_name" % idx)
          disk = {
            constants.IDISK_SIZE: disk_sz,
            constants.IDISK_NAME: disk_name
            }
          disks.append(disk)
      self.op.disks = disks
      if not disks and self.op.disk_template != constants.DT_DISKLESS:
        raise errors.OpPrereqError("No disk info specified and the export"
                                   " is missing the disk information",
                                   errors.ECODE_INVAL)

    if not self.op.nics:
      nics = []
      for idx in range(constants.MAX_NICS):
        if einfo.has_option(constants.INISECT_INS, "nic%d_mac" % idx):
          ndict = {}
          for name in [constants.INIC_IP,
                       constants.INIC_MAC, constants.INIC_NAME]:
            nic_param_name = "nic%d_%s" % (idx, name)
            if einfo.has_option(constants.INISECT_INS, nic_param_name):
              v = einfo.get(constants.INISECT_INS, "nic%d_%s" % (idx, name))
              ndict[name] = v
          network = einfo.get(constants.INISECT_INS,
                              "nic%d_%s" % (idx, constants.INIC_NETWORK))
          # in case network is given link and mode are inherited
          # from nodegroup's netparams and thus should not be passed here
          if network:
            ndict[constants.INIC_NETWORK] = network
          else:
            for name in list(constants.NICS_PARAMETERS):
              v = einfo.get(constants.INISECT_INS, "nic%d_%s" % (idx, name))
              ndict[name] = v
          nics.append(ndict)
        else:
          break
      self.op.nics = nics

    if not self.op.tags and einfo.has_option(constants.INISECT_INS, "tags"):
      self.op.tags = einfo.get(constants.INISECT_INS, "tags").split()

    if (self.op.hypervisor is None and
        einfo.has_option(constants.INISECT_INS, "hypervisor")):
      self.op.hypervisor = einfo.get(constants.INISECT_INS, "hypervisor")

    if einfo.has_section(constants.INISECT_HYP):
      # use the export parameters but do not override the ones
      # specified by the user
      for name, value in einfo.items(constants.INISECT_HYP):
        if name not in self.op.hvparams:
          self.op.hvparams[name] = value

    if einfo.has_section(constants.INISECT_BEP):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_BEP):
        if name not in self.op.beparams:
          self.op.beparams[name] = value
        # Compatibility for the old "memory" be param
        if name == constants.BE_MEMORY:
          if constants.BE_MAXMEM not in self.op.beparams:
            self.op.beparams[constants.BE_MAXMEM] = value
          if constants.BE_MINMEM not in self.op.beparams:
            self.op.beparams[constants.BE_MINMEM] = value
    else:
      # try to read the parameters old style, from the main section
      for name in constants.BES_PARAMETERS:
        if (name not in self.op.beparams and
            einfo.has_option(constants.INISECT_INS, name)):
          self.op.beparams[name] = einfo.get(constants.INISECT_INS, name)

    if einfo.has_section(constants.INISECT_OSP):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_OSP):
        if name not in self.op.osparams:
          self.op.osparams[name] = value

    if einfo.has_section(constants.INISECT_OSP_PRIVATE):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_OSP_PRIVATE):
        if name not in self.op.osparams_private:
          self.op.osparams_private[name] = serializer.Private(value, descr=name)

  def _RevertToDefaults(self, cluster):
    """Revert the instance parameters to the default values.

    """
    # hvparams
    hv_defs = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type, {})
    for name in self.op.hvparams.keys():
      if name in hv_defs and hv_defs[name] == self.op.hvparams[name]:
        del self.op.hvparams[name]
    # beparams
    be_defs = cluster.SimpleFillBE({})
    for name in self.op.beparams.keys():
      if name in be_defs and be_defs[name] == self.op.beparams[name]:
        del self.op.beparams[name]
    # nic params
    nic_defs = cluster.SimpleFillNIC({})
    for nic in self.op.nics:
      for name in constants.NICS_PARAMETERS:
        if name in nic and name in nic_defs and nic[name] == nic_defs[name]:
          del nic[name]
    # osparams
    os_defs = cluster.SimpleFillOS(self.op.os_type, {})
    for name in self.op.osparams.keys():
      if name in os_defs and os_defs[name] == self.op.osparams[name]:
        del self.op.osparams[name]

    os_defs_ = cluster.SimpleFillOS(self.op.os_type, {},
                                    os_params_private={})
    for name in self.op.osparams_private.keys():
      if name in os_defs_ and os_defs_[name] == self.op.osparams_private[name]:
        del self.op.osparams_private[name]

  def _GetNodesFromForthcomingInstance(self):
    """Set nodes as in the forthcoming instance

    """
    (uuid, name) = self.cfg.ExpandInstanceName(self.op.instance_name)
    inst = self.cfg.GetInstanceInfo(uuid)
    self.op.pnode_uuid = inst.primary_node
    self.op.pnode = self.cfg.GetNodeName(inst.primary_node)
    sec_nodes = self.cfg.GetInstanceSecondaryNodes(uuid)
    node_names = [self.op.pnode]
    if sec_nodes:
      self.op.snode_uuid = sec_nodes[0]
      self.op.snode = self.cfg.GetNodeName(sec_nodes[0])
      node_names.append(self.op.snode)
    self.LogInfo("Nodes of instance %s: %s", name, node_names)

  def CheckPrereq(self): # pylint: disable=R0914
    """Check prerequisites.

    """
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    if self.op.commit:
      # Check that the instance is still on the cluster, forthcoming, and
      # still resides on the nodes we acquired.
      (uuid, name) = self.cfg.ExpandInstanceName(self.op.instance_name)
      if uuid is None:
        raise errors.OpPrereqError("Instance %s disappeared from the cluster"
                                   " while waiting for locks"
                                   % (self.op.instance_name,),
                                   errors.ECODE_STATE)
      if not self.cfg.GetInstanceInfo(uuid).forthcoming:
        raise errors.OpPrereqError("Instance %s (with uuid %s) is no longer"
                                   " forthcoming" % (name, uuid),
                                   errors.ECODE_STATE)
      required_nodes = self.cfg.GetInstanceNodes(uuid)
      if not owned_nodes.issuperset(required_nodes):
        raise errors.OpPrereqError("Forthcoming instance %s nodes changed"
                                   " since locks were acquired; retry the"
                                   " operation" % self.op.instance_name,
                                   errors.ECODE_STATE)
    else:
      CheckInstanceExistence(self, self.op.instance_name)

    # Check that the optimistically acquired groups are correct wrt the
    # acquired nodes
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    cur_groups = list(self.cfg.GetNodeGroupsFromNodes(owned_nodes))
    if not owned_groups.issuperset(cur_groups):
      raise errors.OpPrereqError("New instance %s's node groups changed since"
                                 " locks were acquired, current groups are"
                                 " are '%s', owning groups '%s'; retry the"
                                 " operation" %
                                 (self.op.instance_name,
                                  utils.CommaJoin(cur_groups),
                                  utils.CommaJoin(owned_groups)),
                                 errors.ECODE_STATE)

    self.instance_file_storage_dir = CalculateFileStorageDir(
        self.op.disk_template, self.cfg, self.op.instance_name,
        self.op.file_storage_dir)

    if self.op.mode == constants.INSTANCE_IMPORT:
      export_info = self._ReadExportInfo()
      self._ReadExportParams(export_info)
      self._old_instance_name = export_info.get(constants.INISECT_INS, "name")
    else:
      self._old_instance_name = None

    if (not self.cfg.GetVGName() and
        self.op.disk_template not in constants.DTS_NOT_LVM):
      raise errors.OpPrereqError("Cluster does not support lvm-based"
                                 " instances", errors.ECODE_STATE)

    if (self.op.hypervisor is None or
        self.op.hypervisor == constants.VALUE_AUTO):
      self.op.hypervisor = self.cfg.GetHypervisorType()

    cluster = self.cfg.GetClusterInfo()
    enabled_hvs = cluster.enabled_hypervisors
    if self.op.hypervisor not in enabled_hvs:
      raise errors.OpPrereqError("Selected hypervisor (%s) not enabled in the"
                                 " cluster (%s)" %
                                 (self.op.hypervisor, ",".join(enabled_hvs)),
                                 errors.ECODE_STATE)

    # Check tag validity
    for tag in self.op.tags:
      objects.TaggableObject.ValidateTag(tag)

    # check hypervisor parameter syntax (locally)
    utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
    filled_hvp = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type,
                                      self.op.hvparams)
    hv_type = hypervisor.GetHypervisorClass(self.op.hypervisor)
    hv_type.CheckParameterSyntax(filled_hvp)
    self.hv_full = filled_hvp
    # check that we don't specify global parameters on an instance
    CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS, "hypervisor",
                         "instance", "cluster")

    # fill and remember the beparams dict
    self.be_full = ComputeFullBeParams(self.op, cluster)

    # build os parameters
    if self.op.osparams_private is None:
      self.op.osparams_private = serializer.PrivateDict()
    if self.op.osparams_secret is None:
      self.op.osparams_secret = serializer.PrivateDict()

    self.os_full = cluster.SimpleFillOS(
      self.op.os_type,
      self.op.osparams,
      os_params_private=self.op.osparams_private,
      os_params_secret=self.op.osparams_secret
    )

    # now that hvp/bep are in final format, let's reset to defaults,
    # if told to do so
    if self.op.identify_defaults:
      self._RevertToDefaults(cluster)

    # NIC buildup
    self.nics = ComputeNics(self.op, cluster, self.check_ip, self.cfg,
                            self.proc.GetECId())

    # disk checks/pre-build
    default_vg = self.cfg.GetVGName()
    self.disks = ComputeDisks(self.op.disks, self.op.disk_template, default_vg)

    if self.op.mode == constants.INSTANCE_IMPORT:
      disk_images = []
      for idx in range(len(self.disks)):
        option = "disk%d_dump" % idx
        if export_info.has_option(constants.INISECT_INS, option):
          # FIXME: are the old os-es, disk sizes, etc. useful?
          export_name = export_info.get(constants.INISECT_INS, option)
          image = utils.PathJoin(self.op.src_path, export_name)
          disk_images.append(image)
        else:
          disk_images.append(False)

      self.src_images = disk_images

      if self.op.instance_name == self._old_instance_name:
        for idx, nic in enumerate(self.nics):
          if nic.mac == constants.VALUE_AUTO:
            nic_mac_ini = "nic%d_mac" % idx
            nic.mac = export_info.get(constants.INISECT_INS, nic_mac_ini)

    # ENDIF: self.op.mode == constants.INSTANCE_IMPORT

    # ip ping checks (we use the same ip that was resolved in ExpandNames)
    if self.op.ip_check:
      if netutils.TcpPing(self.check_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (self.check_ip, self.op.instance_name),
                                   errors.ECODE_NOTUNIQUE)

    #### mac address generation
    # By generating here the mac address both the allocator and the hooks get
    # the real final mac address rather than the 'auto' or 'generate' value.
    # There is a race condition between the generation and the instance object
    # creation, which means that we know the mac is valid now, but we're not
    # sure it will be when we actually add the instance. If things go bad
    # adding the instance will abort because of a duplicate mac, and the
    # creation job will fail.
    for nic in self.nics:
      if nic.mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        nic.mac = self.cfg.GenerateMAC(nic.network, self.proc.GetECId())

    #### allocator run

    if self.op.iallocator is not None:
      if self.op.commit:
        self._GetNodesFromForthcomingInstance()
      else:
        self._RunAllocator()

    # Release all unneeded node locks
    keep_locks = filter(None, [self.op.pnode_uuid, self.op.snode_uuid,
                               self.op.src_node_uuid])
    ReleaseLocks(self, locking.LEVEL_NODE, keep=keep_locks)
    ReleaseLocks(self, locking.LEVEL_NODE_RES, keep=keep_locks)
    # Release all unneeded group locks
    ReleaseLocks(self, locking.LEVEL_NODEGROUP,
                 keep=self.cfg.GetNodeGroupsFromNodes(keep_locks))

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES)), \
      ("Node locks differ from node resource locks (%s vs %s)"
       % (self.owned_locks(locking.LEVEL_NODE),
          self.owned_locks(locking.LEVEL_NODE_RES)))

    #### node related checks

    # check primary node
    self.pnode = pnode = self.cfg.GetNodeInfo(self.op.pnode_uuid)
    assert self.pnode is not None, \
      "Cannot retrieve locked node %s" % self.op.pnode_uuid
    if pnode.offline:
      raise errors.OpPrereqError("Cannot use offline primary node '%s'" %
                                 pnode.name, errors.ECODE_STATE)
    if pnode.drained:
      raise errors.OpPrereqError("Cannot use drained primary node '%s'" %
                                 pnode.name, errors.ECODE_STATE)
    if not pnode.vm_capable:
      raise errors.OpPrereqError("Cannot use non-vm_capable primary node"
                                 " '%s'" % pnode.name, errors.ECODE_STATE)

    self.secondaries = []

    # Fill in any IPs from IP pools. This must happen here, because we need to
    # know the nic's primary node, as specified by the iallocator
    for idx, nic in enumerate(self.nics):
      net_uuid = nic.network
      if net_uuid is not None:
        nobj = self.cfg.GetNetwork(net_uuid)
        netparams = self.cfg.GetGroupNetParams(net_uuid, self.pnode.uuid)
        if netparams is None:
          raise errors.OpPrereqError("No netparams found for network"
                                     " %s. Probably not connected to"
                                     " node's %s nodegroup" %
                                     (nobj.name, self.pnode.name),
                                     errors.ECODE_INVAL)
        self.LogInfo("NIC/%d inherits netparams %s" %
                     (idx, netparams.values()))
        nic.nicparams = dict(netparams)
        if nic.ip is not None:
          if nic.ip.lower() == constants.NIC_IP_POOL:
            try:
              nic.ip = self.cfg.GenerateIp(net_uuid, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("Unable to get a free IP for NIC %d"
                                         " from the address pool" % idx,
                                         errors.ECODE_STATE)
            self.LogInfo("Chose IP %s from network %s", nic.ip, nobj.name)
          else:
            try:
              self.cfg.ReserveIp(net_uuid, nic.ip, self.proc.GetECId(),
                                 check=self.op.conflicts_check)
            except errors.ReservationError:
              raise errors.OpPrereqError("IP address %s already in use"
                                         " or does not belong to network %s" %
                                         (nic.ip, nobj.name),
                                         errors.ECODE_NOTUNIQUE)

      # net is None, ip None or given
      elif self.op.conflicts_check:
        CheckForConflictingIp(self, nic.ip, self.pnode.uuid)

    # mirror node verification
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.snode_uuid == pnode.uuid:
        raise errors.OpPrereqError("The secondary node cannot be the"
                                   " primary node", errors.ECODE_INVAL)
      CheckNodeOnline(self, self.op.snode_uuid)
      CheckNodeNotDrained(self, self.op.snode_uuid)
      CheckNodeVmCapable(self, self.op.snode_uuid)
      self.secondaries.append(self.op.snode_uuid)

      snode = self.cfg.GetNodeInfo(self.op.snode_uuid)
      if pnode.group != snode.group:
        self.LogWarning("The primary and secondary nodes are in two"
                        " different node groups; the disk parameters"
                        " from the first disk's node group will be"
                        " used")

    nodes = [pnode]
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      nodes.append(snode)
    has_es = lambda n: IsExclusiveStorageEnabledNode(self.cfg, n)
    excl_stor = compat.any(map(has_es, nodes))
    if excl_stor and not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      raise errors.OpPrereqError("Disk template %s not supported with"
                                 " exclusive storage" % self.op.disk_template,
                                 errors.ECODE_STATE)
    for disk in self.disks:
      CheckSpindlesExclusiveStorage(disk, excl_stor, True)

    node_uuids = [pnode.uuid] + self.secondaries

    if not self.adopt_disks:
      if self.op.disk_template == constants.DT_RBD:
        # _CheckRADOSFreeSpace() is just a placeholder.
        # Any function that checks prerequisites can be placed here.
        # Check if there is enough space on the RADOS cluster.
        CheckRADOSFreeSpace()
      elif self.op.disk_template == constants.DT_EXT:
        # FIXME: Function that checks prereqs if needed
        pass
      elif self.op.disk_template in constants.DTS_LVM:
        # Check lv size requirements, if not adopting
        req_sizes = ComputeDiskSizePerVG(self.op.disk_template, self.disks)
        CheckNodesFreeDiskPerVG(self, node_uuids, req_sizes)
      else:
        # FIXME: add checks for other, non-adopting, non-lvm disk templates
        pass

    elif self.op.disk_template == constants.DT_PLAIN: # Check the adoption data
      all_lvs = set(["%s/%s" % (disk[constants.IDISK_VG],
                                disk[constants.IDISK_ADOPT])
                     for disk in self.disks])
      if len(all_lvs) != len(self.disks):
        raise errors.OpPrereqError("Duplicate volume names given for adoption",
                                   errors.ECODE_INVAL)
      for lv_name in all_lvs:
        try:
          # FIXME: lv_name here is "vg/lv" need to ensure that other calls
          # to ReserveLV uses the same syntax
          self.cfg.ReserveLV(lv_name, self.proc.GetECId())
        except errors.ReservationError:
          raise errors.OpPrereqError("LV named %s used by another instance" %
                                     lv_name, errors.ECODE_NOTUNIQUE)

      vg_names = self.rpc.call_vg_list([pnode.uuid])[pnode.uuid]
      vg_names.Raise("Cannot get VG information from node %s" % pnode.name,
                     prereq=True)

      node_lvs = self.rpc.call_lv_list([pnode.uuid],
                                       vg_names.payload.keys())[pnode.uuid]
      node_lvs.Raise("Cannot get LV information from node %s" % pnode.name,
                     prereq=True)
      node_lvs = node_lvs.payload

      delta = all_lvs.difference(node_lvs.keys())
      if delta:
        raise errors.OpPrereqError("Missing logical volume(s): %s" %
                                   utils.CommaJoin(delta),
                                   errors.ECODE_INVAL)
      online_lvs = [lv for lv in all_lvs if node_lvs[lv][2]]
      if online_lvs:
        raise errors.OpPrereqError("Online logical volumes found, cannot"
                                   " adopt: %s" % utils.CommaJoin(online_lvs),
                                   errors.ECODE_STATE)
      # update the size of disk based on what is found
      for dsk in self.disks:
        dsk[constants.IDISK_SIZE] = \
          int(float(node_lvs["%s/%s" % (dsk[constants.IDISK_VG],
                                        dsk[constants.IDISK_ADOPT])][0]))

    elif self.op.disk_template == constants.DT_BLOCK:
      # Normalize and de-duplicate device paths
      all_disks = set([os.path.abspath(disk[constants.IDISK_ADOPT])
                       for disk in self.disks])
      if len(all_disks) != len(self.disks):
        raise errors.OpPrereqError("Duplicate disk names given for adoption",
                                   errors.ECODE_INVAL)
      baddisks = [d for d in all_disks
                  if not d.startswith(constants.ADOPTABLE_BLOCKDEV_ROOT)]
      if baddisks:
        raise errors.OpPrereqError("Device node(s) %s lie outside %s and"
                                   " cannot be adopted" %
                                   (utils.CommaJoin(baddisks),
                                    constants.ADOPTABLE_BLOCKDEV_ROOT),
                                   errors.ECODE_INVAL)

      node_disks = self.rpc.call_bdev_sizes([pnode.uuid],
                                            list(all_disks))[pnode.uuid]
      node_disks.Raise("Cannot get block device information from node %s" %
                       pnode.name, prereq=True)
      node_disks = node_disks.payload
      delta = all_disks.difference(node_disks.keys())
      if delta:
        raise errors.OpPrereqError("Missing block device(s): %s" %
                                   utils.CommaJoin(delta),
                                   errors.ECODE_INVAL)
      for dsk in self.disks:
        dsk[constants.IDISK_SIZE] = \
          int(float(node_disks[dsk[constants.IDISK_ADOPT]]))

    # Check disk access param to be compatible with specified hypervisor
    node_info = self.cfg.GetNodeInfo(self.op.pnode_uuid)
    node_group = self.cfg.GetNodeGroup(node_info.group)
    group_disk_params = self.cfg.GetGroupDiskParams(node_group)
    group_access_type = group_disk_params[self.op.disk_template].get(
      constants.RBD_ACCESS, constants.DISK_KERNELSPACE
    )
    for dsk in self.disks:
      access_type = dsk.get(constants.IDISK_ACCESS, group_access_type)
      if not IsValidDiskAccessModeCombination(self.op.hypervisor,
                                              self.op.disk_template,
                                              access_type):
        raise errors.OpPrereqError("Selected hypervisor (%s) cannot be"
                                   " used with %s disk access param" %
                                   (self.op.hypervisor, access_type),
                                    errors.ECODE_STATE)

    # Verify instance specs
    spindle_use = self.be_full.get(constants.BE_SPINDLE_USE, None)
    ispec = {
      constants.ISPEC_MEM_SIZE: self.be_full.get(constants.BE_MAXMEM, None),
      constants.ISPEC_CPU_COUNT: self.be_full.get(constants.BE_VCPUS, None),
      constants.ISPEC_DISK_COUNT: len(self.disks),
      constants.ISPEC_DISK_SIZE: [disk[constants.IDISK_SIZE]
                                  for disk in self.disks],
      constants.ISPEC_NIC_COUNT: len(self.nics),
      constants.ISPEC_SPINDLE_USE: spindle_use,
      }

    group_info = self.cfg.GetNodeGroup(pnode.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    disk_types = [self.op.disk_template] * len(self.disks)
    res = ComputeIPolicyInstanceSpecViolation(ipolicy, ispec, disk_types)
    if not self.op.ignore_ipolicy and res:
      msg = ("Instance allocation to group %s (%s) violates policy: %s" %
             (pnode.group, group_info.name, utils.CommaJoin(res)))
      raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

    CheckHVParams(self, node_uuids, self.op.hypervisor, self.op.hvparams)

    CheckOSParams(self, True, node_uuids, self.op.os_type, self.os_full,
                  self.op.force_variant)

    CheckNicsBridgesExist(self, self.nics, self.pnode.uuid)

    CheckCompressionTool(self, self.op.compress)

    #TODO: _CheckExtParams (remotely)
    # Check parameters for extstorage

    # memory check on primary node
    #TODO(dynmem): use MINMEM for checking
    if self.op.start:
      hvfull = objects.FillDict(cluster.hvparams.get(self.op.hypervisor, {}),
                                self.op.hvparams)
      CheckNodeFreeMemory(self, self.pnode.uuid,
                          "creating instance %s" % self.op.instance_name,
                          self.be_full[constants.BE_MAXMEM],
                          self.op.hypervisor, hvfull)

    self.dry_run_result = list(node_uuids)

  def _RemoveDegradedDisks(self, feedback_fn, disk_abort, instance):
    """Removes degraded disks and instance.

    It optionally checks whether disks are degraded.  If the disks are
    degraded, they are removed and the instance is also removed from
    the configuration.

    If L{disk_abort} is True, then the disks are considered degraded
    and removed, and the instance is removed from the configuration.

    If L{disk_abort} is False, then it first checks whether disks are
    degraded and, if so, it removes the disks and the instance is
    removed from the configuration.

    @type feedback_fn: callable
    @param feedback_fn: function used send feedback back to the caller

    @type disk_abort: boolean
    @param disk_abort:
      True if disks are degraded, False to first check if disks are
      degraded
    @type instance: L{objects.Instance}
    @param instance: instance containing the disks to check

    @rtype: NoneType
    @return: None
    @raise errors.OpPrereqError: if disks are degraded

    """
    disk_info = self.cfg.GetInstanceDisks(instance.uuid)
    if disk_abort:
      pass
    elif self.op.wait_for_sync:
      disk_abort = not WaitForSync(self, instance)
    elif utils.AnyDiskOfType(disk_info, constants.DTS_INT_MIRROR):
      # make sure the disks are not degraded (still sync-ing is ok)
      feedback_fn("* checking mirrors status")
      disk_abort = not WaitForSync(self, instance, oneshot=True)
    else:
      disk_abort = False

    if disk_abort:
      RemoveDisks(self, instance)
      for disk_uuid in instance.disks:
        self.cfg.RemoveInstanceDisk(instance.uuid, disk_uuid)
      self.cfg.RemoveInstance(instance.uuid)
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance")

  def RunOsScripts(self, feedback_fn, iobj):
    """Run OS scripts

    If necessary, disks are paused.  It handles instance create,
    import, and remote import.

    @type feedback_fn: callable
    @param feedback_fn: function used send feedback back to the caller

    @type iobj: L{objects.Instance}
    @param iobj: instance object

    """
    if not iobj.disks:
      return

    if self.adopt_disks:
      return

    disks = self.cfg.GetInstanceDisks(iobj.uuid)
    if self.op.mode == constants.INSTANCE_CREATE:
      os_image = objects.GetOSImage(self.op.osparams)

      if os_image is None and not self.op.no_install:
        pause_sync = (not self.op.wait_for_sync and
                      utils.AnyDiskOfType(disks, constants.DTS_INT_MIRROR))
        if pause_sync:
          feedback_fn("* pausing disk sync to install instance OS")
          result = self.rpc.call_blockdev_pause_resume_sync(self.pnode.uuid,
                                                            (disks, iobj),
                                                            True)
          for idx, success in enumerate(result.payload):
            if not success:
              logging.warn("pause-sync of instance %s for disk %d failed",
                           self.op.instance_name, idx)

        feedback_fn("* running the instance OS create scripts...")
        # FIXME: pass debug option from opcode to backend
        os_add_result = \
          self.rpc.call_instance_os_add(self.pnode.uuid,
                                        (iobj, self.op.osparams_secret),
                                        False,
                                        self.op.debug_level)
        if pause_sync:
          feedback_fn("* resuming disk sync")
          result = self.rpc.call_blockdev_pause_resume_sync(self.pnode.uuid,
                                                            (disks, iobj),
                                                            False)
          for idx, success in enumerate(result.payload):
            if not success:
              logging.warn("resume-sync of instance %s for disk %d failed",
                           self.op.instance_name, idx)

        os_add_result.Raise("Could not add os for instance %s"
                            " on node %s" % (self.op.instance_name,
                                             self.pnode.name))

    else:
      if self.op.mode == constants.INSTANCE_IMPORT:
        feedback_fn("* running the instance OS import scripts...")

        transfers = []

        for idx, image in enumerate(self.src_images):
          if not image:
            continue

          if iobj.os:
            dst_io = constants.IEIO_SCRIPT
            dst_ioargs = ((disks[idx], iobj), idx)
          else:
            dst_io = constants.IEIO_RAW_DISK
            dst_ioargs = (disks[idx], iobj)

          # FIXME: pass debug option from opcode to backend
          dt = masterd.instance.DiskTransfer("disk/%s" % idx,
                                             constants.IEIO_FILE, (image, ),
                                             dst_io, dst_ioargs,
                                             None)
          transfers.append(dt)

        import_result = \
          masterd.instance.TransferInstanceData(self, feedback_fn,
                                                self.op.src_node_uuid,
                                                self.pnode.uuid,
                                                self.pnode.secondary_ip,
                                                self.op.compress,
                                                iobj, transfers)
        if not compat.all(import_result):
          self.LogWarning("Some disks for instance %s on node %s were not"
                          " imported successfully" % (self.op.instance_name,
                                                      self.pnode.name))

        rename_from = self._old_instance_name

      elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
        feedback_fn("* preparing remote import...")
        # The source cluster will stop the instance before attempting to make
        # a connection. In some cases stopping an instance can take a long
        # time, hence the shutdown timeout is added to the connection
        # timeout.
        connect_timeout = (constants.RIE_CONNECT_TIMEOUT +
                           self.op.source_shutdown_timeout)
        timeouts = masterd.instance.ImportExportTimeouts(connect_timeout)

        assert iobj.primary_node == self.pnode.uuid
        disk_results = \
          masterd.instance.RemoteImport(self, feedback_fn, iobj, self.pnode,
                                        self.source_x509_ca,
                                        self._cds, self.op.compress, timeouts)
        if not compat.all(disk_results):
          # TODO: Should the instance still be started, even if some disks
          # failed to import (valid for local imports, too)?
          self.LogWarning("Some disks for instance %s on node %s were not"
                          " imported successfully" % (self.op.instance_name,
                                                      self.pnode.name))

        rename_from = self.source_instance_name

      else:
        # also checked in the prereq part
        raise errors.ProgrammerError("Unknown OS initialization mode '%s'"
                                     % self.op.mode)

      assert iobj.name == self.op.instance_name

      # Run rename script on newly imported instance
      if iobj.os:
        feedback_fn("Running rename script for %s" % self.op.instance_name)
        result = self.rpc.call_instance_run_rename(self.pnode.uuid, iobj,
                                                   rename_from,
                                                   self.op.debug_level)
        result.Warn("Failed to run rename script for %s on node %s" %
                    (self.op.instance_name, self.pnode.name), self.LogWarning)

  def GetOsInstallPackageEnvironment(self, instance, script):
    """Returns the OS scripts environment for the helper VM

    @type instance: L{objects.Instance}
    @param instance: instance for which the OS scripts are run

    @type script: string
    @param script: script to run (e.g.,
                   constants.OS_SCRIPT_CREATE_UNTRUSTED)

    @rtype: dict of string to string
    @return: OS scripts environment for the helper VM

    """
    env = {"OS_SCRIPT": script}

    # We pass only the instance's disks, not the helper VM's disks.
    if instance.hypervisor == constants.HT_KVM:
      prefix = "/dev/vd"
    elif instance.hypervisor in [constants.HT_XEN_PVM, constants.HT_XEN_HVM]:
      prefix = "/dev/xvd"
    else:
      raise errors.OpExecError("Cannot run OS scripts in a virtualized"
                               " environment for hypervisor '%s'"
                               % instance.hypervisor)

    num_disks = len(self.cfg.GetInstanceDisks(instance.uuid))

    for idx, disk_label in enumerate(utils.GetDiskLabels(prefix, num_disks + 1,
                                                         start=1)):
      env["DISK_%d_PATH" % idx] = disk_label

    return env

  def UpdateInstanceOsInstallPackage(self, feedback_fn, instance, override_env):
    """Updates the OS parameter 'os-install-package' for an instance.

    The OS install package is an archive containing an OS definition
    and a file containing the environment variables needed to run the
    OS scripts.

    The OS install package is served by the metadata daemon to the
    instances, so the OS scripts can run inside the virtualized
    environment.

    @type feedback_fn: callable
    @param feedback_fn: function used send feedback back to the caller

    @type instance: L{objects.Instance}
    @param instance: instance for which the OS parameter
                     'os-install-package' is updated

    @type override_env: dict of string to string
    @param override_env: if supplied, it overrides the environment of
                         the export OS scripts archive

    """
    if "os-install-package" in instance.osparams:
      feedback_fn("Using OS install package '%s'" %
                  instance.osparams["os-install-package"])
    else:
      result = self.rpc.call_os_export(instance.primary_node, instance,
                                       override_env)
      result.Raise("Could not export OS '%s'" % instance.os)
      instance.osparams["os-install-package"] = result.payload

      feedback_fn("Created OS install package '%s'" % result.payload)

  def RunOsScriptsVirtualized(self, feedback_fn, instance):
    """Runs the OS scripts inside a safe virtualized environment.

    The virtualized environment reuses the instance and temporarily
    creates a disk onto which the image of the helper VM is dumped.
    The temporary disk is used to boot the helper VM.  The OS scripts
    are passed to the helper VM through the metadata daemon and the OS
    install package.

    @type feedback_fn: callable
    @param feedback_fn: function used send feedback back to the caller

    @type instance: L{objects.Instance}
    @param instance: instance for which the OS scripts must be run
                     inside the virtualized environment

    """
    install_image = self.cfg.GetInstallImage()

    if not install_image:
      raise errors.OpExecError("Cannot create install instance because an"
                               " install image has not been specified")

    env = self.GetOsInstallPackageEnvironment(
      instance,
      constants.OS_SCRIPT_CREATE_UNTRUSTED)
    self.UpdateInstanceOsInstallPackage(feedback_fn, instance, env)
    UpdateMetadata(feedback_fn, self.rpc, instance,
                   osparams_private=self.op.osparams_private,
                   osparams_secret=self.op.osparams_secret)

    RunWithHelperVM(self, instance, install_image,
                    self.op.helper_startup_timeout,
                    self.op.helper_shutdown_timeout,
                    log_prefix="Running OS create script",
                    feedback_fn=feedback_fn)

  def Exec(self, feedback_fn):
    """Create and add the instance to the cluster.

    """
    assert not (self.owned_locks(locking.LEVEL_NODE_RES) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Node locks differ from node resource locks"

    ht_kind = self.op.hypervisor
    if ht_kind in constants.HTS_REQ_PORT:
      network_port = self.cfg.AllocatePort()
    else:
      network_port = None

    if self.op.commit:
      (instance_uuid, _) = self.cfg.ExpandInstanceName(self.op.instance_name)
    else:
      instance_uuid = self.cfg.GenerateUniqueID(self.proc.GetECId())

    # This is ugly but we got a chicken-egg problem here
    # We can only take the group disk parameters, as the instance
    # has no disks yet (we are generating them right here).
    nodegroup = self.cfg.GetNodeGroup(self.pnode.group)

    if self.op.commit:
      disks = self.cfg.GetInstanceDisks(instance_uuid)
      CommitDisks(disks)
    else:
      disks = GenerateDiskTemplate(self,
                                   self.op.disk_template,
                                   instance_uuid, self.pnode.uuid,
                                   self.secondaries,
                                   self.disks,
                                   self.instance_file_storage_dir,
                                   self.op.file_driver,
                                   0,
                                   feedback_fn,
                                   self.cfg.GetGroupDiskParams(nodegroup),
                                   forthcoming=self.op.forthcoming)

    if self.op.os_type is None:
      os_type = ""
    else:
      os_type = self.op.os_type

    iobj = objects.Instance(name=self.op.instance_name,
                            uuid=instance_uuid,
                            os=os_type,
                            primary_node=self.pnode.uuid,
                            nics=self.nics, disks=[],
                            disk_template=self.op.disk_template,
                            disks_active=False,
                            admin_state=constants.ADMINST_DOWN,
                            admin_state_source=constants.ADMIN_SOURCE,
                            network_port=network_port,
                            beparams=self.op.beparams,
                            hvparams=self.op.hvparams,
                            hypervisor=self.op.hypervisor,
                            osparams=self.op.osparams,
                            osparams_private=self.op.osparams_private,
                            forthcoming=self.op.forthcoming,
                            )

    if self.op.tags:
      for tag in self.op.tags:
        iobj.AddTag(tag)

    if self.adopt_disks:
      if self.op.disk_template == constants.DT_PLAIN:
        # rename LVs to the newly-generated names; we need to construct
        # 'fake' LV disks with the old data, plus the new unique_id
        tmp_disks = [objects.Disk.FromDict(v.ToDict()) for v in disks]
        rename_to = []
        for t_dsk, a_dsk in zip(tmp_disks, self.disks):
          rename_to.append(t_dsk.logical_id)
          t_dsk.logical_id = (t_dsk.logical_id[0], a_dsk[constants.IDISK_ADOPT])
        result = self.rpc.call_blockdev_rename(self.pnode.uuid,
                                               zip(tmp_disks, rename_to))
        result.Raise("Failed to rename adoped LVs")
    elif self.op.forthcoming:
      feedback_fn("Instance is forthcoming, not creating disks")
    else:
      feedback_fn("* creating instance disks...")
      try:
        CreateDisks(self, iobj, disks=disks)
      except errors.OpExecError:
        self.LogWarning("Device creation failed")
        for disk in disks:
          self.cfg.ReleaseDRBDMinors(disk.uuid)
        raise

    feedback_fn("adding instance %s to cluster config" % self.op.instance_name)
    self.cfg.AddInstance(iobj, self.proc.GetECId(), replace=self.op.commit)

    feedback_fn("adding disks to cluster config")
    for disk in disks:
      self.cfg.AddInstanceDisk(iobj.uuid, disk, replace=self.op.commit)

    if self.op.forthcoming:
      feedback_fn("Instance is forthcoming; not creating the actual instance")
      return self.cfg.GetNodeNames(list(self.cfg.GetInstanceNodes(iobj.uuid)))

    # re-read the instance from the configuration
    iobj = self.cfg.GetInstanceInfo(iobj.uuid)

    if self.op.mode == constants.INSTANCE_IMPORT:
      # Release unused nodes
      ReleaseLocks(self, locking.LEVEL_NODE, keep=[self.op.src_node_uuid])
    else:
      # Release all nodes
      ReleaseLocks(self, locking.LEVEL_NODE)

    # Wipe disks
    disk_abort = False
    if not self.adopt_disks and self.cfg.GetClusterInfo().prealloc_wipe_disks:
      feedback_fn("* wiping instance disks...")
      try:
        WipeDisks(self, iobj)
      except errors.OpExecError, err:
        logging.exception("Wiping disks failed")
        self.LogWarning("Wiping instance disks failed (%s)", err)
        disk_abort = True

    self._RemoveDegradedDisks(feedback_fn, disk_abort, iobj)

    # Image disks
    os_image = objects.GetOSImage(iobj.osparams)
    disk_abort = False

    if not self.adopt_disks and os_image is not None:
      feedback_fn("* imaging instance disks...")
      try:
        ImageDisks(self, iobj, os_image)
      except errors.OpExecError, err:
        logging.exception("Imaging disks failed")
        self.LogWarning("Imaging instance disks failed (%s)", err)
        disk_abort = True

    self._RemoveDegradedDisks(feedback_fn, disk_abort, iobj)

    # instance disks are now active
    iobj.disks_active = True

    # Release all node resource locks
    ReleaseLocks(self, locking.LEVEL_NODE_RES)

    if iobj.os:
      result = self.rpc.call_os_diagnose([iobj.primary_node])[iobj.primary_node]
      result.Raise("Failed to get OS '%s'" % iobj.os)

      trusted = None

      for (name, _, _, _, _, _, _, os_trusted) in result.payload:
        if name == objects.OS.GetName(iobj.os):
          trusted = os_trusted
          break

      if trusted is None:
        raise errors.OpPrereqError("OS '%s' is not available in node '%s'" %
                                   (iobj.os, iobj.primary_node))
      elif trusted:
        self.RunOsScripts(feedback_fn, iobj)
      else:
        self.RunOsScriptsVirtualized(feedback_fn, iobj)
        # Instance is modified by 'RunOsScriptsVirtualized',
        # therefore, it must be retrieved once again from the
        # configuration, otherwise there will be a config object
        # version mismatch.
        iobj = self.cfg.GetInstanceInfo(iobj.uuid)

    # Update instance metadata so that it can be reached from the
    # metadata service.
    UpdateMetadata(feedback_fn, self.rpc, iobj,
                   osparams_private=self.op.osparams_private,
                   osparams_secret=self.op.osparams_secret)

    assert not self.owned_locks(locking.LEVEL_NODE_RES)

    if self.op.start:
      iobj.admin_state = constants.ADMINST_UP
      self.cfg.Update(iobj, feedback_fn)
      logging.info("Starting instance %s on node %s", self.op.instance_name,
                   self.pnode.name)
      feedback_fn("* starting instance...")
      result = self.rpc.call_instance_start(self.pnode.uuid, (iobj, None, None),
                                            False, self.op.reason)
      result.Raise("Could not start instance")

    return self.cfg.GetNodeNames(list(self.cfg.GetInstanceNodes(iobj.uuid)))

  def PrepareRetry(self, feedback_fn):
    # A temporary lack of resources can only happen if opportunistic locking
    # is used.
    assert self.op.opportunistic_locking

    logging.info("Opportunistic locking did not suceed, falling back to"
                 " full lock allocation")
    feedback_fn("* falling back to full lock allocation")
    self.op.opportunistic_locking = False
