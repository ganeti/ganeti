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


"""Global Configuration data for Ganeti.

This module provides the interface to a special case of cluster
configuration data, which is mostly static and available to all nodes.

"""

import sys
import errno
import logging

from ganeti import errors
from ganeti import constants
from ganeti import utils
from ganeti import netutils
from ganeti import pathutils


SSCONF_LOCK_TIMEOUT = 10

#: Valid ssconf keys
_VALID_KEYS = constants.VALID_SS_KEYS

#: Maximum size for ssconf files
_MAX_SIZE = 128 * 1024


def ReadSsconfFile(filename):
  """Reads an ssconf file and verifies its size.

  @type filename: string
  @param filename: Path to file
  @rtype: string
  @return: File contents without newlines at the end
  @raise RuntimeError: When the file size exceeds L{_MAX_SIZE}

  """
  statcb = utils.FileStatHelper()

  data = utils.ReadFile(filename, size=_MAX_SIZE, preread=statcb)

  if statcb.st.st_size > _MAX_SIZE:
    msg = ("File '%s' has a size of %s bytes (up to %s allowed)" %
           (filename, statcb.st.st_size, _MAX_SIZE))
    raise RuntimeError(msg)

  return data.rstrip("\n")


class SimpleStore(object):
  """Interface to static cluster data.

  This is different that the config.ConfigWriter and
  SimpleConfigReader classes in that it holds data that will always be
  present, even on nodes which don't have all the cluster data.

  Other particularities of the datastore:
    - keys are restricted to predefined values

  """
  def __init__(self, cfg_location=None, _lockfile=pathutils.SSCONF_LOCK_FILE):
    if cfg_location is None:
      self._cfg_dir = pathutils.DATA_DIR
    else:
      self._cfg_dir = cfg_location

    self._lockfile = _lockfile

  def KeyToFilename(self, key):
    """Convert a given key into filename.

    """
    if key not in _VALID_KEYS:
      raise errors.ProgrammerError("Invalid key requested from SSConf: '%s'"
                                   % str(key))

    filename = self._cfg_dir + "/" + constants.SSCONF_FILEPREFIX + key
    return filename

  def _ReadFile(self, key, default=None):
    """Generic routine to read keys.

    This will read the file which holds the value requested. Errors
    will be changed into ConfigurationErrors.

    """
    filename = self.KeyToFilename(key)
    try:
      return ReadSsconfFile(filename)
    except EnvironmentError, err:
      if err.errno == errno.ENOENT and default is not None:
        return default
      raise errors.ConfigurationError("Can't read ssconf file %s: %s" %
                                      (filename, str(err)))

  def ReadAll(self):
    """Reads all keys and returns their values.

    @rtype: dict
    @return: Dictionary, ssconf key as key, value as value

    """
    result = []

    for key in _VALID_KEYS:
      try:
        value = self._ReadFile(key)
      except errors.ConfigurationError:
        # Ignore non-existing files
        pass
      else:
        result.append((key, value))

    return dict(result)

  def WriteFiles(self, values, dry_run=False):
    """Writes ssconf files used by external scripts.

    @type values: dict
    @param values: Dictionary of (name, value)
    @type dry_run boolean
    @param dry_run: Whether to perform a dry run

    """
    ssconf_lock = utils.FileLock.Open(self._lockfile)

    # Get lock while writing files
    ssconf_lock.Exclusive(blocking=True, timeout=SSCONF_LOCK_TIMEOUT)
    try:
      for name, value in values.iteritems():
        if isinstance(value, (list, tuple)):
          value = "\n".join(value)
        if value and not value.endswith("\n"):
          value += "\n"

        if len(value) > _MAX_SIZE:
          msg = ("Value '%s' has a length of %s bytes, but only up to %s are"
                 " allowed" % (name, len(value), _MAX_SIZE))
          raise errors.ConfigurationError(msg)

        utils.WriteFile(self.KeyToFilename(name), data=value,
                        mode=constants.SS_FILE_PERMS,
                        dry_run=dry_run)
    finally:
      ssconf_lock.Unlock()

  def GetFileList(self):
    """Return the list of all config files.

    This is used for computing node replication data.

    """
    return [self.KeyToFilename(key) for key in _VALID_KEYS]

  def GetClusterName(self):
    """Get the cluster name.

    """
    return self._ReadFile(constants.SS_CLUSTER_NAME)

  def GetFileStorageDir(self):
    """Get the file storage dir.

    """
    return self._ReadFile(constants.SS_FILE_STORAGE_DIR)

  def GetSharedFileStorageDir(self):
    """Get the shared file storage dir.

    """
    return self._ReadFile(constants.SS_SHARED_FILE_STORAGE_DIR)

  def GetGlusterStorageDir(self):
    """Get the Gluster storage dir.

    """
    return self._ReadFile(constants.SS_GLUSTER_STORAGE_DIR)

  def GetMasterCandidates(self):
    """Return the list of master candidates.

    """
    data = self._ReadFile(constants.SS_MASTER_CANDIDATES)
    nl = data.splitlines(False)
    return nl

  def GetMasterCandidatesIPList(self):
    """Return the list of master candidates' primary IP.

    """
    data = self._ReadFile(constants.SS_MASTER_CANDIDATES_IPS)
    nl = data.splitlines(False)
    return nl

  def _GetDictOfSsconfMap(self, ss_file_key):
    """Reads a file with lines like key=value and returns a dict.

    This utility function reads a file containing ssconf values of
    the form "key=value", splits the lines at "=" and returns a
    dictionary mapping the keys to the values.

    @type ss_file_key: string
    @param ss_file_key: the constant referring to an ssconf file
    @rtype: dict of string to string
    @return: a dictionary mapping the keys to the values

    """
    data = self._ReadFile(ss_file_key)
    lines = data.splitlines(False)
    mapping = {}
    for line in lines:
      (key, value) = line.split("=")
      mapping[key] = value
    return mapping

  def GetMasterCandidatesCertMap(self):
    """Returns the map of master candidate UUIDs to ssl cert.

    @rtype: dict of string to string
    @return: dictionary mapping the master candidates' UUIDs
      to their SSL certificate digests

    """
    return self._GetDictOfSsconfMap(constants.SS_MASTER_CANDIDATES_CERTS)

  def GetSshPortMap(self):
    """Returns the map of node names to SSH port.

    @rtype: dict of string to string
    @return: dictionary mapping the node names to their SSH port

    """
    return dict([(node_name, int(ssh_port)) for
                  node_name, ssh_port in
                  self._GetDictOfSsconfMap(constants.SS_SSH_PORTS).items()])

  def GetMasterIP(self):
    """Get the IP of the master node for this cluster.

    """
    return self._ReadFile(constants.SS_MASTER_IP)

  def GetMasterNetdev(self):
    """Get the netdev to which we'll add the master ip.

    """
    return self._ReadFile(constants.SS_MASTER_NETDEV)

  def GetMasterNetmask(self):
    """Get the master netmask.

    """
    try:
      return self._ReadFile(constants.SS_MASTER_NETMASK)
    except errors.ConfigurationError:
      family = self.GetPrimaryIPFamily()
      ipcls = netutils.IPAddress.GetClassFromIpFamily(family)
      return ipcls.iplen

  def GetMasterNode(self):
    """Get the hostname of the master node for this cluster.

    """
    return self._ReadFile(constants.SS_MASTER_NODE)

  def GetNodeList(self):
    """Return the list of cluster nodes.

    """
    data = self._ReadFile(constants.SS_NODE_LIST)
    nl = data.splitlines(False)
    return nl

  def GetOnlineNodeList(self):
    """Return the list of online cluster nodes.

    """
    data = self._ReadFile(constants.SS_ONLINE_NODES)
    nl = data.splitlines(False)
    return nl

  def GetNodePrimaryIPList(self):
    """Return the list of cluster nodes' primary IP.

    """
    data = self._ReadFile(constants.SS_NODE_PRIMARY_IPS)
    nl = data.splitlines(False)
    return nl

  def GetNodeSecondaryIPList(self):
    """Return the list of cluster nodes' secondary IP.

    """
    data = self._ReadFile(constants.SS_NODE_SECONDARY_IPS)
    nl = data.splitlines(False)
    return nl

  def GetNodesVmCapable(self):
    """Return the cluster nodes' vm capable value.

    @rtype: dict of string to bool
    @return: mapping of node names to vm capable values

    """
    data = self._ReadFile(constants.SS_NODE_VM_CAPABLE)
    vm_capable = {}
    for line in data.splitlines(False):
      (node_uuid, node_vm_capable) = line.split("=")
      vm_capable[node_uuid] = node_vm_capable == "True"
    return vm_capable

  def GetNodegroupList(self):
    """Return the list of nodegroups.

    """
    data = self._ReadFile(constants.SS_NODEGROUPS)
    nl = data.splitlines(False)
    return nl

  def GetNetworkList(self):
    """Return the list of networks.

    """
    data = self._ReadFile(constants.SS_NETWORKS)
    nl = data.splitlines(False)
    return nl

  def GetClusterTags(self):
    """Return the cluster tags.

    """
    data = self._ReadFile(constants.SS_CLUSTER_TAGS)
    nl = data.splitlines(False)
    return nl

  def GetHypervisorList(self):
    """Return the list of enabled hypervisors.

    """
    data = self._ReadFile(constants.SS_HYPERVISOR_LIST)
    nl = data.splitlines(False)
    return nl

  def GetHvparamsForHypervisor(self, hvname):
    """Return the hypervisor parameters of the given hypervisor.

    @type hvname: string
    @param hvname: name of the hypervisor, must be in C{constants.HYPER_TYPES}
    @rtype: dict of strings
    @returns: dictionary with hypervisor parameters

    """
    return self._GetDictOfSsconfMap(constants.SS_HVPARAMS_PREF + hvname)

  def GetHvparams(self):
    """Return the hypervisor parameters of all hypervisors.

    @rtype: dict of dict of strings
    @returns: dictionary mapping hypervisor names to hvparams

    """
    all_hvparams = {}
    for hv in constants.HYPER_TYPES:
      all_hvparams[hv] = self.GetHvparamsForHypervisor(hv)
    return all_hvparams

  def GetMaintainNodeHealth(self):
    """Return the value of the maintain_node_health option.

    """
    data = self._ReadFile(constants.SS_MAINTAIN_NODE_HEALTH)
    # we rely on the bool serialization here
    return data == "True"

  def GetUidPool(self):
    """Return the user-id pool definition string.

    The separator character is a newline.

    The return value can be parsed using uidpool.ParseUidPool()::

      ss = ssconf.SimpleStore()
      uid_pool = uidpool.ParseUidPool(ss.GetUidPool(), separator="\\n")

    """
    data = self._ReadFile(constants.SS_UID_POOL)
    return data

  def GetPrimaryIPFamily(self):
    """Return the cluster-wide primary address family.

    """
    try:
      return int(self._ReadFile(constants.SS_PRIMARY_IP_FAMILY,
                                default=netutils.IP4Address.family))
    except (ValueError, TypeError), err:
      raise errors.ConfigurationError("Error while trying to parse primary IP"
                                      " family: %s" % err)

  def GetEnabledUserShutdown(self):
    """Return whether user shutdown is enabled.

    @rtype: bool
    @return: 'True' if user shutdown is enabled, 'False' otherwise

    """
    return self._ReadFile(constants.SS_ENABLED_USER_SHUTDOWN) == "True"


def WriteSsconfFiles(values, dry_run=False):
  """Update all ssconf files.

  Wrapper around L{SimpleStore.WriteFiles}.

  """
  SimpleStore().WriteFiles(values, dry_run=dry_run)


def GetMasterAndMyself(ss=None):
  """Get the master node and my own hostname.

  This can be either used for a 'soft' check (compared to CheckMaster,
  which exits) or just for computing both at the same time.

  The function does not handle any errors, these should be handled in
  the caller (errors.ConfigurationError, errors.ResolverError).

  @param ss: either a sstore.SimpleConfigReader or a
      sstore.SimpleStore instance
  @rtype: tuple
  @return: a tuple (master node name, my own name)

  """
  if ss is None:
    ss = SimpleStore()
  return ss.GetMasterNode(), netutils.Hostname.GetSysName()


def CheckMaster(debug, ss=None):
  """Checks the node setup.

  If this is the master, the function will return. Otherwise it will
  exit with an exit code based on the node status.

  """
  try:
    master_name, myself = GetMasterAndMyself(ss)
  except errors.ConfigurationError, err:
    print "Cluster configuration incomplete: '%s'" % str(err)
    sys.exit(constants.EXIT_NODESETUP_ERROR)
  except errors.ResolverError, err:
    sys.stderr.write("Cannot resolve my own name (%s)\n" % err.args[0])
    sys.exit(constants.EXIT_NODESETUP_ERROR)

  if myself != master_name:
    if debug:
      sys.stderr.write("Not master, exiting.\n")
    sys.exit(constants.EXIT_NOTMASTER)


def VerifyClusterName(name, _cfg_location=None):
  """Verifies cluster name against a local cluster name.

  @type name: string
  @param name: Cluster name

  """
  sstore = SimpleStore(cfg_location=_cfg_location)

  try:
    local_name = sstore.GetClusterName()
  except errors.ConfigurationError, err:
    logging.debug("Can't get local cluster name: %s", err)
  else:
    if name != local_name:
      raise errors.GenericError("Current cluster name is '%s'" % local_name)


def VerifyKeys(keys):
  """Raises an exception if unknown ssconf keys are given.

  @type keys: sequence
  @param keys: Key names to verify
  @raise errors.GenericError: When invalid keys were found

  """
  invalid = frozenset(keys) - _VALID_KEYS
  if invalid:
    raise errors.GenericError("Invalid ssconf keys: %s" %
                              utils.CommaJoin(sorted(invalid)))
