#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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

# pylint: disable-msg=C0103,R0201,R0904
# C0103: Invalid name, since call_ are not valid
# R0201: Method could be a function, we keep all rpcs instance methods
# as not to change them back and forth between static/instance methods
# if they need to start using instance attributes
# R0904: Too many public methods

import os
import logging
import zlib
import base64
import pycurl
import threading

from ganeti import utils
from ganeti import objects
from ganeti import http
from ganeti import serializer
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import ssconf
from ganeti import runtime

# pylint has a bug here, doesn't see this import
import ganeti.http.client  # pylint: disable-msg=W0611


# Timeout for connecting to nodes (seconds)
_RPC_CONNECT_TIMEOUT = 5

_RPC_CLIENT_HEADERS = [
  "Content-type: %s" % http.HTTP_APP_JSON,
  "Expect:",
  ]

# Various time constants for the timeout table
_TMO_URGENT = 60 # one minute
_TMO_FAST = 5 * 60 # five minutes
_TMO_NORMAL = 15 * 60 # 15 minutes
_TMO_SLOW = 3600 # one hour
_TMO_4HRS = 4 * 3600
_TMO_1DAY = 86400

# Timeout table that will be built later by decorators
# Guidelines for choosing timeouts:
# - call used during watcher: timeout -> 1min, _TMO_URGENT
# - trivial (but be sure it is trivial) (e.g. reading a file): 5min, _TMO_FAST
# - other calls: 15 min, _TMO_NORMAL
# - special calls (instance add, etc.): either _TMO_SLOW (1h) or huge timeouts

_TIMEOUTS = {
}


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
  noded_cert = str(constants.NODED_CERT_FILE)

  curl.setopt(pycurl.FOLLOWLOCATION, False)
  curl.setopt(pycurl.CAINFO, noded_cert)
  curl.setopt(pycurl.SSL_VERIFYHOST, 0)
  curl.setopt(pycurl.SSL_VERIFYPEER, True)
  curl.setopt(pycurl.SSLCERTTYPE, "PEM")
  curl.setopt(pycurl.SSLCERT, noded_cert)
  curl.setopt(pycurl.SSLKEYTYPE, "PEM")
  curl.setopt(pycurl.SSLKEY, noded_cert)
  curl.setopt(pycurl.CONNECTTIMEOUT, _RPC_CONNECT_TIMEOUT)


# Aliasing this module avoids the following warning by epydoc: "Warning: No
# information available for ganeti.rpc._RpcThreadLocal's base threading.local"
_threading = threading


class _RpcThreadLocal(_threading.local):
  def GetHttpClientPool(self):
    """Returns a per-thread HTTP client pool.

    @rtype: L{http.client.HttpClientPool}

    """
    try:
      pool = self.hcp
    except AttributeError:
      pool = http.client.HttpClientPool(_ConfigRpcCurl)
      self.hcp = pool

    return pool


# Remove module alias (see above)
del _threading


_thread_local = _RpcThreadLocal()


def _RpcTimeout(secs):
  """Timeout decorator.

  When applied to a rpc call_* function, it updates the global timeout
  table with the given function/timeout.

  """
  def decorator(f):
    name = f.__name__
    assert name.startswith("call_")
    _TIMEOUTS[name[len("call_"):]] = secs
    return f
  return decorator


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


class RpcResult(object):
  """RPC Result class.

  This class holds an RPC result. It is needed since in multi-node
  calls we can't raise an exception just because one one out of many
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
    raise ec(*args) # pylint: disable-msg=W0142


def _AddressLookup(node_list,
                   ssc=ssconf.SimpleStore,
                   nslookup_fn=netutils.Hostname.GetIP):
  """Return addresses for given node names.

  @type node_list: list
  @param node_list: List of node names
  @type ssc: class
  @param ssc: SimpleStore class that is used to obtain node->ip mappings
  @type nslookup_fn: callable
  @param nslookup_fn: function use to do NS lookup
  @rtype: list of addresses and/or None's
  @returns: List of corresponding addresses, if found

  """
  ss = ssc()
  iplist = ss.GetNodePrimaryIPList()
  family = ss.GetPrimaryIPFamily()
  addresses = []
  ipmap = dict(entry.split() for entry in iplist)
  for node in node_list:
    address = ipmap.get(node)
    if address is None:
      address = nslookup_fn(node, family=family)
    addresses.append(address)

  return addresses


class Client:
  """RPC Client class.

  This class, given a (remote) method name, a list of parameters and a
  list of nodes, will contact (in parallel) all nodes, and return a
  dict of results (key: node name, value: result).

  One current bug is that generic failure is still signaled by
  'False' result, which is not good. This overloading of values can
  cause bugs.

  """
  def __init__(self, procedure, body, port, address_lookup_fn=_AddressLookup):
    assert procedure in _TIMEOUTS, ("New RPC call not declared in the"
                                    " timeouts table")
    self.procedure = procedure
    self.body = body
    self.port = port
    self._request = {}
    self._address_lookup_fn = address_lookup_fn

  def ConnectList(self, node_list, address_list=None, read_timeout=None):
    """Add a list of nodes to the target nodes.

    @type node_list: list
    @param node_list: the list of node names to connect
    @type address_list: list or None
    @keyword address_list: either None or a list with node addresses,
        which must have the same length as the node list
    @type read_timeout: int
    @param read_timeout: overwrites default timeout for operation

    """
    if address_list is None:
      # Always use IP address instead of node name
      address_list = self._address_lookup_fn(node_list)

    assert len(node_list) == len(address_list), \
           "Name and address lists must have the same length"

    for node, address in zip(node_list, address_list):
      self.ConnectNode(node, address, read_timeout=read_timeout)

  def ConnectNode(self, name, address=None, read_timeout=None):
    """Add a node to the target list.

    @type name: str
    @param name: the node name
    @type address: str
    @param address: the node address, if known
    @type read_timeout: int
    @param read_timeout: overwrites default timeout for operation

    """
    if address is None:
      # Always use IP address instead of node name
      address = self._address_lookup_fn([name])[0]

    assert(address is not None)

    if read_timeout is None:
      read_timeout = _TIMEOUTS[self.procedure]

    self._request[name] = \
      http.client.HttpClientRequest(str(address), self.port,
                                    http.HTTP_PUT, str("/%s" % self.procedure),
                                    headers=_RPC_CLIENT_HEADERS,
                                    post_data=str(self.body),
                                    read_timeout=read_timeout)

  def GetResults(self, http_pool=None):
    """Call nodes and return results.

    @rtype: list
    @return: List of RPC results

    """
    if not http_pool:
      http_pool = _thread_local.GetHttpClientPool()

    http_pool.ProcessRequests(self._request.values())

    results = {}

    for name, req in self._request.iteritems():
      if req.success and req.resp_status_code == http.HTTP_OK:
        results[name] = RpcResult(data=serializer.LoadJson(req.resp_body),
                                  node=name, call=self.procedure)
        continue

      # TODO: Better error reporting
      if req.error:
        msg = req.error
      else:
        msg = req.resp_body

      logging.error("RPC error in %s from node %s: %s",
                    self.procedure, name, msg)
      results[name] = RpcResult(data=msg, failed=True, node=name,
                                call=self.procedure)

    return results


def _EncodeImportExportIO(ieio, ieioargs):
  """Encodes import/export I/O information.

  """
  if ieio == constants.IEIO_RAW_DISK:
    assert len(ieioargs) == 1
    return (ieioargs[0].ToDict(), )

  if ieio == constants.IEIO_SCRIPT:
    assert len(ieioargs) == 2
    return (ieioargs[0].ToDict(), ieioargs[1])

  return ieioargs


class RpcRunner(object):
  """RPC runner class"""

  def __init__(self, cfg):
    """Initialized the rpc runner.

    @type cfg:  C{config.ConfigWriter}
    @param cfg: the configuration object that will be used to get data
                about the cluster

    """
    self._cfg = cfg
    self.port = netutils.GetDaemonPort(constants.NODED)

  def _InstDict(self, instance, hvp=None, bep=None, osp=None):
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
    for nic in idict["nics"]:
      nic['nicparams'] = objects.FillDict(
        cluster.nicparams[constants.PP_DEFAULT],
        nic['nicparams'])
    return idict

  def _ConnectList(self, client, node_list, call, read_timeout=None):
    """Helper for computing node addresses.

    @type client: L{ganeti.rpc.Client}
    @param client: a C{Client} instance
    @type node_list: list
    @param node_list: the node list we should connect
    @type call: string
    @param call: the name of the remote procedure call, for filling in
        correctly any eventual offline nodes' results
    @type read_timeout: int
    @param read_timeout: overwrites the default read timeout for the
        given operation

    """
    all_nodes = self._cfg.GetAllNodesInfo()
    name_list = []
    addr_list = []
    skip_dict = {}
    for node in node_list:
      if node in all_nodes:
        if all_nodes[node].offline:
          skip_dict[node] = RpcResult(node=node, offline=True, call=call)
          continue
        val = all_nodes[node].primary_ip
      else:
        val = None
      addr_list.append(val)
      name_list.append(node)
    if name_list:
      client.ConnectList(name_list, address_list=addr_list,
                         read_timeout=read_timeout)
    return skip_dict

  def _ConnectNode(self, client, node, call, read_timeout=None):
    """Helper for computing one node's address.

    @type client: L{ganeti.rpc.Client}
    @param client: a C{Client} instance
    @type node: str
    @param node: the node we should connect
    @type call: string
    @param call: the name of the remote procedure call, for filling in
        correctly any eventual offline nodes' results
    @type read_timeout: int
    @param read_timeout: overwrites the default read timeout for the
        given operation

    """
    node_info = self._cfg.GetNodeInfo(node)
    if node_info is not None:
      if node_info.offline:
        return RpcResult(node=node, offline=True, call=call)
      addr = node_info.primary_ip
    else:
      addr = None
    client.ConnectNode(node, address=addr, read_timeout=read_timeout)

  def _MultiNodeCall(self, node_list, procedure, args, read_timeout=None):
    """Helper for making a multi-node call

    """
    body = serializer.DumpJson(args, indent=False)
    c = Client(procedure, body, self.port)
    skip_dict = self._ConnectList(c, node_list, procedure,
                                  read_timeout=read_timeout)
    skip_dict.update(c.GetResults())
    return skip_dict

  @classmethod
  def _StaticMultiNodeCall(cls, node_list, procedure, args,
                           address_list=None, read_timeout=None):
    """Helper for making a multi-node static call

    """
    body = serializer.DumpJson(args, indent=False)
    c = Client(procedure, body, netutils.GetDaemonPort(constants.NODED))
    c.ConnectList(node_list, address_list=address_list,
                  read_timeout=read_timeout)
    return c.GetResults()

  def _SingleNodeCall(self, node, procedure, args, read_timeout=None):
    """Helper for making a single-node call

    """
    body = serializer.DumpJson(args, indent=False)
    c = Client(procedure, body, self.port)
    result = self._ConnectNode(c, node, procedure, read_timeout=read_timeout)
    if result is None:
      # we did connect, node is not offline
      result = c.GetResults()[node]
    return result

  @classmethod
  def _StaticSingleNodeCall(cls, node, procedure, args, read_timeout=None):
    """Helper for making a single-node static call

    """
    body = serializer.DumpJson(args, indent=False)
    c = Client(procedure, body, netutils.GetDaemonPort(constants.NODED))
    c.ConnectNode(node, read_timeout=read_timeout)
    return c.GetResults()[node]

  @staticmethod
  def _Compress(data):
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

  #
  # Begin RPC calls
  #

  @_RpcTimeout(_TMO_URGENT)
  def call_bdev_sizes(self, node_list, devices):
    """Gets the sizes of requested block devices present on a node

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "bdev_sizes", [devices])

  @_RpcTimeout(_TMO_URGENT)
  def call_lv_list(self, node_list, vg_name):
    """Gets the logical volumes present in a given volume group.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "lv_list", [vg_name])

  @_RpcTimeout(_TMO_URGENT)
  def call_vg_list(self, node_list):
    """Gets the volume group list.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "vg_list", [])

  @_RpcTimeout(_TMO_NORMAL)
  def call_storage_list(self, node_list, su_name, su_args, name, fields):
    """Get list of storage units.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "storage_list",
                               [su_name, su_args, name, fields])

  @_RpcTimeout(_TMO_NORMAL)
  def call_storage_modify(self, node, su_name, su_args, name, changes):
    """Modify a storage unit.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "storage_modify",
                                [su_name, su_args, name, changes])

  @_RpcTimeout(_TMO_NORMAL)
  def call_storage_execute(self, node, su_name, su_args, name, op):
    """Executes an operation on a storage unit.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "storage_execute",
                                [su_name, su_args, name, op])

  @_RpcTimeout(_TMO_URGENT)
  def call_bridges_exist(self, node, bridges_list):
    """Checks if a node has all the bridges given.

    This method checks if all bridges given in the bridges_list are
    present on the remote node, so that an instance that uses interfaces
    on those bridges can be started.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "bridges_exist", [bridges_list])

  @_RpcTimeout(_TMO_NORMAL)
  def call_instance_start(self, node, instance, hvp, bep):
    """Starts an instance.

    This is a single-node call.

    """
    idict = self._InstDict(instance, hvp=hvp, bep=bep)
    return self._SingleNodeCall(node, "instance_start", [idict])

  @_RpcTimeout(_TMO_NORMAL)
  def call_instance_shutdown(self, node, instance, timeout):
    """Stops an instance.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "instance_shutdown",
                                [self._InstDict(instance), timeout])

  @_RpcTimeout(_TMO_NORMAL)
  def call_migration_info(self, node, instance):
    """Gather the information necessary to prepare an instance migration.

    This is a single-node call.

    @type node: string
    @param node: the node on which the instance is currently running
    @type instance: C{objects.Instance}
    @param instance: the instance definition

    """
    return self._SingleNodeCall(node, "migration_info",
                                [self._InstDict(instance)])

  @_RpcTimeout(_TMO_NORMAL)
  def call_accept_instance(self, node, instance, info, target):
    """Prepare a node to accept an instance.

    This is a single-node call.

    @type node: string
    @param node: the target node for the migration
    @type instance: C{objects.Instance}
    @param instance: the instance definition
    @type info: opaque/hypervisor specific (string/data)
    @param info: result for the call_migration_info call
    @type target: string
    @param target: target hostname (usually ip address) (on the node itself)

    """
    return self._SingleNodeCall(node, "accept_instance",
                                [self._InstDict(instance), info, target])

  @_RpcTimeout(_TMO_NORMAL)
  def call_finalize_migration(self, node, instance, info, success):
    """Finalize any target-node migration specific operation.

    This is called both in case of a successful migration and in case of error
    (in which case it should abort the migration).

    This is a single-node call.

    @type node: string
    @param node: the target node for the migration
    @type instance: C{objects.Instance}
    @param instance: the instance definition
    @type info: opaque/hypervisor specific (string/data)
    @param info: result for the call_migration_info call
    @type success: boolean
    @param success: whether the migration was a success or a failure

    """
    return self._SingleNodeCall(node, "finalize_migration",
                                [self._InstDict(instance), info, success])

  @_RpcTimeout(_TMO_SLOW)
  def call_instance_migrate(self, node, instance, target, live):
    """Migrate an instance.

    This is a single-node call.

    @type node: string
    @param node: the node on which the instance is currently running
    @type instance: C{objects.Instance}
    @param instance: the instance definition
    @type target: string
    @param target: the target node name
    @type live: boolean
    @param live: whether the migration should be done live or not (the
        interpretation of this parameter is left to the hypervisor)

    """
    return self._SingleNodeCall(node, "instance_migrate",
                                [self._InstDict(instance), target, live])

  @_RpcTimeout(_TMO_NORMAL)
  def call_instance_reboot(self, node, inst, reboot_type, shutdown_timeout):
    """Reboots an instance.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "instance_reboot",
                                [self._InstDict(inst), reboot_type,
                                 shutdown_timeout])

  @_RpcTimeout(_TMO_1DAY)
  def call_instance_os_add(self, node, inst, reinstall, debug, osparams=None):
    """Installs an OS on the given instance.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "instance_os_add",
                                [self._InstDict(inst, osp=osparams),
                                 reinstall, debug])

  @_RpcTimeout(_TMO_SLOW)
  def call_instance_run_rename(self, node, inst, old_name, debug):
    """Run the OS rename script for an instance.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "instance_run_rename",
                                [self._InstDict(inst), old_name, debug])

  @_RpcTimeout(_TMO_URGENT)
  def call_instance_info(self, node, instance, hname):
    """Returns information about a single instance.

    This is a single-node call.

    @type node: list
    @param node: the list of nodes to query
    @type instance: string
    @param instance: the instance name
    @type hname: string
    @param hname: the hypervisor type of the instance

    """
    return self._SingleNodeCall(node, "instance_info", [instance, hname])

  @_RpcTimeout(_TMO_NORMAL)
  def call_instance_migratable(self, node, instance):
    """Checks whether the given instance can be migrated.

    This is a single-node call.

    @param node: the node to query
    @type instance: L{objects.Instance}
    @param instance: the instance to check


    """
    return self._SingleNodeCall(node, "instance_migratable",
                                [self._InstDict(instance)])

  @_RpcTimeout(_TMO_URGENT)
  def call_all_instances_info(self, node_list, hypervisor_list):
    """Returns information about all instances on the given nodes.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type hypervisor_list: list
    @param hypervisor_list: the hypervisors to query for instances

    """
    return self._MultiNodeCall(node_list, "all_instances_info",
                               [hypervisor_list])

  @_RpcTimeout(_TMO_URGENT)
  def call_instance_list(self, node_list, hypervisor_list):
    """Returns the list of running instances on a given node.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type hypervisor_list: list
    @param hypervisor_list: the hypervisors to query for instances

    """
    return self._MultiNodeCall(node_list, "instance_list", [hypervisor_list])

  @_RpcTimeout(_TMO_FAST)
  def call_node_tcp_ping(self, node, source, target, port, timeout,
                         live_port_needed):
    """Do a TcpPing on the remote node

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "node_tcp_ping",
                                [source, target, port, timeout,
                                 live_port_needed])

  @_RpcTimeout(_TMO_FAST)
  def call_node_has_ip_address(self, node, address):
    """Checks if a node has the given IP address.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "node_has_ip_address", [address])

  @_RpcTimeout(_TMO_URGENT)
  def call_node_info(self, node_list, vg_name, hypervisor_type):
    """Return node information.

    This will return memory information and volume group size and free
    space.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type vg_name: C{string}
    @param vg_name: the name of the volume group to ask for disk space
        information
    @type hypervisor_type: C{str}
    @param hypervisor_type: the name of the hypervisor to ask for
        memory information

    """
    return self._MultiNodeCall(node_list, "node_info",
                               [vg_name, hypervisor_type])

  @_RpcTimeout(_TMO_NORMAL)
  def call_etc_hosts_modify(self, node, mode, name, ip):
    """Modify hosts file with name

    @type node: string
    @param node: The node to call
    @type mode: string
    @param mode: The mode to operate. Currently "add" or "remove"
    @type name: string
    @param name: The host name to be modified
    @type ip: string
    @param ip: The ip of the entry (just valid if mode is "add")

    """
    return self._SingleNodeCall(node, "etc_hosts_modify", [mode, name, ip])

  @_RpcTimeout(_TMO_NORMAL)
  def call_node_verify(self, node_list, checkdict, cluster_name):
    """Request verification of given parameters.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "node_verify",
                               [checkdict, cluster_name])

  @classmethod
  @_RpcTimeout(_TMO_FAST)
  def call_node_start_master(cls, node, start_daemons, no_voting):
    """Tells a node to activate itself as a master.

    This is a single-node call.

    """
    return cls._StaticSingleNodeCall(node, "node_start_master",
                                     [start_daemons, no_voting])

  @classmethod
  @_RpcTimeout(_TMO_FAST)
  def call_node_stop_master(cls, node, stop_daemons):
    """Tells a node to demote itself from master status.

    This is a single-node call.

    """
    return cls._StaticSingleNodeCall(node, "node_stop_master", [stop_daemons])

  @classmethod
  @_RpcTimeout(_TMO_URGENT)
  def call_master_info(cls, node_list):
    """Query master info.

    This is a multi-node call.

    """
    # TODO: should this method query down nodes?
    return cls._StaticMultiNodeCall(node_list, "master_info", [])

  @classmethod
  @_RpcTimeout(_TMO_URGENT)
  def call_version(cls, node_list):
    """Query node version.

    This is a multi-node call.

    """
    return cls._StaticMultiNodeCall(node_list, "version", [])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_create(self, node, bdev, size, owner, on_primary, info):
    """Request creation of a given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_create",
                                [bdev.ToDict(), size, owner, on_primary, info])

  @_RpcTimeout(_TMO_SLOW)
  def call_blockdev_wipe(self, node, bdev, offset, size):
    """Request wipe at given offset with given size of a block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_wipe",
                                [bdev.ToDict(), offset, size])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_remove(self, node, bdev):
    """Request removal of a given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_remove", [bdev.ToDict()])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_rename(self, node, devlist):
    """Request rename of the given block devices.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_rename",
                                [(d.ToDict(), uid) for d, uid in devlist])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_pause_resume_sync(self, node, disks, pause):
    """Request a pause/resume of given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_pause_resume_sync",
                                [[bdev.ToDict() for bdev in disks], pause])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_assemble(self, node, disk, owner, on_primary, idx):
    """Request assembling of a given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_assemble",
                                [disk.ToDict(), owner, on_primary, idx])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_shutdown(self, node, disk):
    """Request shutdown of a given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_shutdown", [disk.ToDict()])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_addchildren(self, node, bdev, ndevs):
    """Request adding a list of children to a (mirroring) device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_addchildren",
                                [bdev.ToDict(),
                                 [disk.ToDict() for disk in ndevs]])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_removechildren(self, node, bdev, ndevs):
    """Request removing a list of children from a (mirroring) device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_removechildren",
                                [bdev.ToDict(),
                                 [disk.ToDict() for disk in ndevs]])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_getmirrorstatus(self, node, disks):
    """Request status of a (mirroring) device.

    This is a single-node call.

    """
    result = self._SingleNodeCall(node, "blockdev_getmirrorstatus",
                                  [dsk.ToDict() for dsk in disks])
    if not result.fail_msg:
      result.payload = [objects.BlockDevStatus.FromDict(i)
                        for i in result.payload]
    return result

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_getmirrorstatus_multi(self, node_list, node_disks):
    """Request status of (mirroring) devices from multiple nodes.

    This is a multi-node call.

    """
    result = self._MultiNodeCall(node_list, "blockdev_getmirrorstatus_multi",
                                 [dict((name, [dsk.ToDict() for dsk in disks])
                                       for name, disks in node_disks.items())])
    for nres in result.values():
      if nres.fail_msg:
        continue

      for idx, (success, status) in enumerate(nres.payload):
        if success:
          nres.payload[idx] = (success, objects.BlockDevStatus.FromDict(status))

    return result

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_find(self, node, disk):
    """Request identification of a given block device.

    This is a single-node call.

    """
    result = self._SingleNodeCall(node, "blockdev_find", [disk.ToDict()])
    if not result.fail_msg and result.payload is not None:
      result.payload = objects.BlockDevStatus.FromDict(result.payload)
    return result

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_close(self, node, instance_name, disks):
    """Closes the given block devices.

    This is a single-node call.

    """
    params = [instance_name, [cf.ToDict() for cf in disks]]
    return self._SingleNodeCall(node, "blockdev_close", params)

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_getsize(self, node, disks):
    """Returns the size of the given disks.

    This is a single-node call.

    """
    params = [[cf.ToDict() for cf in disks]]
    return self._SingleNodeCall(node, "blockdev_getsize", params)

  @_RpcTimeout(_TMO_NORMAL)
  def call_drbd_disconnect_net(self, node_list, nodes_ip, disks):
    """Disconnects the network of the given drbd devices.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "drbd_disconnect_net",
                               [nodes_ip, [cf.ToDict() for cf in disks]])

  @_RpcTimeout(_TMO_NORMAL)
  def call_drbd_attach_net(self, node_list, nodes_ip,
                           disks, instance_name, multimaster):
    """Disconnects the given drbd devices.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "drbd_attach_net",
                               [nodes_ip, [cf.ToDict() for cf in disks],
                                instance_name, multimaster])

  @_RpcTimeout(_TMO_SLOW)
  def call_drbd_wait_sync(self, node_list, nodes_ip, disks):
    """Waits for the synchronization of drbd devices is complete.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "drbd_wait_sync",
                               [nodes_ip, [cf.ToDict() for cf in disks]])

  @_RpcTimeout(_TMO_URGENT)
  def call_drbd_helper(self, node_list):
    """Gets drbd helper.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "drbd_helper", [])

  @classmethod
  @_RpcTimeout(_TMO_NORMAL)
  def call_upload_file(cls, node_list, file_name, address_list=None):
    """Upload a file.

    The node will refuse the operation in case the file is not on the
    approved file list.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of node names to upload to
    @type file_name: str
    @param file_name: the filename to upload
    @type address_list: list or None
    @keyword address_list: an optional list of node addresses, in order
        to optimize the RPC speed

    """
    file_contents = utils.ReadFile(file_name)
    data = cls._Compress(file_contents)
    st = os.stat(file_name)
    getents = runtime.GetEnts()
    params = [file_name, data, st.st_mode, getents.LookupUid(st.st_uid),
              getents.LookupGid(st.st_gid), st.st_atime, st.st_mtime]
    return cls._StaticMultiNodeCall(node_list, "upload_file", params,
                                    address_list=address_list)

  @classmethod
  @_RpcTimeout(_TMO_NORMAL)
  def call_write_ssconf_files(cls, node_list, values):
    """Write ssconf files.

    This is a multi-node call.

    """
    return cls._StaticMultiNodeCall(node_list, "write_ssconf_files", [values])

  @_RpcTimeout(_TMO_NORMAL)
  def call_run_oob(self, node, oob_program, command, remote_node, timeout):
    """Runs OOB.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "run_oob", [oob_program, command,
                                                  remote_node, timeout])

  @_RpcTimeout(_TMO_FAST)
  def call_os_diagnose(self, node_list):
    """Request a diagnose of OS definitions.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "os_diagnose", [])

  @_RpcTimeout(_TMO_FAST)
  def call_os_get(self, node, name):
    """Returns an OS definition.

    This is a single-node call.

    """
    result = self._SingleNodeCall(node, "os_get", [name])
    if not result.fail_msg and isinstance(result.payload, dict):
      result.payload = objects.OS.FromDict(result.payload)
    return result

  @_RpcTimeout(_TMO_FAST)
  def call_os_validate(self, required, nodes, name, checks, params):
    """Run a validation routine for a given OS.

    This is a multi-node call.

    """
    return self._MultiNodeCall(nodes, "os_validate",
                               [required, name, checks, params])

  @_RpcTimeout(_TMO_NORMAL)
  def call_hooks_runner(self, node_list, hpath, phase, env):
    """Call the hooks runner.

    Args:
      - op: the OpCode instance
      - env: a dictionary with the environment

    This is a multi-node call.

    """
    params = [hpath, phase, env]
    return self._MultiNodeCall(node_list, "hooks_runner", params)

  @_RpcTimeout(_TMO_NORMAL)
  def call_iallocator_runner(self, node, name, idata):
    """Call an iallocator on a remote node

    Args:
      - name: the iallocator name
      - input: the json-encoded input string

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "iallocator_runner", [name, idata])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_grow(self, node, cf_bdev, amount, dryrun):
    """Request a snapshot of the given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_grow",
                                [cf_bdev.ToDict(), amount, dryrun])

  @_RpcTimeout(_TMO_1DAY)
  def call_blockdev_export(self, node, cf_bdev,
                           dest_node, dest_path, cluster_name):
    """Export a given disk to another node.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_export",
                                [cf_bdev.ToDict(), dest_node, dest_path,
                                 cluster_name])

  @_RpcTimeout(_TMO_NORMAL)
  def call_blockdev_snapshot(self, node, cf_bdev):
    """Request a snapshot of the given block device.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "blockdev_snapshot", [cf_bdev.ToDict()])

  @_RpcTimeout(_TMO_NORMAL)
  def call_finalize_export(self, node, instance, snap_disks):
    """Request the completion of an export operation.

    This writes the export config file, etc.

    This is a single-node call.

    """
    flat_disks = []
    for disk in snap_disks:
      if isinstance(disk, bool):
        flat_disks.append(disk)
      else:
        flat_disks.append(disk.ToDict())

    return self._SingleNodeCall(node, "finalize_export",
                                [self._InstDict(instance), flat_disks])

  @_RpcTimeout(_TMO_FAST)
  def call_export_info(self, node, path):
    """Queries the export information in a given path.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "export_info", [path])

  @_RpcTimeout(_TMO_FAST)
  def call_export_list(self, node_list):
    """Gets the stored exports list.

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "export_list", [])

  @_RpcTimeout(_TMO_FAST)
  def call_export_remove(self, node, export):
    """Requests removal of a given export.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "export_remove", [export])

  @classmethod
  @_RpcTimeout(_TMO_NORMAL)
  def call_node_leave_cluster(cls, node, modify_ssh_setup):
    """Requests a node to clean the cluster information it has.

    This will remove the configuration information from the ganeti data
    dir.

    This is a single-node call.

    """
    return cls._StaticSingleNodeCall(node, "node_leave_cluster",
                                     [modify_ssh_setup])

  @_RpcTimeout(_TMO_FAST)
  def call_node_volumes(self, node_list):
    """Gets all volumes on node(s).

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "node_volumes", [])

  @_RpcTimeout(_TMO_FAST)
  def call_node_demote_from_mc(self, node):
    """Demote a node from the master candidate role.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "node_demote_from_mc", [])

  @_RpcTimeout(_TMO_NORMAL)
  def call_node_powercycle(self, node, hypervisor):
    """Tries to powercycle a node.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "node_powercycle", [hypervisor])

  @_RpcTimeout(None)
  def call_test_delay(self, node_list, duration):
    """Sleep for a fixed time on given node(s).

    This is a multi-node call.

    """
    return self._MultiNodeCall(node_list, "test_delay", [duration],
                               read_timeout=int(duration + 5))

  @_RpcTimeout(_TMO_FAST)
  def call_file_storage_dir_create(self, node, file_storage_dir):
    """Create the given file storage directory.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "file_storage_dir_create",
                                [file_storage_dir])

  @_RpcTimeout(_TMO_FAST)
  def call_file_storage_dir_remove(self, node, file_storage_dir):
    """Remove the given file storage directory.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "file_storage_dir_remove",
                                [file_storage_dir])

  @_RpcTimeout(_TMO_FAST)
  def call_file_storage_dir_rename(self, node, old_file_storage_dir,
                                   new_file_storage_dir):
    """Rename file storage directory.

    This is a single-node call.

    """
    return self._SingleNodeCall(node, "file_storage_dir_rename",
                                [old_file_storage_dir, new_file_storage_dir])

  @classmethod
  @_RpcTimeout(_TMO_URGENT)
  def call_jobqueue_update(cls, node_list, address_list, file_name, content):
    """Update job queue.

    This is a multi-node call.

    """
    return cls._StaticMultiNodeCall(node_list, "jobqueue_update",
                                    [file_name, cls._Compress(content)],
                                    address_list=address_list)

  @classmethod
  @_RpcTimeout(_TMO_NORMAL)
  def call_jobqueue_purge(cls, node):
    """Purge job queue.

    This is a single-node call.

    """
    return cls._StaticSingleNodeCall(node, "jobqueue_purge", [])

  @classmethod
  @_RpcTimeout(_TMO_URGENT)
  def call_jobqueue_rename(cls, node_list, address_list, rename):
    """Rename a job queue file.

    This is a multi-node call.

    """
    return cls._StaticMultiNodeCall(node_list, "jobqueue_rename", rename,
                                    address_list=address_list)

  @_RpcTimeout(_TMO_NORMAL)
  def call_hypervisor_validate_params(self, node_list, hvname, hvparams):
    """Validate the hypervisor params.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type hvname: string
    @param hvname: the hypervisor name
    @type hvparams: dict
    @param hvparams: the hypervisor parameters to be validated

    """
    cluster = self._cfg.GetClusterInfo()
    hv_full = objects.FillDict(cluster.hvparams.get(hvname, {}), hvparams)
    return self._MultiNodeCall(node_list, "hypervisor_validate_params",
                               [hvname, hv_full])

  @_RpcTimeout(_TMO_NORMAL)
  def call_x509_cert_create(self, node, validity):
    """Creates a new X509 certificate for SSL/TLS.

    This is a single-node call.

    @type validity: int
    @param validity: Validity in seconds

    """
    return self._SingleNodeCall(node, "x509_cert_create", [validity])

  @_RpcTimeout(_TMO_NORMAL)
  def call_x509_cert_remove(self, node, name):
    """Removes a X509 certificate.

    This is a single-node call.

    @type name: string
    @param name: Certificate name

    """
    return self._SingleNodeCall(node, "x509_cert_remove", [name])

  @_RpcTimeout(_TMO_NORMAL)
  def call_import_start(self, node, opts, instance, dest, dest_args):
    """Starts a listener for an import.

    This is a single-node call.

    @type node: string
    @param node: Node name
    @type instance: C{objects.Instance}
    @param instance: Instance object

    """
    return self._SingleNodeCall(node, "import_start",
                                [opts.ToDict(),
                                 self._InstDict(instance), dest,
                                 _EncodeImportExportIO(dest, dest_args)])

  @_RpcTimeout(_TMO_NORMAL)
  def call_export_start(self, node, opts, host, port,
                        instance, source, source_args):
    """Starts an export daemon.

    This is a single-node call.

    @type node: string
    @param node: Node name
    @type instance: C{objects.Instance}
    @param instance: Instance object

    """
    return self._SingleNodeCall(node, "export_start",
                                [opts.ToDict(), host, port,
                                 self._InstDict(instance), source,
                                 _EncodeImportExportIO(source, source_args)])

  @_RpcTimeout(_TMO_FAST)
  def call_impexp_status(self, node, names):
    """Gets the status of an import or export.

    This is a single-node call.

    @type node: string
    @param node: Node name
    @type names: List of strings
    @param names: Import/export names
    @rtype: List of L{objects.ImportExportStatus} instances
    @return: Returns a list of the state of each named import/export or None if
             a status couldn't be retrieved

    """
    result = self._SingleNodeCall(node, "impexp_status", [names])

    if not result.fail_msg:
      decoded = []

      for i in result.payload:
        if i is None:
          decoded.append(None)
          continue
        decoded.append(objects.ImportExportStatus.FromDict(i))

      result.payload = decoded

    return result

  @_RpcTimeout(_TMO_NORMAL)
  def call_impexp_abort(self, node, name):
    """Aborts an import or export.

    This is a single-node call.

    @type node: string
    @param node: Node name
    @type name: string
    @param name: Import/export name

    """
    return self._SingleNodeCall(node, "impexp_abort", [name])

  @_RpcTimeout(_TMO_NORMAL)
  def call_impexp_cleanup(self, node, name):
    """Cleans up after an import or export.

    This is a single-node call.

    @type node: string
    @param node: Node name
    @type name: string
    @param name: Import/export name

    """
    return self._SingleNodeCall(node, "impexp_cleanup", [name])
