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


"""Inter-node RPC library.

"""

# pylint: disable=C0103,R0201,R0904
# C0103: Invalid name, since call_ are not valid
# R0201: Method could be a function, we keep all rpcs instance methods
# as not to change them back and forth between static/instance methods
# if they need to start using instance attributes
# R0904: Too many public methods

import logging
import zlib
import base64
import pycurl
import threading
import copy

from ganeti import utils
from ganeti import objects
from ganeti import http
from ganeti import serializer
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import ssconf
from ganeti import runtime
from ganeti import compat
from ganeti import rpc_defs
from ganeti import pathutils
from ganeti import vcluster

# Special module generated at build time
from ganeti import _generated_rpc

# pylint has a bug here, doesn't see this import
import ganeti.http.client  # pylint: disable=W0611


_RPC_CLIENT_HEADERS = [
  "Content-type: %s" % http.HTTP_APP_JSON,
  "Expect:",
  ]

#: Special value to describe an offline host
_OFFLINE = object()


def Init():
  """Initializes the module-global HTTP client manager.

  Must be called before using any RPC function and while exactly one thread is
  running.

  """
  # curl_global_init(3) and curl_global_cleanup(3) must be called with only
  # one thread running. This check is just a safety measure -- it doesn't
  # cover all cases.
  assert threading.activeCount() == 1, \
         "Found more than one active thread when initializing pycURL"

  logging.info("Using PycURL %s", pycurl.version)

  pycurl.global_init(pycurl.GLOBAL_ALL)


def Shutdown():
  """Stops the module-global HTTP client manager.

  Must be called before quitting the program and while exactly one thread is
  running.

  """
  pycurl.global_cleanup()


def _ConfigRpcCurl(curl):
  noded_cert = str(pathutils.NODED_CERT_FILE)

  curl.setopt(pycurl.FOLLOWLOCATION, False)
  curl.setopt(pycurl.CAINFO, noded_cert)
  curl.setopt(pycurl.SSL_VERIFYHOST, 0)
  curl.setopt(pycurl.SSL_VERIFYPEER, True)
  curl.setopt(pycurl.SSLCERTTYPE, "PEM")
  curl.setopt(pycurl.SSLCERT, noded_cert)
  curl.setopt(pycurl.SSLKEYTYPE, "PEM")
  curl.setopt(pycurl.SSLKEY, noded_cert)
  curl.setopt(pycurl.CONNECTTIMEOUT, constants.RPC_CONNECT_TIMEOUT)


def RunWithRPC(fn):
  """RPC-wrapper decorator.

  When applied to a function, it runs it with the RPC system
  initialized, and it shutsdown the system afterwards. This means the
  function must be called without RPC being initialized.

  """
  def wrapper(*args, **kwargs):
    Init()
    try:
      return fn(*args, **kwargs)
    finally:
      Shutdown()
  return wrapper


def _Compress(_, data):
  """Compresses a string for transport over RPC.

  Small amounts of data are not compressed.

  @type data: str
  @param data: Data
  @rtype: tuple
  @return: Encoded data to send

  """
  # Small amounts of data are not compressed
  if len(data) < 512:
    return (constants.RPC_ENCODING_NONE, data)

  # Compress with zlib and encode in base64
  return (constants.RPC_ENCODING_ZLIB_BASE64,
          base64.b64encode(zlib.compress(data, 3)))


class RpcResult(object):
  """RPC Result class.

  This class holds an RPC result. It is needed since in multi-node
  calls we can't raise an exception just because one out of many
  failed, and therefore we use this class to encapsulate the result.

  @ivar data: the data payload, for successful results, or None
  @ivar call: the name of the RPC call
  @ivar node: the name of the node to which we made the call
  @ivar offline: whether the operation failed because the node was
      offline, as opposed to actual failure; offline=True will always
      imply failed=True, in order to allow simpler checking if
      the user doesn't care about the exact failure mode
  @ivar fail_msg: the error message if the call failed

  """
  def __init__(self, data=None, failed=False, offline=False,
               call=None, node=None):
    self.offline = offline
    self.call = call
    self.node = node

    if offline:
      self.fail_msg = "Node is marked offline"
      self.data = self.payload = None
    elif failed:
      self.fail_msg = self._EnsureErr(data)
      self.data = self.payload = None
    else:
      self.data = data
      if not isinstance(self.data, (tuple, list)):
        self.fail_msg = ("RPC layer error: invalid result type (%s)" %
                         type(self.data))
        self.payload = None
      elif len(data) != 2:
        self.fail_msg = ("RPC layer error: invalid result length (%d), "
                         "expected 2" % len(self.data))
        self.payload = None
      elif not self.data[0]:
        self.fail_msg = self._EnsureErr(self.data[1])
        self.payload = None
      else:
        # finally success
        self.fail_msg = None
        self.payload = data[1]

    for attr_name in ["call", "data", "fail_msg",
                      "node", "offline", "payload"]:
      assert hasattr(self, attr_name), "Missing attribute %s" % attr_name

  def __repr__(self):
    return ("RpcResult(data=%s, call=%s, node=%s, offline=%s, fail_msg=%s)" %
            (self.offline, self.call, self.node, self.offline, self.fail_msg))

  @staticmethod
  def _EnsureErr(val):
    """Helper to ensure we return a 'True' value for error."""
    if val:
      return val
    else:
      return "No error information"

  def Raise(self, msg, prereq=False, ecode=None):
    """If the result has failed, raise an OpExecError.

    This is used so that LU code doesn't have to check for each
    result, but instead can call this function.

    """
    if not self.fail_msg:
      return

    if not msg: # one could pass None for default message
      msg = ("Call '%s' to node '%s' has failed: %s" %
             (self.call, self.node, self.fail_msg))
    else:
      msg = "%s: %s" % (msg, self.fail_msg)
    if prereq:
      ec = errors.OpPrereqError
    else:
      ec = errors.OpExecError
    if ecode is not None:
      args = (msg, ecode)
    else:
      args = (msg, )
    raise ec(*args) # pylint: disable=W0142

  def Warn(self, msg, feedback_fn):
    """If the result has failed, call the feedback_fn.

    This is used to in cases were LU wants to warn the
    user about a failure, but continue anyway.

    """
    if not self.fail_msg:
      return

    msg = "%s: %s" % (msg, self.fail_msg)
    feedback_fn(msg)


def _SsconfResolver(ssconf_ips, node_list, _,
                    ssc=ssconf.SimpleStore,
                    nslookup_fn=netutils.Hostname.GetIP):
  """Return addresses for given node names.

  @type ssconf_ips: bool
  @param ssconf_ips: Use the ssconf IPs
  @type node_list: list
  @param node_list: List of node names
  @type ssc: class
  @param ssc: SimpleStore class that is used to obtain node->ip mappings
  @type nslookup_fn: callable
  @param nslookup_fn: function use to do NS lookup
  @rtype: list of tuple; (string, string)
  @return: List of tuples containing node name and IP address

  """
  ss = ssc()
  family = ss.GetPrimaryIPFamily()

  if ssconf_ips:
    iplist = ss.GetNodePrimaryIPList()
    ipmap = dict(entry.split() for entry in iplist)
  else:
    ipmap = {}

  result = []
  for node in node_list:
    ip = ipmap.get(node)
    if ip is None:
      ip = nslookup_fn(node, family=family)
    result.append((node, ip, node))

  return result


class _StaticResolver:
  def __init__(self, addresses):
    """Initializes this class.

    """
    self._addresses = addresses

  def __call__(self, hosts, _):
    """Returns static addresses for hosts.

    """
    assert len(hosts) == len(self._addresses)
    return zip(hosts, self._addresses, hosts)


def _CheckConfigNode(node_uuid_or_name, node, accept_offline_node):
  """Checks if a node is online.

  @type node_uuid_or_name: string
  @param node_uuid_or_name: Node UUID
  @type node: L{objects.Node} or None
  @param node: Node object

  """
  if node is None:
    # Assume that the passed parameter was actually a node name, so depend on
    # DNS for name resolution
    return (node_uuid_or_name, node_uuid_or_name, node_uuid_or_name)
  else:
    if node.offline and not accept_offline_node:
      ip = _OFFLINE
    else:
      ip = node.primary_ip
    return (node.name, ip, node_uuid_or_name)


def _NodeConfigResolver(single_node_fn, all_nodes_fn, node_uuids, opts):
  """Calculate node addresses using configuration.

  Note that strings in node_uuids are treated as node names if the UUID is not
  found in the configuration.

  """
  accept_offline_node = (opts is rpc_defs.ACCEPT_OFFLINE_NODE)

  assert accept_offline_node or opts is None, "Unknown option"

  # Special case for single-host lookups
  if len(node_uuids) == 1:
    (uuid, ) = node_uuids
    return [_CheckConfigNode(uuid, single_node_fn(uuid), accept_offline_node)]
  else:
    all_nodes = all_nodes_fn()
    return [_CheckConfigNode(uuid, all_nodes.get(uuid, None),
                             accept_offline_node)
            for uuid in node_uuids]


class _RpcProcessor:
  def __init__(self, resolver, port, lock_monitor_cb=None):
    """Initializes this class.

    @param resolver: callable accepting a list of node UUIDs or hostnames,
      returning a list of tuples containing name, IP address and original name
      of the resolved node. IP address can be the name or the special value
      L{_OFFLINE} to mark offline machines.
    @type port: int
    @param port: TCP port
    @param lock_monitor_cb: Callable for registering with lock monitor

    """
    self._resolver = resolver
    self._port = port
    self._lock_monitor_cb = lock_monitor_cb

  @staticmethod
  def _PrepareRequests(hosts, port, procedure, body, read_timeout):
    """Prepares requests by sorting offline hosts into separate list.

    @type body: dict
    @param body: a dictionary with per-host body data

    """
    results = {}
    requests = {}

    assert isinstance(body, dict)
    assert len(body) == len(hosts)
    assert compat.all(isinstance(v, str) for v in body.values())
    assert frozenset(map(lambda x: x[2], hosts)) == frozenset(body.keys()), \
        "%s != %s" % (hosts, body.keys())

    for (name, ip, original_name) in hosts:
      if ip is _OFFLINE:
        # Node is marked as offline
        results[original_name] = RpcResult(node=name,
                                           offline=True,
                                           call=procedure)
      else:
        requests[original_name] = \
          http.client.HttpClientRequest(str(ip), port,
                                        http.HTTP_POST, str("/%s" % procedure),
                                        headers=_RPC_CLIENT_HEADERS,
                                        post_data=body[original_name],
                                        read_timeout=read_timeout,
                                        nicename="%s/%s" % (name, procedure),
                                        curl_config_fn=_ConfigRpcCurl)

    return (results, requests)

  @staticmethod
  def _CombineResults(results, requests, procedure):
    """Combines pre-computed results for offline hosts with actual call results.

    """
    for name, req in requests.items():
      if req.success and req.resp_status_code == http.HTTP_OK:
        host_result = RpcResult(data=serializer.LoadJson(req.resp_body),
                                node=name, call=procedure)
      else:
        # TODO: Better error reporting
        if req.error:
          msg = req.error
        else:
          msg = req.resp_body

        logging.error("RPC error in %s on node %s: %s", procedure, name, msg)
        host_result = RpcResult(data=msg, failed=True, node=name,
                                call=procedure)

      results[name] = host_result

    return results

  def __call__(self, nodes, procedure, body, read_timeout, resolver_opts,
               _req_process_fn=None):
    """Makes an RPC request to a number of nodes.

    @type nodes: sequence
    @param nodes: node UUIDs or Hostnames
    @type procedure: string
    @param procedure: Request path
    @type body: dictionary
    @param body: dictionary with request bodies per host
    @type read_timeout: int or None
    @param read_timeout: Read timeout for request
    @rtype: dictionary
    @return: a dictionary mapping host names to rpc.RpcResult objects

    """
    assert read_timeout is not None, \
      "Missing RPC read timeout for procedure '%s'" % procedure

    if _req_process_fn is None:
      _req_process_fn = http.client.ProcessRequests

    (results, requests) = \
      self._PrepareRequests(self._resolver(nodes, resolver_opts), self._port,
                            procedure, body, read_timeout)

    _req_process_fn(requests.values(), lock_monitor_cb=self._lock_monitor_cb)

    assert not frozenset(results).intersection(requests)

    return self._CombineResults(results, requests, procedure)


class _RpcClientBase:
  def __init__(self, resolver, encoder_fn, lock_monitor_cb=None,
               _req_process_fn=None):
    """Initializes this class.

    """
    proc = _RpcProcessor(resolver,
                         netutils.GetDaemonPort(constants.NODED),
                         lock_monitor_cb=lock_monitor_cb)
    self._proc = compat.partial(proc, _req_process_fn=_req_process_fn)
    self._encoder = compat.partial(self._EncodeArg, encoder_fn)

  @staticmethod
  def _EncodeArg(encoder_fn, node, (argkind, value)):
    """Encode argument.

    """
    if argkind is None:
      return value
    else:
      return encoder_fn(argkind)(node, value)

  def _Call(self, cdef, node_list, args):
    """Entry point for automatically generated RPC wrappers.

    """
    (procedure, _, resolver_opts, timeout, argdefs,
     prep_fn, postproc_fn, _) = cdef

    if callable(timeout):
      read_timeout = timeout(args)
    else:
      read_timeout = timeout

    if callable(resolver_opts):
      req_resolver_opts = resolver_opts(args)
    else:
      req_resolver_opts = resolver_opts

    if len(args) != len(argdefs):
      raise errors.ProgrammerError("Number of passed arguments doesn't match")

    if prep_fn is None:
      prep_fn = lambda _, args: args
    assert callable(prep_fn)

    # encode the arguments for each node individually, pass them and the node
    # name to the prep_fn, and serialise its return value
    encode_args_fn = lambda node: map(compat.partial(self._encoder, node),
                                      zip(map(compat.snd, argdefs), args))
    pnbody = dict(
      (n,
       serializer.DumpJson(prep_fn(n, encode_args_fn(n)),
                           private_encoder=serializer.EncodeWithPrivateFields))
      for n in node_list
    )

    result = self._proc(node_list, procedure, pnbody, read_timeout,
                        req_resolver_opts)

    if postproc_fn:
      return dict(map(lambda (key, value): (key, postproc_fn(value)),
                      result.items()))
    else:
      return result


def _ObjectToDict(_, value):
  """Converts an object to a dictionary.

  @note: See L{objects}.

  """
  return value.ToDict()


def _ObjectListToDict(node, value):
  """Converts a list of L{objects} to dictionaries.

  """
  return map(compat.partial(_ObjectToDict, node), value)


def _PrepareFileUpload(getents_fn, node, filename):
  """Loads a file and prepares it for an upload to nodes.

  """
  statcb = utils.FileStatHelper()
  data = _Compress(node, utils.ReadFile(filename, preread=statcb))
  st = statcb.st

  if getents_fn is None:
    getents_fn = runtime.GetEnts

  getents = getents_fn()

  virt_filename = vcluster.MakeVirtualPath(filename)

  return [virt_filename, data, st.st_mode, getents.LookupUid(st.st_uid),
          getents.LookupGid(st.st_gid), st.st_atime, st.st_mtime]


def _PrepareFinalizeExportDisks(_, snap_disks):
  """Encodes disks for finalizing export.

  """
  flat_disks = []

  for disk in snap_disks:
    if isinstance(disk, bool):
      flat_disks.append(disk)
    else:
      flat_disks.append(disk.ToDict())

  return flat_disks


def _EncodeBlockdevRename(_, value):
  """Encodes information for renaming block devices.

  """
  return [(d.ToDict(), uid) for d, uid in value]


def _AddSpindlesToLegacyNodeInfo(result, space_info):
  """Extracts the spindle information from the space info and adds
  it to the result dictionary.

  @type result: dict of strings
  @param result: dictionary holding the result of the legacy node info
  @type space_info: list of dicts of strings
  @param space_info: list, each row holding space information of one storage
    unit
  @rtype: None
  @return: does not return anything, manipulates the C{result} variable

  """
  lvm_pv_info = utils.storage.LookupSpaceInfoByStorageType(
      space_info, constants.ST_LVM_PV)
  if lvm_pv_info:
    result["spindles_free"] = lvm_pv_info["storage_free"]
    result["spindles_total"] = lvm_pv_info["storage_size"]
  else:
    result["spindles_free"] = 0
    result["spindles_total"] = 0


def _AddStorageInfoToLegacyNodeInfoByTemplate(
    result, space_info, disk_template):
  """Extracts the storage space information of the disk template from
  the space info and adds it to the result dictionary.

  @see: C{_AddSpindlesToLegacyNodeInfo} for parameter information.

  """
  if utils.storage.DiskTemplateSupportsSpaceReporting(disk_template):
    disk_info = utils.storage.LookupSpaceInfoByDiskTemplate(
        space_info, disk_template)
    result["name"] = disk_info["name"]
    result["storage_free"] = disk_info["storage_free"]
    result["storage_size"] = disk_info["storage_size"]
  else:
    # FIXME: consider displaying '-' in this case
    result["storage_free"] = 0
    result["storage_size"] = 0


def MakeLegacyNodeInfo(data, disk_template):
  """Formats the data returned by call_node_info.

  Converts the data into a single dictionary. This is fine for most use cases,
  but some require information from more than one volume group or hypervisor.

  """
  (bootid, space_info, (hv_info, )) = data

  ret = utils.JoinDisjointDicts(hv_info, {"bootid": bootid})

  _AddSpindlesToLegacyNodeInfo(ret, space_info)
  _AddStorageInfoToLegacyNodeInfoByTemplate(ret, space_info, disk_template)

  return ret


def _AnnotateDParamsDRBD(disk, (drbd_params, data_params, meta_params)):
  """Annotates just DRBD disks layouts.

  """
  assert disk.dev_type == constants.DT_DRBD8

  disk.params = objects.FillDict(drbd_params, disk.params)
  (dev_data, dev_meta) = disk.children
  dev_data.params = objects.FillDict(data_params, dev_data.params)
  dev_meta.params = objects.FillDict(meta_params, dev_meta.params)

  return disk


def _AnnotateDParamsGeneric(disk, (params, )):
  """Generic disk parameter annotation routine.

  """
  assert disk.dev_type != constants.DT_DRBD8

  disk.params = objects.FillDict(params, disk.params)

  return disk


def AnnotateDiskParams(disks, disk_params):
  """Annotates the disk objects with the disk parameters.

  @param disks: The list of disks objects to annotate
  @param disk_params: The disk parameters for annotation
  @returns: A list of disk objects annotated

  """
  def AnnotateDisk(disk):
    if disk.dev_type == constants.DT_DISKLESS:
      return disk

    ld_params = objects.Disk.ComputeLDParams(disk.dev_type, disk_params)

    if disk.dev_type == constants.DT_DRBD8:
      return _AnnotateDParamsDRBD(disk, ld_params)
    else:
      return _AnnotateDParamsGeneric(disk, ld_params)

  return [AnnotateDisk(disk.Copy()) for disk in disks]


def _GetExclusiveStorageFlag(cfg, node_uuid):
  ni = cfg.GetNodeInfo(node_uuid)
  if ni is None:
    raise errors.OpPrereqError("Invalid node name %s" % node_uuid,
                               errors.ECODE_NOENT)
  return cfg.GetNdParams(ni)[constants.ND_EXCLUSIVE_STORAGE]


def _AddExclusiveStorageFlagToLvmStorageUnits(storage_units, es_flag):
  """Adds the exclusive storage flag to lvm units.

  This function creates a copy of the storage_units lists, with the
  es_flag being added to all lvm storage units.

  @type storage_units: list of pairs (string, string)
  @param storage_units: list of 'raw' storage units, consisting only of
    (storage_type, storage_key)
  @type es_flag: boolean
  @param es_flag: exclusive storage flag
  @rtype: list of tuples (string, string, list)
  @return: list of storage units (storage_type, storage_key, params) with
    the params containing the es_flag for lvm-vg storage units

  """
  result = []
  for (storage_type, storage_key) in storage_units:
    if storage_type in [constants.ST_LVM_VG]:
      result.append((storage_type, storage_key, [es_flag]))
      if es_flag:
        result.append((constants.ST_LVM_PV, storage_key, [es_flag]))
    else:
      result.append((storage_type, storage_key, []))
  return result


def GetExclusiveStorageForNodes(cfg, node_uuids):
  """Return the exclusive storage flag for all the given nodes.

  @type cfg: L{config.ConfigWriter}
  @param cfg: cluster configuration
  @type node_uuids: list or tuple
  @param node_uuids: node UUIDs for which to read the flag
  @rtype: dict
  @return: mapping from node uuids to exclusive storage flags
  @raise errors.OpPrereqError: if any given node name has no corresponding
  node

  """
  getflag = lambda n: _GetExclusiveStorageFlag(cfg, n)
  flags = map(getflag, node_uuids)
  return dict(zip(node_uuids, flags))


def PrepareStorageUnitsForNodes(cfg, storage_units, node_uuids):
  """Return the lvm storage unit for all the given nodes.

  Main purpose of this function is to map the exclusive storage flag, which
  can be different for each node, to the default LVM storage unit.

  @type cfg: L{config.ConfigWriter}
  @param cfg: cluster configuration
  @type storage_units: list of pairs (string, string)
  @param storage_units: list of 'raw' storage units, e.g. pairs of
    (storage_type, storage_key)
  @type node_uuids: list or tuple
  @param node_uuids: node UUIDs for which to read the flag
  @rtype: dict
  @return: mapping from node uuids to a list of storage units which include
    the exclusive storage flag for lvm storage
  @raise errors.OpPrereqError: if any given node name has no corresponding
  node

  """
  getunit = lambda n: _AddExclusiveStorageFlagToLvmStorageUnits(
      storage_units, _GetExclusiveStorageFlag(cfg, n))
  flags = map(getunit, node_uuids)
  return dict(zip(node_uuids, flags))


#: Generic encoders
_ENCODERS = {
  rpc_defs.ED_OBJECT_DICT: _ObjectToDict,
  rpc_defs.ED_OBJECT_DICT_LIST: _ObjectListToDict,
  rpc_defs.ED_COMPRESS: _Compress,
  rpc_defs.ED_FINALIZE_EXPORT_DISKS: _PrepareFinalizeExportDisks,
  rpc_defs.ED_BLOCKDEV_RENAME: _EncodeBlockdevRename,
  }


class RpcRunner(_RpcClientBase,
                _generated_rpc.RpcClientDefault,
                _generated_rpc.RpcClientBootstrap,
                _generated_rpc.RpcClientDnsOnly,
                _generated_rpc.RpcClientConfig):
  """RPC runner class.

  """
  def __init__(self, cfg, lock_monitor_cb, _req_process_fn=None, _getents=None):
    """Initialized the RPC runner.

    @type cfg: L{config.ConfigWriter}
    @param cfg: Configuration
    @type lock_monitor_cb: callable
    @param lock_monitor_cb: Lock monitor callback

    """
    self._cfg = cfg

    encoders = _ENCODERS.copy()

    encoders.update({
      # Encoders requiring configuration object
      rpc_defs.ED_INST_DICT: self._InstDict,
      rpc_defs.ED_INST_DICT_HVP_BEP_DP: self._InstDictHvpBepDp,
      rpc_defs.ED_INST_DICT_OSP_DP: self._InstDictOspDp,
      rpc_defs.ED_NIC_DICT: self._NicDict,
      rpc_defs.ED_DEVICE_DICT: self._DeviceDict,

      # Encoders annotating disk parameters
      rpc_defs.ED_DISKS_DICT_DP: self._DisksDictDP,
      rpc_defs.ED_MULTI_DISKS_DICT_DP: self._MultiDiskDictDP,
      rpc_defs.ED_SINGLE_DISK_DICT_DP: self._SingleDiskDictDP,
      rpc_defs.ED_NODE_TO_DISK_DICT_DP: self._EncodeNodeToDiskDictDP,

      # Encoders with special requirements
      rpc_defs.ED_FILE_DETAILS: compat.partial(_PrepareFileUpload, _getents),

      rpc_defs.ED_IMPEXP_IO: self._EncodeImportExportIO,
      })

    # Resolver using configuration
    resolver = compat.partial(_NodeConfigResolver, cfg.GetNodeInfo,
                              cfg.GetAllNodesInfo)

    # Pylint doesn't recognize multiple inheritance properly, see
    # <http://www.logilab.org/ticket/36586> and
    # <http://www.logilab.org/ticket/35642>
    # pylint: disable=W0233
    _RpcClientBase.__init__(self, resolver, encoders.get,
                            lock_monitor_cb=lock_monitor_cb,
                            _req_process_fn=_req_process_fn)
    _generated_rpc.RpcClientConfig.__init__(self)
    _generated_rpc.RpcClientBootstrap.__init__(self)
    _generated_rpc.RpcClientDnsOnly.__init__(self)
    _generated_rpc.RpcClientDefault.__init__(self)

  def _NicDict(self, _, nic):
    """Convert the given nic to a dict and encapsulate netinfo

    """
    n = copy.deepcopy(nic)
    if n.network:
      net_uuid = self._cfg.LookupNetwork(n.network)
      if net_uuid:
        nobj = self._cfg.GetNetwork(net_uuid)
        n.netinfo = objects.Network.ToDict(nobj)
    return n.ToDict()

  def _DeviceDict(self, _, (device, instance)):
    if isinstance(device, objects.NIC):
      return self._NicDict(None, device)
    elif isinstance(device, objects.Disk):
      return self._SingleDiskDictDP(None, (device, instance))

  def _InstDict(self, node, instance, hvp=None, bep=None, osp=None):
    """Convert the given instance to a dict.

    This is done via the instance's ToDict() method and additionally
    we fill the hvparams with the cluster defaults.

    @type instance: L{objects.Instance}
    @param instance: an Instance object
    @type hvp: dict or None
    @param hvp: a dictionary with overridden hypervisor parameters
    @type bep: dict or None
    @param bep: a dictionary with overridden backend parameters
    @type osp: dict or None
    @param osp: a dictionary with overridden os parameters
    @rtype: dict
    @return: the instance dict, with the hvparams filled with the
        cluster defaults

    """
    idict = instance.ToDict()
    cluster = self._cfg.GetClusterInfo()
    idict["hvparams"] = cluster.FillHV(instance)
    if hvp is not None:
      idict["hvparams"].update(hvp)
    idict["beparams"] = cluster.FillBE(instance)
    if bep is not None:
      idict["beparams"].update(bep)
    idict["osparams"] = cluster.SimpleFillOS(instance.os, instance.osparams)
    if osp is not None:
      idict["osparams"].update(osp)
    idict["disks"] = self._DisksDictDP(node, (instance.disks, instance))
    for nic in idict["nics"]:
      nic["nicparams"] = objects.FillDict(
        cluster.nicparams[constants.PP_DEFAULT],
        nic["nicparams"])
      network = nic.get("network", None)
      if network:
        net_uuid = self._cfg.LookupNetwork(network)
        if net_uuid:
          nobj = self._cfg.GetNetwork(net_uuid)
          nic["netinfo"] = objects.Network.ToDict(nobj)
    return idict

  def _InstDictHvpBepDp(self, node, (instance, hvp, bep)):
    """Wrapper for L{_InstDict}.

    """
    return self._InstDict(node, instance, hvp=hvp, bep=bep)

  def _InstDictOspDp(self, node, (instance, osparams)):
    """Wrapper for L{_InstDict}.

    """
    return self._InstDict(node, instance, osp=osparams)

  def _DisksDictDP(self, node, (disks, instance)):
    """Wrapper for L{AnnotateDiskParams}.

    """
    diskparams = self._cfg.GetInstanceDiskParams(instance)
    ret = []
    for disk in AnnotateDiskParams(disks, diskparams):
      disk_node_uuids = disk.GetNodes(instance.primary_node)
      node_ips = dict((uuid, node.secondary_ip) for (uuid, node)
                      in self._cfg.GetMultiNodeInfo(disk_node_uuids))

      disk.UpdateDynamicDiskParams(node, node_ips)

      ret.append(disk.ToDict(include_dynamic_params=True))

    return ret

  def _MultiDiskDictDP(self, node, disks_insts):
    """Wrapper for L{AnnotateDiskParams}.

    Supports a list of (disk, instance) tuples.
    """
    return [disk for disk_inst in disks_insts
            for disk in self._DisksDictDP(node, disk_inst)]

  def _SingleDiskDictDP(self, node, (disk, instance)):
    """Wrapper for L{AnnotateDiskParams}.

    """
    (anno_disk,) = self._DisksDictDP(node, ([disk], instance))
    return anno_disk

  def _EncodeNodeToDiskDictDP(self, node, value):
    """Encode dict of node name -> list of (disk, instance) tuples as values.

    """
    return dict((name, [self._SingleDiskDictDP(node, disk) for disk in disks])
                for name, disks in value.items())

  def _EncodeImportExportIO(self, node, (ieio, ieioargs)):
    """Encodes import/export I/O information.

    """
    if ieio == constants.IEIO_RAW_DISK:
      assert len(ieioargs) == 2
      return (ieio, (self._SingleDiskDictDP(node, ieioargs), ))

    if ieio == constants.IEIO_SCRIPT:
      assert len(ieioargs) == 2
      return (ieio, (self._SingleDiskDictDP(node, ieioargs[0]), ieioargs[1]))

    return (ieio, ieioargs)


class JobQueueRunner(_RpcClientBase, _generated_rpc.RpcClientJobQueue):
  """RPC wrappers for job queue.

  """
  def __init__(self, context, address_list):
    """Initializes this class.

    """
    if address_list is None:
      resolver = compat.partial(_SsconfResolver, True)
    else:
      # Caller provided an address list
      resolver = _StaticResolver(address_list)

    _RpcClientBase.__init__(self, resolver, _ENCODERS.get,
                            lock_monitor_cb=context.glm.AddToLockMonitor)
    _generated_rpc.RpcClientJobQueue.__init__(self)


class BootstrapRunner(_RpcClientBase,
                      _generated_rpc.RpcClientBootstrap,
                      _generated_rpc.RpcClientDnsOnly):
  """RPC wrappers for bootstrapping.

  """
  def __init__(self):
    """Initializes this class.

    """
    # Pylint doesn't recognize multiple inheritance properly, see
    # <http://www.logilab.org/ticket/36586> and
    # <http://www.logilab.org/ticket/35642>
    # pylint: disable=W0233
    _RpcClientBase.__init__(self, compat.partial(_SsconfResolver, True),
                            _ENCODERS.get)
    _generated_rpc.RpcClientBootstrap.__init__(self)
    _generated_rpc.RpcClientDnsOnly.__init__(self)


class DnsOnlyRunner(_RpcClientBase, _generated_rpc.RpcClientDnsOnly):
  """RPC wrappers for calls using only DNS.

  """
  def __init__(self):
    """Initialize this class.

    """
    _RpcClientBase.__init__(self, compat.partial(_SsconfResolver, False),
                            _ENCODERS.get)
    _generated_rpc.RpcClientDnsOnly.__init__(self)


class ConfigRunner(_RpcClientBase, _generated_rpc.RpcClientConfig):
  """RPC wrappers for L{config}.

  """
  def __init__(self, context, address_list, _req_process_fn=None,
               _getents=None):
    """Initializes this class.

    """
    if context:
      lock_monitor_cb = context.glm.AddToLockMonitor
    else:
      lock_monitor_cb = None

    if address_list is None:
      resolver = compat.partial(_SsconfResolver, True)
    else:
      # Caller provided an address list
      resolver = _StaticResolver(address_list)

    encoders = _ENCODERS.copy()

    encoders.update({
      rpc_defs.ED_FILE_DETAILS: compat.partial(_PrepareFileUpload, _getents),
      })

    _RpcClientBase.__init__(self, resolver, encoders.get,
                            lock_monitor_cb=lock_monitor_cb,
                            _req_process_fn=_req_process_fn)
    _generated_rpc.RpcClientConfig.__init__(self)
