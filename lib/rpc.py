#
#

# Copyright (C) 2006, 2007 Google Inc.
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
import socket
import httplib
import logging

from ganeti import utils
from ganeti import objects
from ganeti import http
from ganeti import serializer


class Client:
  """RPC Client class.

  This class, given a (remote) method name, a list of parameters and a
  list of nodes, will contact (in parallel) all nodes, and return a
  dict of results (key: node name, value: result).

  One current bug is that generic failure is still signalled by
  'False' result, which is not good. This overloading of values can
  cause bugs.

  """
  def __init__(self, procedure, args):
    self.procedure = procedure
    self.args = args
    self.body = serializer.DumpJson(args, indent=False)

    self.port = utils.GetNodeDaemonPort()
    self.nodepw = utils.GetNodeDaemonPassword()
    self.nc = {}

  def ConnectList(self, node_list, address_list=None):
    """Add a list of nodes to the target nodes.

    @type node_list: list
    @param node_list: the list of node names to connect
    @type address_list: list or None
    @keyword address_list: either None or a list with node addresses,
        which must have the same length as the node list

    """
    if address_list is None:
      address_list = [None for _ in node_list]
    else:
      assert len(node_list) == len(address_list), \
             "Name and address lists should have the same length"
    for node, address in zip(node_list, address_list):
      self.ConnectNode(node, address)

  def ConnectNode(self, name, address=None):
    """Add a node to the target list.

    @type name: str
    @param name: the node name
    @type address: str
    @keyword address: the node address, if known

    """
    if address is None:
      address = name

    self.nc[name] = http.HttpClientRequest(address, self.port, http.HTTP_PUT,
                                           "/%s" % self.procedure,
                                           post_data=self.body)

  def GetResults(self):
    """Call nodes and return results.

    @rtype: list
    @returns: List of RPC results

    """
    # TODO: Shared and reused manager
    mgr = http.HttpClientManager()
    try:
      mgr.ExecRequests(self.nc.values())
    finally:
      mgr.Shutdown()

    results = {}

    for name, req in self.nc.iteritems():
      if req.success and req.resp_status == http.HTTP_OK:
        results[name] = serializer.LoadJson(req.resp_body)
        continue

      if req.error:
        msg = req.error
      else:
        msg = req.resp_body

      logging.error("RPC error from node %s: %s", name, msg)
      results[name] = False

    return results


class RpcRunner(object):
  """RPC runner class"""

  def __init__(self, cfg):
    """Initialized the rpc runner.

    @type cfg:  C{config.ConfigWriter}
    @param cfg: the configuration object that will be used to get data
                about the cluster

    """
    self._cfg = cfg

  def _InstDict(self, instance):
    """Convert the given instance to a dict.

    This is done via the instance's ToDict() method and additionally
    we fill the hvparams with the cluster defaults.

    @type instance: L{objects.Instance}
    @param instance: an Instance object
    @rtype: dict
    @return: the instance dict, with the hvparams filled with the
        cluster defaults

    """
    idict = instance.ToDict()
    cluster = self._cfg.GetClusterInfo()
    idict["hvparams"] = cluster.FillHV(instance)
    idict["beparams"] = cluster.FillBE(instance)
    return idict

  def _ConnectList(self, client, node_list):
    """Helper for computing node addresses.

    @type client: L{Client}
    @param client: a C{Client} instance
    @type node_list: list
    @param node_list: the node list we should connect

    """
    all_nodes = self._cfg.GetAllNodesInfo()
    addr_list = []
    for node in node_list:
      if node in all_nodes:
        val = all_nodes[node].primary_ip
      else:
        val = None
      addr_list.append(val)
    client.ConnectList(node_list, address_list=addr_list)

  def _ConnectNode(self, client, node):
    """Helper for computing one node's address.

    @type client: L{Client}
    @param client: a C{Client} instance
    @type node: str
    @param node: the node we should connect

    """
    node_info = self._cfg.GetNodeInfo(node)
    if node_info is not None:
      addr = node_info.primary_ip
    else:
      addr = None
    client.ConnectNode(node, address=addr)

  def call_volume_list(self, node_list, vg_name):
    """Gets the logical volumes present in a given volume group.

    This is a multi-node call.

    """
    c = Client("volume_list", [vg_name])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_vg_list(self, node_list):
    """Gets the volume group list.

    This is a multi-node call.

    """
    c = Client("vg_list", [])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_bridges_exist(self, node, bridges_list):
    """Checks if a node has all the bridges given.

    This method checks if all bridges given in the bridges_list are
    present on the remote node, so that an instance that uses interfaces
    on those bridges can be started.

    This is a single-node call.

    """
    c = Client("bridges_exist", [bridges_list])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_instance_start(self, node, instance, extra_args):
    """Starts an instance.

    This is a single-node call.

    """
    c = Client("instance_start", [self._InstDict(instance), extra_args])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_instance_shutdown(self, node, instance):
    """Stops an instance.

    This is a single-node call.

    """
    c = Client("instance_shutdown", [self._InstDict(instance)])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

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
    c = Client("instance_migrate", [self._InstDict(instance), target, live])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_instance_reboot(self, node, instance, reboot_type, extra_args):
    """Reboots an instance.

    This is a single-node call.

    """
    c = Client("instance_reboot", [self._InstDict(instance),
                                   reboot_type, extra_args])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_instance_os_add(self, node, inst):
    """Installs an OS on the given instance.

    This is a single-node call.

    """
    params = [self._InstDict(inst)]
    c = Client("instance_os_add", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_instance_run_rename(self, node, inst, old_name):
    """Run the OS rename script for an instance.

    This is a single-node call.

    """
    params = [self._InstDict(inst), old_name]
    c = Client("instance_run_rename", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_instance_info(self, node, instance, hname):
    """Returns information about a single instance.

    This is a single-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type instance: string
    @param instance: the instance name
    @type hname: string
    @param hname: the hypervisor type of the instance

    """
    c = Client("instance_info", [instance, hname])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_all_instances_info(self, node_list, hypervisor_list):
    """Returns information about all instances on the given nodes.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type hypervisor_list: list
    @param hypervisor_list: the hypervisors to query for instances

    """
    c = Client("all_instances_info", [hypervisor_list])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_instance_list(self, node_list, hypervisor_list):
    """Returns the list of running instances on a given node.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type hypervisor_list: list
    @param hypervisor_list: the hypervisors to query for instances

    """
    c = Client("instance_list", [hypervisor_list])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_node_tcp_ping(self, node, source, target, port, timeout,
                         live_port_needed):
    """Do a TcpPing on the remote node

    This is a single-node call.

    """
    c = Client("node_tcp_ping", [source, target, port, timeout,
                                 live_port_needed])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_node_has_ip_address(self, node, address):
    """Checks if a node has the given IP address.

    This is a single-node call.

    """
    c = Client("node_has_ip_address", [address])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_node_info(self, node_list, vg_name, hypervisor_type):
    """Return node information.

    This will return memory information and volume group size and free
    space.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type vgname: C{string}
    @param vgname: the name of the volume group to ask for disk space
        information
    @type hypervisor_type: C{str}
    @param hypervisor_type: the name of the hypervisor to ask for
        memory information

    """
    c = Client("node_info", [vg_name, hypervisor_type])
    self._ConnectList(c, node_list)
    retux = c.GetResults()

    for node_name in retux:
      ret = retux.get(node_name, False)
      if type(ret) != dict:
        logging.error("could not connect to node %s", node_name)
        ret = {}

      utils.CheckDict(ret,
                      { 'memory_total' : '-',
                        'memory_dom0' : '-',
                        'memory_free' : '-',
                        'vg_size' : 'node_unreachable',
                        'vg_free' : '-' },
                      "call_node_info",
                      )
    return retux

  def call_node_add(self, node, dsa, dsapub, rsa, rsapub, ssh, sshpub):
    """Add a node to the cluster.

    This is a single-node call.

    """
    params = [dsa, dsapub, rsa, rsapub, ssh, sshpub]
    c = Client("node_add", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_node_verify(self, node_list, checkdict, cluster_name):
    """Request verification of given parameters.

    This is a multi-node call.

    """
    c = Client("node_verify", [checkdict, cluster_name])
    self._ConnectList(c, node_list)
    return c.GetResults()

  @staticmethod
  def call_node_start_master(node, start_daemons):
    """Tells a node to activate itself as a master.

    This is a single-node call.

    """
    c = Client("node_start_master", [start_daemons])
    c.ConnectNode(node)
    return c.GetResults().get(node, False)

  @staticmethod
  def call_node_stop_master(node, stop_daemons):
    """Tells a node to demote itself from master status.

    This is a single-node call.

    """
    c = Client("node_stop_master", [stop_daemons])
    c.ConnectNode(node)
    return c.GetResults().get(node, False)

  @staticmethod
  def call_master_info(node_list):
    """Query master info.

    This is a multi-node call.

    """
    # TODO: should this method query down nodes?
    c = Client("master_info", [])
    c.ConnectList(node_list)
    return c.GetResults()

  def call_version(self, node_list):
    """Query node version.

    This is a multi-node call.

    """
    c = Client("version", [])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_blockdev_create(self, node, bdev, size, owner, on_primary, info):
    """Request creation of a given block device.

    This is a single-node call.

    """
    params = [bdev.ToDict(), size, owner, on_primary, info]
    c = Client("blockdev_create", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_remove(self, node, bdev):
    """Request removal of a given block device.

    This is a single-node call.

    """
    c = Client("blockdev_remove", [bdev.ToDict()])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_rename(self, node, devlist):
    """Request rename of the given block devices.

    This is a single-node call.

    """
    params = [(d.ToDict(), uid) for d, uid in devlist]
    c = Client("blockdev_rename", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_assemble(self, node, disk, owner, on_primary):
    """Request assembling of a given block device.

    This is a single-node call.

    """
    params = [disk.ToDict(), owner, on_primary]
    c = Client("blockdev_assemble", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_shutdown(self, node, disk):
    """Request shutdown of a given block device.

    This is a single-node call.

    """
    c = Client("blockdev_shutdown", [disk.ToDict()])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_addchildren(self, node, bdev, ndevs):
    """Request adding a list of children to a (mirroring) device.

    This is a single-node call.

    """
    params = [bdev.ToDict(), [disk.ToDict() for disk in ndevs]]
    c = Client("blockdev_addchildren", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_removechildren(self, node, bdev, ndevs):
    """Request removing a list of children from a (mirroring) device.

    This is a single-node call.

    """
    params = [bdev.ToDict(), [disk.ToDict() for disk in ndevs]]
    c = Client("blockdev_removechildren", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_getmirrorstatus(self, node, disks):
    """Request status of a (mirroring) device.

    This is a single-node call.

    """
    params = [dsk.ToDict() for dsk in disks]
    c = Client("blockdev_getmirrorstatus", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_find(self, node, disk):
    """Request identification of a given block device.

    This is a single-node call.

    """
    c = Client("blockdev_find", [disk.ToDict()])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_close(self, node, disks):
    """Closes the given block devices.

    This is a single-node call.

    """
    params = [cf.ToDict() for cf in disks]
    c = Client("blockdev_close", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  @staticmethod
  def call_upload_file(node_list, file_name, address_list=None):
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
    fh = file(file_name)
    try:
      data = fh.read()
    finally:
      fh.close()
    st = os.stat(file_name)
    params = [file_name, data, st.st_mode, st.st_uid, st.st_gid,
              st.st_atime, st.st_mtime]
    c = Client("upload_file", params)
    c.ConnectList(node_list, address_list=address_list)
    return c.GetResults()

  def call_os_diagnose(self, node_list):
    """Request a diagnose of OS definitions.

    This is a multi-node call.

    """
    c = Client("os_diagnose", [])
    self._ConnectList(c, node_list)
    result = c.GetResults()
    new_result = {}
    for node_name in result:
      if result[node_name]:
        nr = [objects.OS.FromDict(oss) for oss in result[node_name]]
      else:
        nr = []
      new_result[node_name] = nr
    return new_result

  def call_os_get(self, node, name):
    """Returns an OS definition.

    This is a single-node call.

    """
    c = Client("os_get", [name])
    self._ConnectNode(c, node)
    result = c.GetResults().get(node, False)
    if isinstance(result, dict):
      return objects.OS.FromDict(result)
    else:
      return result

  def call_hooks_runner(self, node_list, hpath, phase, env):
    """Call the hooks runner.

    Args:
      - op: the OpCode instance
      - env: a dictionary with the environment

    This is a multi-node call.

    """
    params = [hpath, phase, env]
    c = Client("hooks_runner", params)
    self._ConnectList(c, node_list)
    result = c.GetResults()
    return result

  def call_iallocator_runner(self, node, name, idata):
    """Call an iallocator on a remote node

    Args:
      - name: the iallocator name
      - input: the json-encoded input string

    This is a single-node call.

    """
    params = [name, idata]
    c = Client("iallocator_runner", params)
    self._ConnectNode(c, node)
    result = c.GetResults().get(node, False)
    return result

  def call_blockdev_grow(self, node, cf_bdev, amount):
    """Request a snapshot of the given block device.

    This is a single-node call.

    """
    c = Client("blockdev_grow", [cf_bdev.ToDict(), amount])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_blockdev_snapshot(self, node, cf_bdev):
    """Request a snapshot of the given block device.

    This is a single-node call.

    """
    c = Client("blockdev_snapshot", [cf_bdev.ToDict()])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_snapshot_export(self, node, snap_bdev, dest_node, instance,
                           cluster_name, idx):
    """Request the export of a given snapshot.

    This is a single-node call.

    """
    params = [snap_bdev.ToDict(), dest_node,
              self._InstDict(instance), cluster_name, idx]
    c = Client("snapshot_export", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_finalize_export(self, node, instance, snap_disks):
    """Request the completion of an export operation.

    This writes the export config file, etc.

    This is a single-node call.

    """
    flat_disks = []
    for disk in snap_disks:
      flat_disks.append(disk.ToDict())
    params = [self._InstDict(instance), flat_disks]
    c = Client("finalize_export", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_export_info(self, node, path):
    """Queries the export information in a given path.

    This is a single-node call.

    """
    c = Client("export_info", [path])
    self._ConnectNode(c, node)
    result = c.GetResults().get(node, False)
    if not result:
      return result
    return objects.SerializableConfigParser.Loads(str(result))

  def call_instance_os_import(self, node, inst, src_node, src_images,
                              cluster_name):
    """Request the import of a backup into an instance.

    This is a single-node call.

    """
    params = [self._InstDict(inst), src_node, src_images, cluster_name]
    c = Client("instance_os_import", params)
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_export_list(self, node_list):
    """Gets the stored exports list.

    This is a multi-node call.

    """
    c = Client("export_list", [])
    self._ConnectList(c, node_list)
    result = c.GetResults()
    return result

  def call_export_remove(self, node, export):
    """Requests removal of a given export.

    This is a single-node call.

    """
    c = Client("export_remove", [export])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  @staticmethod
  def call_node_leave_cluster(node):
    """Requests a node to clean the cluster information it has.

    This will remove the configuration information from the ganeti data
    dir.

    This is a single-node call.

    """
    c = Client("node_leave_cluster", [])
    c.ConnectNode(node)
    return c.GetResults().get(node, False)

  def call_node_volumes(self, node_list):
    """Gets all volumes on node(s).

    This is a multi-node call.

    """
    c = Client("node_volumes", [])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_test_delay(self, node_list, duration):
    """Sleep for a fixed time on given node(s).

    This is a multi-node call.

    """
    c = Client("test_delay", [duration])
    self._ConnectList(c, node_list)
    return c.GetResults()

  def call_file_storage_dir_create(self, node, file_storage_dir):
    """Create the given file storage directory.

    This is a single-node call.

    """
    c = Client("file_storage_dir_create", [file_storage_dir])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_file_storage_dir_remove(self, node, file_storage_dir):
    """Remove the given file storage directory.

    This is a single-node call.

    """
    c = Client("file_storage_dir_remove", [file_storage_dir])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  def call_file_storage_dir_rename(self, node, old_file_storage_dir,
                                   new_file_storage_dir):
    """Rename file storage directory.

    This is a single-node call.

    """
    c = Client("file_storage_dir_rename",
               [old_file_storage_dir, new_file_storage_dir])
    self._ConnectNode(c, node)
    return c.GetResults().get(node, False)

  @staticmethod
  def call_jobqueue_update(node_list, address_list, file_name, content):
    """Update job queue.

    This is a multi-node call.

    """
    c = Client("jobqueue_update", [file_name, content])
    c.ConnectList(node_list, address_list=address_list)
    result = c.GetResults()
    return result

  @staticmethod
  def call_jobqueue_purge(node):
    """Purge job queue.

    This is a single-node call.

    """
    c = Client("jobqueue_purge", [])
    c.ConnectNode(node)
    return c.GetResults().get(node, False)

  @staticmethod
  def call_jobqueue_rename(node_list, address_list, old, new):
    """Rename a job queue file.

    This is a multi-node call.

    """
    c = Client("jobqueue_rename", [old, new])
    c.ConnectList(node_list, address_list=address_list)
    result = c.GetResults()
    return result


  @staticmethod
  def call_jobqueue_set_drain(node_list, drain_flag):
    """Set the drain flag on the queue.

    This is a multi-node call.

    @type node_list: list
    @param node_list: the list of nodes to query
    @type drain_flag: bool
    @param drain_flag: if True, will set the drain flag, otherwise reset it.

    """
    c = Client("jobqueue_set_drain", [drain_flag])
    c.ConnectList(node_list)
    result = c.GetResults()
    return result


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
    hv_full = cluster.FillDict(cluster.hvparams.get(hvname, {}), hvparams)
    c = Client("hypervisor_validate_params", [hvname, hv_full])
    self._ConnectList(c, node_list)
    result = c.GetResults()
    return result
