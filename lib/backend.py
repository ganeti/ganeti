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


"""Functions used by the node daemon

@var _ALLOWED_UPLOAD_FILES: denotes which files are accepted in
     the L{UploadFile} function
@var _ALLOWED_CLEAN_DIRS: denotes which directories are accepted
     in the L{_CleanDirectory} function

"""

# pylint: disable=E1103,C0302

# E1103: %s %r has no %r member (but some types could not be
# inferred), because the _TryOSFromDisk returns either (True, os_obj)
# or (False, "string") which confuses pylint

# C0302: This module has become too big and should be split up


import os
import os.path
import shutil
import time
import stat
import errno
import re
import random
import logging
import tempfile
import zlib
import base64
import signal

from ganeti import errors
from ganeti import utils
from ganeti import ssh
from ganeti import hypervisor
from ganeti import constants
from ganeti.storage import bdev
from ganeti.storage import drbd
from ganeti.storage import filestorage
from ganeti import objects
from ganeti import ssconf
from ganeti import serializer
from ganeti import netutils
from ganeti import runtime
from ganeti import compat
from ganeti import pathutils
from ganeti import vcluster
from ganeti import ht
from ganeti.storage.base import BlockDev
from ganeti.storage.drbd import DRBD8
from ganeti import hooksmaster


_BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
_ALLOWED_CLEAN_DIRS = compat.UniqueFrozenset([
  pathutils.DATA_DIR,
  pathutils.JOB_QUEUE_ARCHIVE_DIR,
  pathutils.QUEUE_DIR,
  pathutils.CRYPTO_KEYS_DIR,
  ])
_MAX_SSL_CERT_VALIDITY = 7 * 24 * 60 * 60
_X509_KEY_FILE = "key"
_X509_CERT_FILE = "cert"
_IES_STATUS_FILE = "status"
_IES_PID_FILE = "pid"
_IES_CA_FILE = "ca"

#: Valid LVS output line regex
_LVSLINE_REGEX = re.compile(r"^ *([^|]+)\|([^|]+)\|([0-9.]+)\|([^|]{6,})\|?$")

# Actions for the master setup script
_MASTER_START = "start"
_MASTER_STOP = "stop"

#: Maximum file permissions for restricted command directory and executables
_RCMD_MAX_MODE = (stat.S_IRWXU |
                  stat.S_IRGRP | stat.S_IXGRP |
                  stat.S_IROTH | stat.S_IXOTH)

#: Delay before returning an error for restricted commands
_RCMD_INVALID_DELAY = 10

#: How long to wait to acquire lock for restricted commands (shorter than
#: L{_RCMD_INVALID_DELAY}) to reduce blockage of noded forks when many
#: command requests arrive
_RCMD_LOCK_TIMEOUT = _RCMD_INVALID_DELAY * 0.8


class RPCFail(Exception):
  """Class denoting RPC failure.

  Its argument is the error message.

  """


def _GetInstReasonFilename(instance_name):
  """Path of the file containing the reason of the instance status change.

  @type instance_name: string
  @param instance_name: The name of the instance
  @rtype: string
  @return: The path of the file

  """
  return utils.PathJoin(pathutils.INSTANCE_REASON_DIR, instance_name)


def _StoreInstReasonTrail(instance_name, trail):
  """Serialize a reason trail related to an instance change of state to file.

  The exact location of the file depends on the name of the instance and on
  the configuration of the Ganeti cluster defined at deploy time.

  @type instance_name: string
  @param instance_name: The name of the instance
  @rtype: None

  """
  json = serializer.DumpJson(trail)
  filename = _GetInstReasonFilename(instance_name)
  utils.WriteFile(filename, data=json)


def _Fail(msg, *args, **kwargs):
  """Log an error and the raise an RPCFail exception.

  This exception is then handled specially in the ganeti daemon and
  turned into a 'failed' return type. As such, this function is a
  useful shortcut for logging the error and returning it to the master
  daemon.

  @type msg: string
  @param msg: the text of the exception
  @raise RPCFail

  """
  if args:
    msg = msg % args
  if "log" not in kwargs or kwargs["log"]: # if we should log this error
    if "exc" in kwargs and kwargs["exc"]:
      logging.exception(msg)
    else:
      logging.error(msg)
  raise RPCFail(msg)


def _GetConfig():
  """Simple wrapper to return a SimpleStore.

  @rtype: L{ssconf.SimpleStore}
  @return: a SimpleStore instance

  """
  return ssconf.SimpleStore()


def _GetSshRunner(cluster_name):
  """Simple wrapper to return an SshRunner.

  @type cluster_name: str
  @param cluster_name: the cluster name, which is needed
      by the SshRunner constructor
  @rtype: L{ssh.SshRunner}
  @return: an SshRunner instance

  """
  return ssh.SshRunner(cluster_name)


def _Decompress(data):
  """Unpacks data compressed by the RPC client.

  @type data: list or tuple
  @param data: Data sent by RPC client
  @rtype: str
  @return: Decompressed data

  """
  assert isinstance(data, (list, tuple))
  assert len(data) == 2
  (encoding, content) = data
  if encoding == constants.RPC_ENCODING_NONE:
    return content
  elif encoding == constants.RPC_ENCODING_ZLIB_BASE64:
    return zlib.decompress(base64.b64decode(content))
  else:
    raise AssertionError("Unknown data encoding")


def _CleanDirectory(path, exclude=None):
  """Removes all regular files in a directory.

  @type path: str
  @param path: the directory to clean
  @type exclude: list
  @param exclude: list of files to be excluded, defaults
      to the empty list

  """
  if path not in _ALLOWED_CLEAN_DIRS:
    _Fail("Path passed to _CleanDirectory not in allowed clean targets: '%s'",
          path)

  if not os.path.isdir(path):
    return
  if exclude is None:
    exclude = []
  else:
    # Normalize excluded paths
    exclude = [os.path.normpath(i) for i in exclude]

  for rel_name in utils.ListVisibleFiles(path):
    full_name = utils.PathJoin(path, rel_name)
    if full_name in exclude:
      continue
    if os.path.isfile(full_name) and not os.path.islink(full_name):
      utils.RemoveFile(full_name)


def _BuildUploadFileList():
  """Build the list of allowed upload files.

  This is abstracted so that it's built only once at module import time.

  """
  allowed_files = set([
    pathutils.CLUSTER_CONF_FILE,
    pathutils.ETC_HOSTS,
    pathutils.SSH_KNOWN_HOSTS_FILE,
    pathutils.VNC_PASSWORD_FILE,
    pathutils.RAPI_CERT_FILE,
    pathutils.SPICE_CERT_FILE,
    pathutils.SPICE_CACERT_FILE,
    pathutils.RAPI_USERS_FILE,
    pathutils.CONFD_HMAC_KEY,
    pathutils.CLUSTER_DOMAIN_SECRET_FILE,
    ])

  for hv_name in constants.HYPER_TYPES:
    hv_class = hypervisor.GetHypervisorClass(hv_name)
    allowed_files.update(hv_class.GetAncillaryFiles()[0])

  assert pathutils.FILE_STORAGE_PATHS_FILE not in allowed_files, \
    "Allowed file storage paths should never be uploaded via RPC"

  return frozenset(allowed_files)


_ALLOWED_UPLOAD_FILES = _BuildUploadFileList()


def JobQueuePurge():
  """Removes job queue files and archived jobs.

  @rtype: tuple
  @return: True, None

  """
  _CleanDirectory(pathutils.QUEUE_DIR, exclude=[pathutils.JOB_QUEUE_LOCK_FILE])
  _CleanDirectory(pathutils.JOB_QUEUE_ARCHIVE_DIR)


def GetMasterNodeName():
  """Returns the master node name.

  @rtype: string
  @return: name of the master node
  @raise RPCFail: in case of errors

  """
  try:
    return _GetConfig().GetMasterNode()
  except errors.ConfigurationError, err:
    _Fail("Cluster configuration incomplete: %s", err, exc=True)


def RunLocalHooks(hook_opcode, hooks_path, env_builder_fn):
  """Decorator that runs hooks before and after the decorated function.

  @type hook_opcode: string
  @param hook_opcode: opcode of the hook
  @type hooks_path: string
  @param hooks_path: path of the hooks
  @type env_builder_fn: function
  @param env_builder_fn: function that returns a dictionary containing the
    environment variables for the hooks. Will get all the parameters of the
    decorated function.
  @raise RPCFail: in case of pre-hook failure

  """
  def decorator(fn):
    def wrapper(*args, **kwargs):
      _, myself = ssconf.GetMasterAndMyself()
      nodes = ([myself], [myself])  # these hooks run locally

      env_fn = compat.partial(env_builder_fn, *args, **kwargs)

      cfg = _GetConfig()
      hr = HooksRunner()
      hm = hooksmaster.HooksMaster(hook_opcode, hooks_path, nodes,
                                   hr.RunLocalHooks, None, env_fn,
                                   logging.warning, cfg.GetClusterName(),
                                   cfg.GetMasterNode())
      hm.RunPhase(constants.HOOKS_PHASE_PRE)
      result = fn(*args, **kwargs)
      hm.RunPhase(constants.HOOKS_PHASE_POST)

      return result
    return wrapper
  return decorator


def _BuildMasterIpEnv(master_params, use_external_mip_script=None):
  """Builds environment variables for master IP hooks.

  @type master_params: L{objects.MasterNetworkParameters}
  @param master_params: network parameters of the master
  @type use_external_mip_script: boolean
  @param use_external_mip_script: whether to use an external master IP
    address setup script (unused, but necessary per the implementation of the
    _RunLocalHooks decorator)

  """
  # pylint: disable=W0613
  ver = netutils.IPAddress.GetVersionFromAddressFamily(master_params.ip_family)
  env = {
    "MASTER_NETDEV": master_params.netdev,
    "MASTER_IP": master_params.ip,
    "MASTER_NETMASK": str(master_params.netmask),
    "CLUSTER_IP_VERSION": str(ver),
  }

  return env


def _RunMasterSetupScript(master_params, action, use_external_mip_script):
  """Execute the master IP address setup script.

  @type master_params: L{objects.MasterNetworkParameters}
  @param master_params: network parameters of the master
  @type action: string
  @param action: action to pass to the script. Must be one of
    L{backend._MASTER_START} or L{backend._MASTER_STOP}
  @type use_external_mip_script: boolean
  @param use_external_mip_script: whether to use an external master IP
    address setup script
  @raise backend.RPCFail: if there are errors during the execution of the
    script

  """
  env = _BuildMasterIpEnv(master_params)

  if use_external_mip_script:
    setup_script = pathutils.EXTERNAL_MASTER_SETUP_SCRIPT
  else:
    setup_script = pathutils.DEFAULT_MASTER_SETUP_SCRIPT

  result = utils.RunCmd([setup_script, action], env=env, reset_env=True)

  if result.failed:
    _Fail("Failed to %s the master IP. Script return value: %s, output: '%s'" %
          (action, result.exit_code, result.output), log=True)


@RunLocalHooks(constants.FAKE_OP_MASTER_TURNUP, "master-ip-turnup",
               _BuildMasterIpEnv)
def ActivateMasterIp(master_params, use_external_mip_script):
  """Activate the IP address of the master daemon.

  @type master_params: L{objects.MasterNetworkParameters}
  @param master_params: network parameters of the master
  @type use_external_mip_script: boolean
  @param use_external_mip_script: whether to use an external master IP
    address setup script
  @raise RPCFail: in case of errors during the IP startup

  """
  _RunMasterSetupScript(master_params, _MASTER_START,
                        use_external_mip_script)


def StartMasterDaemons(no_voting):
  """Activate local node as master node.

  The function will start the master daemons (ganeti-masterd and ganeti-rapi).

  @type no_voting: boolean
  @param no_voting: whether to start ganeti-masterd without a node vote
      but still non-interactively
  @rtype: None

  """

  if no_voting:
    masterd_args = "--no-voting --yes-do-it"
  else:
    masterd_args = ""

  env = {
    "EXTRA_MASTERD_ARGS": masterd_args,
    }

  result = utils.RunCmd([pathutils.DAEMON_UTIL, "start-master"], env=env)
  if result.failed:
    msg = "Can't start Ganeti master: %s" % result.output
    logging.error(msg)
    _Fail(msg)


@RunLocalHooks(constants.FAKE_OP_MASTER_TURNDOWN, "master-ip-turndown",
               _BuildMasterIpEnv)
def DeactivateMasterIp(master_params, use_external_mip_script):
  """Deactivate the master IP on this node.

  @type master_params: L{objects.MasterNetworkParameters}
  @param master_params: network parameters of the master
  @type use_external_mip_script: boolean
  @param use_external_mip_script: whether to use an external master IP
    address setup script
  @raise RPCFail: in case of errors during the IP turndown

  """
  _RunMasterSetupScript(master_params, _MASTER_STOP,
                        use_external_mip_script)


def StopMasterDaemons():
  """Stop the master daemons on this node.

  Stop the master daemons (ganeti-masterd and ganeti-rapi) on this node.

  @rtype: None

  """
  # TODO: log and report back to the caller the error failures; we
  # need to decide in which case we fail the RPC for this

  result = utils.RunCmd([pathutils.DAEMON_UTIL, "stop-master"])
  if result.failed:
    logging.error("Could not stop Ganeti master, command %s had exitcode %s"
                  " and error %s",
                  result.cmd, result.exit_code, result.output)


def ChangeMasterNetmask(old_netmask, netmask, master_ip, master_netdev):
  """Change the netmask of the master IP.

  @param old_netmask: the old value of the netmask
  @param netmask: the new value of the netmask
  @param master_ip: the master IP
  @param master_netdev: the master network device

  """
  if old_netmask == netmask:
    return

  if not netutils.IPAddress.Own(master_ip):
    _Fail("The master IP address is not up, not attempting to change its"
          " netmask")

  result = utils.RunCmd([constants.IP_COMMAND_PATH, "address", "add",
                         "%s/%s" % (master_ip, netmask),
                         "dev", master_netdev, "label",
                         "%s:0" % master_netdev])
  if result.failed:
    _Fail("Could not set the new netmask on the master IP address")

  result = utils.RunCmd([constants.IP_COMMAND_PATH, "address", "del",
                         "%s/%s" % (master_ip, old_netmask),
                         "dev", master_netdev, "label",
                         "%s:0" % master_netdev])
  if result.failed:
    _Fail("Could not bring down the master IP address with the old netmask")


def EtcHostsModify(mode, host, ip):
  """Modify a host entry in /etc/hosts.

  @param mode: The mode to operate. Either add or remove entry
  @param host: The host to operate on
  @param ip: The ip associated with the entry

  """
  if mode == constants.ETC_HOSTS_ADD:
    if not ip:
      RPCFail("Mode 'add' needs 'ip' parameter, but parameter not"
              " present")
    utils.AddHostToEtcHosts(host, ip)
  elif mode == constants.ETC_HOSTS_REMOVE:
    if ip:
      RPCFail("Mode 'remove' does not allow 'ip' parameter, but"
              " parameter is present")
    utils.RemoveHostFromEtcHosts(host)
  else:
    RPCFail("Mode not supported")


def LeaveCluster(modify_ssh_setup):
  """Cleans up and remove the current node.

  This function cleans up and prepares the current node to be removed
  from the cluster.

  If processing is successful, then it raises an
  L{errors.QuitGanetiException} which is used as a special case to
  shutdown the node daemon.

  @param modify_ssh_setup: boolean

  """
  _CleanDirectory(pathutils.DATA_DIR)
  _CleanDirectory(pathutils.CRYPTO_KEYS_DIR)
  JobQueuePurge()

  if modify_ssh_setup:
    try:
      priv_key, pub_key, auth_keys = ssh.GetUserFiles(constants.SSH_LOGIN_USER)

      utils.RemoveAuthorizedKey(auth_keys, utils.ReadFile(pub_key))

      utils.RemoveFile(priv_key)
      utils.RemoveFile(pub_key)
    except errors.OpExecError:
      logging.exception("Error while processing ssh files")

  try:
    utils.RemoveFile(pathutils.CONFD_HMAC_KEY)
    utils.RemoveFile(pathutils.RAPI_CERT_FILE)
    utils.RemoveFile(pathutils.SPICE_CERT_FILE)
    utils.RemoveFile(pathutils.SPICE_CACERT_FILE)
    utils.RemoveFile(pathutils.NODED_CERT_FILE)
  except: # pylint: disable=W0702
    logging.exception("Error while removing cluster secrets")

  result = utils.RunCmd([pathutils.DAEMON_UTIL, "stop", constants.CONFD])
  if result.failed:
    logging.error("Command %s failed with exitcode %s and error %s",
                  result.cmd, result.exit_code, result.output)

  # Raise a custom exception (handled in ganeti-noded)
  raise errors.QuitGanetiException(True, "Shutdown scheduled")


def _CheckStorageParams(params, num_params):
  """Performs sanity checks for storage parameters.

  @type params: list
  @param params: list of storage parameters
  @type num_params: int
  @param num_params: expected number of parameters

  """
  if params is None:
    raise errors.ProgrammerError("No storage parameters for storage"
                                 " reporting is provided.")
  if not isinstance(params, list):
    raise errors.ProgrammerError("The storage parameters are not of type"
                                 " list: '%s'" % params)
  if not len(params) == num_params:
    raise errors.ProgrammerError("Did not receive the expected number of"
                                 "storage parameters: expected %s,"
                                 " received '%s'" % (num_params, len(params)))


def _CheckLvmStorageParams(params):
  """Performs sanity check for the 'exclusive storage' flag.

  @see: C{_CheckStorageParams}

  """
  _CheckStorageParams(params, 1)
  excl_stor = params[0]
  if not isinstance(params[0], bool):
    raise errors.ProgrammerError("Exclusive storage parameter is not"
                                 " boolean: '%s'." % excl_stor)
  return excl_stor


def _GetLvmVgSpaceInfo(name, params):
  """Wrapper around C{_GetVgInfo} which checks the storage parameters.

  @type name: string
  @param name: name of the volume group
  @type params: list
  @param params: list of storage parameters, which in this case should be
    containing only one for exclusive storage

  """
  excl_stor = _CheckLvmStorageParams(params)
  return _GetVgInfo(name, excl_stor)


def _GetVgInfo(
    name, excl_stor, info_fn=bdev.LogicalVolume.GetVGInfo):
  """Retrieves information about a LVM volume group.

  """
  # TODO: GetVGInfo supports returning information for multiple VGs at once
  vginfo = info_fn([name], excl_stor)
  if vginfo:
    vg_free = int(round(vginfo[0][0], 0))
    vg_size = int(round(vginfo[0][1], 0))
  else:
    vg_free = None
    vg_size = None

  return {
    "type": constants.ST_LVM_VG,
    "name": name,
    "storage_free": vg_free,
    "storage_size": vg_size,
    }


def _GetLvmPvSpaceInfo(name, params):
  """Wrapper around C{_GetVgSpindlesInfo} with sanity checks.

  @see: C{_GetLvmVgSpaceInfo}

  """
  excl_stor = _CheckLvmStorageParams(params)
  return _GetVgSpindlesInfo(name, excl_stor)


def _GetVgSpindlesInfo(
    name, excl_stor, info_fn=bdev.LogicalVolume.GetVgSpindlesInfo):
  """Retrieves information about spindles in an LVM volume group.

  @type name: string
  @param name: VG name
  @type excl_stor: bool
  @param excl_stor: exclusive storage
  @rtype: dict
  @return: dictionary whose keys are "name", "vg_free", "vg_size" for VG name,
      free spindles, total spindles respectively

  """
  if excl_stor:
    (vg_free, vg_size) = info_fn(name)
  else:
    vg_free = 0
    vg_size = 0
  return {
    "type": constants.ST_LVM_PV,
    "name": name,
    "storage_free": vg_free,
    "storage_size": vg_size,
    }


def _GetHvInfo(name, hvparams, get_hv_fn=hypervisor.GetHypervisor):
  """Retrieves node information from a hypervisor.

  The information returned depends on the hypervisor. Common items:

    - vg_size is the size of the configured volume group in MiB
    - vg_free is the free size of the volume group in MiB
    - memory_dom0 is the memory allocated for domain0 in MiB
    - memory_free is the currently available (free) ram in MiB
    - memory_total is the total number of ram in MiB
    - hv_version: the hypervisor version, if available

  @type hvparams: dict of string
  @param hvparams: the hypervisor's hvparams

  """
  return get_hv_fn(name).GetNodeInfo(hvparams=hvparams)


def _GetHvInfoAll(hv_specs, get_hv_fn=hypervisor.GetHypervisor):
  """Retrieves node information for all hypervisors.

  See C{_GetHvInfo} for information on the output.

  @type hv_specs: list of pairs (string, dict of strings)
  @param hv_specs: list of pairs of a hypervisor's name and its hvparams

  """
  if hv_specs is None:
    return None

  result = []
  for hvname, hvparams in hv_specs:
    result.append(_GetHvInfo(hvname, hvparams, get_hv_fn))
  return result


def _GetNamedNodeInfo(names, fn):
  """Calls C{fn} for all names in C{names} and returns a dictionary.

  @rtype: None or dict

  """
  if names is None:
    return None
  else:
    return map(fn, names)


def GetNodeInfo(storage_units, hv_specs):
  """Gives back a hash with different information about the node.

  @type storage_units: list of tuples (string, string, list)
  @param storage_units: List of tuples (storage unit, identifier, parameters) to
    ask for disk space information. In case of lvm-vg, the identifier is
    the VG name. The parameters can contain additional, storage-type-specific
    parameters, for example exclusive storage for lvm storage.
  @type hv_specs: list of pairs (string, dict of strings)
  @param hv_specs: list of pairs of a hypervisor's name and its hvparams
  @rtype: tuple; (string, None/dict, None/dict)
  @return: Tuple containing boot ID, volume group information and hypervisor
    information

  """
  bootid = utils.ReadFile(_BOOT_ID_PATH, size=128).rstrip("\n")
  storage_info = _GetNamedNodeInfo(
    storage_units,
    (lambda (storage_type, storage_key, storage_params):
        _ApplyStorageInfoFunction(storage_type, storage_key, storage_params)))
  hv_info = _GetHvInfoAll(hv_specs)
  return (bootid, storage_info, hv_info)


def _GetFileStorageSpaceInfo(path, params):
  """Wrapper around filestorage.GetSpaceInfo.

  The purpose of this wrapper is to call filestorage.GetFileStorageSpaceInfo
  and ignore the *args parameter to not leak it into the filestorage
  module's code.

  @see: C{filestorage.GetFileStorageSpaceInfo} for description of the
    parameters.

  """
  _CheckStorageParams(params, 0)
  return filestorage.GetFileStorageSpaceInfo(path)


# FIXME: implement storage reporting for all missing storage types.
_STORAGE_TYPE_INFO_FN = {
  constants.ST_BLOCK: None,
  constants.ST_DISKLESS: None,
  constants.ST_EXT: None,
  constants.ST_FILE: _GetFileStorageSpaceInfo,
  constants.ST_LVM_PV: _GetLvmPvSpaceInfo,
  constants.ST_LVM_VG: _GetLvmVgSpaceInfo,
  constants.ST_SHARED_FILE: None,
  constants.ST_RADOS: None,
}


def _ApplyStorageInfoFunction(storage_type, storage_key, *args):
  """Looks up and applies the correct function to calculate free and total
  storage for the given storage type.

  @type storage_type: string
  @param storage_type: the storage type for which the storage shall be reported.
  @type storage_key: string
  @param storage_key: identifier of a storage unit, e.g. the volume group name
    of an LVM storage unit
  @type args: any
  @param args: various parameters that can be used for storage reporting. These
    parameters and their semantics vary from storage type to storage type and
    are just propagated in this function.
  @return: the results of the application of the storage space function (see
    _STORAGE_TYPE_INFO_FN) if storage space reporting is implemented for that
    storage type
  @raises NotImplementedError: for storage types who don't support space
    reporting yet
  """
  fn = _STORAGE_TYPE_INFO_FN[storage_type]
  if fn is not None:
    return fn(storage_key, *args)
  else:
    raise NotImplementedError


def _CheckExclusivePvs(pvi_list):
  """Check that PVs are not shared among LVs

  @type pvi_list: list of L{objects.LvmPvInfo} objects
  @param pvi_list: information about the PVs

  @rtype: list of tuples (string, list of strings)
  @return: offending volumes, as tuples: (pv_name, [lv1_name, lv2_name...])

  """
  res = []
  for pvi in pvi_list:
    if len(pvi.lv_list) > 1:
      res.append((pvi.name, pvi.lv_list))
  return res


def _VerifyHypervisors(what, vm_capable, result, all_hvparams,
                       get_hv_fn=hypervisor.GetHypervisor):
  """Verifies the hypervisor. Appends the results to the 'results' list.

  @type what: C{dict}
  @param what: a dictionary of things to check
  @type vm_capable: boolean
  @param vm_capable: whether or not this node is vm capable
  @type result: dict
  @param result: dictionary of verification results; results of the
    verifications in this function will be added here
  @type all_hvparams: dict of dict of string
  @param all_hvparams: dictionary mapping hypervisor names to hvparams
  @type get_hv_fn: function
  @param get_hv_fn: function to retrieve the hypervisor, to improve testability

  """
  if not vm_capable:
    return

  if constants.NV_HYPERVISOR in what:
    result[constants.NV_HYPERVISOR] = {}
    for hv_name in what[constants.NV_HYPERVISOR]:
      hvparams = all_hvparams[hv_name]
      try:
        val = get_hv_fn(hv_name).Verify(hvparams=hvparams)
      except errors.HypervisorError, err:
        val = "Error while checking hypervisor: %s" % str(err)
      result[constants.NV_HYPERVISOR][hv_name] = val


def _VerifyHvparams(what, vm_capable, result,
                    get_hv_fn=hypervisor.GetHypervisor):
  """Verifies the hvparams. Appends the results to the 'results' list.

  @type what: C{dict}
  @param what: a dictionary of things to check
  @type vm_capable: boolean
  @param vm_capable: whether or not this node is vm capable
  @type result: dict
  @param result: dictionary of verification results; results of the
    verifications in this function will be added here
  @type get_hv_fn: function
  @param get_hv_fn: function to retrieve the hypervisor, to improve testability

  """
  if not vm_capable:
    return

  if constants.NV_HVPARAMS in what:
    result[constants.NV_HVPARAMS] = []
    for source, hv_name, hvparms in what[constants.NV_HVPARAMS]:
      try:
        logging.info("Validating hv %s, %s", hv_name, hvparms)
        get_hv_fn(hv_name).ValidateParameters(hvparms)
      except errors.HypervisorError, err:
        result[constants.NV_HVPARAMS].append((source, hv_name, str(err)))


def _VerifyInstanceList(what, vm_capable, result, all_hvparams):
  """Verifies the instance list.

  @type what: C{dict}
  @param what: a dictionary of things to check
  @type vm_capable: boolean
  @param vm_capable: whether or not this node is vm capable
  @type result: dict
  @param result: dictionary of verification results; results of the
    verifications in this function will be added here
  @type all_hvparams: dict of dict of string
  @param all_hvparams: dictionary mapping hypervisor names to hvparams

  """
  if constants.NV_INSTANCELIST in what and vm_capable:
    # GetInstanceList can fail
    try:
      val = GetInstanceList(what[constants.NV_INSTANCELIST],
                            all_hvparams=all_hvparams)
    except RPCFail, err:
      val = str(err)
    result[constants.NV_INSTANCELIST] = val


def _VerifyNodeInfo(what, vm_capable, result, all_hvparams):
  """Verifies the node info.

  @type what: C{dict}
  @param what: a dictionary of things to check
  @type vm_capable: boolean
  @param vm_capable: whether or not this node is vm capable
  @type result: dict
  @param result: dictionary of verification results; results of the
    verifications in this function will be added here
  @type all_hvparams: dict of dict of string
  @param all_hvparams: dictionary mapping hypervisor names to hvparams

  """
  if constants.NV_HVINFO in what and vm_capable:
    hvname = what[constants.NV_HVINFO]
    hyper = hypervisor.GetHypervisor(hvname)
    hvparams = all_hvparams[hvname]
    result[constants.NV_HVINFO] = hyper.GetNodeInfo(hvparams=hvparams)


def _VerifyClientCertificate(cert_file=pathutils.NODED_CLIENT_CERT_FILE):
  """Verify the existance and validity of the client SSL certificate.

  """
  create_cert_cmd = "gnt-cluster renew-crypto --new-node-certificates"
  if not os.path.exists(cert_file):
    return (constants.CV_ERROR,
            "The client certificate does not exist. Run '%s' to create"
            "client certificates for all nodes." % create_cert_cmd)

  (errcode, msg) = utils.VerifyCertificate(cert_file)
  if errcode is not None:
    return (errcode, msg)
  else:
    # if everything is fine, we return the digest to be compared to the config
    return (None, utils.GetCertificateDigest(cert_filename=cert_file))


def VerifyNode(what, cluster_name, all_hvparams, node_groups, groups_cfg):
  """Verify the status of the local node.

  Based on the input L{what} parameter, various checks are done on the
  local node.

  If the I{filelist} key is present, this list of
  files is checksummed and the file/checksum pairs are returned.

  If the I{nodelist} key is present, we check that we have
  connectivity via ssh with the target nodes (and check the hostname
  report).

  If the I{node-net-test} key is present, we check that we have
  connectivity to the given nodes via both primary IP and, if
  applicable, secondary IPs.

  @type what: C{dict}
  @param what: a dictionary of things to check:
      - filelist: list of files for which to compute checksums
      - nodelist: list of nodes we should check ssh communication with
      - node-net-test: list of nodes we should check node daemon port
        connectivity with
      - hypervisor: list with hypervisors to run the verify for
  @type cluster_name: string
  @param cluster_name: the cluster's name
  @type all_hvparams: dict of dict of strings
  @param all_hvparams: a dictionary mapping hypervisor names to hvparams
  @type node_groups: a dict of strings
  @param node_groups: node _names_ mapped to their group uuids (it's enough to
      have only those nodes that are in `what["nodelist"]`)
  @type groups_cfg: a dict of dict of strings
  @param groups_cfg: a dictionary mapping group uuids to their configuration
  @rtype: dict
  @return: a dictionary with the same keys as the input dict, and
      values representing the result of the checks

  """
  result = {}
  my_name = netutils.Hostname.GetSysName()
  port = netutils.GetDaemonPort(constants.NODED)
  vm_capable = my_name not in what.get(constants.NV_VMNODES, [])

  _VerifyHypervisors(what, vm_capable, result, all_hvparams)
  _VerifyHvparams(what, vm_capable, result)

  if constants.NV_FILELIST in what:
    fingerprints = utils.FingerprintFiles(map(vcluster.LocalizeVirtualPath,
                                              what[constants.NV_FILELIST]))
    result[constants.NV_FILELIST] = \
      dict((vcluster.MakeVirtualPath(key), value)
           for (key, value) in fingerprints.items())

  if constants.NV_CLIENT_CERT in what:
    result[constants.NV_CLIENT_CERT] = _VerifyClientCertificate()

  if constants.NV_NODELIST in what:
    (nodes, bynode) = what[constants.NV_NODELIST]

    # Add nodes from other groups (different for each node)
    try:
      nodes.extend(bynode[my_name])
    except KeyError:
      pass

    # Use a random order
    random.shuffle(nodes)

    # Try to contact all nodes
    val = {}
    for node in nodes:
      params = groups_cfg.get(node_groups.get(node))
      ssh_port = params["ndparams"].get(constants.ND_SSH_PORT)
      logging.debug("Ssh port %s (None = default) for node %s",
                    str(ssh_port), node)
      success, message = _GetSshRunner(cluster_name). \
                            VerifyNodeHostname(node, ssh_port)
      if not success:
        val[node] = message

    result[constants.NV_NODELIST] = val

  if constants.NV_NODENETTEST in what:
    result[constants.NV_NODENETTEST] = tmp = {}
    my_pip = my_sip = None
    for name, pip, sip in what[constants.NV_NODENETTEST]:
      if name == my_name:
        my_pip = pip
        my_sip = sip
        break
    if not my_pip:
      tmp[my_name] = ("Can't find my own primary/secondary IP"
                      " in the node list")
    else:
      for name, pip, sip in what[constants.NV_NODENETTEST]:
        fail = []
        if not netutils.TcpPing(pip, port, source=my_pip):
          fail.append("primary")
        if sip != pip:
          if not netutils.TcpPing(sip, port, source=my_sip):
            fail.append("secondary")
        if fail:
          tmp[name] = ("failure using the %s interface(s)" %
                       " and ".join(fail))

  if constants.NV_MASTERIP in what:
    # FIXME: add checks on incoming data structures (here and in the
    # rest of the function)
    master_name, master_ip = what[constants.NV_MASTERIP]
    if master_name == my_name:
      source = constants.IP4_ADDRESS_LOCALHOST
    else:
      source = None
    result[constants.NV_MASTERIP] = netutils.TcpPing(master_ip, port,
                                                     source=source)

  if constants.NV_USERSCRIPTS in what:
    result[constants.NV_USERSCRIPTS] = \
      [script for script in what[constants.NV_USERSCRIPTS]
       if not utils.IsExecutable(script)]

  if constants.NV_OOB_PATHS in what:
    result[constants.NV_OOB_PATHS] = tmp = []
    for path in what[constants.NV_OOB_PATHS]:
      try:
        st = os.stat(path)
      except OSError, err:
        tmp.append("error stating out of band helper: %s" % err)
      else:
        if stat.S_ISREG(st.st_mode):
          if stat.S_IMODE(st.st_mode) & stat.S_IXUSR:
            tmp.append(None)
          else:
            tmp.append("out of band helper %s is not executable" % path)
        else:
          tmp.append("out of band helper %s is not a file" % path)

  if constants.NV_LVLIST in what and vm_capable:
    try:
      val = GetVolumeList(utils.ListVolumeGroups().keys())
    except RPCFail, err:
      val = str(err)
    result[constants.NV_LVLIST] = val

  _VerifyInstanceList(what, vm_capable, result, all_hvparams)

  if constants.NV_VGLIST in what and vm_capable:
    result[constants.NV_VGLIST] = utils.ListVolumeGroups()

  if constants.NV_PVLIST in what and vm_capable:
    check_exclusive_pvs = constants.NV_EXCLUSIVEPVS in what
    val = bdev.LogicalVolume.GetPVInfo(what[constants.NV_PVLIST],
                                       filter_allocatable=False,
                                       include_lvs=check_exclusive_pvs)
    if check_exclusive_pvs:
      result[constants.NV_EXCLUSIVEPVS] = _CheckExclusivePvs(val)
      for pvi in val:
        # Avoid sending useless data on the wire
        pvi.lv_list = []
    result[constants.NV_PVLIST] = map(objects.LvmPvInfo.ToDict, val)

  if constants.NV_VERSION in what:
    result[constants.NV_VERSION] = (constants.PROTOCOL_VERSION,
                                    constants.RELEASE_VERSION)

  _VerifyNodeInfo(what, vm_capable, result, all_hvparams)

  if constants.NV_DRBDVERSION in what and vm_capable:
    try:
      drbd_version = DRBD8.GetProcInfo().GetVersionString()
    except errors.BlockDeviceError, err:
      logging.warning("Can't get DRBD version", exc_info=True)
      drbd_version = str(err)
    result[constants.NV_DRBDVERSION] = drbd_version

  if constants.NV_DRBDLIST in what and vm_capable:
    try:
      used_minors = drbd.DRBD8.GetUsedDevs()
    except errors.BlockDeviceError, err:
      logging.warning("Can't get used minors list", exc_info=True)
      used_minors = str(err)
    result[constants.NV_DRBDLIST] = used_minors

  if constants.NV_DRBDHELPER in what and vm_capable:
    status = True
    try:
      payload = drbd.DRBD8.GetUsermodeHelper()
    except errors.BlockDeviceError, err:
      logging.error("Can't get DRBD usermode helper: %s", str(err))
      status = False
      payload = str(err)
    result[constants.NV_DRBDHELPER] = (status, payload)

  if constants.NV_NODESETUP in what:
    result[constants.NV_NODESETUP] = tmpr = []
    if not os.path.isdir("/sys/block") or not os.path.isdir("/sys/class/net"):
      tmpr.append("The sysfs filesytem doesn't seem to be mounted"
                  " under /sys, missing required directories /sys/block"
                  " and /sys/class/net")
    if (not os.path.isdir("/proc/sys") or
        not os.path.isfile("/proc/sysrq-trigger")):
      tmpr.append("The procfs filesystem doesn't seem to be mounted"
                  " under /proc, missing required directory /proc/sys and"
                  " the file /proc/sysrq-trigger")

  if constants.NV_TIME in what:
    result[constants.NV_TIME] = utils.SplitTime(time.time())

  if constants.NV_OSLIST in what and vm_capable:
    result[constants.NV_OSLIST] = DiagnoseOS()

  if constants.NV_BRIDGES in what and vm_capable:
    result[constants.NV_BRIDGES] = [bridge
                                    for bridge in what[constants.NV_BRIDGES]
                                    if not utils.BridgeExists(bridge)]

  if what.get(constants.NV_ACCEPTED_STORAGE_PATHS) == my_name:
    result[constants.NV_ACCEPTED_STORAGE_PATHS] = \
        filestorage.ComputeWrongFileStoragePaths()

  if what.get(constants.NV_FILE_STORAGE_PATH):
    pathresult = filestorage.CheckFileStoragePath(
        what[constants.NV_FILE_STORAGE_PATH])
    if pathresult:
      result[constants.NV_FILE_STORAGE_PATH] = pathresult

  if what.get(constants.NV_SHARED_FILE_STORAGE_PATH):
    pathresult = filestorage.CheckFileStoragePath(
        what[constants.NV_SHARED_FILE_STORAGE_PATH])
    if pathresult:
      result[constants.NV_SHARED_FILE_STORAGE_PATH] = pathresult

  return result


def GetCryptoTokens(token_requests):
  """Perform actions on the node's cryptographic tokens.

  Token types can be 'ssl' or 'ssh'. So far only some actions are implemented
  for 'ssl'. Action 'get' returns the digest of the public client ssl
  certificate. Action 'create' creates a new client certificate and private key
  and also returns the digest of the certificate. The third parameter of a
  token request are optional parameters for the actions, so far only the
  filename is supported.

  @type token_requests: list of tuples of (string, string, dict), where the
    first string is in constants.CRYPTO_TYPES, the second in
    constants.CRYPTO_ACTIONS. The third parameter is a dictionary of string
    to string.
  @param token_requests: list of requests of cryptographic tokens and actions
    to perform on them. The actions come with a dictionary of options.
  @rtype: list of tuples (string, string)
  @return: list of tuples of the token type and the public crypto token

  """
  _VALID_CERT_FILES = [pathutils.NODED_CERT_FILE,
                       pathutils.NODED_CLIENT_CERT_FILE,
                       pathutils.NODED_CLIENT_CERT_FILE_TMP]
  _DEFAULT_CERT_FILE = pathutils.NODED_CLIENT_CERT_FILE
  tokens = []
  for (token_type, action, options) in token_requests:
    if token_type not in constants.CRYPTO_TYPES:
      raise errors.ProgrammerError("Token type '%s' not supported." %
                                   token_type)
    if action not in constants.CRYPTO_ACTIONS:
      raise errors.ProgrammerError("Action '%s' is not supported." %
                                   action)
    if token_type == constants.CRYPTO_TYPE_SSL_DIGEST:
      if action == constants.CRYPTO_ACTION_CREATE:
        cert_filename = None
        if options:
          cert_filename = options.get(constants.CRYPTO_OPTION_CERT_FILE)
        if not cert_filename:
          cert_filename = _DEFAULT_CERT_FILE
        # For security reason, we don't allow arbitrary filenames
        if not cert_filename in _VALID_CERT_FILES:
          raise errors.ProgrammerError(
            "The certificate file name path '%s' is not allowed." %
            cert_filename)
        utils.GenerateNewSslCert(
          True, cert_filename,
          "Create new client SSL certificate in %s." % cert_filename)
        tokens.append((token_type,
                       utils.GetCertificateDigest(
                         cert_filename=cert_filename)))
      elif action == constants.CRYPTO_ACTION_GET:
        tokens.append((token_type,
                       utils.GetCertificateDigest()))
  return tokens


def GetBlockDevSizes(devices):
  """Return the size of the given block devices

  @type devices: list
  @param devices: list of block device nodes to query
  @rtype: dict
  @return:
    dictionary of all block devices under /dev (key). The value is their
    size in MiB.

    {'/dev/disk/by-uuid/123456-12321231-312312-312': 124}

  """
  DEV_PREFIX = "/dev/"
  blockdevs = {}

  for devpath in devices:
    if not utils.IsBelowDir(DEV_PREFIX, devpath):
      continue

    try:
      st = os.stat(devpath)
    except EnvironmentError, err:
      logging.warning("Error stat()'ing device %s: %s", devpath, str(err))
      continue

    if stat.S_ISBLK(st.st_mode):
      result = utils.RunCmd(["blockdev", "--getsize64", devpath])
      if result.failed:
        # We don't want to fail, just do not list this device as available
        logging.warning("Cannot get size for block device %s", devpath)
        continue

      size = int(result.stdout) / (1024 * 1024)
      blockdevs[devpath] = size
  return blockdevs


def GetVolumeList(vg_names):
  """Compute list of logical volumes and their size.

  @type vg_names: list
  @param vg_names: the volume groups whose LVs we should list, or
      empty for all volume groups
  @rtype: dict
  @return:
      dictionary of all partions (key) with value being a tuple of
      their size (in MiB), inactive and online status::

        {'xenvg/test1': ('20.06', True, True)}

      in case of errors, a string is returned with the error
      details.

  """
  lvs = {}
  sep = "|"
  if not vg_names:
    vg_names = []
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m", "--nosuffix",
                         "--separator=%s" % sep,
                         "-ovg_name,lv_name,lv_size,lv_attr"] + vg_names)
  if result.failed:
    _Fail("Failed to list logical volumes, lvs output: %s", result.output)

  for line in result.stdout.splitlines():
    line = line.strip()
    match = _LVSLINE_REGEX.match(line)
    if not match:
      logging.error("Invalid line returned from lvs output: '%s'", line)
      continue
    vg_name, name, size, attr = match.groups()
    inactive = attr[4] == "-"
    online = attr[5] == "o"
    virtual = attr[0] == "v"
    if virtual:
      # we don't want to report such volumes as existing, since they
      # don't really hold data
      continue
    lvs[vg_name + "/" + name] = (size, inactive, online)

  return lvs


def ListVolumeGroups():
  """List the volume groups and their size.

  @rtype: dict
  @return: dictionary with keys volume name and values the
      size of the volume

  """
  return utils.ListVolumeGroups()


def NodeVolumes():
  """List all volumes on this node.

  @rtype: list
  @return:
    A list of dictionaries, each having four keys:
      - name: the logical volume name,
      - size: the size of the logical volume
      - dev: the physical device on which the LV lives
      - vg: the volume group to which it belongs

    In case of errors, we return an empty list and log the
    error.

    Note that since a logical volume can live on multiple physical
    volumes, the resulting list might include a logical volume
    multiple times.

  """
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m", "--nosuffix",
                         "--separator=|",
                         "--options=lv_name,lv_size,devices,vg_name"])
  if result.failed:
    _Fail("Failed to list logical volumes, lvs output: %s",
          result.output)

  def parse_dev(dev):
    return dev.split("(")[0]

  def handle_dev(dev):
    return [parse_dev(x) for x in dev.split(",")]

  def map_line(line):
    line = [v.strip() for v in line]
    return [{"name": line[0], "size": line[1],
             "dev": dev, "vg": line[3]} for dev in handle_dev(line[2])]

  all_devs = []
  for line in result.stdout.splitlines():
    if line.count("|") >= 3:
      all_devs.extend(map_line(line.split("|")))
    else:
      logging.warning("Strange line in the output from lvs: '%s'", line)
  return all_devs


def BridgesExist(bridges_list):
  """Check if a list of bridges exist on the current node.

  @rtype: boolean
  @return: C{True} if all of them exist, C{False} otherwise

  """
  missing = []
  for bridge in bridges_list:
    if not utils.BridgeExists(bridge):
      missing.append(bridge)

  if missing:
    _Fail("Missing bridges %s", utils.CommaJoin(missing))


def GetInstanceListForHypervisor(hname, hvparams=None,
                                 get_hv_fn=hypervisor.GetHypervisor):
  """Provides a list of instances of the given hypervisor.

  @type hname: string
  @param hname: name of the hypervisor
  @type hvparams: dict of strings
  @param hvparams: hypervisor parameters for the given hypervisor
  @type get_hv_fn: function
  @param get_hv_fn: function that returns a hypervisor for the given hypervisor
    name; optional parameter to increase testability

  @rtype: list
  @return: a list of all running instances on the current node
    - instance1.example.com
    - instance2.example.com

  """
  results = []
  try:
    hv = get_hv_fn(hname)
    names = hv.ListInstances(hvparams=hvparams)
    results.extend(names)
  except errors.HypervisorError, err:
    _Fail("Error enumerating instances (hypervisor %s): %s",
          hname, err, exc=True)
  return results


def GetInstanceList(hypervisor_list, all_hvparams=None,
                    get_hv_fn=hypervisor.GetHypervisor):
  """Provides a list of instances.

  @type hypervisor_list: list
  @param hypervisor_list: the list of hypervisors to query information
  @type all_hvparams: dict of dict of strings
  @param all_hvparams: a dictionary mapping hypervisor types to respective
    cluster-wide hypervisor parameters
  @type get_hv_fn: function
  @param get_hv_fn: function that returns a hypervisor for the given hypervisor
    name; optional parameter to increase testability

  @rtype: list
  @return: a list of all running instances on the current node
    - instance1.example.com
    - instance2.example.com

  """
  results = []
  for hname in hypervisor_list:
    hvparams = all_hvparams[hname]
    results.extend(GetInstanceListForHypervisor(hname, hvparams=hvparams,
                                                get_hv_fn=get_hv_fn))
  return results


def GetInstanceInfo(instance, hname, hvparams=None):
  """Gives back the information about an instance as a dictionary.

  @type instance: string
  @param instance: the instance name
  @type hname: string
  @param hname: the hypervisor type of the instance
  @type hvparams: dict of strings
  @param hvparams: the instance's hvparams

  @rtype: dict
  @return: dictionary with the following keys:
      - memory: memory size of instance (int)
      - state: state of instance (HvInstanceState)
      - time: cpu time of instance (float)
      - vcpus: the number of vcpus (int)

  """
  output = {}

  iinfo = hypervisor.GetHypervisor(hname).GetInstanceInfo(instance,
                                                          hvparams=hvparams)
  if iinfo is not None:
    output["memory"] = iinfo[2]
    output["vcpus"] = iinfo[3]
    output["state"] = iinfo[4]
    output["time"] = iinfo[5]

  return output


def GetInstanceMigratable(instance):
  """Computes whether an instance can be migrated.

  @type instance: L{objects.Instance}
  @param instance: object representing the instance to be checked.

  @rtype: tuple
  @return: tuple of (result, description) where:
      - result: whether the instance can be migrated or not
      - description: a description of the issue, if relevant

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  iname = instance.name
  if iname not in hyper.ListInstances(instance.hvparams):
    _Fail("Instance %s is not running", iname)

  for idx in range(len(instance.disks)):
    link_name = _GetBlockDevSymlinkPath(iname, idx)
    if not os.path.islink(link_name):
      logging.warning("Instance %s is missing symlink %s for disk %d",
                      iname, link_name, idx)


def GetAllInstancesInfo(hypervisor_list, all_hvparams):
  """Gather data about all instances.

  This is the equivalent of L{GetInstanceInfo}, except that it
  computes data for all instances at once, thus being faster if one
  needs data about more than one instance.

  @type hypervisor_list: list
  @param hypervisor_list: list of hypervisors to query for instance data
  @type all_hvparams: dict of dict of strings
  @param all_hvparams: mapping of hypervisor names to hvparams

  @rtype: dict
  @return: dictionary of instance: data, with data having the following keys:
      - memory: memory size of instance (int)
      - state: xen state of instance (string)
      - time: cpu time of instance (float)
      - vcpus: the number of vcpus

  """
  output = {}
  for hname in hypervisor_list:
    hvparams = all_hvparams[hname]
    iinfo = hypervisor.GetHypervisor(hname).GetAllInstancesInfo(hvparams)
    if iinfo:
      for name, _, memory, vcpus, state, times in iinfo:
        value = {
          "memory": memory,
          "vcpus": vcpus,
          "state": state,
          "time": times,
          }
        if name in output:
          # we only check static parameters, like memory and vcpus,
          # and not state and time which can change between the
          # invocations of the different hypervisors
          for key in "memory", "vcpus":
            if value[key] != output[name][key]:
              _Fail("Instance %s is running twice"
                    " with different parameters", name)
        output[name] = value

  return output


def GetInstanceConsoleInfo(instance_param_dict,
                           get_hv_fn=hypervisor.GetHypervisor):
  """Gather data about the console access of a set of instances of this node.

  This function assumes that the caller already knows which instances are on
  this node, by calling a function such as L{GetAllInstancesInfo} or
  L{GetInstanceList}.

  For every instance, a large amount of configuration data needs to be
  provided to the hypervisor interface in order to receive the console
  information. Whether this could or should be cut down can be discussed.
  The information is provided in a dictionary indexed by instance name,
  allowing any number of instance queries to be done.

  @type instance_param_dict: dict of string to tuple of dictionaries, where the
    dictionaries represent: L{objects.Instance}, L{objects.Node},
    L{objects.NodeGroup}, HvParams, BeParams
  @param instance_param_dict: mapping of instance name to parameters necessary
    for console information retrieval

  @rtype: dict
  @return: dictionary of instance: data, with data having the following keys:
      - instance: instance name
      - kind: console kind
      - message: used with kind == CONS_MESSAGE, indicates console to be
                 unavailable, supplies error message
      - host: host to connect to
      - port: port to use
      - user: user for login
      - command: the command, broken into parts as an array
      - display: unknown, potentially unused?

  """

  output = {}
  for inst_name in instance_param_dict:
    instance = instance_param_dict[inst_name]["instance"]
    pnode = instance_param_dict[inst_name]["node"]
    group = instance_param_dict[inst_name]["group"]
    hvparams = instance_param_dict[inst_name]["hvParams"]
    beparams = instance_param_dict[inst_name]["beParams"]

    instance = objects.Instance.FromDict(instance)
    pnode = objects.Node.FromDict(pnode)
    group = objects.NodeGroup.FromDict(group)

    h = get_hv_fn(instance.hypervisor)
    output[inst_name] = h.GetInstanceConsole(instance, pnode, group,
                                             hvparams, beparams).ToDict()

  return output


def _InstanceLogName(kind, os_name, instance, component):
  """Compute the OS log filename for a given instance and operation.

  The instance name and os name are passed in as strings since not all
  operations have these as part of an instance object.

  @type kind: string
  @param kind: the operation type (e.g. add, import, etc.)
  @type os_name: string
  @param os_name: the os name
  @type instance: string
  @param instance: the name of the instance being imported/added/etc.
  @type component: string or None
  @param component: the name of the component of the instance being
      transferred

  """
  # TODO: Use tempfile.mkstemp to create unique filename
  if component:
    assert "/" not in component
    c_msg = "-%s" % component
  else:
    c_msg = ""
  base = ("%s-%s-%s%s-%s.log" %
          (kind, os_name, instance, c_msg, utils.TimestampForFilename()))
  return utils.PathJoin(pathutils.LOG_OS_DIR, base)


def InstanceOsAdd(instance, reinstall, debug):
  """Add an OS to an instance.

  @type instance: L{objects.Instance}
  @param instance: Instance whose OS is to be installed
  @type reinstall: boolean
  @param reinstall: whether this is an instance reinstall
  @type debug: integer
  @param debug: debug level, passed to the OS scripts
  @rtype: None

  """
  inst_os = OSFromDisk(instance.os)

  create_env = OSEnvironment(instance, inst_os, debug)
  if reinstall:
    create_env["INSTANCE_REINSTALL"] = "1"

  logfile = _InstanceLogName("add", instance.os, instance.name, None)

  result = utils.RunCmd([inst_os.create_script], env=create_env,
                        cwd=inst_os.path, output=logfile, reset_env=True)
  if result.failed:
    logging.error("os create command '%s' returned error: %s, logfile: %s,"
                  " output: %s", result.cmd, result.fail_reason, logfile,
                  result.output)
    lines = [utils.SafeEncode(val)
             for val in utils.TailFile(logfile, lines=20)]
    _Fail("OS create script failed (%s), last lines in the"
          " log file:\n%s", result.fail_reason, "\n".join(lines), log=False)


def RunRenameInstance(instance, old_name, debug):
  """Run the OS rename script for an instance.

  @type instance: L{objects.Instance}
  @param instance: Instance whose OS is to be installed
  @type old_name: string
  @param old_name: previous instance name
  @type debug: integer
  @param debug: debug level, passed to the OS scripts
  @rtype: boolean
  @return: the success of the operation

  """
  inst_os = OSFromDisk(instance.os)

  rename_env = OSEnvironment(instance, inst_os, debug)
  rename_env["OLD_INSTANCE_NAME"] = old_name

  logfile = _InstanceLogName("rename", instance.os,
                             "%s-%s" % (old_name, instance.name), None)

  result = utils.RunCmd([inst_os.rename_script], env=rename_env,
                        cwd=inst_os.path, output=logfile, reset_env=True)

  if result.failed:
    logging.error("os create command '%s' returned error: %s output: %s",
                  result.cmd, result.fail_reason, result.output)
    lines = [utils.SafeEncode(val)
             for val in utils.TailFile(logfile, lines=20)]
    _Fail("OS rename script failed (%s), last lines in the"
          " log file:\n%s", result.fail_reason, "\n".join(lines), log=False)


def _GetBlockDevSymlinkPath(instance_name, idx, _dir=None):
  """Returns symlink path for block device.

  """
  if _dir is None:
    _dir = pathutils.DISK_LINKS_DIR

  return utils.PathJoin(_dir,
                        ("%s%s%s" %
                         (instance_name, constants.DISK_SEPARATOR, idx)))


def _SymlinkBlockDev(instance_name, device_path, idx):
  """Set up symlinks to a instance's block device.

  This is an auxiliary function run when an instance is start (on the primary
  node) or when an instance is migrated (on the target node).


  @param instance_name: the name of the target instance
  @param device_path: path of the physical block device, on the node
  @param idx: the disk index
  @return: absolute path to the disk's symlink

  """
  link_name = _GetBlockDevSymlinkPath(instance_name, idx)
  try:
    os.symlink(device_path, link_name)
  except OSError, err:
    if err.errno == errno.EEXIST:
      if (not os.path.islink(link_name) or
          os.readlink(link_name) != device_path):
        os.remove(link_name)
        os.symlink(device_path, link_name)
    else:
      raise

  return link_name


def _RemoveBlockDevLinks(instance_name, disks):
  """Remove the block device symlinks belonging to the given instance.

  """
  for idx, _ in enumerate(disks):
    link_name = _GetBlockDevSymlinkPath(instance_name, idx)
    if os.path.islink(link_name):
      try:
        os.remove(link_name)
      except OSError:
        logging.exception("Can't remove symlink '%s'", link_name)


def _CalculateDeviceURI(instance, disk, device):
  """Get the URI for the device.

  @type instance: L{objects.Instance}
  @param instance: the instance which disk belongs to
  @type disk: L{objects.Disk}
  @param disk: the target disk object
  @type device: L{bdev.BlockDev}
  @param device: the corresponding BlockDevice
  @rtype: string
  @return: the device uri if any else None

  """
  access_mode = disk.params.get(constants.LDP_ACCESS,
                                constants.DISK_KERNELSPACE)
  if access_mode == constants.DISK_USERSPACE:
    # This can raise errors.BlockDeviceError
    return device.GetUserspaceAccessUri(instance.hypervisor)
  else:
    return None


def _GatherAndLinkBlockDevs(instance):
  """Set up an instance's block device(s).

  This is run on the primary node at instance startup. The block
  devices must be already assembled.

  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should assemble
  @rtype: list
  @return: list of (disk_object, link_name, drive_uri)

  """
  block_devices = []
  for idx, disk in enumerate(instance.disks):
    device = _RecursiveFindBD(disk)
    if device is None:
      raise errors.BlockDeviceError("Block device '%s' is not set up." %
                                    str(disk))
    device.Open()
    try:
      link_name = _SymlinkBlockDev(instance.name, device.dev_path, idx)
    except OSError, e:
      raise errors.BlockDeviceError("Cannot create block device symlink: %s" %
                                    e.strerror)
    uri = _CalculateDeviceURI(instance, disk, device)

    block_devices.append((disk, link_name, uri))

  return block_devices


def StartInstance(instance, startup_paused, reason, store_reason=True):
  """Start an instance.

  @type instance: L{objects.Instance}
  @param instance: the instance object
  @type startup_paused: bool
  @param instance: pause instance at startup?
  @type reason: list of reasons
  @param reason: the reason trail for this startup
  @type store_reason: boolean
  @param store_reason: whether to store the shutdown reason trail on file
  @rtype: None

  """
  running_instances = GetInstanceListForHypervisor(instance.hypervisor,
                                                   instance.hvparams)

  if instance.name in running_instances:
    logging.info("Instance %s already running, not starting", instance.name)
    return

  try:
    block_devices = _GatherAndLinkBlockDevs(instance)
    hyper = hypervisor.GetHypervisor(instance.hypervisor)
    hyper.StartInstance(instance, block_devices, startup_paused)
    if store_reason:
      _StoreInstReasonTrail(instance.name, reason)
  except errors.BlockDeviceError, err:
    _Fail("Block device error: %s", err, exc=True)
  except errors.HypervisorError, err:
    _RemoveBlockDevLinks(instance.name, instance.disks)
    _Fail("Hypervisor error: %s", err, exc=True)


def InstanceShutdown(instance, timeout, reason, store_reason=True):
  """Shut an instance down.

  @note: this functions uses polling with a hardcoded timeout.

  @type instance: L{objects.Instance}
  @param instance: the instance object
  @type timeout: integer
  @param timeout: maximum timeout for soft shutdown
  @type reason: list of reasons
  @param reason: the reason trail for this shutdown
  @type store_reason: boolean
  @param store_reason: whether to store the shutdown reason trail on file
  @rtype: None

  """
  hv_name = instance.hypervisor
  hyper = hypervisor.GetHypervisor(hv_name)
  iname = instance.name

  if instance.name not in hyper.ListInstances(instance.hvparams):
    logging.info("Instance %s not running, doing nothing", iname)
    return

  class _TryShutdown:
    def __init__(self):
      self.tried_once = False

    def __call__(self):
      if iname not in hyper.ListInstances(instance.hvparams):
        return

      try:
        hyper.StopInstance(instance, retry=self.tried_once)
        if store_reason:
          _StoreInstReasonTrail(instance.name, reason)
      except errors.HypervisorError, err:
        if iname not in hyper.ListInstances(instance.hvparams):
          # if the instance is no longer existing, consider this a
          # success and go to cleanup
          return

        _Fail("Failed to stop instance %s: %s", iname, err)

      self.tried_once = True

      raise utils.RetryAgain()

  try:
    utils.Retry(_TryShutdown(), 5, timeout)
  except utils.RetryTimeout:
    # the shutdown did not succeed
    logging.error("Shutdown of '%s' unsuccessful, forcing", iname)

    try:
      hyper.StopInstance(instance, force=True)
    except errors.HypervisorError, err:
      if iname in hyper.ListInstances(instance.hvparams):
        # only raise an error if the instance still exists, otherwise
        # the error could simply be "instance ... unknown"!
        _Fail("Failed to force stop instance %s: %s", iname, err)

    time.sleep(1)

    if iname in hyper.ListInstances(instance.hvparams):
      _Fail("Could not shutdown instance %s even by destroy", iname)

  try:
    hyper.CleanupInstance(instance.name)
  except errors.HypervisorError, err:
    logging.warning("Failed to execute post-shutdown cleanup step: %s", err)

  _RemoveBlockDevLinks(iname, instance.disks)


def InstanceReboot(instance, reboot_type, shutdown_timeout, reason):
  """Reboot an instance.

  @type instance: L{objects.Instance}
  @param instance: the instance object to reboot
  @type reboot_type: str
  @param reboot_type: the type of reboot, one the following
    constants:
      - L{constants.INSTANCE_REBOOT_SOFT}: only reboot the
        instance OS, do not recreate the VM
      - L{constants.INSTANCE_REBOOT_HARD}: tear down and
        restart the VM (at the hypervisor level)
      - the other reboot type (L{constants.INSTANCE_REBOOT_FULL}) is
        not accepted here, since that mode is handled differently, in
        cmdlib, and translates into full stop and start of the
        instance (instead of a call_instance_reboot RPC)
  @type shutdown_timeout: integer
  @param shutdown_timeout: maximum timeout for soft shutdown
  @type reason: list of reasons
  @param reason: the reason trail for this reboot
  @rtype: None

  """
  running_instances = GetInstanceListForHypervisor(instance.hypervisor,
                                                   instance.hvparams)

  if instance.name not in running_instances:
    _Fail("Cannot reboot instance %s that is not running", instance.name)

  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  if reboot_type == constants.INSTANCE_REBOOT_SOFT:
    try:
      hyper.RebootInstance(instance)
    except errors.HypervisorError, err:
      _Fail("Failed to soft reboot instance %s: %s", instance.name, err)
  elif reboot_type == constants.INSTANCE_REBOOT_HARD:
    try:
      InstanceShutdown(instance, shutdown_timeout, reason, store_reason=False)
      result = StartInstance(instance, False, reason, store_reason=False)
      _StoreInstReasonTrail(instance.name, reason)
      return result
    except errors.HypervisorError, err:
      _Fail("Failed to hard reboot instance %s: %s", instance.name, err)
  else:
    _Fail("Invalid reboot_type received: %s", reboot_type)


def InstanceBalloonMemory(instance, memory):
  """Resize an instance's memory.

  @type instance: L{objects.Instance}
  @param instance: the instance object
  @type memory: int
  @param memory: new memory amount in MB
  @rtype: None

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  running = hyper.ListInstances(instance.hvparams)
  if instance.name not in running:
    logging.info("Instance %s is not running, cannot balloon", instance.name)
    return
  try:
    hyper.BalloonInstanceMemory(instance, memory)
  except errors.HypervisorError, err:
    _Fail("Failed to balloon instance memory: %s", err, exc=True)


def MigrationInfo(instance):
  """Gather information about an instance to be migrated.

  @type instance: L{objects.Instance}
  @param instance: the instance definition

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  try:
    info = hyper.MigrationInfo(instance)
  except errors.HypervisorError, err:
    _Fail("Failed to fetch migration information: %s", err, exc=True)
  return info


def AcceptInstance(instance, info, target):
  """Prepare the node to accept an instance.

  @type instance: L{objects.Instance}
  @param instance: the instance definition
  @type info: string/data (opaque)
  @param info: migration information, from the source node
  @type target: string
  @param target: target host (usually ip), on this node

  """
  # TODO: why is this required only for DTS_EXT_MIRROR?
  if instance.disk_template in constants.DTS_EXT_MIRROR:
    # Create the symlinks, as the disks are not active
    # in any way
    try:
      _GatherAndLinkBlockDevs(instance)
    except errors.BlockDeviceError, err:
      _Fail("Block device error: %s", err, exc=True)

  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  try:
    hyper.AcceptInstance(instance, info, target)
  except errors.HypervisorError, err:
    if instance.disk_template in constants.DTS_EXT_MIRROR:
      _RemoveBlockDevLinks(instance.name, instance.disks)
    _Fail("Failed to accept instance: %s", err, exc=True)


def FinalizeMigrationDst(instance, info, success):
  """Finalize any preparation to accept an instance.

  @type instance: L{objects.Instance}
  @param instance: the instance definition
  @type info: string/data (opaque)
  @param info: migration information, from the source node
  @type success: boolean
  @param success: whether the migration was a success or a failure

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  try:
    hyper.FinalizeMigrationDst(instance, info, success)
  except errors.HypervisorError, err:
    _Fail("Failed to finalize migration on the target node: %s", err, exc=True)


def MigrateInstance(cluster_name, instance, target, live):
  """Migrates an instance to another node.

  @type cluster_name: string
  @param cluster_name: name of the cluster
  @type instance: L{objects.Instance}
  @param instance: the instance definition
  @type target: string
  @param target: the target node name
  @type live: boolean
  @param live: whether the migration should be done live or not (the
      interpretation of this parameter is left to the hypervisor)
  @raise RPCFail: if migration fails for some reason

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)

  try:
    hyper.MigrateInstance(cluster_name, instance, target, live)
  except errors.HypervisorError, err:
    _Fail("Failed to migrate instance: %s", err, exc=True)


def FinalizeMigrationSource(instance, success, live):
  """Finalize the instance migration on the source node.

  @type instance: L{objects.Instance}
  @param instance: the instance definition of the migrated instance
  @type success: bool
  @param success: whether the migration succeeded or not
  @type live: bool
  @param live: whether the user requested a live migration or not
  @raise RPCFail: If the execution fails for some reason

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)

  try:
    hyper.FinalizeMigrationSource(instance, success, live)
  except Exception, err:  # pylint: disable=W0703
    _Fail("Failed to finalize the migration on the source node: %s", err,
          exc=True)


def GetMigrationStatus(instance):
  """Get the migration status

  @type instance: L{objects.Instance}
  @param instance: the instance that is being migrated
  @rtype: L{objects.MigrationStatus}
  @return: the status of the current migration (one of
           L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
           progress info that can be retrieved from the hypervisor
  @raise RPCFail: If the migration status cannot be retrieved

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  try:
    return hyper.GetMigrationStatus(instance)
  except Exception, err:  # pylint: disable=W0703
    _Fail("Failed to get migration status: %s", err, exc=True)


def HotplugDevice(instance, action, dev_type, device, extra, seq):
  """Hotplug a device

  Hotplug is currently supported only for KVM Hypervisor.
  @type instance: L{objects.Instance}
  @param instance: the instance to which we hotplug a device
  @type action: string
  @param action: the hotplug action to perform
  @type dev_type: string
  @param dev_type: the device type to hotplug
  @type device: either L{objects.NIC} or L{objects.Disk}
  @param device: the device object to hotplug
  @type extra: string
  @param extra: extra info used by hotplug code (e.g. disk link)
  @type seq: int
  @param seq: the index of the device from master perspective
  @raise RPCFail: in case instance does not have KVM hypervisor

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  try:
    hyper.VerifyHotplugSupport(instance, action, dev_type)
  except errors.HotplugError, err:
    _Fail("Hotplug is not supported: %s", err)

  if action == constants.HOTPLUG_ACTION_ADD:
    fn = hyper.HotAddDevice
  elif action == constants.HOTPLUG_ACTION_REMOVE:
    fn = hyper.HotDelDevice
  elif action == constants.HOTPLUG_ACTION_MODIFY:
    fn = hyper.HotModDevice
  else:
    assert action in constants.HOTPLUG_ALL_ACTIONS

  return fn(instance, dev_type, device, extra, seq)


def HotplugSupported(instance):
  """Checks if hotplug is generally supported.

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  try:
    hyper.HotplugSupported(instance)
  except errors.HotplugError, err:
    _Fail("Hotplug is not supported: %s", err)


def BlockdevCreate(disk, size, owner, on_primary, info, excl_stor):
  """Creates a block device for an instance.

  @type disk: L{objects.Disk}
  @param disk: the object describing the disk we should create
  @type size: int
  @param size: the size of the physical underlying device, in MiB
  @type owner: str
  @param owner: the name of the instance for which disk is created,
      used for device cache data
  @type on_primary: boolean
  @param on_primary:  indicates if it is the primary node or not
  @type info: string
  @param info: string that will be sent to the physical device
      creation, used for example to set (LVM) tags on LVs
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active

  @return: the new unique_id of the device (this can sometime be
      computed only after creation), or None. On secondary nodes,
      it's not required to return anything.

  """
  # TODO: remove the obsolete "size" argument
  # pylint: disable=W0613
  clist = []
  if disk.children:
    for child in disk.children:
      try:
        crdev = _RecursiveAssembleBD(child, owner, on_primary)
      except errors.BlockDeviceError, err:
        _Fail("Can't assemble device %s: %s", child, err)
      if on_primary or disk.AssembleOnSecondary():
        # we need the children open in case the device itself has to
        # be assembled
        try:
          # pylint: disable=E1103
          crdev.Open()
        except errors.BlockDeviceError, err:
          _Fail("Can't make child '%s' read-write: %s", child, err)
      clist.append(crdev)

  try:
    device = bdev.Create(disk, clist, excl_stor)
  except errors.BlockDeviceError, err:
    _Fail("Can't create block device: %s", err)

  if on_primary or disk.AssembleOnSecondary():
    try:
      device.Assemble()
    except errors.BlockDeviceError, err:
      _Fail("Can't assemble device after creation, unusual event: %s", err)
    if on_primary or disk.OpenOnSecondary():
      try:
        device.Open(force=True)
      except errors.BlockDeviceError, err:
        _Fail("Can't make device r/w after creation, unusual event: %s", err)
    DevCacheManager.UpdateCache(device.dev_path, owner,
                                on_primary, disk.iv_name)

  device.SetInfo(info)

  return device.unique_id


def _WipeDevice(path, offset, size):
  """This function actually wipes the device.

  @param path: The path to the device to wipe
  @param offset: The offset in MiB in the file
  @param size: The size in MiB to write

  """
  # Internal sizes are always in Mebibytes; if the following "dd" command
  # should use a different block size the offset and size given to this
  # function must be adjusted accordingly before being passed to "dd".
  block_size = 1024 * 1024

  cmd = [constants.DD_CMD, "if=/dev/zero", "seek=%d" % offset,
         "bs=%s" % block_size, "oflag=direct", "of=%s" % path,
         "count=%d" % size]
  result = utils.RunCmd(cmd)

  if result.failed:
    _Fail("Wipe command '%s' exited with error: %s; output: %s", result.cmd,
          result.fail_reason, result.output)


def BlockdevWipe(disk, offset, size):
  """Wipes a block device.

  @type disk: L{objects.Disk}
  @param disk: the disk object we want to wipe
  @type offset: int
  @param offset: The offset in MiB in the file
  @type size: int
  @param size: The size in MiB to write

  """
  try:
    rdev = _RecursiveFindBD(disk)
  except errors.BlockDeviceError:
    rdev = None

  if not rdev:
    _Fail("Cannot execute wipe for device %s: device not found", disk.iv_name)

  # Do cross verify some of the parameters
  if offset < 0:
    _Fail("Negative offset")
  if size < 0:
    _Fail("Negative size")
  if offset > rdev.size:
    _Fail("Offset is bigger than device size")
  if (offset + size) > rdev.size:
    _Fail("The provided offset and size to wipe is bigger than device size")

  _WipeDevice(rdev.dev_path, offset, size)


def BlockdevPauseResumeSync(disks, pause):
  """Pause or resume the sync of the block device.

  @type disks: list of L{objects.Disk}
  @param disks: the disks object we want to pause/resume
  @type pause: bool
  @param pause: Wheater to pause or resume

  """
  success = []
  for disk in disks:
    try:
      rdev = _RecursiveFindBD(disk)
    except errors.BlockDeviceError:
      rdev = None

    if not rdev:
      success.append((False, ("Cannot change sync for device %s:"
                              " device not found" % disk.iv_name)))
      continue

    result = rdev.PauseResumeSync(pause)

    if result:
      success.append((result, None))
    else:
      if pause:
        msg = "Pause"
      else:
        msg = "Resume"
      success.append((result, "%s for device %s failed" % (msg, disk.iv_name)))

  return success


def BlockdevRemove(disk):
  """Remove a block device.

  @note: This is intended to be called recursively.

  @type disk: L{objects.Disk}
  @param disk: the disk object we should remove
  @rtype: boolean
  @return: the success of the operation

  """
  msgs = []
  try:
    rdev = _RecursiveFindBD(disk)
  except errors.BlockDeviceError, err:
    # probably can't attach
    logging.info("Can't attach to device %s in remove", disk)
    rdev = None
  if rdev is not None:
    r_path = rdev.dev_path

    def _TryRemove():
      try:
        rdev.Remove()
        return []
      except errors.BlockDeviceError, err:
        return [str(err)]

    msgs.extend(utils.SimpleRetry([], _TryRemove,
                                  constants.DISK_REMOVE_RETRY_INTERVAL,
                                  constants.DISK_REMOVE_RETRY_TIMEOUT))

    if not msgs:
      DevCacheManager.RemoveCache(r_path)

  if disk.children:
    for child in disk.children:
      try:
        BlockdevRemove(child)
      except RPCFail, err:
        msgs.append(str(err))

  if msgs:
    _Fail("; ".join(msgs))


def _RecursiveAssembleBD(disk, owner, as_primary):
  """Activate a block device for an instance.

  This is run on the primary and secondary nodes for an instance.

  @note: this function is called recursively.

  @type disk: L{objects.Disk}
  @param disk: the disk we try to assemble
  @type owner: str
  @param owner: the name of the instance which owns the disk
  @type as_primary: boolean
  @param as_primary: if we should make the block device
      read/write

  @return: the assembled device or None (in case no device
      was assembled)
  @raise errors.BlockDeviceError: in case there is an error
      during the activation of the children or the device
      itself

  """
  children = []
  if disk.children:
    mcn = disk.ChildrenNeeded()
    if mcn == -1:
      mcn = 0 # max number of Nones allowed
    else:
      mcn = len(disk.children) - mcn # max number of Nones
    for chld_disk in disk.children:
      try:
        cdev = _RecursiveAssembleBD(chld_disk, owner, as_primary)
      except errors.BlockDeviceError, err:
        if children.count(None) >= mcn:
          raise
        cdev = None
        logging.error("Error in child activation (but continuing): %s",
                      str(err))
      children.append(cdev)

  if as_primary or disk.AssembleOnSecondary():
    r_dev = bdev.Assemble(disk, children)
    result = r_dev
    if as_primary or disk.OpenOnSecondary():
      r_dev.Open()
    DevCacheManager.UpdateCache(r_dev.dev_path, owner,
                                as_primary, disk.iv_name)

  else:
    result = True
  return result


def BlockdevAssemble(disk, owner, as_primary, idx):
  """Activate a block device for an instance.

  This is a wrapper over _RecursiveAssembleBD.

  @rtype: str or boolean
  @return: a tuple with the C{/dev/...} path and the created symlink
      for primary nodes, and (C{True}, C{True}) for secondary nodes

  """
  try:
    result = _RecursiveAssembleBD(disk, owner, as_primary)
    if isinstance(result, BlockDev):
      # pylint: disable=E1103
      dev_path = result.dev_path
      link_name = None
      if as_primary:
        link_name = _SymlinkBlockDev(owner, dev_path, idx)
    elif result:
      return result, result
    else:
      _Fail("Unexpected result from _RecursiveAssembleBD")
  except errors.BlockDeviceError, err:
    _Fail("Error while assembling disk: %s", err, exc=True)
  except OSError, err:
    _Fail("Error while symlinking disk: %s", err, exc=True)

  return dev_path, link_name


def BlockdevShutdown(disk):
  """Shut down a block device.

  First, if the device is assembled (Attach() is successful), then
  the device is shutdown. Then the children of the device are
  shutdown.

  This function is called recursively. Note that we don't cache the
  children or such, as oppossed to assemble, shutdown of different
  devices doesn't require that the upper device was active.

  @type disk: L{objects.Disk}
  @param disk: the description of the disk we should
      shutdown
  @rtype: None

  """
  msgs = []
  r_dev = _RecursiveFindBD(disk)
  if r_dev is not None:
    r_path = r_dev.dev_path
    try:
      r_dev.Shutdown()
      DevCacheManager.RemoveCache(r_path)
    except errors.BlockDeviceError, err:
      msgs.append(str(err))

  if disk.children:
    for child in disk.children:
      try:
        BlockdevShutdown(child)
      except RPCFail, err:
        msgs.append(str(err))

  if msgs:
    _Fail("; ".join(msgs))


def BlockdevAddchildren(parent_cdev, new_cdevs):
  """Extend a mirrored block device.

  @type parent_cdev: L{objects.Disk}
  @param parent_cdev: the disk to which we should add children
  @type new_cdevs: list of L{objects.Disk}
  @param new_cdevs: the list of children which we should add
  @rtype: None

  """
  parent_bdev = _RecursiveFindBD(parent_cdev)
  if parent_bdev is None:
    _Fail("Can't find parent device '%s' in add children", parent_cdev)
  new_bdevs = [_RecursiveFindBD(disk) for disk in new_cdevs]
  if new_bdevs.count(None) > 0:
    _Fail("Can't find new device(s) to add: %s:%s", new_bdevs, new_cdevs)
  parent_bdev.AddChildren(new_bdevs)


def BlockdevRemovechildren(parent_cdev, new_cdevs):
  """Shrink a mirrored block device.

  @type parent_cdev: L{objects.Disk}
  @param parent_cdev: the disk from which we should remove children
  @type new_cdevs: list of L{objects.Disk}
  @param new_cdevs: the list of children which we should remove
  @rtype: None

  """
  parent_bdev = _RecursiveFindBD(parent_cdev)
  if parent_bdev is None:
    _Fail("Can't find parent device '%s' in remove children", parent_cdev)
  devs = []
  for disk in new_cdevs:
    rpath = disk.StaticDevPath()
    if rpath is None:
      bd = _RecursiveFindBD(disk)
      if bd is None:
        _Fail("Can't find device %s while removing children", disk)
      else:
        devs.append(bd.dev_path)
    else:
      if not utils.IsNormAbsPath(rpath):
        _Fail("Strange path returned from StaticDevPath: '%s'", rpath)
      devs.append(rpath)
  parent_bdev.RemoveChildren(devs)


def BlockdevGetmirrorstatus(disks):
  """Get the mirroring status of a list of devices.

  @type disks: list of L{objects.Disk}
  @param disks: the list of disks which we should query
  @rtype: disk
  @return: List of L{objects.BlockDevStatus}, one for each disk
  @raise errors.BlockDeviceError: if any of the disks cannot be
      found

  """
  stats = []
  for dsk in disks:
    rbd = _RecursiveFindBD(dsk)
    if rbd is None:
      _Fail("Can't find device %s", dsk)

    stats.append(rbd.CombinedSyncStatus())

  return stats


def BlockdevGetmirrorstatusMulti(disks):
  """Get the mirroring status of a list of devices.

  @type disks: list of L{objects.Disk}
  @param disks: the list of disks which we should query
  @rtype: disk
  @return: List of tuples, (bool, status), one for each disk; bool denotes
    success/failure, status is L{objects.BlockDevStatus} on success, string
    otherwise

  """
  result = []
  for disk in disks:
    try:
      rbd = _RecursiveFindBD(disk)
      if rbd is None:
        result.append((False, "Can't find device %s" % disk))
        continue

      status = rbd.CombinedSyncStatus()
    except errors.BlockDeviceError, err:
      logging.exception("Error while getting disk status")
      result.append((False, str(err)))
    else:
      result.append((True, status))

  assert len(disks) == len(result)

  return result


def _RecursiveFindBD(disk):
  """Check if a device is activated.

  If so, return information about the real device.

  @type disk: L{objects.Disk}
  @param disk: the disk object we need to find

  @return: None if the device can't be found,
      otherwise the device instance

  """
  children = []
  if disk.children:
    for chdisk in disk.children:
      children.append(_RecursiveFindBD(chdisk))

  return bdev.FindDevice(disk, children)


def _OpenRealBD(disk):
  """Opens the underlying block device of a disk.

  @type disk: L{objects.Disk}
  @param disk: the disk object we want to open

  """
  real_disk = _RecursiveFindBD(disk)
  if real_disk is None:
    _Fail("Block device '%s' is not set up", disk)

  real_disk.Open()

  return real_disk


def BlockdevFind(disk):
  """Check if a device is activated.

  If it is, return information about the real device.

  @type disk: L{objects.Disk}
  @param disk: the disk to find
  @rtype: None or objects.BlockDevStatus
  @return: None if the disk cannot be found, otherwise a the current
           information

  """
  try:
    rbd = _RecursiveFindBD(disk)
  except errors.BlockDeviceError, err:
    _Fail("Failed to find device: %s", err, exc=True)

  if rbd is None:
    return None

  return rbd.GetSyncStatus()


def BlockdevGetdimensions(disks):
  """Computes the size of the given disks.

  If a disk is not found, returns None instead.

  @type disks: list of L{objects.Disk}
  @param disks: the list of disk to compute the size for
  @rtype: list
  @return: list with elements None if the disk cannot be found,
      otherwise the pair (size, spindles), where spindles is None if the
      device doesn't support that

  """
  result = []
  for cf in disks:
    try:
      rbd = _RecursiveFindBD(cf)
    except errors.BlockDeviceError:
      result.append(None)
      continue
    if rbd is None:
      result.append(None)
    else:
      result.append(rbd.GetActualDimensions())
  return result


def UploadFile(file_name, data, mode, uid, gid, atime, mtime):
  """Write a file to the filesystem.

  This allows the master to overwrite(!) a file. It will only perform
  the operation if the file belongs to a list of configuration files.

  @type file_name: str
  @param file_name: the target file name
  @type data: str
  @param data: the new contents of the file
  @type mode: int
  @param mode: the mode to give the file (can be None)
  @type uid: string
  @param uid: the owner of the file
  @type gid: string
  @param gid: the group of the file
  @type atime: float
  @param atime: the atime to set on the file (can be None)
  @type mtime: float
  @param mtime: the mtime to set on the file (can be None)
  @rtype: None

  """
  file_name = vcluster.LocalizeVirtualPath(file_name)

  if not os.path.isabs(file_name):
    _Fail("Filename passed to UploadFile is not absolute: '%s'", file_name)

  if file_name not in _ALLOWED_UPLOAD_FILES:
    _Fail("Filename passed to UploadFile not in allowed upload targets: '%s'",
          file_name)

  raw_data = _Decompress(data)

  if not (isinstance(uid, basestring) and isinstance(gid, basestring)):
    _Fail("Invalid username/groupname type")

  getents = runtime.GetEnts()
  uid = getents.LookupUser(uid)
  gid = getents.LookupGroup(gid)

  utils.SafeWriteFile(file_name, None,
                      data=raw_data, mode=mode, uid=uid, gid=gid,
                      atime=atime, mtime=mtime)


def RunOob(oob_program, command, node, timeout):
  """Executes oob_program with given command on given node.

  @param oob_program: The path to the executable oob_program
  @param command: The command to invoke on oob_program
  @param node: The node given as an argument to the program
  @param timeout: Timeout after which we kill the oob program

  @return: stdout
  @raise RPCFail: If execution fails for some reason

  """
  result = utils.RunCmd([oob_program, command, node], timeout=timeout)

  if result.failed:
    _Fail("'%s' failed with reason '%s'; output: %s", result.cmd,
          result.fail_reason, result.output)

  return result.stdout


def _OSOndiskAPIVersion(os_dir):
  """Compute and return the API version of a given OS.

  This function will try to read the API version of the OS residing in
  the 'os_dir' directory.

  @type os_dir: str
  @param os_dir: the directory in which we should look for the OS
  @rtype: tuple
  @return: tuple (status, data) with status denoting the validity and
      data holding either the vaid versions or an error message

  """
  api_file = utils.PathJoin(os_dir, constants.OS_API_FILE)

  try:
    st = os.stat(api_file)
  except EnvironmentError, err:
    return False, ("Required file '%s' not found under path %s: %s" %
                   (constants.OS_API_FILE, os_dir, utils.ErrnoOrStr(err)))

  if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
    return False, ("File '%s' in %s is not a regular file" %
                   (constants.OS_API_FILE, os_dir))

  try:
    api_versions = utils.ReadFile(api_file).splitlines()
  except EnvironmentError, err:
    return False, ("Error while reading the API version file at %s: %s" %
                   (api_file, utils.ErrnoOrStr(err)))

  try:
    api_versions = [int(version.strip()) for version in api_versions]
  except (TypeError, ValueError), err:
    return False, ("API version(s) can't be converted to integer: %s" %
                   str(err))

  return True, api_versions


def DiagnoseOS(top_dirs=None):
  """Compute the validity for all OSes.

  @type top_dirs: list
  @param top_dirs: the list of directories in which to
      search (if not given defaults to
      L{pathutils.OS_SEARCH_PATH})
  @rtype: list of L{objects.OS}
  @return: a list of tuples (name, path, status, diagnose, variants,
      parameters, api_version) for all (potential) OSes under all
      search paths, where:
          - name is the (potential) OS name
          - path is the full path to the OS
          - status True/False is the validity of the OS
          - diagnose is the error message for an invalid OS, otherwise empty
          - variants is a list of supported OS variants, if any
          - parameters is a list of (name, help) parameters, if any
          - api_version is a list of support OS API versions

  """
  if top_dirs is None:
    top_dirs = pathutils.OS_SEARCH_PATH

  result = []
  for dir_name in top_dirs:
    if os.path.isdir(dir_name):
      try:
        f_names = utils.ListVisibleFiles(dir_name)
      except EnvironmentError, err:
        logging.exception("Can't list the OS directory %s: %s", dir_name, err)
        break
      for name in f_names:
        os_path = utils.PathJoin(dir_name, name)
        status, os_inst = _TryOSFromDisk(name, base_dir=dir_name)
        if status:
          diagnose = ""
          variants = os_inst.supported_variants
          parameters = os_inst.supported_parameters
          api_versions = os_inst.api_versions
        else:
          diagnose = os_inst
          variants = parameters = api_versions = []
        result.append((name, os_path, status, diagnose, variants,
                       parameters, api_versions))

  return result


def _TryOSFromDisk(name, base_dir=None):
  """Create an OS instance from disk.

  This function will return an OS instance if the given name is a
  valid OS name.

  @type base_dir: string
  @keyword base_dir: Base directory containing OS installations.
                     Defaults to a search in all the OS_SEARCH_PATH dirs.
  @rtype: tuple
  @return: success and either the OS instance if we find a valid one,
      or error message

  """
  if base_dir is None:
    os_dir = utils.FindFile(name, pathutils.OS_SEARCH_PATH, os.path.isdir)
  else:
    os_dir = utils.FindFile(name, [base_dir], os.path.isdir)

  if os_dir is None:
    return False, "Directory for OS %s not found in search path" % name

  status, api_versions = _OSOndiskAPIVersion(os_dir)
  if not status:
    # push the error up
    return status, api_versions

  if not constants.OS_API_VERSIONS.intersection(api_versions):
    return False, ("API version mismatch for path '%s': found %s, want %s." %
                   (os_dir, api_versions, constants.OS_API_VERSIONS))

  # OS Files dictionary, we will populate it with the absolute path
  # names; if the value is True, then it is a required file, otherwise
  # an optional one
  os_files = dict.fromkeys(constants.OS_SCRIPTS, True)

  if max(api_versions) >= constants.OS_API_V15:
    os_files[constants.OS_VARIANTS_FILE] = False

  if max(api_versions) >= constants.OS_API_V20:
    os_files[constants.OS_PARAMETERS_FILE] = True
  else:
    del os_files[constants.OS_SCRIPT_VERIFY]

  for (filename, required) in os_files.items():
    os_files[filename] = utils.PathJoin(os_dir, filename)

    try:
      st = os.stat(os_files[filename])
    except EnvironmentError, err:
      if err.errno == errno.ENOENT and not required:
        del os_files[filename]
        continue
      return False, ("File '%s' under path '%s' is missing (%s)" %
                     (filename, os_dir, utils.ErrnoOrStr(err)))

    if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
      return False, ("File '%s' under path '%s' is not a regular file" %
                     (filename, os_dir))

    if filename in constants.OS_SCRIPTS:
      if stat.S_IMODE(st.st_mode) & stat.S_IXUSR != stat.S_IXUSR:
        return False, ("File '%s' under path '%s' is not executable" %
                       (filename, os_dir))

  variants = []
  if constants.OS_VARIANTS_FILE in os_files:
    variants_file = os_files[constants.OS_VARIANTS_FILE]
    try:
      variants = \
        utils.FilterEmptyLinesAndComments(utils.ReadFile(variants_file))
    except EnvironmentError, err:
      # we accept missing files, but not other errors
      if err.errno != errno.ENOENT:
        return False, ("Error while reading the OS variants file at %s: %s" %
                       (variants_file, utils.ErrnoOrStr(err)))

  parameters = []
  if constants.OS_PARAMETERS_FILE in os_files:
    parameters_file = os_files[constants.OS_PARAMETERS_FILE]
    try:
      parameters = utils.ReadFile(parameters_file).splitlines()
    except EnvironmentError, err:
      return False, ("Error while reading the OS parameters file at %s: %s" %
                     (parameters_file, utils.ErrnoOrStr(err)))
    parameters = [v.split(None, 1) for v in parameters]

  os_obj = objects.OS(name=name, path=os_dir,
                      create_script=os_files[constants.OS_SCRIPT_CREATE],
                      export_script=os_files[constants.OS_SCRIPT_EXPORT],
                      import_script=os_files[constants.OS_SCRIPT_IMPORT],
                      rename_script=os_files[constants.OS_SCRIPT_RENAME],
                      verify_script=os_files.get(constants.OS_SCRIPT_VERIFY,
                                                 None),
                      supported_variants=variants,
                      supported_parameters=parameters,
                      api_versions=api_versions)
  return True, os_obj


def OSFromDisk(name, base_dir=None):
  """Create an OS instance from disk.

  This function will return an OS instance if the given name is a
  valid OS name. Otherwise, it will raise an appropriate
  L{RPCFail} exception, detailing why this is not a valid OS.

  This is just a wrapper over L{_TryOSFromDisk}, which doesn't raise
  an exception but returns true/false status data.

  @type base_dir: string
  @keyword base_dir: Base directory containing OS installations.
                     Defaults to a search in all the OS_SEARCH_PATH dirs.
  @rtype: L{objects.OS}
  @return: the OS instance if we find a valid one
  @raise RPCFail: if we don't find a valid OS

  """
  name_only = objects.OS.GetName(name)
  status, payload = _TryOSFromDisk(name_only, base_dir)

  if not status:
    _Fail(payload)

  return payload


def OSCoreEnv(os_name, inst_os, os_params, debug=0):
  """Calculate the basic environment for an os script.

  @type os_name: str
  @param os_name: full operating system name (including variant)
  @type inst_os: L{objects.OS}
  @param inst_os: operating system for which the environment is being built
  @type os_params: dict
  @param os_params: the OS parameters
  @type debug: integer
  @param debug: debug level (0 or 1, for OS Api 10)
  @rtype: dict
  @return: dict of environment variables
  @raise errors.BlockDeviceError: if the block device
      cannot be found

  """
  result = {}
  api_version = \
    max(constants.OS_API_VERSIONS.intersection(inst_os.api_versions))
  result["OS_API_VERSION"] = "%d" % api_version
  result["OS_NAME"] = inst_os.name
  result["DEBUG_LEVEL"] = "%d" % debug

  # OS variants
  if api_version >= constants.OS_API_V15 and inst_os.supported_variants:
    variant = objects.OS.GetVariant(os_name)
    if not variant:
      variant = inst_os.supported_variants[0]
  else:
    variant = ""
  result["OS_VARIANT"] = variant

  # OS params
  for pname, pvalue in os_params.items():
    result["OSP_%s" % pname.upper()] = pvalue

  # Set a default path otherwise programs called by OS scripts (or
  # even hooks called from OS scripts) might break, and we don't want
  # to have each script require setting a PATH variable
  result["PATH"] = constants.HOOKS_PATH

  return result


def OSEnvironment(instance, inst_os, debug=0):
  """Calculate the environment for an os script.

  @type instance: L{objects.Instance}
  @param instance: target instance for the os script run
  @type inst_os: L{objects.OS}
  @param inst_os: operating system for which the environment is being built
  @type debug: integer
  @param debug: debug level (0 or 1, for OS Api 10)
  @rtype: dict
  @return: dict of environment variables
  @raise errors.BlockDeviceError: if the block device
      cannot be found

  """
  result = OSCoreEnv(instance.os, inst_os, instance.osparams, debug=debug)

  for attr in ["name", "os", "uuid", "ctime", "mtime", "primary_node"]:
    result["INSTANCE_%s" % attr.upper()] = str(getattr(instance, attr))

  result["HYPERVISOR"] = instance.hypervisor
  result["DISK_COUNT"] = "%d" % len(instance.disks)
  result["NIC_COUNT"] = "%d" % len(instance.nics)
  result["INSTANCE_SECONDARY_NODES"] = \
      ("%s" % " ".join(instance.secondary_nodes))

  # Disks
  for idx, disk in enumerate(instance.disks):
    real_disk = _OpenRealBD(disk)
    result["DISK_%d_PATH" % idx] = real_disk.dev_path
    result["DISK_%d_ACCESS" % idx] = disk.mode
    result["DISK_%d_UUID" % idx] = disk.uuid
    if disk.name:
      result["DISK_%d_NAME" % idx] = disk.name
    if constants.HV_DISK_TYPE in instance.hvparams:
      result["DISK_%d_FRONTEND_TYPE" % idx] = \
        instance.hvparams[constants.HV_DISK_TYPE]
    if disk.dev_type in constants.DTS_BLOCK:
      result["DISK_%d_BACKEND_TYPE" % idx] = "block"
    elif disk.dev_type in constants.DTS_FILEBASED:
      result["DISK_%d_BACKEND_TYPE" % idx] = \
        "file:%s" % disk.logical_id[0]

  # NICs
  for idx, nic in enumerate(instance.nics):
    result["NIC_%d_MAC" % idx] = nic.mac
    result["NIC_%d_UUID" % idx] = nic.uuid
    if nic.name:
      result["NIC_%d_NAME" % idx] = nic.name
    if nic.ip:
      result["NIC_%d_IP" % idx] = nic.ip
    result["NIC_%d_MODE" % idx] = nic.nicparams[constants.NIC_MODE]
    if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
      result["NIC_%d_BRIDGE" % idx] = nic.nicparams[constants.NIC_LINK]
    if nic.nicparams[constants.NIC_LINK]:
      result["NIC_%d_LINK" % idx] = nic.nicparams[constants.NIC_LINK]
    if nic.netinfo:
      nobj = objects.Network.FromDict(nic.netinfo)
      result.update(nobj.HooksDict("NIC_%d_" % idx))
    if constants.HV_NIC_TYPE in instance.hvparams:
      result["NIC_%d_FRONTEND_TYPE" % idx] = \
        instance.hvparams[constants.HV_NIC_TYPE]

  # HV/BE params
  for source, kind in [(instance.beparams, "BE"), (instance.hvparams, "HV")]:
    for key, value in source.items():
      result["INSTANCE_%s_%s" % (kind, key)] = str(value)

  return result


def DiagnoseExtStorage(top_dirs=None):
  """Compute the validity for all ExtStorage Providers.

  @type top_dirs: list
  @param top_dirs: the list of directories in which to
      search (if not given defaults to
      L{pathutils.ES_SEARCH_PATH})
  @rtype: list of L{objects.ExtStorage}
  @return: a list of tuples (name, path, status, diagnose, parameters)
      for all (potential) ExtStorage Providers under all
      search paths, where:
          - name is the (potential) ExtStorage Provider
          - path is the full path to the ExtStorage Provider
          - status True/False is the validity of the ExtStorage Provider
          - diagnose is the error message for an invalid ExtStorage Provider,
            otherwise empty
          - parameters is a list of (name, help) parameters, if any

  """
  if top_dirs is None:
    top_dirs = pathutils.ES_SEARCH_PATH

  result = []
  for dir_name in top_dirs:
    if os.path.isdir(dir_name):
      try:
        f_names = utils.ListVisibleFiles(dir_name)
      except EnvironmentError, err:
        logging.exception("Can't list the ExtStorage directory %s: %s",
                          dir_name, err)
        break
      for name in f_names:
        es_path = utils.PathJoin(dir_name, name)
        status, es_inst = bdev.ExtStorageFromDisk(name, base_dir=dir_name)
        if status:
          diagnose = ""
          parameters = es_inst.supported_parameters
        else:
          diagnose = es_inst
          parameters = []
        result.append((name, es_path, status, diagnose, parameters))

  return result


def BlockdevGrow(disk, amount, dryrun, backingstore, excl_stor):
  """Grow a stack of block devices.

  This function is called recursively, with the childrens being the
  first ones to resize.

  @type disk: L{objects.Disk}
  @param disk: the disk to be grown
  @type amount: integer
  @param amount: the amount (in mebibytes) to grow with
  @type dryrun: boolean
  @param dryrun: whether to execute the operation in simulation mode
      only, without actually increasing the size
  @param backingstore: whether to execute the operation on backing storage
      only, or on "logical" storage only; e.g. DRBD is logical storage,
      whereas LVM, file, RBD are backing storage
  @rtype: (status, result)
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active
  @return: a tuple with the status of the operation (True/False), and
      the errors message if status is False

  """
  r_dev = _RecursiveFindBD(disk)
  if r_dev is None:
    _Fail("Cannot find block device %s", disk)

  try:
    r_dev.Grow(amount, dryrun, backingstore, excl_stor)
  except errors.BlockDeviceError, err:
    _Fail("Failed to grow block device: %s", err, exc=True)


def BlockdevSnapshot(disk):
  """Create a snapshot copy of a block device.

  This function is called recursively, and the snapshot is actually created
  just for the leaf lvm backend device.

  @type disk: L{objects.Disk}
  @param disk: the disk to be snapshotted
  @rtype: string
  @return: snapshot disk ID as (vg, lv)

  """
  if disk.dev_type == constants.DT_DRBD8:
    if not disk.children:
      _Fail("DRBD device '%s' without backing storage cannot be snapshotted",
            disk.unique_id)
    return BlockdevSnapshot(disk.children[0])
  elif disk.dev_type == constants.DT_PLAIN:
    r_dev = _RecursiveFindBD(disk)
    if r_dev is not None:
      # FIXME: choose a saner value for the snapshot size
      # let's stay on the safe side and ask for the full size, for now
      return r_dev.Snapshot(disk.size)
    else:
      _Fail("Cannot find block device %s", disk)
  else:
    _Fail("Cannot snapshot non-lvm block device '%s' of type '%s'",
          disk.unique_id, disk.dev_type)


def BlockdevSetInfo(disk, info):
  """Sets 'metadata' information on block devices.

  This function sets 'info' metadata on block devices. Initial
  information is set at device creation; this function should be used
  for example after renames.

  @type disk: L{objects.Disk}
  @param disk: the disk to be grown
  @type info: string
  @param info: new 'info' metadata
  @rtype: (status, result)
  @return: a tuple with the status of the operation (True/False), and
      the errors message if status is False

  """
  r_dev = _RecursiveFindBD(disk)
  if r_dev is None:
    _Fail("Cannot find block device %s", disk)

  try:
    r_dev.SetInfo(info)
  except errors.BlockDeviceError, err:
    _Fail("Failed to set information on block device: %s", err, exc=True)


def FinalizeExport(instance, snap_disks):
  """Write out the export configuration information.

  @type instance: L{objects.Instance}
  @param instance: the instance which we export, used for
      saving configuration
  @type snap_disks: list of L{objects.Disk}
  @param snap_disks: list of snapshot block devices, which
      will be used to get the actual name of the dump file

  @rtype: None

  """
  destdir = utils.PathJoin(pathutils.EXPORT_DIR, instance.name + ".new")
  finaldestdir = utils.PathJoin(pathutils.EXPORT_DIR, instance.name)

  config = objects.SerializableConfigParser()

  config.add_section(constants.INISECT_EXP)
  config.set(constants.INISECT_EXP, "version", "0")
  config.set(constants.INISECT_EXP, "timestamp", "%d" % int(time.time()))
  config.set(constants.INISECT_EXP, "source", instance.primary_node)
  config.set(constants.INISECT_EXP, "os", instance.os)
  config.set(constants.INISECT_EXP, "compression", "none")

  config.add_section(constants.INISECT_INS)
  config.set(constants.INISECT_INS, "name", instance.name)
  config.set(constants.INISECT_INS, "maxmem", "%d" %
             instance.beparams[constants.BE_MAXMEM])
  config.set(constants.INISECT_INS, "minmem", "%d" %
             instance.beparams[constants.BE_MINMEM])
  # "memory" is deprecated, but useful for exporting to old ganeti versions
  config.set(constants.INISECT_INS, "memory", "%d" %
             instance.beparams[constants.BE_MAXMEM])
  config.set(constants.INISECT_INS, "vcpus", "%d" %
             instance.beparams[constants.BE_VCPUS])
  config.set(constants.INISECT_INS, "disk_template", instance.disk_template)
  config.set(constants.INISECT_INS, "hypervisor", instance.hypervisor)
  config.set(constants.INISECT_INS, "tags", " ".join(instance.GetTags()))

  nic_total = 0
  for nic_count, nic in enumerate(instance.nics):
    nic_total += 1
    config.set(constants.INISECT_INS, "nic%d_mac" %
               nic_count, "%s" % nic.mac)
    config.set(constants.INISECT_INS, "nic%d_ip" % nic_count, "%s" % nic.ip)
    config.set(constants.INISECT_INS, "nic%d_network" % nic_count,
               "%s" % nic.network)
    for param in constants.NICS_PARAMETER_TYPES:
      config.set(constants.INISECT_INS, "nic%d_%s" % (nic_count, param),
                 "%s" % nic.nicparams.get(param, None))
  # TODO: redundant: on load can read nics until it doesn't exist
  config.set(constants.INISECT_INS, "nic_count", "%d" % nic_total)

  disk_total = 0
  for disk_count, disk in enumerate(snap_disks):
    if disk:
      disk_total += 1
      config.set(constants.INISECT_INS, "disk%d_ivname" % disk_count,
                 ("%s" % disk.iv_name))
      config.set(constants.INISECT_INS, "disk%d_dump" % disk_count,
                 ("%s" % disk.logical_id[1]))
      config.set(constants.INISECT_INS, "disk%d_size" % disk_count,
                 ("%d" % disk.size))

  config.set(constants.INISECT_INS, "disk_count", "%d" % disk_total)

  # New-style hypervisor/backend parameters

  config.add_section(constants.INISECT_HYP)
  for name, value in instance.hvparams.items():
    if name not in constants.HVC_GLOBALS:
      config.set(constants.INISECT_HYP, name, str(value))

  config.add_section(constants.INISECT_BEP)
  for name, value in instance.beparams.items():
    config.set(constants.INISECT_BEP, name, str(value))

  config.add_section(constants.INISECT_OSP)
  for name, value in instance.osparams.items():
    config.set(constants.INISECT_OSP, name, str(value))

  config.add_section(constants.INISECT_OSP_PRIVATE)
  for name, value in instance.osparams_private.items():
    config.set(constants.INISECT_OSP_PRIVATE, name, str(value.Get()))

  utils.WriteFile(utils.PathJoin(destdir, constants.EXPORT_CONF_FILE),
                  data=config.Dumps())
  shutil.rmtree(finaldestdir, ignore_errors=True)
  shutil.move(destdir, finaldestdir)


def ExportInfo(dest):
  """Get export configuration information.

  @type dest: str
  @param dest: directory containing the export

  @rtype: L{objects.SerializableConfigParser}
  @return: a serializable config file containing the
      export info

  """
  cff = utils.PathJoin(dest, constants.EXPORT_CONF_FILE)

  config = objects.SerializableConfigParser()
  config.read(cff)

  if (not config.has_section(constants.INISECT_EXP) or
      not config.has_section(constants.INISECT_INS)):
    _Fail("Export info file doesn't have the required fields")

  return config.Dumps()


def ListExports():
  """Return a list of exports currently available on this machine.

  @rtype: list
  @return: list of the exports

  """
  if os.path.isdir(pathutils.EXPORT_DIR):
    return sorted(utils.ListVisibleFiles(pathutils.EXPORT_DIR))
  else:
    _Fail("No exports directory")


def RemoveExport(export):
  """Remove an existing export from the node.

  @type export: str
  @param export: the name of the export to remove
  @rtype: None

  """
  target = utils.PathJoin(pathutils.EXPORT_DIR, export)

  try:
    shutil.rmtree(target)
  except EnvironmentError, err:
    _Fail("Error while removing the export: %s", err, exc=True)


def BlockdevRename(devlist):
  """Rename a list of block devices.

  @type devlist: list of tuples
  @param devlist: list of tuples of the form  (disk, new_unique_id); disk is
      an L{objects.Disk} object describing the current disk, and new
      unique_id is the name we rename it to
  @rtype: boolean
  @return: True if all renames succeeded, False otherwise

  """
  msgs = []
  result = True
  for disk, unique_id in devlist:
    dev = _RecursiveFindBD(disk)
    if dev is None:
      msgs.append("Can't find device %s in rename" % str(disk))
      result = False
      continue
    try:
      old_rpath = dev.dev_path
      dev.Rename(unique_id)
      new_rpath = dev.dev_path
      if old_rpath != new_rpath:
        DevCacheManager.RemoveCache(old_rpath)
        # FIXME: we should add the new cache information here, like:
        # DevCacheManager.UpdateCache(new_rpath, owner, ...)
        # but we don't have the owner here - maybe parse from existing
        # cache? for now, we only lose lvm data when we rename, which
        # is less critical than DRBD or MD
    except errors.BlockDeviceError, err:
      msgs.append("Can't rename device '%s' to '%s': %s" %
                  (dev, unique_id, err))
      logging.exception("Can't rename device '%s' to '%s'", dev, unique_id)
      result = False
  if not result:
    _Fail("; ".join(msgs))


def _TransformFileStorageDir(fs_dir):
  """Checks whether given file_storage_dir is valid.

  Checks wheter the given fs_dir is within the cluster-wide default
  file_storage_dir or the shared_file_storage_dir, which are stored in
  SimpleStore. Only paths under those directories are allowed.

  @type fs_dir: str
  @param fs_dir: the path to check

  @return: the normalized path if valid, None otherwise

  """
  filestorage.CheckFileStoragePath(fs_dir)

  return os.path.normpath(fs_dir)


def CreateFileStorageDir(file_storage_dir):
  """Create file storage directory.

  @type file_storage_dir: str
  @param file_storage_dir: directory to create

  @rtype: tuple
  @return: tuple with first element a boolean indicating wheter dir
      creation was successful or not

  """
  file_storage_dir = _TransformFileStorageDir(file_storage_dir)
  if os.path.exists(file_storage_dir):
    if not os.path.isdir(file_storage_dir):
      _Fail("Specified storage dir '%s' is not a directory",
            file_storage_dir)
  else:
    try:
      os.makedirs(file_storage_dir, 0750)
    except OSError, err:
      _Fail("Cannot create file storage directory '%s': %s",
            file_storage_dir, err, exc=True)


def RemoveFileStorageDir(file_storage_dir):
  """Remove file storage directory.

  Remove it only if it's empty. If not log an error and return.

  @type file_storage_dir: str
  @param file_storage_dir: the directory we should cleanup
  @rtype: tuple (success,)
  @return: tuple of one element, C{success}, denoting
      whether the operation was successful

  """
  file_storage_dir = _TransformFileStorageDir(file_storage_dir)
  if os.path.exists(file_storage_dir):
    if not os.path.isdir(file_storage_dir):
      _Fail("Specified Storage directory '%s' is not a directory",
            file_storage_dir)
    # deletes dir only if empty, otherwise we want to fail the rpc call
    try:
      os.rmdir(file_storage_dir)
    except OSError, err:
      _Fail("Cannot remove file storage directory '%s': %s",
            file_storage_dir, err)


def RenameFileStorageDir(old_file_storage_dir, new_file_storage_dir):
  """Rename the file storage directory.

  @type old_file_storage_dir: str
  @param old_file_storage_dir: the current path
  @type new_file_storage_dir: str
  @param new_file_storage_dir: the name we should rename to
  @rtype: tuple (success,)
  @return: tuple of one element, C{success}, denoting
      whether the operation was successful

  """
  old_file_storage_dir = _TransformFileStorageDir(old_file_storage_dir)
  new_file_storage_dir = _TransformFileStorageDir(new_file_storage_dir)
  if not os.path.exists(new_file_storage_dir):
    if os.path.isdir(old_file_storage_dir):
      try:
        os.rename(old_file_storage_dir, new_file_storage_dir)
      except OSError, err:
        _Fail("Cannot rename '%s' to '%s': %s",
              old_file_storage_dir, new_file_storage_dir, err)
    else:
      _Fail("Specified storage dir '%s' is not a directory",
            old_file_storage_dir)
  else:
    if os.path.exists(old_file_storage_dir):
      _Fail("Cannot rename '%s' to '%s': both locations exist",
            old_file_storage_dir, new_file_storage_dir)


def _EnsureJobQueueFile(file_name):
  """Checks whether the given filename is in the queue directory.

  @type file_name: str
  @param file_name: the file name we should check
  @rtype: None
  @raises RPCFail: if the file is not valid

  """
  if not utils.IsBelowDir(pathutils.QUEUE_DIR, file_name):
    _Fail("Passed job queue file '%s' does not belong to"
          " the queue directory '%s'", file_name, pathutils.QUEUE_DIR)


def JobQueueUpdate(file_name, content):
  """Updates a file in the queue directory.

  This is just a wrapper over L{utils.io.WriteFile}, with proper
  checking.

  @type file_name: str
  @param file_name: the job file name
  @type content: str
  @param content: the new job contents
  @rtype: boolean
  @return: the success of the operation

  """
  file_name = vcluster.LocalizeVirtualPath(file_name)

  _EnsureJobQueueFile(file_name)
  getents = runtime.GetEnts()

  # Write and replace the file atomically
  utils.WriteFile(file_name, data=_Decompress(content), uid=getents.masterd_uid,
                  gid=getents.daemons_gid, mode=constants.JOB_QUEUE_FILES_PERMS)


def JobQueueRename(old, new):
  """Renames a job queue file.

  This is just a wrapper over os.rename with proper checking.

  @type old: str
  @param old: the old (actual) file name
  @type new: str
  @param new: the desired file name
  @rtype: tuple
  @return: the success of the operation and payload

  """
  old = vcluster.LocalizeVirtualPath(old)
  new = vcluster.LocalizeVirtualPath(new)

  _EnsureJobQueueFile(old)
  _EnsureJobQueueFile(new)

  getents = runtime.GetEnts()

  utils.RenameFile(old, new, mkdir=True, mkdir_mode=0750,
                   dir_uid=getents.masterd_uid, dir_gid=getents.daemons_gid)


def BlockdevClose(instance_name, disks):
  """Closes the given block devices.

  This means they will be switched to secondary mode (in case of
  DRBD).

  @param instance_name: if the argument is not empty, the symlinks
      of this instance will be removed
  @type disks: list of L{objects.Disk}
  @param disks: the list of disks to be closed
  @rtype: tuple (success, message)
  @return: a tuple of success and message, where success
      indicates the succes of the operation, and message
      which will contain the error details in case we
      failed

  """
  bdevs = []
  for cf in disks:
    rd = _RecursiveFindBD(cf)
    if rd is None:
      _Fail("Can't find device %s", cf)
    bdevs.append(rd)

  msg = []
  for rd in bdevs:
    try:
      rd.Close()
    except errors.BlockDeviceError, err:
      msg.append(str(err))
  if msg:
    _Fail("Can't make devices secondary: %s", ",".join(msg))
  else:
    if instance_name:
      _RemoveBlockDevLinks(instance_name, disks)


def ValidateHVParams(hvname, hvparams):
  """Validates the given hypervisor parameters.

  @type hvname: string
  @param hvname: the hypervisor name
  @type hvparams: dict
  @param hvparams: the hypervisor parameters to be validated
  @rtype: None

  """
  try:
    hv_type = hypervisor.GetHypervisor(hvname)
    hv_type.ValidateParameters(hvparams)
  except errors.HypervisorError, err:
    _Fail(str(err), log=False)


def _CheckOSPList(os_obj, parameters):
  """Check whether a list of parameters is supported by the OS.

  @type os_obj: L{objects.OS}
  @param os_obj: OS object to check
  @type parameters: list
  @param parameters: the list of parameters to check

  """
  supported = [v[0] for v in os_obj.supported_parameters]
  delta = frozenset(parameters).difference(supported)
  if delta:
    _Fail("The following parameters are not supported"
          " by the OS %s: %s" % (os_obj.name, utils.CommaJoin(delta)))


def ValidateOS(required, osname, checks, osparams):
  """Validate the given OS' parameters.

  @type required: boolean
  @param required: whether absence of the OS should translate into
      failure or not
  @type osname: string
  @param osname: the OS to be validated
  @type checks: list
  @param checks: list of the checks to run (currently only 'parameters')
  @type osparams: dict
  @param osparams: dictionary with OS parameters, some of which may be
                   private.
  @rtype: boolean
  @return: True if the validation passed, or False if the OS was not
      found and L{required} was false

  """
  if not constants.OS_VALIDATE_CALLS.issuperset(checks):
    _Fail("Unknown checks required for OS %s: %s", osname,
          set(checks).difference(constants.OS_VALIDATE_CALLS))

  name_only = objects.OS.GetName(osname)
  status, tbv = _TryOSFromDisk(name_only, None)

  if not status:
    if required:
      _Fail(tbv)
    else:
      return False

  if max(tbv.api_versions) < constants.OS_API_V20:
    return True

  if constants.OS_VALIDATE_PARAMETERS in checks:
    _CheckOSPList(tbv, osparams.keys())

  validate_env = OSCoreEnv(osname, tbv, osparams)
  result = utils.RunCmd([tbv.verify_script] + checks, env=validate_env,
                        cwd=tbv.path, reset_env=True)
  if result.failed:
    logging.error("os validate command '%s' returned error: %s output: %s",
                  result.cmd, result.fail_reason, result.output)
    _Fail("OS validation script failed (%s), output: %s",
          result.fail_reason, result.output, log=False)

  return True


def DemoteFromMC():
  """Demotes the current node from master candidate role.

  """
  # try to ensure we're not the master by mistake
  master, myself = ssconf.GetMasterAndMyself()
  if master == myself:
    _Fail("ssconf status shows I'm the master node, will not demote")

  result = utils.RunCmd([pathutils.DAEMON_UTIL, "check", constants.MASTERD])
  if not result.failed:
    _Fail("The master daemon is running, will not demote")

  try:
    if os.path.isfile(pathutils.CLUSTER_CONF_FILE):
      utils.CreateBackup(pathutils.CLUSTER_CONF_FILE)
  except EnvironmentError, err:
    if err.errno != errno.ENOENT:
      _Fail("Error while backing up cluster file: %s", err, exc=True)

  utils.RemoveFile(pathutils.CLUSTER_CONF_FILE)


def _GetX509Filenames(cryptodir, name):
  """Returns the full paths for the private key and certificate.

  """
  return (utils.PathJoin(cryptodir, name),
          utils.PathJoin(cryptodir, name, _X509_KEY_FILE),
          utils.PathJoin(cryptodir, name, _X509_CERT_FILE))


def CreateX509Certificate(validity, cryptodir=pathutils.CRYPTO_KEYS_DIR):
  """Creates a new X509 certificate for SSL/TLS.

  @type validity: int
  @param validity: Validity in seconds
  @rtype: tuple; (string, string)
  @return: Certificate name and public part

  """
  (key_pem, cert_pem) = \
    utils.GenerateSelfSignedX509Cert(netutils.Hostname.GetSysName(),
                                     min(validity, _MAX_SSL_CERT_VALIDITY))

  cert_dir = tempfile.mkdtemp(dir=cryptodir,
                              prefix="x509-%s-" % utils.TimestampForFilename())
  try:
    name = os.path.basename(cert_dir)
    assert len(name) > 5

    (_, key_file, cert_file) = _GetX509Filenames(cryptodir, name)

    utils.WriteFile(key_file, mode=0400, data=key_pem)
    utils.WriteFile(cert_file, mode=0400, data=cert_pem)

    # Never return private key as it shouldn't leave the node
    return (name, cert_pem)
  except Exception:
    shutil.rmtree(cert_dir, ignore_errors=True)
    raise


def RemoveX509Certificate(name, cryptodir=pathutils.CRYPTO_KEYS_DIR):
  """Removes a X509 certificate.

  @type name: string
  @param name: Certificate name

  """
  (cert_dir, key_file, cert_file) = _GetX509Filenames(cryptodir, name)

  utils.RemoveFile(key_file)
  utils.RemoveFile(cert_file)

  try:
    os.rmdir(cert_dir)
  except EnvironmentError, err:
    _Fail("Cannot remove certificate directory '%s': %s",
          cert_dir, err)


def _GetImportExportIoCommand(instance, mode, ieio, ieargs):
  """Returns the command for the requested input/output.

  @type instance: L{objects.Instance}
  @param instance: The instance object
  @param mode: Import/export mode
  @param ieio: Input/output type
  @param ieargs: Input/output arguments

  """
  assert mode in (constants.IEM_IMPORT, constants.IEM_EXPORT)

  env = None
  prefix = None
  suffix = None
  exp_size = None

  if ieio == constants.IEIO_FILE:
    (filename, ) = ieargs

    if not utils.IsNormAbsPath(filename):
      _Fail("Path '%s' is not normalized or absolute", filename)

    real_filename = os.path.realpath(filename)
    directory = os.path.dirname(real_filename)

    if not utils.IsBelowDir(pathutils.EXPORT_DIR, real_filename):
      _Fail("File '%s' is not under exports directory '%s': %s",
            filename, pathutils.EXPORT_DIR, real_filename)

    # Create directory
    utils.Makedirs(directory, mode=0750)

    quoted_filename = utils.ShellQuote(filename)

    if mode == constants.IEM_IMPORT:
      suffix = "> %s" % quoted_filename
    elif mode == constants.IEM_EXPORT:
      suffix = "< %s" % quoted_filename

      # Retrieve file size
      try:
        st = os.stat(filename)
      except EnvironmentError, err:
        logging.error("Can't stat(2) %s: %s", filename, err)
      else:
        exp_size = utils.BytesToMebibyte(st.st_size)

  elif ieio == constants.IEIO_RAW_DISK:
    (disk, ) = ieargs

    real_disk = _OpenRealBD(disk)

    if mode == constants.IEM_IMPORT:
      # we use nocreat to fail if the device is not already there or we pass a
      # wrong path; we use notrunc to no attempt truncate on an LV device
      suffix = utils.BuildShellCmd("| dd of=%s conv=nocreat,notrunc bs=%s",
                                   real_disk.dev_path,
                                   str(1024 * 1024)) # 1 MB

    elif mode == constants.IEM_EXPORT:
      # the block size on the read dd is 1MiB to match our units
      prefix = utils.BuildShellCmd("dd if=%s bs=%s count=%s |",
                                   real_disk.dev_path,
                                   str(1024 * 1024), # 1 MB
                                   str(disk.size))
      exp_size = disk.size

  elif ieio == constants.IEIO_SCRIPT:
    (disk, disk_index, ) = ieargs

    assert isinstance(disk_index, (int, long))

    inst_os = OSFromDisk(instance.os)
    env = OSEnvironment(instance, inst_os)

    if mode == constants.IEM_IMPORT:
      env["IMPORT_DEVICE"] = env["DISK_%d_PATH" % disk_index]
      env["IMPORT_INDEX"] = str(disk_index)
      script = inst_os.import_script

    elif mode == constants.IEM_EXPORT:
      real_disk = _OpenRealBD(disk)
      env["EXPORT_DEVICE"] = real_disk.dev_path
      env["EXPORT_INDEX"] = str(disk_index)
      script = inst_os.export_script

    # TODO: Pass special environment only to script
    script_cmd = utils.BuildShellCmd("( cd %s && %s; )", inst_os.path, script)

    if mode == constants.IEM_IMPORT:
      suffix = "| %s" % script_cmd

    elif mode == constants.IEM_EXPORT:
      prefix = "%s |" % script_cmd

    # Let script predict size
    exp_size = constants.IE_CUSTOM_SIZE

  else:
    _Fail("Invalid %s I/O mode %r", mode, ieio)

  return (env, prefix, suffix, exp_size)


def _CreateImportExportStatusDir(prefix):
  """Creates status directory for import/export.

  """
  return tempfile.mkdtemp(dir=pathutils.IMPORT_EXPORT_DIR,
                          prefix=("%s-%s-" %
                                  (prefix, utils.TimestampForFilename())))


def StartImportExportDaemon(mode, opts, host, port, instance, component,
                            ieio, ieioargs):
  """Starts an import or export daemon.

  @param mode: Import/output mode
  @type opts: L{objects.ImportExportOptions}
  @param opts: Daemon options
  @type host: string
  @param host: Remote host for export (None for import)
  @type port: int
  @param port: Remote port for export (None for import)
  @type instance: L{objects.Instance}
  @param instance: Instance object
  @type component: string
  @param component: which part of the instance is transferred now,
      e.g. 'disk/0'
  @param ieio: Input/output type
  @param ieioargs: Input/output arguments

  """
  if mode == constants.IEM_IMPORT:
    prefix = "import"

    if not (host is None and port is None):
      _Fail("Can not specify host or port on import")

  elif mode == constants.IEM_EXPORT:
    prefix = "export"

    if host is None or port is None:
      _Fail("Host and port must be specified for an export")

  else:
    _Fail("Invalid mode %r", mode)

  if (opts.key_name is None) ^ (opts.ca_pem is None):
    _Fail("Cluster certificate can only be used for both key and CA")

  (cmd_env, cmd_prefix, cmd_suffix, exp_size) = \
    _GetImportExportIoCommand(instance, mode, ieio, ieioargs)

  if opts.key_name is None:
    # Use server.pem
    key_path = pathutils.NODED_CERT_FILE
    cert_path = pathutils.NODED_CERT_FILE
    assert opts.ca_pem is None
  else:
    (_, key_path, cert_path) = _GetX509Filenames(pathutils.CRYPTO_KEYS_DIR,
                                                 opts.key_name)
    assert opts.ca_pem is not None

  for i in [key_path, cert_path]:
    if not os.path.exists(i):
      _Fail("File '%s' does not exist" % i)

  status_dir = _CreateImportExportStatusDir("%s-%s" % (prefix, component))
  try:
    status_file = utils.PathJoin(status_dir, _IES_STATUS_FILE)
    pid_file = utils.PathJoin(status_dir, _IES_PID_FILE)
    ca_file = utils.PathJoin(status_dir, _IES_CA_FILE)

    if opts.ca_pem is None:
      # Use server.pem
      ca = utils.ReadFile(pathutils.NODED_CERT_FILE)
    else:
      ca = opts.ca_pem

    # Write CA file
    utils.WriteFile(ca_file, data=ca, mode=0400)

    cmd = [
      pathutils.IMPORT_EXPORT_DAEMON,
      status_file, mode,
      "--key=%s" % key_path,
      "--cert=%s" % cert_path,
      "--ca=%s" % ca_file,
      ]

    if host:
      cmd.append("--host=%s" % host)

    if port:
      cmd.append("--port=%s" % port)

    if opts.ipv6:
      cmd.append("--ipv6")
    else:
      cmd.append("--ipv4")

    if opts.compress:
      cmd.append("--compress=%s" % opts.compress)

    if opts.magic:
      cmd.append("--magic=%s" % opts.magic)

    if exp_size is not None:
      cmd.append("--expected-size=%s" % exp_size)

    if cmd_prefix:
      cmd.append("--cmd-prefix=%s" % cmd_prefix)

    if cmd_suffix:
      cmd.append("--cmd-suffix=%s" % cmd_suffix)

    if mode == constants.IEM_EXPORT:
      # Retry connection a few times when connecting to remote peer
      cmd.append("--connect-retries=%s" % constants.RIE_CONNECT_RETRIES)
      cmd.append("--connect-timeout=%s" % constants.RIE_CONNECT_ATTEMPT_TIMEOUT)
    elif opts.connect_timeout is not None:
      assert mode == constants.IEM_IMPORT
      # Overall timeout for establishing connection while listening
      cmd.append("--connect-timeout=%s" % opts.connect_timeout)

    logfile = _InstanceLogName(prefix, instance.os, instance.name, component)

    # TODO: Once _InstanceLogName uses tempfile.mkstemp, StartDaemon has
    # support for receiving a file descriptor for output
    utils.StartDaemon(cmd, env=cmd_env, pidfile=pid_file,
                      output=logfile)

    # The import/export name is simply the status directory name
    return os.path.basename(status_dir)

  except Exception:
    shutil.rmtree(status_dir, ignore_errors=True)
    raise


def GetImportExportStatus(names):
  """Returns import/export daemon status.

  @type names: sequence
  @param names: List of names
  @rtype: List of dicts
  @return: Returns a list of the state of each named import/export or None if a
           status couldn't be read

  """
  result = []

  for name in names:
    status_file = utils.PathJoin(pathutils.IMPORT_EXPORT_DIR, name,
                                 _IES_STATUS_FILE)

    try:
      data = utils.ReadFile(status_file)
    except EnvironmentError, err:
      if err.errno != errno.ENOENT:
        raise
      data = None

    if not data:
      result.append(None)
      continue

    result.append(serializer.LoadJson(data))

  return result


def AbortImportExport(name):
  """Sends SIGTERM to a running import/export daemon.

  """
  logging.info("Abort import/export %s", name)

  status_dir = utils.PathJoin(pathutils.IMPORT_EXPORT_DIR, name)
  pid = utils.ReadLockedPidFile(utils.PathJoin(status_dir, _IES_PID_FILE))

  if pid:
    logging.info("Import/export %s is running with PID %s, sending SIGTERM",
                 name, pid)
    utils.IgnoreProcessNotFound(os.kill, pid, signal.SIGTERM)


def CleanupImportExport(name):
  """Cleanup after an import or export.

  If the import/export daemon is still running it's killed. Afterwards the
  whole status directory is removed.

  """
  logging.info("Finalizing import/export %s", name)

  status_dir = utils.PathJoin(pathutils.IMPORT_EXPORT_DIR, name)

  pid = utils.ReadLockedPidFile(utils.PathJoin(status_dir, _IES_PID_FILE))

  if pid:
    logging.info("Import/export %s is still running with PID %s",
                 name, pid)
    utils.KillProcess(pid, waitpid=False)

  shutil.rmtree(status_dir, ignore_errors=True)


def _FindDisks(disks):
  """Finds attached L{BlockDev}s for the given disks.

  @type disks: list of L{objects.Disk}
  @param disks: the disk objects we need to find

  @return: list of L{BlockDev} objects or C{None} if a given disk
           was not found or was no attached.

  """
  bdevs = []

  for disk in disks:
    rd = _RecursiveFindBD(disk)
    if rd is None:
      _Fail("Can't find device %s", disk)
    bdevs.append(rd)
  return bdevs


def DrbdDisconnectNet(disks):
  """Disconnects the network on a list of drbd devices.

  """
  bdevs = _FindDisks(disks)

  # disconnect disks
  for rd in bdevs:
    try:
      rd.DisconnectNet()
    except errors.BlockDeviceError, err:
      _Fail("Can't change network configuration to standalone mode: %s",
            err, exc=True)


def DrbdAttachNet(disks, instance_name, multimaster):
  """Attaches the network on a list of drbd devices.

  """
  bdevs = _FindDisks(disks)

  if multimaster:
    for idx, rd in enumerate(bdevs):
      try:
        _SymlinkBlockDev(instance_name, rd.dev_path, idx)
      except EnvironmentError, err:
        _Fail("Can't create symlink: %s", err)
  # reconnect disks, switch to new master configuration and if
  # needed primary mode
  for rd in bdevs:
    try:
      rd.AttachNet(multimaster)
    except errors.BlockDeviceError, err:
      _Fail("Can't change network configuration: %s", err)

  # wait until the disks are connected; we need to retry the re-attach
  # if the device becomes standalone, as this might happen if the one
  # node disconnects and reconnects in a different mode before the
  # other node reconnects; in this case, one or both of the nodes will
  # decide it has wrong configuration and switch to standalone

  def _Attach():
    all_connected = True

    for rd in bdevs:
      stats = rd.GetProcStatus()

      if multimaster:
        # In the multimaster case we have to wait explicitly until
        # the resource is Connected and UpToDate/UpToDate, because
        # we promote *both nodes* to primary directly afterwards.
        # Being in resync is not enough, since there is a race during which we
        # may promote a node with an Outdated disk to primary, effectively
        # tearing down the connection.
        all_connected = (all_connected and
                         stats.is_connected and
                         stats.is_disk_uptodate and
                         stats.peer_disk_uptodate)
      else:
        all_connected = (all_connected and
                         (stats.is_connected or stats.is_in_resync))

      if stats.is_standalone:
        # peer had different config info and this node became
        # standalone, even though this should not happen with the
        # new staged way of changing disk configs
        try:
          rd.AttachNet(multimaster)
        except errors.BlockDeviceError, err:
          _Fail("Can't change network configuration: %s", err)

    if not all_connected:
      raise utils.RetryAgain()

  try:
    # Start with a delay of 100 miliseconds and go up to 5 seconds
    utils.Retry(_Attach, (0.1, 1.5, 5.0), 2 * 60)
  except utils.RetryTimeout:
    _Fail("Timeout in disk reconnecting")

  if multimaster:
    # change to primary mode
    for rd in bdevs:
      try:
        rd.Open()
      except errors.BlockDeviceError, err:
        _Fail("Can't change to primary mode: %s", err)


def DrbdWaitSync(disks):
  """Wait until DRBDs have synchronized.

  """
  def _helper(rd):
    stats = rd.GetProcStatus()
    if not (stats.is_connected or stats.is_in_resync):
      raise utils.RetryAgain()
    return stats

  bdevs = _FindDisks(disks)

  min_resync = 100
  alldone = True
  for rd in bdevs:
    try:
      # poll each second for 15 seconds
      stats = utils.Retry(_helper, 1, 15, args=[rd])
    except utils.RetryTimeout:
      stats = rd.GetProcStatus()
      # last check
      if not (stats.is_connected or stats.is_in_resync):
        _Fail("DRBD device %s is not in sync: stats=%s", rd, stats)
    alldone = alldone and (not stats.is_in_resync)
    if stats.sync_percent is not None:
      min_resync = min(min_resync, stats.sync_percent)

  return (alldone, min_resync)


def DrbdNeedsActivation(disks):
  """Checks which of the passed disks needs activation and returns their UUIDs.

  """
  faulty_disks = []

  for disk in disks:
    rd = _RecursiveFindBD(disk)
    if rd is None:
      faulty_disks.append(disk)
      continue

    stats = rd.GetProcStatus()
    if stats.is_standalone or stats.is_diskless:
      faulty_disks.append(disk)

  return [disk.uuid for disk in faulty_disks]


def GetDrbdUsermodeHelper():
  """Returns DRBD usermode helper currently configured.

  """
  try:
    return drbd.DRBD8.GetUsermodeHelper()
  except errors.BlockDeviceError, err:
    _Fail(str(err))


def PowercycleNode(hypervisor_type, hvparams=None):
  """Hard-powercycle the node.

  Because we need to return first, and schedule the powercycle in the
  background, we won't be able to report failures nicely.

  """
  hyper = hypervisor.GetHypervisor(hypervisor_type)
  try:
    pid = os.fork()
  except OSError:
    # if we can't fork, we'll pretend that we're in the child process
    pid = 0
  if pid > 0:
    return "Reboot scheduled in 5 seconds"
  # ensure the child is running on ram
  try:
    utils.Mlockall()
  except Exception: # pylint: disable=W0703
    pass
  time.sleep(5)
  hyper.PowercycleNode(hvparams=hvparams)


def _VerifyRestrictedCmdName(cmd):
  """Verifies a restricted command name.

  @type cmd: string
  @param cmd: Command name
  @rtype: tuple; (boolean, string or None)
  @return: The tuple's first element is the status; if C{False}, the second
    element is an error message string, otherwise it's C{None}

  """
  if not cmd.strip():
    return (False, "Missing command name")

  if os.path.basename(cmd) != cmd:
    return (False, "Invalid command name")

  if not constants.EXT_PLUGIN_MASK.match(cmd):
    return (False, "Command name contains forbidden characters")

  return (True, None)


def _CommonRestrictedCmdCheck(path, owner):
  """Common checks for restricted command file system directories and files.

  @type path: string
  @param path: Path to check
  @param owner: C{None} or tuple containing UID and GID
  @rtype: tuple; (boolean, string or C{os.stat} result)
  @return: The tuple's first element is the status; if C{False}, the second
    element is an error message string, otherwise it's the result of C{os.stat}

  """
  if owner is None:
    # Default to root as owner
    owner = (0, 0)

  try:
    st = os.stat(path)
  except EnvironmentError, err:
    return (False, "Can't stat(2) '%s': %s" % (path, err))

  if stat.S_IMODE(st.st_mode) & (~_RCMD_MAX_MODE):
    return (False, "Permissions on '%s' are too permissive" % path)

  if (st.st_uid, st.st_gid) != owner:
    (owner_uid, owner_gid) = owner
    return (False, "'%s' is not owned by %s:%s" % (path, owner_uid, owner_gid))

  return (True, st)


def _VerifyRestrictedCmdDirectory(path, _owner=None):
  """Verifies restricted command directory.

  @type path: string
  @param path: Path to check
  @rtype: tuple; (boolean, string or None)
  @return: The tuple's first element is the status; if C{False}, the second
    element is an error message string, otherwise it's C{None}

  """
  (status, value) = _CommonRestrictedCmdCheck(path, _owner)

  if not status:
    return (False, value)

  if not stat.S_ISDIR(value.st_mode):
    return (False, "Path '%s' is not a directory" % path)

  return (True, None)


def _VerifyRestrictedCmd(path, cmd, _owner=None):
  """Verifies a whole restricted command and returns its executable filename.

  @type path: string
  @param path: Directory containing restricted commands
  @type cmd: string
  @param cmd: Command name
  @rtype: tuple; (boolean, string)
  @return: The tuple's first element is the status; if C{False}, the second
    element is an error message string, otherwise the second element is the
    absolute path to the executable

  """
  executable = utils.PathJoin(path, cmd)

  (status, msg) = _CommonRestrictedCmdCheck(executable, _owner)

  if not status:
    return (False, msg)

  if not utils.IsExecutable(executable):
    return (False, "access(2) thinks '%s' can't be executed" % executable)

  return (True, executable)


def _PrepareRestrictedCmd(path, cmd,
                          _verify_dir=_VerifyRestrictedCmdDirectory,
                          _verify_name=_VerifyRestrictedCmdName,
                          _verify_cmd=_VerifyRestrictedCmd):
  """Performs a number of tests on a restricted command.

  @type path: string
  @param path: Directory containing restricted commands
  @type cmd: string
  @param cmd: Command name
  @return: Same as L{_VerifyRestrictedCmd}

  """
  # Verify the directory first
  (status, msg) = _verify_dir(path)
  if status:
    # Check command if everything was alright
    (status, msg) = _verify_name(cmd)

  if not status:
    return (False, msg)

  # Check actual executable
  return _verify_cmd(path, cmd)


def RunRestrictedCmd(cmd,
                     _lock_timeout=_RCMD_LOCK_TIMEOUT,
                     _lock_file=pathutils.RESTRICTED_COMMANDS_LOCK_FILE,
                     _path=pathutils.RESTRICTED_COMMANDS_DIR,
                     _sleep_fn=time.sleep,
                     _prepare_fn=_PrepareRestrictedCmd,
                     _runcmd_fn=utils.RunCmd,
                     _enabled=constants.ENABLE_RESTRICTED_COMMANDS):
  """Executes a restricted command after performing strict tests.

  @type cmd: string
  @param cmd: Command name
  @rtype: string
  @return: Command output
  @raise RPCFail: In case of an error

  """
  logging.info("Preparing to run restricted command '%s'", cmd)

  if not _enabled:
    _Fail("Restricted commands disabled at configure time")

  lock = None
  try:
    cmdresult = None
    try:
      lock = utils.FileLock.Open(_lock_file)
      lock.Exclusive(blocking=True, timeout=_lock_timeout)

      (status, value) = _prepare_fn(_path, cmd)

      if status:
        cmdresult = _runcmd_fn([value], env={}, reset_env=True,
                               postfork_fn=lambda _: lock.Unlock())
      else:
        logging.error(value)
    except Exception: # pylint: disable=W0703
      # Keep original error in log
      logging.exception("Caught exception")

    if cmdresult is None:
      logging.info("Sleeping for %0.1f seconds before returning",
                   _RCMD_INVALID_DELAY)
      _sleep_fn(_RCMD_INVALID_DELAY)

      # Do not include original error message in returned error
      _Fail("Executing command '%s' failed" % cmd)
    elif cmdresult.failed or cmdresult.fail_reason:
      _Fail("Restricted command '%s' failed: %s; output: %s",
            cmd, cmdresult.fail_reason, cmdresult.output)
    else:
      return cmdresult.output
  finally:
    if lock is not None:
      # Release lock at last
      lock.Close()
      lock = None


def SetWatcherPause(until, _filename=pathutils.WATCHER_PAUSEFILE):
  """Creates or removes the watcher pause file.

  @type until: None or number
  @param until: Unix timestamp saying until when the watcher shouldn't run

  """
  if until is None:
    logging.info("Received request to no longer pause watcher")
    utils.RemoveFile(_filename)
  else:
    logging.info("Received request to pause watcher until %s", until)

    if not ht.TNumber(until):
      _Fail("Duration must be numeric")

    utils.WriteFile(_filename, data="%d\n" % (until, ), mode=0644)


def ConfigureOVS(ovs_name, ovs_link):
  """Creates a OpenvSwitch on the node.

  This function sets up a OpenvSwitch on the node with given name nad
  connects it via a given eth device.

  @type ovs_name: string
  @param ovs_name: Name of the OpenvSwitch to create.
  @type ovs_link: None or string
  @param ovs_link: Ethernet device for outside connection (can be missing)

  """
  # Initialize the OpenvSwitch
  result = utils.RunCmd(["ovs-vsctl", "add-br", ovs_name])
  if result.failed:
    _Fail("Failed to create openvswitch. Script return value: %s, output: '%s'"
          % (result.exit_code, result.output), log=True)

  # And connect it to a physical interface, if given
  if ovs_link:
    result = utils.RunCmd(["ovs-vsctl", "add-port", ovs_name, ovs_link])
    if result.failed:
      _Fail("Failed to connect openvswitch to  interface %s. Script return"
            " value: %s, output: '%s'" % (ovs_link, result.exit_code,
            result.output), log=True)


class HooksRunner(object):
  """Hook runner.

  This class is instantiated on the node side (ganeti-noded) and not
  on the master side.

  """
  def __init__(self, hooks_base_dir=None):
    """Constructor for hooks runner.

    @type hooks_base_dir: str or None
    @param hooks_base_dir: if not None, this overrides the
        L{pathutils.HOOKS_BASE_DIR} (useful for unittests)

    """
    if hooks_base_dir is None:
      hooks_base_dir = pathutils.HOOKS_BASE_DIR
    # yeah, _BASE_DIR is not valid for attributes, we use it like a
    # constant
    self._BASE_DIR = hooks_base_dir # pylint: disable=C0103

  def RunLocalHooks(self, node_list, hpath, phase, env):
    """Check that the hooks will be run only locally and then run them.

    """
    assert len(node_list) == 1
    node = node_list[0]
    _, myself = ssconf.GetMasterAndMyself()
    assert node == myself

    results = self.RunHooks(hpath, phase, env)

    # Return values in the form expected by HooksMaster
    return {node: (None, False, results)}

  def RunHooks(self, hpath, phase, env):
    """Run the scripts in the hooks directory.

    @type hpath: str
    @param hpath: the path to the hooks directory which
        holds the scripts
    @type phase: str
    @param phase: either L{constants.HOOKS_PHASE_PRE} or
        L{constants.HOOKS_PHASE_POST}
    @type env: dict
    @param env: dictionary with the environment for the hook
    @rtype: list
    @return: list of 3-element tuples:
      - script path
      - script result, either L{constants.HKR_SUCCESS} or
        L{constants.HKR_FAIL}
      - output of the script

    @raise errors.ProgrammerError: for invalid input
        parameters

    """
    if phase == constants.HOOKS_PHASE_PRE:
      suffix = "pre"
    elif phase == constants.HOOKS_PHASE_POST:
      suffix = "post"
    else:
      _Fail("Unknown hooks phase '%s'", phase)

    subdir = "%s-%s.d" % (hpath, suffix)
    dir_name = utils.PathJoin(self._BASE_DIR, subdir)

    results = []

    if not os.path.isdir(dir_name):
      # for non-existing/non-dirs, we simply exit instead of logging a
      # warning at every operation
      return results

    runparts_results = utils.RunParts(dir_name, env=env, reset_env=True)

    for (relname, relstatus, runresult) in runparts_results:
      if relstatus == constants.RUNPARTS_SKIP:
        rrval = constants.HKR_SKIP
        output = ""
      elif relstatus == constants.RUNPARTS_ERR:
        rrval = constants.HKR_FAIL
        output = "Hook script execution error: %s" % runresult
      elif relstatus == constants.RUNPARTS_RUN:
        if runresult.failed:
          rrval = constants.HKR_FAIL
        else:
          rrval = constants.HKR_SUCCESS
        output = utils.SafeEncode(runresult.output.strip())
      results.append(("%s/%s" % (subdir, relname), rrval, output))

    return results


class IAllocatorRunner(object):
  """IAllocator runner.

  This class is instantiated on the node side (ganeti-noded) and not on
  the master side.

  """
  @staticmethod
  def Run(name, idata, ial_params):
    """Run an iallocator script.

    @type name: str
    @param name: the iallocator script name
    @type idata: str
    @param idata: the allocator input data
    @type ial_params: list
    @param ial_params: the iallocator parameters

    @rtype: tuple
    @return: two element tuple of:
       - status
       - either error message or stdout of allocator (for success)

    """
    alloc_script = utils.FindFile(name, constants.IALLOCATOR_SEARCH_PATH,
                                  os.path.isfile)
    if alloc_script is None:
      _Fail("iallocator module '%s' not found in the search path", name)

    fd, fin_name = tempfile.mkstemp(prefix="ganeti-iallocator.")
    try:
      os.write(fd, idata)
      os.close(fd)
      result = utils.RunCmd([alloc_script, fin_name] + ial_params)
      if result.failed:
        _Fail("iallocator module '%s' failed: %s, output '%s'",
              name, result.fail_reason, result.output)
    finally:
      os.unlink(fin_name)

    return result.stdout


class DevCacheManager(object):
  """Simple class for managing a cache of block device information.

  """
  _DEV_PREFIX = "/dev/"
  _ROOT_DIR = pathutils.BDEV_CACHE_DIR

  @classmethod
  def _ConvertPath(cls, dev_path):
    """Converts a /dev/name path to the cache file name.

    This replaces slashes with underscores and strips the /dev
    prefix. It then returns the full path to the cache file.

    @type dev_path: str
    @param dev_path: the C{/dev/} path name
    @rtype: str
    @return: the converted path name

    """
    if dev_path.startswith(cls._DEV_PREFIX):
      dev_path = dev_path[len(cls._DEV_PREFIX):]
    dev_path = dev_path.replace("/", "_")
    fpath = utils.PathJoin(cls._ROOT_DIR, "bdev_%s" % dev_path)
    return fpath

  @classmethod
  def UpdateCache(cls, dev_path, owner, on_primary, iv_name):
    """Updates the cache information for a given device.

    @type dev_path: str
    @param dev_path: the pathname of the device
    @type owner: str
    @param owner: the owner (instance name) of the device
    @type on_primary: bool
    @param on_primary: whether this is the primary
        node nor not
    @type iv_name: str
    @param iv_name: the instance-visible name of the
        device, as in objects.Disk.iv_name

    @rtype: None

    """
    if dev_path is None:
      logging.error("DevCacheManager.UpdateCache got a None dev_path")
      return
    fpath = cls._ConvertPath(dev_path)
    if on_primary:
      state = "primary"
    else:
      state = "secondary"
    if iv_name is None:
      iv_name = "not_visible"
    fdata = "%s %s %s\n" % (str(owner), state, iv_name)
    try:
      utils.WriteFile(fpath, data=fdata)
    except EnvironmentError, err:
      logging.exception("Can't update bdev cache for %s: %s", dev_path, err)

  @classmethod
  def RemoveCache(cls, dev_path):
    """Remove data for a dev_path.

    This is just a wrapper over L{utils.io.RemoveFile} with a converted
    path name and logging.

    @type dev_path: str
    @param dev_path: the pathname of the device

    @rtype: None

    """
    if dev_path is None:
      logging.error("DevCacheManager.RemoveCache got a None dev_path")
      return
    fpath = cls._ConvertPath(dev_path)
    try:
      utils.RemoveFile(fpath)
    except EnvironmentError, err:
      logging.exception("Can't update bdev cache for %s: %s", dev_path, err)
