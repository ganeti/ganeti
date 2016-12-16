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


"""Test logical units."""

import logging
import shutil
import socket
import tempfile
import time

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import utils
from ganeti.masterd import iallocator
from ganeti.cmdlib.base import NoHooksLU
from ganeti.cmdlib.common import ExpandInstanceUuidAndName, GetWantedNodes, \
  GetWantedInstances


class TestSocketWrapper(object):
  """ Utility class that opens a domain socket and cleans up as needed.

  """
  def __init__(self):
    """ Constructor cleaning up variables to be used.

    """
    self.tmpdir = None
    self.sock = None

  def Create(self, max_connections=1):
    """ Creates a bound and ready socket, cleaning up in case of failure.

    @type max_connections: int
    @param max_connections: The number of max connections allowed for the
                            socket.

    @rtype: tuple of socket, string
    @return: The socket object and the path to reach it with.

    """
    # Using a temporary directory as there's no easy way to create temporary
    # sockets without writing a custom loop around tempfile.mktemp and
    # socket.bind
    self.tmpdir = tempfile.mkdtemp()
    try:
      tmpsock = utils.PathJoin(self.tmpdir, "sock")
      logging.debug("Creating temporary socket at %s", tmpsock)
      self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      try:
        self.sock.bind(tmpsock)
        self.sock.listen(max_connections)
      except:
        self.sock.close()
        raise
    except:
      shutil.rmtree(self.tmpdir)
      raise

    return self.sock, tmpsock

  def Destroy(self):
    """ Destroys the socket and performs all necessary cleanup.

    """
    if self.tmpdir is None or self.sock is None:
      raise Exception("A socket must be created successfully before attempting "
                      "its destruction")

    try:
      self.sock.close()
    finally:
      shutil.rmtree(self.tmpdir)


class LUTestDelay(NoHooksLU):
  """Sleep for a specified amount of time.

  This LU sleeps on the master and/or nodes for a specified amount of
  time.

  """
  REQ_BGL = False

  def ExpandNames(self):
    """Expand names and set required locks.

    This expands the node list, if any.

    """
    self.needed_locks = {}

    if self.op.duration <= 0:
      raise errors.OpPrereqError("Duration must be greater than zero")

    if not self.op.no_locks and (self.op.on_nodes or self.op.on_master):
      self.needed_locks[locking.LEVEL_NODE] = []

    self.op.on_node_uuids = []
    if self.op.on_nodes:
      # _GetWantedNodes can be used here, but is not always appropriate to use
      # this way in ExpandNames. Check LogicalUnit.ExpandNames docstring for
      # more information.
      (self.op.on_node_uuids, self.op.on_nodes) = \
        GetWantedNodes(self, self.op.on_nodes)

    master_uuid = self.cfg.GetMasterNode()
    if self.op.on_master and master_uuid not in self.op.on_node_uuids:
      self.op.on_node_uuids.append(master_uuid)

    self.needed_locks = {}
    self.needed_locks[locking.LEVEL_NODE] = self.op.on_node_uuids

  def _InterruptibleDelay(self):
    """Delays but provides the mechanisms necessary to interrupt the delay as
    needed.

    """
    socket_wrapper = TestSocketWrapper()
    sock, path = socket_wrapper.Create()

    self.Log(constants.ELOG_DELAY_TEST, (path,))

    try:
      sock.settimeout(self.op.duration)
      start = time.time()
      (conn, _) = sock.accept()
    except socket.timeout, _:
      # If we timed out, all is well
      return False
    finally:
      # Destroys the original socket, but the new connection is still usable
      socket_wrapper.Destroy()

    try:
      # Change to remaining time
      time_to_go = self.op.duration - (time.time() - start)
      self.Log(constants.ELOG_MESSAGE,
               "Received connection, time to go is %d" % time_to_go)
      if time_to_go < 0:
        time_to_go = 0
      # pylint: disable=E1101
      # Instance of '_socketobject' has no ... member
      conn.settimeout(time_to_go)
      conn.recv(1)
    except socket.timeout, _:
      # A second timeout can occur if no data is sent
      return False
    finally:
      conn.close()

    self.Log(constants.ELOG_MESSAGE,
             "Interrupted, time spent waiting: %d" % (time.time() - start))

    # Reaching this point means we were interrupted
    return True

  def _UninterruptibleDelay(self):
    """Delays without allowing interruptions.

    """
    if self.op.on_node_uuids:
      result = self.rpc.call_test_delay(self.op.on_node_uuids, self.op.duration)
      for node_uuid, node_result in result.items():
        node_result.Raise("Failure during rpc call to node %s" %
                          self.cfg.GetNodeName(node_uuid))
    else:
      if not utils.TestDelay(self.op.duration)[0]:
        raise errors.OpExecError("Error during master delay test")

  def _TestDelay(self):
    """Do the actual sleep.

    @rtype: bool
    @return: Whether the delay was interrupted

    """
    if self.op.interruptible:
      return self._InterruptibleDelay()
    else:
      self._UninterruptibleDelay()
      return False

  def Exec(self, feedback_fn):
    """Execute the test delay opcode, with the wanted repetitions.

    """
    if self.op.repeat == 0:
      i = self._TestDelay()
    else:
      top_value = self.op.repeat - 1
      for i in range(self.op.repeat):
        self.LogInfo("Test delay iteration %d/%d", i, top_value)
        # Break in case of interruption
        if self._TestDelay():
          break


class LUTestJqueue(NoHooksLU):
  """Utility LU to test some aspects of the job queue.

  """
  REQ_BGL = False

  # Must be lower than default timeout for WaitForJobChange to see whether it
  # notices changed jobs
  _CLIENT_CONNECT_TIMEOUT = 20.0
  _CLIENT_CONFIRM_TIMEOUT = 60.0

  @classmethod
  def _NotifyUsingSocket(cls, cb, errcls):
    """Opens a Unix socket and waits for another program to connect.

    @type cb: callable
    @param cb: Callback to send socket name to client
    @type errcls: class
    @param errcls: Exception class to use for errors

    """

    # Using a temporary directory as there's no easy way to create temporary
    # sockets without writing a custom loop around tempfile.mktemp and
    # socket.bind

    socket_wrapper = TestSocketWrapper()
    sock, path = socket_wrapper.Create()

    cb(path)

    try:
      sock.settimeout(cls._CLIENT_CONNECT_TIMEOUT)
      (conn, _) = sock.accept()
    except socket.error, err:
      raise errcls("Client didn't connect in time (%s)" % err)
    finally:
      socket_wrapper.Destroy()

    # Wait for client to close
    try:
      try:
        # pylint: disable=E1101
        # Instance of '_socketobject' has no ... member
        conn.settimeout(cls._CLIENT_CONFIRM_TIMEOUT)
        conn.recv(1)
      except socket.error, err:
        raise errcls("Client failed to confirm notification (%s)" % err)
    finally:
      conn.close()

  def _SendNotification(self, test, arg, sockname):
    """Sends a notification to the client.

    @type test: string
    @param test: Test name
    @param arg: Test argument (depends on test)
    @type sockname: string
    @param sockname: Socket path

    """
    self.Log(constants.ELOG_JQUEUE_TEST, (sockname, test, arg))

  def _Notify(self, prereq, test, arg):
    """Notifies the client of a test.

    @type prereq: bool
    @param prereq: Whether this is a prereq-phase test
    @type test: string
    @param test: Test name
    @param arg: Test argument (depends on test)

    """
    if prereq:
      errcls = errors.OpPrereqError
    else:
      errcls = errors.OpExecError

    return self._NotifyUsingSocket(compat.partial(self._SendNotification,
                                                  test, arg),
                                   errcls)

  def CheckArguments(self):
    self.checkargs_calls = getattr(self, "checkargs_calls", 0) + 1
    self.expandnames_calls = 0

  def ExpandNames(self):
    checkargs_calls = getattr(self, "checkargs_calls", 0)
    if checkargs_calls < 1:
      raise errors.ProgrammerError("CheckArguments was not called")

    self.expandnames_calls += 1

    if self.op.notify_waitlock:
      self._Notify(True, constants.JQT_EXPANDNAMES, None)

    self.LogInfo("Expanding names")

    # Get lock on master node (just to get a lock, not for a particular reason)
    self.needed_locks = {
      locking.LEVEL_NODE: self.cfg.GetMasterNode(),
      }

  def Exec(self, feedback_fn):
    if self.expandnames_calls < 1:
      raise errors.ProgrammerError("ExpandNames was not called")

    if self.op.notify_exec:
      self._Notify(False, constants.JQT_EXEC, None)

    self.LogInfo("Executing")

    if self.op.log_messages:
      self._Notify(False, constants.JQT_STARTMSG, len(self.op.log_messages))
      for idx, msg in enumerate(self.op.log_messages):
        self.LogInfo("Sending log message %s", idx + 1)
        feedback_fn(constants.JQT_MSGPREFIX + msg)
        # Report how many test messages have been sent
        self._Notify(False, constants.JQT_LOGMSG, idx + 1)

    if self.op.fail:
      raise errors.OpExecError("Opcode failure was requested")

    return True


class LUTestOsParams(NoHooksLU):
  """Utility LU to test secret OS parameter transmission.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    if self.op.osparams_secret:
      msg = "Secret OS parameters: %s" % self.op.osparams_secret.Unprivate()
      feedback_fn(msg)
    else:
      raise errors.OpExecError("Opcode needs secret parameters")


class LUTestAllocator(NoHooksLU):
  """Run allocator tests.

  This LU runs the allocator tests

  """
  def CheckPrereq(self):
    """Check prerequisites.

    This checks the opcode parameters depending on the director and mode test.

    """
    if self.op.mode in (constants.IALLOCATOR_MODE_ALLOC,
                        constants.IALLOCATOR_MODE_MULTI_ALLOC):
      (self.inst_uuid, iname) = self.cfg.ExpandInstanceName(self.op.name)
      if iname is not None:
        raise errors.OpPrereqError("Instance '%s' already in the cluster" %
                                   iname, errors.ECODE_EXISTS)
      for row in self.op.disks:
        if (not isinstance(row, dict) or
            constants.IDISK_SIZE not in row or
            not isinstance(row[constants.IDISK_SIZE], int) or
            constants.IDISK_MODE not in row or
            row[constants.IDISK_MODE] not in constants.DISK_ACCESS_SET):
          raise errors.OpPrereqError("Invalid contents of the 'disks'"
                                     " parameter", errors.ECODE_INVAL)
      if self.op.hypervisor is None:
        self.op.hypervisor = self.cfg.GetHypervisorType()
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      (self.inst_uuid, self.op.name) = ExpandInstanceUuidAndName(self.cfg, None,
                                                                 self.op.name)
      self.relocate_from_node_uuids = \
          list(self.cfg.GetInstanceSecondaryNodes(self.inst_uuid))
    elif self.op.mode in (constants.IALLOCATOR_MODE_CHG_GROUP,
                          constants.IALLOCATOR_MODE_NODE_EVAC):
      if not self.op.instances:
        raise errors.OpPrereqError("Missing instances", errors.ECODE_INVAL)
      (_, self.op.instances) = GetWantedInstances(self, self.op.instances)
    else:
      raise errors.OpPrereqError("Invalid test allocator mode '%s'" %
                                 self.op.mode, errors.ECODE_INVAL)

    if self.op.direction == constants.IALLOCATOR_DIR_OUT:
      if self.op.iallocator is None:
        raise errors.OpPrereqError("Missing allocator name",
                                   errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Run the allocator test.

    """
    if self.op.mode == constants.IALLOCATOR_MODE_ALLOC:
      req = iallocator.IAReqInstanceAlloc(name=self.op.name,
                                          memory=self.op.memory,
                                          disks=self.op.disks,
                                          disk_template=self.op.disk_template,
                                          group_name=self.op.group_name,
                                          os=self.op.os,
                                          tags=self.op.tags,
                                          nics=self.op.nics,
                                          vcpus=self.op.vcpus,
                                          spindle_use=self.op.spindle_use,
                                          hypervisor=self.op.hypervisor,
                                          node_whitelist=None)
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      req = iallocator.IAReqRelocate(
            inst_uuid=self.inst_uuid,
            relocate_from_node_uuids=list(self.relocate_from_node_uuids))
    elif self.op.mode == constants.IALLOCATOR_MODE_CHG_GROUP:
      req = iallocator.IAReqGroupChange(instances=self.op.instances,
                                        target_groups=self.op.target_groups)
    elif self.op.mode == constants.IALLOCATOR_MODE_NODE_EVAC:
      req = iallocator.IAReqNodeEvac(instances=self.op.instances,
                                     evac_mode=self.op.evac_mode,
                                     ignore_soft_errors=False)
    elif self.op.mode == constants.IALLOCATOR_MODE_MULTI_ALLOC:
      disk_template = self.op.disk_template
      insts = [iallocator.IAReqInstanceAlloc(name="%s%s" % (self.op.name, idx),
                                             memory=self.op.memory,
                                             disks=self.op.disks,
                                             disk_template=disk_template,
                                             group_name=self.op.group_name,
                                             os=self.op.os,
                                             tags=self.op.tags,
                                             nics=self.op.nics,
                                             vcpus=self.op.vcpus,
                                             spindle_use=self.op.spindle_use,
                                             hypervisor=self.op.hypervisor,
                                             node_whitelist=None)
               for idx in range(self.op.count)]
      req = iallocator.IAReqMultiInstanceAlloc(instances=insts)
    else:
      raise errors.ProgrammerError("Uncatched mode %s in"
                                   " LUTestAllocator.Exec", self.op.mode)

    ial = iallocator.IAllocator(self.cfg, self.rpc, req)
    if self.op.direction == constants.IALLOCATOR_DIR_IN:
      result = ial.in_text
    else:
      ial.Run(self.op.iallocator, validate=False)
      result = ial.out_text
    return result
