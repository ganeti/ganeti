#
#

# Copyright (C) 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015 Google Inc.
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

"""Library of the tools/cfgupgrade utility.

This code handles only the types supported by simplejson. As an
example, 'set' is a 'list'.

"""

import copy
import os
import os.path
import sys
import logging
import optparse
import time
import functools
from io import StringIO

from ganeti import cli
from ganeti import constants
from ganeti import serializer
from ganeti import utils
from ganeti import bootstrap
from ganeti import config
from ganeti import pathutils
from ganeti import netutils

from ganeti.utils import version


#: Target major version we will upgrade to
TARGET_MAJOR = 3
#: Target minor version we will upgrade to
TARGET_MINOR = 0
#: Last supported v2.x minor
LAST_V2_MINOR = 16
#: Target major version for downgrade
DOWNGRADE_MAJOR = 2
#: Target minor version for downgrade
DOWNGRADE_MINOR = 16

# map of legacy device types
# (mapping differing old LD_* constants to new DT_* constants)
DEV_TYPE_OLD_NEW = {"lvm": constants.DT_PLAIN, "drbd8": constants.DT_DRBD8}
# (mapping differing new DT_* constants to old LD_* constants)
DEV_TYPE_NEW_OLD = dict((v, k) for k, v in DEV_TYPE_OLD_NEW.items())


class Error(Exception):
  """Generic exception"""
  pass


def ParseOptions(args=None):
  parser = optparse.OptionParser(usage="%prog [--debug|--verbose] [--force]")
  parser.add_option("--dry-run", dest="dry_run",
                    action="store_true",
                    help="Try to do the conversion, but don't write"
                         " output file")
  parser.add_option(cli.FORCE_OPT)
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option("--ignore-hostname", dest="ignore_hostname",
                    action="store_true", default=False,
                    help="Don't abort if hostname doesn't match")
  parser.add_option("--path", help="Convert configuration in this"
                    " directory instead of '%s'" % pathutils.DATA_DIR,
                    default=pathutils.DATA_DIR, dest="data_dir")
  parser.add_option("--confdir",
                    help=("Use this directory instead of '%s'" %
                          pathutils.CONF_DIR),
                    default=pathutils.CONF_DIR, dest="conf_dir")
  parser.add_option("--no-verify",
                    help="Do not verify configuration after upgrade",
                    action="store_true", dest="no_verify", default=False)
  parser.add_option("--downgrade",
                    help="Downgrade to the previous stable version",
                    action="store_true", dest="downgrade", default=False)
  return parser.parse_args(args=args)


def OrFail(description=None):
  """Make failure non-fatal and improve reporting."""
  def wrapper(f):
    @functools.wraps(f)
    def wrapped(self):
      safety = copy.deepcopy(self.config_data)
      try:
        f(self)
      except BaseException as e:
        msg = "%s failed:\n%s" % (description or f.func_name, e)
        logging.exception(msg)
        self.config_data = safety
        self.errors.append(msg)
    return wrapped
  return wrapper


class CfgUpgrade(object):
  def __init__(self, opts, args):
    self.opts = opts
    self.args = args
    self.errors = []

  def Run(self):
    """Main program.

    """
    self._ComposePaths()

    self.SetupLogging()

    # Option checking
    if self.args:
      raise Error("No arguments expected")
    if self.opts.downgrade and not self.opts.no_verify:
      self.opts.no_verify = True

    # Check master name
    if not (self.CheckHostname(self.opts.SSCONF_MASTER_NODE) or
            self.opts.ignore_hostname):
      logging.error("Aborting due to hostname mismatch")
      sys.exit(constants.EXIT_FAILURE)

    self._AskUser()

    # Check whether it's a Ganeti configuration directory
    if not (os.path.isfile(self.opts.CONFIG_DATA_PATH) and
            os.path.isfile(self.opts.SERVER_PEM_PATH) and
            os.path.isfile(self.opts.KNOWN_HOSTS_PATH)):
      raise Error(("%s does not seem to be a Ganeti configuration"
                   " directory") % self.opts.data_dir)

    if not os.path.isdir(self.opts.conf_dir):
      raise Error("Not a directory: %s" % self.opts.conf_dir)

    self.config_data = serializer.LoadJson(utils.ReadFile(
        self.opts.CONFIG_DATA_PATH))

    try:
      config_version = self.config_data["version"]
    except KeyError:
      raise Error("Unable to determine configuration version")

    (config_major, config_minor, config_revision) = \
      version.SplitVersion(config_version)

    logging.info("Found configuration version %s (%d.%d.%d)",
                 config_version, config_major, config_minor, config_revision)

    if "config_version" in self.config_data["cluster"]:
      raise Error("Inconsistent configuration: found config_version in"
                  " configuration file")

    # Downgrade to the previous stable version
    if self.opts.downgrade:
      self._Downgrade(config_major, config_minor, config_version,
                      config_revision)

    # Upgrade from 2.0-2.16 to 3.0
    # TODO: handle upgrades from 2.17beta
    elif config_major == 2 and config_minor in range(0, LAST_V2_MINOR + 1):
      if config_revision != 0:
        logging.warning("Config revision is %s, not 0", config_revision)
      if not self.UpgradeAll():
        raise Error("Upgrade failed:\n%s" % '\n'.join(self.errors))

    elif config_major == TARGET_MAJOR and config_minor == TARGET_MINOR:
      logging.info("No changes necessary")

    else:
      raise Error("Configuration version %d.%d.%d not supported by this tool" %
                  (config_major, config_minor, config_revision))

    try:
      logging.info("Writing configuration file to %s",
                   self.opts.CONFIG_DATA_PATH)
      utils.WriteFile(file_name=self.opts.CONFIG_DATA_PATH,
                      data=serializer.DumpJson(self.config_data),
                      mode=0o600,
                      dry_run=self.opts.dry_run,
                      backup=True)

      if not self.opts.dry_run:
        # This creates the cluster certificate if it does not exist yet.
        # In this case, we do not automatically create a client certificate
        # as well, because if the cluster certificate did not exist before,
        # no client certificate will exist on any node yet. In this case
        # all client certificate should be renewed by 'gnt-cluster
        # renew-crypto --new-node-certificates'. This will be enforced
        # by a nagging warning in 'gnt-cluster verify'.
        bootstrap.GenerateClusterCrypto(
          False, False, False, False, False, False, None,
          nodecert_file=self.opts.SERVER_PEM_PATH,
          rapicert_file=self.opts.RAPI_CERT_FILE,
          spicecert_file=self.opts.SPICE_CERT_FILE,
          spicecacert_file=self.opts.SPICE_CACERT_FILE,
          hmackey_file=self.opts.CONFD_HMAC_KEY,
          cds_file=self.opts.CDS_FILE)

    except Exception:
      logging.critical("Writing configuration failed. It is probably in an"
                       " inconsistent state and needs manual intervention.")
      raise

    self._TestLoadingConfigFile()

  def SetupLogging(self):
    """Configures the logging module.

    """
    formatter = logging.Formatter("%(asctime)s: %(message)s")

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    if self.opts.debug:
      stderr_handler.setLevel(logging.NOTSET)
    elif self.opts.verbose:
      stderr_handler.setLevel(logging.INFO)
    else:
      stderr_handler.setLevel(logging.WARNING)

    root_logger = logging.getLogger("")
    root_logger.setLevel(logging.NOTSET)
    root_logger.addHandler(stderr_handler)

  @staticmethod
  def CheckHostname(path):
    """Ensures hostname matches ssconf value.

    @param path: Path to ssconf file

    """
    ssconf_master_node = utils.ReadOneLineFile(path)
    hostname = netutils.GetHostname().name

    if ssconf_master_node == hostname:
      return True

    logging.warning("Warning: ssconf says master node is '%s', but this"
                    " machine's name is '%s'; this tool must be run on"
                    " the master node", ssconf_master_node, hostname)
    return False

  @staticmethod
  def _FillIPolicySpecs(default_ipolicy, ipolicy):
    if "minmax" in ipolicy:
      for (key, spec) in ipolicy["minmax"][0].items():
        for (par, val) in default_ipolicy["minmax"][0][key].items():
          if par not in spec:
            spec[par] = val

  def UpgradeIPolicy(self, ipolicy, default_ipolicy, isgroup):
    minmax_keys = ["min", "max"]
    if any((k in ipolicy) for k in minmax_keys):
      minmax = {}
      for key in minmax_keys:
        if key in ipolicy:
          if ipolicy[key]:
            minmax[key] = ipolicy[key]
          del ipolicy[key]
      if minmax:
        ipolicy["minmax"] = [minmax]
    if isgroup and "std" in ipolicy:
      del ipolicy["std"]
    self._FillIPolicySpecs(default_ipolicy, ipolicy)

  @OrFail("Setting networks")
  def UpgradeNetworks(self):
    assert isinstance(self.config_data, dict)
    # pylint can't infer config_data type
    # pylint: disable=E1103
    networks = self.config_data.get("networks", None)
    if not networks:
      self.config_data["networks"] = {}

  @OrFail("Upgrading cluster")
  def UpgradeCluster(self):
    assert isinstance(self.config_data, dict)
    # pylint can't infer config_data type
    # pylint: disable=E1103
    cluster = self.config_data.get("cluster", None)
    if cluster is None:
      raise Error("Cannot find cluster")

    ipolicy = cluster.setdefault("ipolicy", None)
    if ipolicy:
      self.UpgradeIPolicy(ipolicy, constants.IPOLICY_DEFAULTS, False)
    ial_params = cluster.get("default_iallocator_params", None)

    if not ial_params:
      cluster["default_iallocator_params"] = {}

    if not "candidate_certs" in cluster:
      cluster["candidate_certs"] = {}

    cluster["instance_communication_network"] = \
      cluster.get("instance_communication_network", "")

    cluster["install_image"] = \
      cluster.get("install_image", "")

    cluster["zeroing_image"] = \
      cluster.get("zeroing_image", "")

    cluster["compression_tools"] = \
      cluster.get("compression_tools", constants.IEC_DEFAULT_TOOLS)

    if "enabled_user_shutdown" not in cluster:
      cluster["enabled_user_shutdown"] = False

    cluster["data_collectors"] = cluster.get("data_collectors", {})
    for name in constants.DATA_COLLECTOR_NAMES:
      cluster["data_collectors"][name] = \
        cluster["data_collectors"].get(
            name, dict(active=True,
                       interval=constants.MOND_TIME_INTERVAL * 1e6))

    # These parameters are set to pre-2.16 default values, which
    # differ from post-2.16 default values
    if "ssh_key_type" not in cluster:
      cluster["ssh_key_type"] = constants.SSHK_DSA

    if "ssh_key_bits" not in cluster:
      cluster["ssh_key_bits"] = 1024

  @OrFail("Upgrading groups")
  def UpgradeGroups(self):
    cl_ipolicy = self.config_data["cluster"].get("ipolicy")
    for group in self.config_data["nodegroups"].values():
      networks = group.get("networks", None)
      if not networks:
        group["networks"] = {}
      ipolicy = group.get("ipolicy", None)
      if ipolicy:
        if cl_ipolicy is None:
          raise Error("A group defines an instance policy but there is no"
                      " instance policy at cluster level")
        self.UpgradeIPolicy(ipolicy, cl_ipolicy, True)

  def GetExclusiveStorageValue(self):
    """Return a conservative value of the exclusive_storage flag.

    Return C{True} if the cluster or at least a nodegroup have the flag set.

    """
    ret = False
    cluster = self.config_data["cluster"]
    ndparams = cluster.get("ndparams")
    if ndparams is not None and ndparams.get("exclusive_storage"):
      ret = True
    for group in self.config_data["nodegroups"].values():
      ndparams = group.get("ndparams")
      if ndparams is not None and ndparams.get("exclusive_storage"):
        ret = True
    return ret

  def RemovePhysicalId(self, disk):
    if "children" in disk:
      for d in disk["children"]:
        self.RemovePhysicalId(d)
    if "physical_id" in disk:
      del disk["physical_id"]

  def ChangeDiskDevType(self, disk, dev_type_map):
    """Replaces disk's dev_type attributes according to the given map.

    This can be used for both, up or downgrading the disks.
    """
    if disk["dev_type"] in dev_type_map:
      disk["dev_type"] = dev_type_map[disk["dev_type"]]
    if "children" in disk:
      for child in disk["children"]:
        self.ChangeDiskDevType(child, dev_type_map)

  def UpgradeDiskDevType(self, disk):
    """Upgrades the disks' device type."""
    self.ChangeDiskDevType(disk, DEV_TYPE_OLD_NEW)

  @staticmethod
  def _ConvertNicNameToUuid(iobj, network2uuid):
    for nic in iobj["nics"]:
      name = nic.get("network", None)
      if name:
        uuid = network2uuid.get(name, None)
        if uuid:
          print("NIC with network name %s found."
                " Substituting with uuid %s." % (name, uuid))
          nic["network"] = uuid

  @classmethod
  def AssignUuid(cls, disk):
    if not "uuid" in disk:
      disk["uuid"] = utils.io.NewUUID()
    if "children" in disk:
      for d in disk["children"]:
        cls.AssignUuid(d)

  def _ConvertDiskAndCheckMissingSpindles(self, iobj, instance):
    missing_spindles = False
    if "disks" not in iobj:
      raise Error("Instance '%s' doesn't have a disks entry?!" % instance)
    disks = iobj["disks"]
    if not all(isinstance(d, str) for d in disks):
      #  Disks are not top level citizens
      for idx, dobj in enumerate(disks):
        self.RemovePhysicalId(dobj)

        expected = "disk/%s" % idx
        current = dobj.get("iv_name", "")
        if current != expected:
          logging.warning("Updating iv_name for instance %s/disk %s"
                          " from '%s' to '%s'",
                          instance, idx, current, expected)
          dobj["iv_name"] = expected

        if "dev_type" in dobj:
          self.UpgradeDiskDevType(dobj)

        if not "spindles" in dobj:
          missing_spindles = True

        self.AssignUuid(dobj)
    return missing_spindles

  @OrFail("Upgrading instance with spindles")
  def UpgradeInstances(self):
    """Upgrades the instances' configuration."""

    network2uuid = dict((n["name"], n["uuid"])
                        for n in self.config_data["networks"].values())
    if "instances" not in self.config_data:
      raise Error("Can't find the 'instances' key in the configuration!")

    missing_spindles = False
    for instance, iobj in self.config_data["instances"].items():
      self._ConvertNicNameToUuid(iobj, network2uuid)
      if self._ConvertDiskAndCheckMissingSpindles(iobj, instance):
        missing_spindles = True
      if "admin_state_source" not in iobj:
        iobj["admin_state_source"] = constants.ADMIN_SOURCE

    if self.GetExclusiveStorageValue() and missing_spindles:
      # We cannot be sure that the instances that are missing spindles have
      # exclusive storage enabled (the check would be more complicated), so we
      # give a noncommittal message
      logging.warning("Some instance disks could be needing to update the"
                      " spindles parameter; you can check by running"
                      " 'gnt-cluster verify', and fix any problem with"
                      " 'gnt-cluster repair-disk-sizes'")

  def UpgradeRapiUsers(self):
    if (os.path.isfile(self.opts.RAPI_USERS_FILE_PRE24) and
        not os.path.islink(self.opts.RAPI_USERS_FILE_PRE24)):
      if os.path.exists(self.opts.RAPI_USERS_FILE):
        raise Error("Found pre-2.4 RAPI users file at %s, but another file"
                    " already exists at %s" %
                    (self.opts.RAPI_USERS_FILE_PRE24,
                     self.opts.RAPI_USERS_FILE))
      logging.info("Found pre-2.4 RAPI users file at %s, renaming to %s",
                   self.opts.RAPI_USERS_FILE_PRE24, self.opts.RAPI_USERS_FILE)
      if not self.opts.dry_run:
        utils.RenameFile(self.opts.RAPI_USERS_FILE_PRE24,
                         self.opts.RAPI_USERS_FILE,
                         mkdir=True, mkdir_mode=0o750)

    # Create a symlink for RAPI users file
    if (not (os.path.islink(self.opts.RAPI_USERS_FILE_PRE24) or
             os.path.isfile(self.opts.RAPI_USERS_FILE_PRE24)) and
        os.path.isfile(self.opts.RAPI_USERS_FILE)):
      logging.info("Creating symlink from %s to %s",
                   self.opts.RAPI_USERS_FILE_PRE24, self.opts.RAPI_USERS_FILE)
      if not self.opts.dry_run:
        os.symlink(self.opts.RAPI_USERS_FILE, self.opts.RAPI_USERS_FILE_PRE24)

  def UpgradeWatcher(self):
    # Remove old watcher state file if it exists
    if os.path.exists(self.opts.WATCHER_STATEFILE):
      logging.info("Removing watcher state file %s",
                   self.opts.WATCHER_STATEFILE)
      if not self.opts.dry_run:
        utils.RemoveFile(self.opts.WATCHER_STATEFILE)

  @OrFail("Upgrading file storage paths")
  def UpgradeFileStoragePaths(self):
    # Write file storage paths
    if not os.path.exists(self.opts.FILE_STORAGE_PATHS_FILE):
      cluster = self.config_data["cluster"]
      file_storage_dir = cluster.get("file_storage_dir")
      shared_file_storage_dir = cluster.get("shared_file_storage_dir")
      del cluster

      logging.info("Ganeti 2.7 and later only allow whitelisted directories"
                   " for file storage; writing existing configuration values"
                   " into '%s'",
                   self.opts.FILE_STORAGE_PATHS_FILE)

      if file_storage_dir:
        logging.info("File storage directory: %s", file_storage_dir)
      if shared_file_storage_dir:
        logging.info("Shared file storage directory: %s",
                     shared_file_storage_dir)

      buf = StringIO()
      buf.write("# List automatically generated from configuration by\n")
      buf.write("# cfgupgrade at %s\n" % time.asctime())
      if file_storage_dir:
        buf.write("%s\n" % file_storage_dir)
      if shared_file_storage_dir:
        buf.write("%s\n" % shared_file_storage_dir)
      utils.WriteFile(file_name=self.opts.FILE_STORAGE_PATHS_FILE,
                      data=buf.getvalue(),
                      mode=0o600,
                      dry_run=self.opts.dry_run,
                      backup=True)

  @staticmethod
  def GetNewNodeIndex(nodes_by_old_key, old_key, new_key_field):
    if old_key not in nodes_by_old_key:
      logging.warning("Can't find node '%s' in configuration, "
                      "assuming that it's already up-to-date", old_key)
      return old_key
    return nodes_by_old_key[old_key][new_key_field]

  def ChangeNodeIndices(self, config_data, old_key_field, new_key_field):
    def ChangeDiskNodeIndices(disk):
      # Note: 'drbd8' is a legacy device type from pre 2.9 and needs to be
      # considered when up/downgrading from/to any versions touching 2.9 on the
      # way.
      drbd_disk_types = set(["drbd8"]) | constants.DTS_DRBD
      if disk["dev_type"] in drbd_disk_types:
        for i in range(0, 2):
          disk["logical_id"][i] = self.GetNewNodeIndex(nodes_by_old_key,
                                                       disk["logical_id"][i],
                                                       new_key_field)
      if "children" in disk:
        for child in disk["children"]:
          ChangeDiskNodeIndices(child)

    nodes_by_old_key = {}
    nodes_by_new_key = {}
    for (_, node) in config_data["nodes"].items():
      nodes_by_old_key[node[old_key_field]] = node
      nodes_by_new_key[node[new_key_field]] = node

    config_data["nodes"] = nodes_by_new_key

    cluster = config_data["cluster"]
    cluster["master_node"] = self.GetNewNodeIndex(nodes_by_old_key,
                                                  cluster["master_node"],
                                                  new_key_field)

    for inst in config_data["instances"].values():
      inst["primary_node"] = self.GetNewNodeIndex(nodes_by_old_key,
                                                  inst["primary_node"],
                                                  new_key_field)

    for disk in config_data["disks"].values():
      ChangeDiskNodeIndices(disk)

  @staticmethod
  def ChangeInstanceIndices(config_data, old_key_field, new_key_field):
    insts_by_old_key = {}
    insts_by_new_key = {}
    for (_, inst) in config_data["instances"].items():
      insts_by_old_key[inst[old_key_field]] = inst
      insts_by_new_key[inst[new_key_field]] = inst

    config_data["instances"] = insts_by_new_key

  @OrFail("Changing node indices")
  def UpgradeNodeIndices(self):
    self.ChangeNodeIndices(self.config_data, "name", "uuid")

  @OrFail("Changing instance indices")
  def UpgradeInstanceIndices(self):
    self.ChangeInstanceIndices(self.config_data, "name", "uuid")

  @OrFail("Adding filters")
  def UpgradeFilters(self):
    # pylint can't infer config_data type
    # pylint: disable=E1103
    filters = self.config_data.get("filters", None)
    if not filters:
      self.config_data["filters"] = {}

  @OrFail("Set top level disks")
  def UpgradeTopLevelDisks(self):
    """Upgrades the disks as config top level citizens."""
    if "instances" not in self.config_data:
      raise Error("Can't find the 'instances' key in the configuration!")

    if "disks" in self.config_data:
      # Disks are already top level citizens
      return

    self.config_data["disks"] = dict()
    for iobj in self.config_data["instances"].values():
      disk_uuids = []
      for disk in iobj["disks"]:
        duuid = disk["uuid"]
        disk["serial_no"] = 1
        # Instances may not have the ctime value, and the Haskell serialization
        # will have set it to zero.
        disk["ctime"] = disk["mtime"] = iobj.get("ctime", 0)
        self.config_data["disks"][duuid] = disk
        disk_uuids.append(duuid)
      iobj["disks"] = disk_uuids

  @OrFail("Removing disk template")
  def UpgradeDiskTemplate(self):
    if "instances" not in self.config_data:
      raise Error("Can't find the 'instances' dictionary in the configuration.")
    instances = self.config_data["instances"]
    for inst in instances.values():
      if "disk_template" in inst:
        del inst["disk_template"]

  # The following function is based on a method of class Disk with the same
  # name, but adjusted to work with dicts and sets.
  def _ComputeAllNodes(self, disk):
    """Recursively compute nodes given a top device."""
    nodes = set()
    if disk["dev_type"] in constants.DTS_DRBD:
      nodes = set(disk["logical_id"][:2])
    for child in disk.get("children", []):
      nodes |= self._ComputeAllNodes(child)
    return nodes

  def _RecursiveUpdateNodes(self, disk, nodes):
    disk["nodes"] = nodes
    for child in disk.get("children", []):
      self._RecursiveUpdateNodes(child, nodes)

  @OrFail("Upgrading disk nodes")
  def UpgradeDiskNodes(self):
    """Specify the nodes from which a disk is accessible in its definition.

    For every disk that is attached to an instance, get the UUIDs of the nodes
    that it's accessible from. There are three main cases:
    1) Internally mirrored disks (DRBD):
    These disks are accessible from two nodes, so the nodes list will include
    these. Their children (data, meta) are also accessible from two nodes,
    therefore they will inherit the nodes of the parent.
    2) Externally mirrored disks (Blockdev, Ext, Gluster, RBD, Shared File):
    These disks should be accessible from any node in the cluster, therefore the
    nodes list will be empty.
    3) Single-node disks (Plain, File):
    These disks are accessible from one node only, therefore the nodes list will
    consist only of the primary instance node.
    """
    disks = self.config_data["disks"]
    for instance in self.config_data["instances"].values():
      # Get all disk nodes for an instance
      instance_node = set([instance["primary_node"]])
      disk_nodes = set()
      for disk_uuid in instance["disks"]:
        disk_nodes |= self._ComputeAllNodes(disks[disk_uuid])
      all_nodes = list(instance_node | disk_nodes)

      # Populate the `nodes` list field of each disk.
      for disk_uuid in instance["disks"]:
        disk = disks[disk_uuid]
        if "nodes" in disk:
          # The "nodes" field has already been added for this disk.
          continue

        if disk["dev_type"] in constants.DTS_INT_MIRROR:
          self._RecursiveUpdateNodes(disk, all_nodes)
        elif disk["dev_type"] in (constants.DT_PLAIN, constants.DT_FILE):
          disk["nodes"] = all_nodes
        else:
          disk["nodes"] = []

  def UpgradeAll(self):
    self.config_data["version"] = version.BuildVersion(TARGET_MAJOR,
                                                       TARGET_MINOR, 0)
    self.UpgradeRapiUsers()
    self.UpgradeWatcher()
    steps = [self.UpgradeFileStoragePaths,
             self.UpgradeNetworks,
             self.UpgradeCluster,
             self.UpgradeGroups,
             self.UpgradeInstances,
             self.UpgradeTopLevelDisks,
             self.UpgradeNodeIndices,
             self.UpgradeInstanceIndices,
             self.UpgradeFilters,
             self.UpgradeDiskNodes,
             self.UpgradeDiskTemplate]
    for s in steps:
      s()
    return not self.errors

  # DOWNGRADE ------------------------------------------------------------

  @OrFail("Removing SSH parameters")
  def DowngradeSshKeyParams(self):
    """Removes the SSH key type and bits parameters from the config.

    Also fails if these have been changed from values appropriate in lower
    Ganeti versions.

    """
    # pylint: disable=E1103
    # Because config_data is a dictionary which has the get method.
    cluster = self.config_data.get("cluster", None)
    if cluster is None:
      raise Error("Can't find the cluster entry in the configuration")

    def _FetchAndDelete(key):
      val = cluster.get(key, None)
      if key in cluster:
        del cluster[key]
      return val

    ssh_key_type = _FetchAndDelete("ssh_key_type")
    _FetchAndDelete("ssh_key_bits")

    if ssh_key_type is not None and ssh_key_type != "dsa":
      raise Error("The current Ganeti setup is using non-DSA SSH keys, and"
                  " versions below 2.16 do not support these. To downgrade,"
                  " please perform a gnt-cluster renew-crypto using the "
                  " --new-ssh-keys and --ssh-key-type=dsa options, generating"
                  " DSA keys that older versions can also use.")

  def DowngradeAll(self):
    self.config_data["version"] = version.BuildVersion(DOWNGRADE_MAJOR,
                                                       DOWNGRADE_MINOR, 0)

    self.DowngradeSshKeyParams()
    return not self.errors

  def _ComposePaths(self):
    # We need to keep filenames locally because they might be renamed between
    # versions.
    self.opts.data_dir = os.path.abspath(self.opts.data_dir)
    self.opts.CONFIG_DATA_PATH = self.opts.data_dir + "/config.data"
    self.opts.SERVER_PEM_PATH = self.opts.data_dir + "/server.pem"
    self.opts.CLIENT_PEM_PATH = self.opts.data_dir + "/client.pem"
    self.opts.KNOWN_HOSTS_PATH = self.opts.data_dir + "/known_hosts"
    self.opts.RAPI_CERT_FILE = self.opts.data_dir + "/rapi.pem"
    self.opts.SPICE_CERT_FILE = self.opts.data_dir + "/spice.pem"
    self.opts.SPICE_CACERT_FILE = self.opts.data_dir + "/spice-ca.pem"
    self.opts.RAPI_USERS_FILE = self.opts.data_dir + "/rapi/users"
    self.opts.RAPI_USERS_FILE_PRE24 = self.opts.data_dir + "/rapi_users"
    self.opts.CONFD_HMAC_KEY = self.opts.data_dir + "/hmac.key"
    self.opts.CDS_FILE = self.opts.data_dir + "/cluster-domain-secret"
    self.opts.SSCONF_MASTER_NODE = self.opts.data_dir + "/ssconf_master_node"
    self.opts.WATCHER_STATEFILE = self.opts.data_dir + "/watcher.data"
    self.opts.FILE_STORAGE_PATHS_FILE = (self.opts.conf_dir +
                                         "/file-storage-paths")

  def _AskUser(self):
    if not self.opts.force:
      if self.opts.downgrade:
        usertext = ("The configuration is going to be DOWNGRADED "
                    "to version %s.%s. Some configuration data might be "
                    " removed if they don't fit"
                    " in the old format. Please make sure you have read the"
                    " upgrade notes (available in the UPGRADE file and included"
                    " in other documentation formats) to understand what they"
                    " are. Continue with *DOWNGRADING* the configuration?" %
                    (DOWNGRADE_MAJOR, DOWNGRADE_MINOR))
      else:
        usertext = ("Please make sure you have read the upgrade notes for"
                    " Ganeti %s (available in the UPGRADE file and included"
                    " in other documentation formats). Continue with upgrading"
                    " configuration?" % constants.RELEASE_VERSION)
      if not cli.AskUser(usertext):
        sys.exit(constants.EXIT_FAILURE)

  def _Downgrade(self, config_major, config_minor, config_version,
                 config_revision):
    if not ((config_major == TARGET_MAJOR and config_minor == TARGET_MINOR) or
            (config_major == DOWNGRADE_MAJOR and
             config_minor == DOWNGRADE_MINOR)):
      raise Error("Downgrade supported only from the latest version (%s.%s),"
                  " found %s (%s.%s.%s) instead" %
                  (TARGET_MAJOR, TARGET_MINOR, config_version, config_major,
                   config_minor, config_revision))
    if not self.DowngradeAll():
      raise Error("Downgrade failed:\n%s" % "\n".join(self.errors))

  def _TestLoadingConfigFile(self):
    # test loading the config file
    all_ok = True
    if not (self.opts.dry_run or self.opts.no_verify):
      logging.info("Testing the new config file...")
      cfg = config.ConfigWriter(cfg_file=self.opts.CONFIG_DATA_PATH,
                                accept_foreign=self.opts.ignore_hostname,
                                offline=True)
      # if we reached this, it's all fine
      vrfy = cfg.VerifyConfig()
      if vrfy:
        logging.error("Errors after conversion:")
        for item in vrfy:
          logging.error(" - %s", item)
        all_ok = False
      else:
        logging.info("File loaded successfully after upgrading")
      del cfg

    if self.opts.downgrade:
      action = "downgraded"
      out_ver = "%s.%s" % (DOWNGRADE_MAJOR, DOWNGRADE_MINOR)
    else:
      action = "upgraded"
      out_ver = constants.RELEASE_VERSION
    if all_ok:
      cli.ToStderr("Configuration successfully %s to version %s.",
                   action, out_ver)
    else:
      cli.ToStderr("Configuration %s to version %s, but there are errors."
                   "\nPlease review the file.", action, out_ver)
