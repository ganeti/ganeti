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


"""Script to show add a new node to the cluster

"""

# pylint: disable-msg=C0103

import os

from twisted.internet.pollreactor import PollReactor

class ReReactor(PollReactor):
  """A re-startable Reactor implementation.

  """
  def run(self, installSignalHandlers=1):
    """Custom run method.

    This is customized run that, before calling Reactor.run, will
    reinstall the shutdown events and re-create the threadpool in case
    these are not present (as will happen on the second run of the
    reactor).

    """
    if not 'shutdown' in self._eventTriggers:
      # the shutdown queue has been killed, we are most probably
      # at the second run, thus recreate the queue
      self.addSystemEventTrigger('during', 'shutdown', self.crash)
      self.addSystemEventTrigger('during', 'shutdown', self.disconnectAll)
    if self.threadpool is not None and self.threadpool.joined == 1:
      # in case the threadpool has been stopped, re-start it
      # and add a trigger to stop it at reactor shutdown
      self.threadpool.start()
      self.addSystemEventTrigger('during', 'shutdown', self.threadpool.stop)

    return PollReactor.run(self, installSignalHandlers)


import twisted.internet.main
twisted.internet.main.installReactor(ReReactor())

from twisted.spread import pb
from twisted.internet import reactor
from twisted.cred import credentials
from OpenSSL import SSL, crypto

from ganeti import logger
from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import objects
from ganeti import ssconf

class NodeController:
  """Node-handling class.

  For each node that we speak with, we create an instance of this
  class, so that we have a safe place to store the details of this
  individual call.

  """
  def __init__(self, parent, node):
    self.parent = parent
    self.node = node

  def _check_end(self):
    """Stop the reactor if we got all the results.

    """
    if len(self.parent.results) == len(self.parent.nc):
      reactor.stop()

  def cb_call(self, obj):
    """Callback for successful connect.

    If the connect and login sequence succeeded, we proceed with
    making the actual call.

    """
    deferred = obj.callRemote(self.parent.procedure, self.parent.args)
    deferred.addCallbacks(self.cb_done, self.cb_err2)

  def cb_done(self, result):
    """Callback for successful call.

    When we receive the result from a call, we check if it was an
    error and if so we raise a generic RemoteError (we can't pass yet
    the actual exception over). If there was no error, we store the
    result.

    """
    tb, self.parent.results[self.node] = result
    self._check_end()
    if tb:
      raise errors.RemoteError("Remote procedure error calling %s on %s:"
                               "\n%s" % (self.parent.procedure,
                                         self.node,
                                         tb))

  def cb_err1(self, reason):
    """Error callback for unsuccessful connect.

    """
    logger.Error("caller_connect: could not connect to remote host %s,"
                 " reason %s" % (self.node, reason))
    self.parent.results[self.node] = False
    self._check_end()

  def cb_err2(self, reason):
    """Error callback for unsuccessful call.

    This is when the call didn't return anything, not even an error,
    or when it time out, etc.

    """
    logger.Error("caller_call: could not call %s on node %s,"
                 " reason %s" % (self.parent.procedure, self.node, reason))
    self.parent.results[self.node] = False
    self._check_end()


class MirrorContextFactory:
  """Certificate verifier factory.

  This factory creates contexts that verify if the remote end has a
  specific certificate (i.e. our own certificate).

  The checks we do are that the PEM dump of the certificate is the
  same as our own and (somewhat redundantly) that the SHA checksum is
  the same.

  """
  isClient = 1

  def __init__(self):
    try:
      fd = open(constants.SSL_CERT_FILE, 'r')
      try:
        data = fd.read(16384)
      finally:
        fd.close()
    except EnvironmentError, err:
      raise errors.ConfigurationError("missing SSL certificate: %s" %
                                      str(err))
    self.mycert = crypto.load_certificate(crypto.FILETYPE_PEM, data)
    self.mypem = crypto.dump_certificate(crypto.FILETYPE_PEM, self.mycert)
    self.mydigest = self.mycert.digest('SHA')

  def verifier(self, conn, x509, errno, err_depth, retcode):
    """Certificate verify method.

    """
    if self.mydigest != x509.digest('SHA'):
      return False
    if crypto.dump_certificate(crypto.FILETYPE_PEM, x509) != self.mypem:
      return False
    return True

  def getContext(self):
    """Context generator.

    """
    context = SSL.Context(SSL.TLSv1_METHOD)
    context.set_verify(SSL.VERIFY_PEER, self.verifier)
    return context

class Client:
  """RPC Client class.

  This class, given a (remote) method name, a list of parameters and a
  list of nodes, will contact (in parallel) all nodes, and return a
  dict of results (key: node name, value: result).

  One current bug is that generic failure is still signalled by
  'False' result, which is not good. This overloading of values can
  cause bugs.

  """
  result_set = False
  result = False
  allresult = []

  def __init__(self, procedure, args):
    ss = ssconf.SimpleStore()
    self.port = ss.GetNodeDaemonPort()
    self.nodepw = ss.GetNodeDaemonPassword()
    self.nc = {}
    self.results = {}
    self.procedure = procedure
    self.args = args

  #--- generic connector -------------

  def connect_list(self, node_list):
    """Add a list of nodes to the target nodes.

    """
    for node in node_list:
      self.connect(node)

  def connect(self, connect_node):
    """Add a node to the target list.

    """
    factory = pb.PBClientFactory()
    self.nc[connect_node] = nc = NodeController(self, connect_node)
    reactor.connectSSL(connect_node, self.port, factory,
                       MirrorContextFactory())
    #d = factory.getRootObject()
    d = factory.login(credentials.UsernamePassword("master_node", self.nodepw))
    d.addCallbacks(nc.cb_call, nc.cb_err1)

  def getresult(self):
    """Return the results of the call.

    """
    return self.results

  def run(self):
    """Wrapper over reactor.run().

    This function simply calls reactor.run() if we have any requests
    queued, otherwise it does nothing.

    """
    if self.nc:
      reactor.run()


def call_volume_list(node_list, vg_name):
  """Gets the logical volumes present in a given volume group.

  This is a multi-node call.

  """
  c = Client("volume_list", [vg_name])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_vg_list(node_list):
  """Gets the volume group list.

  This is a multi-node call.

  """
  c = Client("vg_list", [])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_bridges_exist(node, bridges_list):
  """Checks if a node has all the bridges given.

  This method checks if all bridges given in the bridges_list are
  present on the remote node, so that an instance that uses interfaces
  on those bridges can be started.

  This is a single-node call.

  """
  c = Client("bridges_exist", [bridges_list])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_instance_start(node, instance, extra_args):
  """Starts an instance.

  This is a single-node call.

  """
  c = Client("instance_start", [instance.ToDict(), extra_args])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_instance_shutdown(node, instance):
  """Stops an instance.

  This is a single-node call.

  """
  c = Client("instance_shutdown", [instance.ToDict()])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_instance_reboot(node, instance, reboot_type, extra_args):
  """Reboots an instance.

  This is a single-node call.

  """
  c = Client("instance_reboot", [instance.ToDict(), reboot_type, extra_args])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_instance_os_add(node, inst, osdev, swapdev):
  """Installs an OS on the given instance.

  This is a single-node call.

  """
  params = [inst.ToDict(), osdev, swapdev]
  c = Client("instance_os_add", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_instance_run_rename(node, inst, old_name, osdev, swapdev):
  """Run the OS rename script for an instance.

  This is a single-node call.

  """
  params = [inst.ToDict(), old_name, osdev, swapdev]
  c = Client("instance_run_rename", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_instance_info(node, instance):
  """Returns information about a single instance.

  This is a single-node call.

  """
  c = Client("instance_info", [instance])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_all_instances_info(node_list):
  """Returns information about all instances on a given node.

  This is a single-node call.

  """
  c = Client("all_instances_info", [])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_instance_list(node_list):
  """Returns the list of running instances on a given node.

  This is a single-node call.

  """
  c = Client("instance_list", [])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_node_tcp_ping(node, source, target, port, timeout, live_port_needed):
  """Do a TcpPing on the remote node

  This is a single-node call.
  """
  c = Client("node_tcp_ping", [source, target, port, timeout,
                               live_port_needed])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_node_info(node_list, vg_name):
  """Return node information.

  This will return memory information and volume group size and free
  space.

  This is a multi-node call.

  """
  c = Client("node_info", [vg_name])
  c.connect_list(node_list)
  c.run()
  retux = c.getresult()

  for node_name in retux:
    ret = retux.get(node_name, False)
    if type(ret) != dict:
      logger.Error("could not connect to node %s" % (node_name))
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


def call_node_add(node, dsa, dsapub, rsa, rsapub, ssh, sshpub):
  """Add a node to the cluster.

  This is a single-node call.

  """
  params = [dsa, dsapub, rsa, rsapub, ssh, sshpub]
  c = Client("node_add", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_node_verify(node_list, checkdict):
  """Request verification of given parameters.

  This is a multi-node call.

  """
  c = Client("node_verify", [checkdict])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_node_start_master(node):
  """Tells a node to activate itself as a master.

  This is a single-node call.

  """
  c = Client("node_start_master", [])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_node_stop_master(node):
  """Tells a node to demote itself from master status.

  This is a single-node call.

  """
  c = Client("node_stop_master", [])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_version(node_list):
  """Query node version.

  This is a multi-node call.

  """
  c = Client("version", [])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_blockdev_create(node, bdev, size, owner, on_primary, info):
  """Request creation of a given block device.

  This is a single-node call.

  """
  params = [bdev.ToDict(), size, owner, on_primary, info]
  c = Client("blockdev_create", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_remove(node, bdev):
  """Request removal of a given block device.

  This is a single-node call.

  """
  c = Client("blockdev_remove", [bdev.ToDict()])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_rename(node, devlist):
  """Request rename of the given block devices.

  This is a single-node call.

  """
  params = [(d.ToDict(), uid) for d, uid in devlist]
  c = Client("blockdev_rename", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_assemble(node, disk, owner, on_primary):
  """Request assembling of a given block device.

  This is a single-node call.

  """
  params = [disk.ToDict(), owner, on_primary]
  c = Client("blockdev_assemble", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_shutdown(node, disk):
  """Request shutdown of a given block device.

  This is a single-node call.

  """
  c = Client("blockdev_shutdown", [disk.ToDict()])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_addchildren(node, bdev, ndevs):
  """Request adding a list of children to a (mirroring) device.

  This is a single-node call.

  """
  params = [bdev.ToDict(), [disk.ToDict() for disk in ndevs]]
  c = Client("blockdev_addchildren", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_removechildren(node, bdev, ndevs):
  """Request removing a list of children from a (mirroring) device.

  This is a single-node call.

  """
  params = [bdev.ToDict(), [disk.ToDict() for disk in ndevs]]
  c = Client("blockdev_removechildren", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_getmirrorstatus(node, disks):
  """Request status of a (mirroring) device.

  This is a single-node call.

  """
  params = [dsk.ToDict() for dsk in disks]
  c = Client("blockdev_getmirrorstatus", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_blockdev_find(node, disk):
  """Request identification of a given block device.

  This is a single-node call.

  """
  c = Client("blockdev_find", [disk.ToDict()])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_upload_file(node_list, file_name):
  """Upload a file.

  The node will refuse the operation in case the file is not on the
  approved file list.

  This is a multi-node call.

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
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_os_diagnose(node_list):
  """Request a diagnose of OS definitions.

  This is a multi-node call.

  """
  c = Client("os_diagnose", [])
  c.connect_list(node_list)
  c.run()
  result = c.getresult()
  new_result = {}
  for node_name in result:
    if result[node_name]:
      nr = [objects.OS.FromDict(oss) for oss in result[node_name]]
    else:
      nr = []
    new_result[node_name] = nr
  return new_result


def call_os_get(node, name):
  """Returns an OS definition.

  This is a single-node call.

  """
  c = Client("os_get", [name])
  c.connect(node)
  c.run()
  result = c.getresult().get(node, False)
  if isinstance(result, dict):
    return objects.OS.FromDict(result)
  else:
    return result


def call_hooks_runner(node_list, hpath, phase, env):
  """Call the hooks runner.

  Args:
    - op: the OpCode instance
    - env: a dictionary with the environment

  This is a multi-node call.

  """
  params = [hpath, phase, env]
  c = Client("hooks_runner", params)
  c.connect_list(node_list)
  c.run()
  result = c.getresult()
  return result


def call_iallocator_runner(node, name, idata):
  """Call an iallocator on a remote node

  Args:
    - name: the iallocator name
    - input: the json-encoded input string

  This is a single-node call.

  """
  params = [name, idata]
  c = Client("iallocator_runner", params)
  c.connect(node)
  c.run()
  result = c.getresult().get(node, False)
  return result


def call_blockdev_snapshot(node, cf_bdev):
  """Request a snapshot of the given block device.

  This is a single-node call.

  """
  c = Client("blockdev_snapshot", [cf_bdev.ToDict()])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_snapshot_export(node, snap_bdev, dest_node, instance):
  """Request the export of a given snapshot.

  This is a single-node call.

  """
  params = [snap_bdev.ToDict(), dest_node, instance.ToDict()]
  c = Client("snapshot_export", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_finalize_export(node, instance, snap_disks):
  """Request the completion of an export operation.

  This writes the export config file, etc.

  This is a single-node call.

  """
  flat_disks = []
  for disk in snap_disks:
    flat_disks.append(disk.ToDict())
  params = [instance.ToDict(), flat_disks]
  c = Client("finalize_export", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_export_info(node, path):
  """Queries the export information in a given path.

  This is a single-node call.

  """
  c = Client("export_info", [path])
  c.connect(node)
  c.run()
  result = c.getresult().get(node, False)
  if not result:
    return result
  return objects.SerializableConfigParser.Loads(result)


def call_instance_os_import(node, inst, osdev, swapdev, src_node, src_image):
  """Request the import of a backup into an instance.

  This is a single-node call.

  """
  params = [inst.ToDict(), osdev, swapdev, src_node, src_image]
  c = Client("instance_os_import", params)
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_export_list(node_list):
  """Gets the stored exports list.

  This is a multi-node call.

  """
  c = Client("export_list", [])
  c.connect_list(node_list)
  c.run()
  result = c.getresult()
  return result


def call_export_remove(node, export):
  """Requests removal of a given export.

  This is a single-node call.

  """
  c = Client("export_remove", [export])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_node_leave_cluster(node):
  """Requests a node to clean the cluster information it has.

  This will remove the configuration information from the ganeti data
  dir.

  This is a single-node call.

  """
  c = Client("node_leave_cluster", [])
  c.connect(node)
  c.run()
  return c.getresult().get(node, False)


def call_node_volumes(node_list):
  """Gets all volumes on node(s).

  This is a multi-node call.

  """
  c = Client("node_volumes", [])
  c.connect_list(node_list)
  c.run()
  return c.getresult()


def call_test_delay(node_list, duration):
  """Sleep for a fixed time on given node(s).

  This is a multi-node call.

  """
  c = Client("test_delay", [duration])
  c.connect_list(node_list)
  c.run()
  return c.getresult()
