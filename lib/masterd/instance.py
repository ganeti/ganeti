#
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Instance-related functions and classes for masterd.

"""

import logging
import time
import OpenSSL

from ganeti import constants
from ganeti import errors
from ganeti import compat
from ganeti import utils
from ganeti import objects
from ganeti import netutils
from ganeti import pathutils


class _ImportExportError(Exception):
  """Local exception to report import/export errors.

  """


class ImportExportTimeouts(object):
  #: Time until daemon starts writing status file
  DEFAULT_READY_TIMEOUT = 10

  #: Length of time until errors cause hard failure
  DEFAULT_ERROR_TIMEOUT = 10

  #: Time after which daemon must be listening
  DEFAULT_LISTEN_TIMEOUT = 10

  #: Progress update interval
  DEFAULT_PROGRESS_INTERVAL = 60

  __slots__ = [
    "error",
    "ready",
    "listen",
    "connect",
    "progress",
    ]

  def __init__(self, connect,
               listen=DEFAULT_LISTEN_TIMEOUT,
               error=DEFAULT_ERROR_TIMEOUT,
               ready=DEFAULT_READY_TIMEOUT,
               progress=DEFAULT_PROGRESS_INTERVAL):
    """Initializes this class.

    @type connect: number
    @param connect: Timeout for establishing connection
    @type listen: number
    @param listen: Timeout for starting to listen for connections
    @type error: number
    @param error: Length of time until errors cause hard failure
    @type ready: number
    @param ready: Timeout for daemon to become ready
    @type progress: number
    @param progress: Progress update interval

    """
    self.error = error
    self.ready = ready
    self.listen = listen
    self.connect = connect
    self.progress = progress


class ImportExportCbBase(object):
  """Callbacks for disk import/export.

  """
  def ReportListening(self, ie, private, component):
    """Called when daemon started listening.

    @type ie: Subclass of L{_DiskImportExportBase}
    @param ie: Import/export object
    @param private: Private data passed to import/export object
    @param component: transfer component name

    """

  def ReportConnected(self, ie, private):
    """Called when a connection has been established.

    @type ie: Subclass of L{_DiskImportExportBase}
    @param ie: Import/export object
    @param private: Private data passed to import/export object

    """

  def ReportProgress(self, ie, private):
    """Called when new progress information should be reported.

    @type ie: Subclass of L{_DiskImportExportBase}
    @param ie: Import/export object
    @param private: Private data passed to import/export object

    """

  def ReportFinished(self, ie, private):
    """Called when a transfer has finished.

    @type ie: Subclass of L{_DiskImportExportBase}
    @param ie: Import/export object
    @param private: Private data passed to import/export object

    """


class _DiskImportExportBase(object):
  MODE_TEXT = None

  def __init__(self, lu, node_uuid, opts,
               instance, component, timeouts, cbs, private=None):
    """Initializes this class.

    @param lu: Logical unit instance
    @type node_uuid: string
    @param node_uuid: Node UUID for import
    @type opts: L{objects.ImportExportOptions}
    @param opts: Import/export daemon options
    @type instance: L{objects.Instance}
    @param instance: Instance object
    @type component: string
    @param component: which part of the instance is being imported
    @type timeouts: L{ImportExportTimeouts}
    @param timeouts: Timeouts for this import
    @type cbs: L{ImportExportCbBase}
    @param cbs: Callbacks
    @param private: Private data for callback functions

    """
    assert self.MODE_TEXT

    self._lu = lu
    self.node_uuid = node_uuid
    self.node_name = lu.cfg.GetNodeName(node_uuid)
    self._opts = opts.Copy()
    self._instance = instance
    self._component = component
    self._timeouts = timeouts
    self._cbs = cbs
    self._private = private

    # Set master daemon's timeout in options for import/export daemon
    assert self._opts.connect_timeout is None
    self._opts.connect_timeout = timeouts.connect

    # Parent loop
    self._loop = None

    # Timestamps
    self._ts_begin = None
    self._ts_connected = None
    self._ts_finished = None
    self._ts_cleanup = None
    self._ts_last_progress = None
    self._ts_last_error = None

    # Transfer status
    self.success = None
    self.final_message = None

    # Daemon status
    self._daemon_name = None
    self._daemon = None

  @property
  def recent_output(self):
    """Returns the most recent output from the daemon.

    """
    if self._daemon:
      return "\n".join(self._daemon.recent_output)

    return None

  @property
  def progress(self):
    """Returns transfer progress information.

    """
    if not self._daemon:
      return None

    return (self._daemon.progress_mbytes,
            self._daemon.progress_throughput,
            self._daemon.progress_percent,
            self._daemon.progress_eta)

  @property
  def magic(self):
    """Returns the magic value for this import/export.

    """
    return self._opts.magic

  @property
  def active(self):
    """Determines whether this transport is still active.

    """
    return self.success is None

  @property
  def loop(self):
    """Returns parent loop.

    @rtype: L{ImportExportLoop}

    """
    return self._loop

  def SetLoop(self, loop):
    """Sets the parent loop.

    @type loop: L{ImportExportLoop}

    """
    if self._loop:
      raise errors.ProgrammerError("Loop can only be set once")

    self._loop = loop

  def _StartDaemon(self):
    """Starts the import/export daemon.

    """
    raise NotImplementedError()

  def CheckDaemon(self):
    """Checks whether daemon has been started and if not, starts it.

    @rtype: string
    @return: Daemon name

    """
    assert self._ts_cleanup is None

    if self._daemon_name is None:
      assert self._ts_begin is None

      result = self._StartDaemon()
      if result.fail_msg:
        raise _ImportExportError("Failed to start %s on %s: %s" %
                                 (self.MODE_TEXT, self.node_name,
                                  result.fail_msg))

      daemon_name = result.payload

      logging.info("Started %s '%s' on %s", self.MODE_TEXT, daemon_name,
                   self.node_name)

      self._ts_begin = time.time()
      self._daemon_name = daemon_name

    return self._daemon_name

  def GetDaemonName(self):
    """Returns the daemon name.

    """
    assert self._daemon_name, "Daemon has not been started"
    assert self._ts_cleanup is None
    return self._daemon_name

  def Abort(self):
    """Sends SIGTERM to import/export daemon (if still active).

    """
    if self._daemon_name:
      self._lu.LogWarning("Aborting %s '%s' on %s",
                          self.MODE_TEXT, self._daemon_name, self.node_uuid)
      result = self._lu.rpc.call_impexp_abort(self.node_uuid, self._daemon_name)
      if result.fail_msg:
        self._lu.LogWarning("Failed to abort %s '%s' on %s: %s",
                            self.MODE_TEXT, self._daemon_name,
                            self.node_uuid, result.fail_msg)
        return False

    return True

  def _SetDaemonData(self, data):
    """Internal function for updating status daemon data.

    @type data: L{objects.ImportExportStatus}
    @param data: Daemon status data

    """
    assert self._ts_begin is not None

    if not data:
      if utils.TimeoutExpired(self._ts_begin, self._timeouts.ready):
        raise _ImportExportError("Didn't become ready after %s seconds" %
                                 self._timeouts.ready)

      return False

    self._daemon = data

    return True

  def SetDaemonData(self, success, data):
    """Updates daemon status data.

    @type success: bool
    @param success: Whether fetching data was successful or not
    @type data: L{objects.ImportExportStatus}
    @param data: Daemon status data

    """
    if not success:
      if self._ts_last_error is None:
        self._ts_last_error = time.time()

      elif utils.TimeoutExpired(self._ts_last_error, self._timeouts.error):
        raise _ImportExportError("Too many errors while updating data")

      return False

    self._ts_last_error = None

    return self._SetDaemonData(data)

  def CheckListening(self):
    """Checks whether the daemon is listening.

    """
    raise NotImplementedError()

  def _GetConnectedCheckEpoch(self):
    """Returns timeout to calculate connect timeout.

    """
    raise NotImplementedError()

  def CheckConnected(self):
    """Checks whether the daemon is connected.

    @rtype: bool
    @return: Whether the daemon is connected

    """
    assert self._daemon, "Daemon status missing"

    if self._ts_connected is not None:
      return True

    if self._daemon.connected:
      self._ts_connected = time.time()

      # TODO: Log remote peer
      logging.debug("%s '%s' on %s is now connected",
                    self.MODE_TEXT, self._daemon_name, self.node_uuid)

      self._cbs.ReportConnected(self, self._private)

      return True

    if utils.TimeoutExpired(self._GetConnectedCheckEpoch(),
                            self._timeouts.connect):
      raise _ImportExportError("Not connected after %s seconds" %
                               self._timeouts.connect)

    return False

  def _CheckProgress(self):
    """Checks whether a progress update should be reported.

    """
    if ((self._ts_last_progress is None or
        utils.TimeoutExpired(self._ts_last_progress,
                             self._timeouts.progress)) and
        self._daemon and
        self._daemon.progress_mbytes is not None and
        self._daemon.progress_throughput is not None):
      self._cbs.ReportProgress(self, self._private)
      self._ts_last_progress = time.time()

  def CheckFinished(self):
    """Checks whether the daemon exited.

    @rtype: bool
    @return: Whether the transfer is finished

    """
    assert self._daemon, "Daemon status missing"

    if self._ts_finished:
      return True

    if self._daemon.exit_status is None:
      # TODO: Adjust delay for ETA expiring soon
      self._CheckProgress()
      return False

    self._ts_finished = time.time()

    self._ReportFinished(self._daemon.exit_status == 0,
                         self._daemon.error_message)

    return True

  def _ReportFinished(self, success, message):
    """Transfer is finished or daemon exited.

    @type success: bool
    @param success: Whether the transfer was successful
    @type message: string
    @param message: Error message

    """
    assert self.success is None

    self.success = success
    self.final_message = message

    if success:
      logging.info("%s '%s' on %s succeeded", self.MODE_TEXT,
                   self._daemon_name, self.node_uuid)
    elif self._daemon_name:
      self._lu.LogWarning("%s '%s' on %s failed: %s",
                          self.MODE_TEXT, self._daemon_name,
                          self._lu.cfg.GetNodeName(self.node_uuid),
                          message)
    else:
      self._lu.LogWarning("%s on %s failed: %s", self.MODE_TEXT,
                          self._lu.cfg.GetNodeName(self.node_uuid), message)

    self._cbs.ReportFinished(self, self._private)

  def _Finalize(self):
    """Makes the RPC call to finalize this import/export.

    """
    return self._lu.rpc.call_impexp_cleanup(self.node_uuid, self._daemon_name)

  def Finalize(self, error=None):
    """Finalizes this import/export.

    """
    if self._daemon_name:
      logging.info("Finalizing %s '%s' on %s",
                   self.MODE_TEXT, self._daemon_name, self.node_uuid)

      result = self._Finalize()
      if result.fail_msg:
        self._lu.LogWarning("Failed to finalize %s '%s' on %s: %s",
                            self.MODE_TEXT, self._daemon_name,
                            self.node_uuid, result.fail_msg)
        return False

      # Daemon is no longer running
      self._daemon_name = None
      self._ts_cleanup = time.time()

    if error:
      self._ReportFinished(False, error)

    return True


class DiskImport(_DiskImportExportBase):
  MODE_TEXT = "import"

  def __init__(self, lu, node_uuid, opts, instance, component,
               dest, dest_args, timeouts, cbs, private=None):
    """Initializes this class.

    @param lu: Logical unit instance
    @type node_uuid: string
    @param node_uuid: Node name for import
    @type opts: L{objects.ImportExportOptions}
    @param opts: Import/export daemon options
    @type instance: L{objects.Instance}
    @param instance: Instance object
    @type component: string
    @param component: which part of the instance is being imported
    @param dest: I/O destination
    @param dest_args: I/O arguments
    @type timeouts: L{ImportExportTimeouts}
    @param timeouts: Timeouts for this import
    @type cbs: L{ImportExportCbBase}
    @param cbs: Callbacks
    @param private: Private data for callback functions

    """
    _DiskImportExportBase.__init__(self, lu, node_uuid, opts, instance,
                                   component, timeouts, cbs, private)
    self._dest = dest
    self._dest_args = dest_args

    # Timestamps
    self._ts_listening = None

  @property
  def listen_port(self):
    """Returns the port the daemon is listening on.

    """
    if self._daemon:
      return self._daemon.listen_port

    return None

  def _StartDaemon(self):
    """Starts the import daemon.

    """
    return self._lu.rpc.call_import_start(self.node_uuid, self._opts,
                                          self._instance, self._component,
                                          (self._dest, self._dest_args))

  def CheckListening(self):
    """Checks whether the daemon is listening.

    @rtype: bool
    @return: Whether the daemon is listening

    """
    assert self._daemon, "Daemon status missing"

    if self._ts_listening is not None:
      return True

    port = self._daemon.listen_port
    if port is not None:
      self._ts_listening = time.time()

      logging.debug("Import '%s' on %s is now listening on port %s",
                    self._daemon_name, self.node_uuid, port)

      self._cbs.ReportListening(self, self._private, self._component)

      return True

    if utils.TimeoutExpired(self._ts_begin, self._timeouts.listen):
      raise _ImportExportError("Not listening after %s seconds" %
                               self._timeouts.listen)

    return False

  def _GetConnectedCheckEpoch(self):
    """Returns the time since we started listening.

    """
    assert self._ts_listening is not None, \
           ("Checking whether an import is connected is only useful"
            " once it's been listening")

    return self._ts_listening


class DiskExport(_DiskImportExportBase):
  MODE_TEXT = "export"

  def __init__(self, lu, node_uuid, opts, dest_host, dest_port,
               instance, component, source, source_args,
               timeouts, cbs, private=None):
    """Initializes this class.

    @param lu: Logical unit instance
    @type node_uuid: string
    @param node_uuid: Node UUID for import
    @type opts: L{objects.ImportExportOptions}
    @param opts: Import/export daemon options
    @type dest_host: string
    @param dest_host: Destination host name or IP address
    @type dest_port: number
    @param dest_port: Destination port number
    @type instance: L{objects.Instance}
    @param instance: Instance object
    @type component: string
    @param component: which part of the instance is being imported
    @param source: I/O source
    @param source_args: I/O source
    @type timeouts: L{ImportExportTimeouts}
    @param timeouts: Timeouts for this import
    @type cbs: L{ImportExportCbBase}
    @param cbs: Callbacks
    @param private: Private data for callback functions

    """
    _DiskImportExportBase.__init__(self, lu, node_uuid, opts, instance,
                                   component, timeouts, cbs, private)
    self._dest_host = dest_host
    self._dest_port = dest_port
    self._source = source
    self._source_args = source_args

  def _StartDaemon(self):
    """Starts the export daemon.

    """
    return self._lu.rpc.call_export_start(self.node_uuid, self._opts,
                                          self._dest_host, self._dest_port,
                                          self._instance, self._component,
                                          (self._source, self._source_args))

  def CheckListening(self):
    """Checks whether the daemon is listening.

    """
    # Only an import can be listening
    return True

  def _GetConnectedCheckEpoch(self):
    """Returns the time since the daemon started.

    """
    assert self._ts_begin is not None

    return self._ts_begin


def FormatProgress(progress):
  """Formats progress information for user consumption

  """
  (mbytes, throughput, percent, eta) = progress

  parts = [
    utils.FormatUnit(mbytes, "h"),

    # Not using FormatUnit as it doesn't support kilobytes
    "%0.1f MiB/s" % throughput,
    ]

  if percent is not None:
    parts.append("%d%%" % percent)

  if eta is not None:
    parts.append("ETA %s" % utils.FormatSeconds(eta))

  return utils.CommaJoin(parts)


class ImportExportLoop:
  MIN_DELAY = 1.0
  MAX_DELAY = 20.0

  def __init__(self, lu):
    """Initializes this class.

    """
    self._lu = lu
    self._queue = []
    self._pending_add = []

  def Add(self, diskie):
    """Adds an import/export object to the loop.

    @type diskie: Subclass of L{_DiskImportExportBase}
    @param diskie: Import/export object

    """
    assert diskie not in self._pending_add
    assert diskie.loop is None

    diskie.SetLoop(self)

    # Adding new objects to a staging list is necessary, otherwise the main
    # loop gets confused if callbacks modify the queue while the main loop is
    # iterating over it.
    self._pending_add.append(diskie)

  @staticmethod
  def _CollectDaemonStatus(lu, daemons):
    """Collects the status for all import/export daemons.

    """
    daemon_status = {}

    for node_name, names in daemons.iteritems():
      result = lu.rpc.call_impexp_status(node_name, names)
      if result.fail_msg:
        lu.LogWarning("Failed to get daemon status on %s: %s",
                      node_name, result.fail_msg)
        continue

      assert len(names) == len(result.payload)

      daemon_status[node_name] = dict(zip(names, result.payload))

    return daemon_status

  @staticmethod
  def _GetActiveDaemonNames(queue):
    """Gets the names of all active daemons.

    """
    result = {}
    for diskie in queue:
      if not diskie.active:
        continue

      try:
        # Start daemon if necessary
        daemon_name = diskie.CheckDaemon()
      except _ImportExportError, err:
        logging.exception("%s failed", diskie.MODE_TEXT)
        diskie.Finalize(error=str(err))
        continue

      result.setdefault(diskie.node_name, []).append(daemon_name)

    assert len(queue) >= len(result)
    assert len(queue) >= sum([len(names) for names in result.itervalues()])

    logging.debug("daemons=%r", result)

    return result

  def _AddPendingToQueue(self):
    """Adds all pending import/export objects to the internal queue.

    """
    assert compat.all(diskie not in self._queue and diskie.loop == self
                      for diskie in self._pending_add)

    self._queue.extend(self._pending_add)

    del self._pending_add[:]

  def Run(self):
    """Utility main loop.

    """
    while True:
      self._AddPendingToQueue()

      # Collect all active daemon names
      daemons = self._GetActiveDaemonNames(self._queue)
      if not daemons:
        break

      # Collection daemon status data
      data = self._CollectDaemonStatus(self._lu, daemons)

      # Use data
      delay = self.MAX_DELAY
      for diskie in self._queue:
        if not diskie.active:
          continue

        try:
          try:
            all_daemon_data = data[diskie.node_name]
          except KeyError:
            result = diskie.SetDaemonData(False, None)
          else:
            result = \
              diskie.SetDaemonData(True,
                                   all_daemon_data[diskie.GetDaemonName()])

          if not result:
            # Daemon not yet ready, retry soon
            delay = min(3.0, delay)
            continue

          if diskie.CheckFinished():
            # Transfer finished
            diskie.Finalize()
            continue

          # Normal case: check again in 5 seconds
          delay = min(5.0, delay)

          if not diskie.CheckListening():
            # Not yet listening, retry soon
            delay = min(1.0, delay)
            continue

          if not diskie.CheckConnected():
            # Not yet connected, retry soon
            delay = min(1.0, delay)
            continue

        except _ImportExportError, err:
          logging.exception("%s failed", diskie.MODE_TEXT)
          diskie.Finalize(error=str(err))

      if not compat.any(diskie.active for diskie in self._queue):
        break

      # Wait a bit
      delay = min(self.MAX_DELAY, max(self.MIN_DELAY, delay))
      logging.debug("Waiting for %ss", delay)
      time.sleep(delay)

  def FinalizeAll(self):
    """Finalizes all pending transfers.

    """
    success = True

    for diskie in self._queue:
      success = diskie.Finalize() and success

    return success


class _TransferInstCbBase(ImportExportCbBase):
  def __init__(self, lu, feedback_fn, instance, timeouts, src_node_uuid,
               src_cbs, dest_node_uuid, dest_ip):
    """Initializes this class.

    """
    ImportExportCbBase.__init__(self)

    self.lu = lu
    self.feedback_fn = feedback_fn
    self.instance = instance
    self.timeouts = timeouts
    self.src_node_uuid = src_node_uuid
    self.src_cbs = src_cbs
    self.dest_node_uuid = dest_node_uuid
    self.dest_ip = dest_ip


class _TransferInstSourceCb(_TransferInstCbBase):
  def ReportConnected(self, ie, dtp):
    """Called when a connection has been established.

    """
    assert self.src_cbs is None
    assert dtp.src_export == ie
    assert dtp.dest_import

    self.feedback_fn("%s is sending data on %s" %
                     (dtp.data.name, ie.node_name))

  def ReportProgress(self, ie, dtp):
    """Called when new progress information should be reported.

    """
    progress = ie.progress
    if not progress:
      return

    self.feedback_fn("%s sent %s" % (dtp.data.name, FormatProgress(progress)))

  def ReportFinished(self, ie, dtp):
    """Called when a transfer has finished.

    """
    assert self.src_cbs is None
    assert dtp.src_export == ie
    assert dtp.dest_import

    if ie.success:
      self.feedback_fn("%s finished sending data" % dtp.data.name)
    else:
      self.feedback_fn("%s failed to send data: %s (recent output: %s)" %
                       (dtp.data.name, ie.final_message, ie.recent_output))

    dtp.RecordResult(ie.success)

    cb = dtp.data.finished_fn
    if cb:
      cb()

    # TODO: Check whether sending SIGTERM right away is okay, maybe we should
    # give the daemon a moment to sort things out
    if dtp.dest_import and not ie.success:
      dtp.dest_import.Abort()


class _TransferInstDestCb(_TransferInstCbBase):
  def ReportListening(self, ie, dtp, component):
    """Called when daemon started listening.

    """
    assert self.src_cbs
    assert dtp.src_export is None
    assert dtp.dest_import
    assert dtp.export_opts

    self.feedback_fn("%s is now listening, starting export" % dtp.data.name)

    # Start export on source node
    de = DiskExport(self.lu, self.src_node_uuid, dtp.export_opts,
                    self.dest_ip, ie.listen_port, self.instance,
                    component, dtp.data.src_io, dtp.data.src_ioargs,
                    self.timeouts, self.src_cbs, private=dtp)
    ie.loop.Add(de)

    dtp.src_export = de

  def ReportConnected(self, ie, dtp):
    """Called when a connection has been established.

    """
    self.feedback_fn("%s is receiving data on %s" %
                     (dtp.data.name,
                      self.lu.cfg.GetNodeName(self.dest_node_uuid)))

  def ReportFinished(self, ie, dtp):
    """Called when a transfer has finished.

    """
    if ie.success:
      self.feedback_fn("%s finished receiving data" % dtp.data.name)
    else:
      self.feedback_fn("%s failed to receive data: %s (recent output: %s)" %
                       (dtp.data.name, ie.final_message, ie.recent_output))

    dtp.RecordResult(ie.success)

    # TODO: Check whether sending SIGTERM right away is okay, maybe we should
    # give the daemon a moment to sort things out
    if dtp.src_export and not ie.success:
      dtp.src_export.Abort()


class DiskTransfer(object):
  def __init__(self, name, src_io, src_ioargs, dest_io, dest_ioargs,
               finished_fn):
    """Initializes this class.

    @type name: string
    @param name: User-visible name for this transfer (e.g. "disk/0")
    @param src_io: Source I/O type
    @param src_ioargs: Source I/O arguments
    @param dest_io: Destination I/O type
    @param dest_ioargs: Destination I/O arguments
    @type finished_fn: callable
    @param finished_fn: Function called once transfer has finished

    """
    self.name = name

    self.src_io = src_io
    self.src_ioargs = src_ioargs

    self.dest_io = dest_io
    self.dest_ioargs = dest_ioargs

    self.finished_fn = finished_fn


class _DiskTransferPrivate(object):
  def __init__(self, data, success, export_opts):
    """Initializes this class.

    @type data: L{DiskTransfer}
    @type success: bool

    """
    self.data = data
    self.success = success
    self.export_opts = export_opts

    self.src_export = None
    self.dest_import = None

  def RecordResult(self, success):
    """Updates the status.

    One failed part will cause the whole transfer to fail.

    """
    self.success = self.success and success


def _GetInstDiskMagic(base, instance_name, index):
  """Computes the magic value for a disk export or import.

  @type base: string
  @param base: Random seed value (can be the same for all disks of a transfer)
  @type instance_name: string
  @param instance_name: Name of instance
  @type index: number
  @param index: Disk index

  """
  h = compat.sha1_hash()
  h.update(str(constants.RIE_VERSION))
  h.update(base)
  h.update(instance_name)
  h.update(str(index))
  return h.hexdigest()


def TransferInstanceData(lu, feedback_fn, src_node_uuid, dest_node_uuid,
                         dest_ip, compress, instance, all_transfers):
  """Transfers an instance's data from one node to another.

  @param lu: Logical unit instance
  @param feedback_fn: Feedback function
  @type src_node_uuid: string
  @param src_node_uuid: Source node UUID
  @type dest_node_uuid: string
  @param dest_node_uuid: Destination node UUID
  @type dest_ip: string
  @param dest_ip: IP address of destination node
  @type compress: string
  @param compress: one of L{constants.IEC_ALL}
  @type instance: L{objects.Instance}
  @param instance: Instance object
  @type all_transfers: list of L{DiskTransfer} instances
  @param all_transfers: List of all disk transfers to be made
  @rtype: list
  @return: List with a boolean (True=successful, False=failed) for success for
           each transfer

  """
  src_node_name = lu.cfg.GetNodeName(src_node_uuid)
  dest_node_name = lu.cfg.GetNodeName(dest_node_uuid)

  logging.debug("Source node %s, destination node %s, compression '%s'",
                src_node_name, dest_node_name, compress)

  timeouts = ImportExportTimeouts(constants.DISK_TRANSFER_CONNECT_TIMEOUT)
  src_cbs = _TransferInstSourceCb(lu, feedback_fn, instance, timeouts,
                                  src_node_uuid, None, dest_node_uuid, dest_ip)
  dest_cbs = _TransferInstDestCb(lu, feedback_fn, instance, timeouts,
                                 src_node_uuid, src_cbs, dest_node_uuid,
                                 dest_ip)

  all_dtp = []

  base_magic = utils.GenerateSecret(6)

  ieloop = ImportExportLoop(lu)
  try:
    for idx, transfer in enumerate(all_transfers):
      if transfer:
        feedback_fn("Exporting %s from %s to %s" %
                    (transfer.name, src_node_name, dest_node_name))

        magic = _GetInstDiskMagic(base_magic, instance.name, idx)
        opts = objects.ImportExportOptions(key_name=None, ca_pem=None,
                                           compress=compress, magic=magic)

        dtp = _DiskTransferPrivate(transfer, True, opts)

        di = DiskImport(lu, dest_node_uuid, opts, instance, "disk%d" % idx,
                        transfer.dest_io, transfer.dest_ioargs,
                        timeouts, dest_cbs, private=dtp)
        ieloop.Add(di)

        dtp.dest_import = di
      else:
        dtp = _DiskTransferPrivate(None, False, None)

      all_dtp.append(dtp)

    ieloop.Run()
  finally:
    ieloop.FinalizeAll()

  assert len(all_dtp) == len(all_transfers)
  assert compat.all((dtp.src_export is None or
                      dtp.src_export.success is not None) and
                     (dtp.dest_import is None or
                      dtp.dest_import.success is not None)
                     for dtp in all_dtp), \
         "Not all imports/exports are finalized"

  return [bool(dtp.success) for dtp in all_dtp]


class _RemoteExportCb(ImportExportCbBase):
  def __init__(self, feedback_fn, disk_count):
    """Initializes this class.

    """
    ImportExportCbBase.__init__(self)
    self._feedback_fn = feedback_fn
    self._dresults = [None] * disk_count

  @property
  def disk_results(self):
    """Returns per-disk results.

    """
    return self._dresults

  def ReportConnected(self, ie, private):
    """Called when a connection has been established.

    """
    (idx, _) = private

    self._feedback_fn("Disk %s is now sending data" % idx)

  def ReportProgress(self, ie, private):
    """Called when new progress information should be reported.

    """
    (idx, _) = private

    progress = ie.progress
    if not progress:
      return

    self._feedback_fn("Disk %s sent %s" % (idx, FormatProgress(progress)))

  def ReportFinished(self, ie, private):
    """Called when a transfer has finished.

    """
    (idx, finished_fn) = private

    if ie.success:
      self._feedback_fn("Disk %s finished sending data" % idx)
    else:
      self._feedback_fn("Disk %s failed to send data: %s (recent output: %s)" %
                        (idx, ie.final_message, ie.recent_output))

    self._dresults[idx] = bool(ie.success)

    if finished_fn:
      finished_fn()


class ExportInstanceHelper:
  def __init__(self, lu, feedback_fn, instance):
    """Initializes this class.

    @param lu: Logical unit instance
    @param feedback_fn: Feedback function
    @type instance: L{objects.Instance}
    @param instance: Instance object

    """
    self._lu = lu
    self._feedback_fn = feedback_fn
    self._instance = instance

    self._snap_disks = []
    self._removed_snaps = [False] * len(instance.disks)

  def CreateSnapshots(self):
    """Creates an LVM snapshot for every disk of the instance.

    """
    assert not self._snap_disks

    instance = self._instance
    src_node = instance.primary_node
    src_node_name = self._lu.cfg.GetNodeName(src_node)

    for idx, disk in enumerate(instance.disks):
      self._feedback_fn("Creating a snapshot of disk/%s on node %s" %
                        (idx, src_node_name))

      # result.payload will be a snapshot of an lvm leaf of the one we
      # passed
      result = self._lu.rpc.call_blockdev_snapshot(src_node, (disk, instance))
      new_dev = False
      msg = result.fail_msg
      if msg:
        self._lu.LogWarning("Could not snapshot disk/%s on node %s: %s",
                            idx, src_node_name, msg)
      elif (not isinstance(result.payload, (tuple, list)) or
            len(result.payload) != 2):
        self._lu.LogWarning("Could not snapshot disk/%s on node %s: invalid"
                            " result '%s'", idx, src_node_name, result.payload)
      else:
        disk_id = tuple(result.payload)
        disk_params = constants.DISK_LD_DEFAULTS[constants.DT_PLAIN].copy()
        new_dev = objects.Disk(dev_type=constants.DT_PLAIN, size=disk.size,
                               logical_id=disk_id, iv_name=disk.iv_name,
                               params=disk_params)

      self._snap_disks.append(new_dev)

    assert len(self._snap_disks) == len(instance.disks)
    assert len(self._removed_snaps) == len(instance.disks)

  def _RemoveSnapshot(self, disk_index):
    """Removes an LVM snapshot.

    @type disk_index: number
    @param disk_index: Index of the snapshot to be removed

    """
    disk = self._snap_disks[disk_index]
    if disk and not self._removed_snaps[disk_index]:
      src_node = self._instance.primary_node
      src_node_name = self._lu.cfg.GetNodeName(src_node)

      self._feedback_fn("Removing snapshot of disk/%s on node %s" %
                        (disk_index, src_node_name))

      result = self._lu.rpc.call_blockdev_remove(src_node,
                                                 (disk, self._instance))
      if result.fail_msg:
        self._lu.LogWarning("Could not remove snapshot for disk/%d from node"
                            " %s: %s", disk_index, src_node_name,
                            result.fail_msg)
      else:
        self._removed_snaps[disk_index] = True

  def LocalExport(self, dest_node, compress):
    """Intra-cluster instance export.

    @type dest_node: L{objects.Node}
    @param dest_node: Destination node
    @type compress: string
    @param compress: one of L{constants.IEC_ALL}

    """
    instance = self._instance
    src_node_uuid = instance.primary_node

    assert len(self._snap_disks) == len(instance.disks)

    transfers = []

    for idx, dev in enumerate(self._snap_disks):
      if not dev:
        transfers.append(None)
        continue

      path = utils.PathJoin(pathutils.EXPORT_DIR, "%s.new" % instance.name,
                            dev.logical_id[1])

      finished_fn = compat.partial(self._TransferFinished, idx)

      # FIXME: pass debug option from opcode to backend
      dt = DiskTransfer("snapshot/%s" % idx,
                        constants.IEIO_SCRIPT, ((dev, instance), idx),
                        constants.IEIO_FILE, (path, ),
                        finished_fn)
      transfers.append(dt)

    # Actually export data
    dresults = TransferInstanceData(self._lu, self._feedback_fn,
                                    src_node_uuid, dest_node.uuid,
                                    dest_node.secondary_ip,
                                    compress,
                                    instance, transfers)

    assert len(dresults) == len(instance.disks)

    self._feedback_fn("Finalizing export on %s" % dest_node.name)
    result = self._lu.rpc.call_finalize_export(dest_node.uuid, instance,
                                               self._snap_disks)
    msg = result.fail_msg
    fin_resu = not msg
    if msg:
      self._lu.LogWarning("Could not finalize export for instance %s"
                          " on node %s: %s", instance.name, dest_node.name, msg)

    return (fin_resu, dresults)

  def RemoteExport(self, disk_info, key_name, dest_ca_pem, compress, timeouts):
    """Inter-cluster instance export.

    @type disk_info: list
    @param disk_info: Per-disk destination information
    @type key_name: string
    @param key_name: Name of X509 key to use
    @type dest_ca_pem: string
    @param dest_ca_pem: Destination X509 CA in PEM format
    @type compress: string
    @param compress: one of L{constants.IEC_ALL}
    @type timeouts: L{ImportExportTimeouts}
    @param timeouts: Timeouts for this import

    """
    instance = self._instance

    assert len(disk_info) == len(instance.disks)

    cbs = _RemoteExportCb(self._feedback_fn, len(instance.disks))

    ieloop = ImportExportLoop(self._lu)
    try:
      for idx, (dev, (host, port, magic)) in enumerate(zip(instance.disks,
                                                           disk_info)):
        # Decide whether to use IPv6
        ipv6 = netutils.IP6Address.IsValid(host)

        opts = objects.ImportExportOptions(key_name=key_name,
                                           ca_pem=dest_ca_pem,
                                           magic=magic,
                                           compress=compress,
                                           ipv6=ipv6)

        self._feedback_fn("Sending disk %s to %s:%s" % (idx, host, port))
        finished_fn = compat.partial(self._TransferFinished, idx)
        ieloop.Add(DiskExport(self._lu, instance.primary_node,
                              opts, host, port, instance, "disk%d" % idx,
                              constants.IEIO_SCRIPT, ((dev, instance), idx),
                              timeouts, cbs, private=(idx, finished_fn)))

      ieloop.Run()
    finally:
      ieloop.FinalizeAll()

    return (True, cbs.disk_results)

  def _TransferFinished(self, idx):
    """Called once a transfer has finished.

    @type idx: number
    @param idx: Disk index

    """
    logging.debug("Transfer %s finished", idx)
    self._RemoveSnapshot(idx)

  def Cleanup(self):
    """Remove all snapshots.

    """
    assert len(self._removed_snaps) == len(self._instance.disks)
    for idx in range(len(self._instance.disks)):
      self._RemoveSnapshot(idx)


class _RemoteImportCb(ImportExportCbBase):
  def __init__(self, feedback_fn, cds, x509_cert_pem, disk_count,
               external_address):
    """Initializes this class.

    @type cds: string
    @param cds: Cluster domain secret
    @type x509_cert_pem: string
    @param x509_cert_pem: CA used for signing import key
    @type disk_count: number
    @param disk_count: Number of disks
    @type external_address: string
    @param external_address: External address of destination node

    """
    ImportExportCbBase.__init__(self)
    self._feedback_fn = feedback_fn
    self._cds = cds
    self._x509_cert_pem = x509_cert_pem
    self._disk_count = disk_count
    self._external_address = external_address

    self._dresults = [None] * disk_count
    self._daemon_port = [None] * disk_count

    self._salt = utils.GenerateSecret(8)

  @property
  def disk_results(self):
    """Returns per-disk results.

    """
    return self._dresults

  def _CheckAllListening(self):
    """Checks whether all daemons are listening.

    If all daemons are listening, the information is sent to the client.

    """
    if not compat.all(dp is not None for dp in self._daemon_port):
      return

    host = self._external_address

    disks = []
    for idx, (port, magic) in enumerate(self._daemon_port):
      disks.append(ComputeRemoteImportDiskInfo(self._cds, self._salt,
                                               idx, host, port, magic))

    assert len(disks) == self._disk_count

    self._feedback_fn(constants.ELOG_REMOTE_IMPORT, {
      "disks": disks,
      "x509_ca": self._x509_cert_pem,
      })

  def ReportListening(self, ie, private, _):
    """Called when daemon started listening.

    """
    (idx, ) = private

    self._feedback_fn("Disk %s is now listening" % idx)

    assert self._daemon_port[idx] is None

    self._daemon_port[idx] = (ie.listen_port, ie.magic)

    self._CheckAllListening()

  def ReportConnected(self, ie, private):
    """Called when a connection has been established.

    """
    (idx, ) = private

    self._feedback_fn("Disk %s is now receiving data" % idx)

  def ReportFinished(self, ie, private):
    """Called when a transfer has finished.

    """
    (idx, ) = private

    # Daemon is certainly no longer listening
    self._daemon_port[idx] = None

    if ie.success:
      self._feedback_fn("Disk %s finished receiving data" % idx)
    else:
      self._feedback_fn(("Disk %s failed to receive data: %s"
                         " (recent output: %s)") %
                        (idx, ie.final_message, ie.recent_output))

    self._dresults[idx] = bool(ie.success)


def RemoteImport(lu, feedback_fn, instance, pnode, source_x509_ca,
                 cds, compress, timeouts):
  """Imports an instance from another cluster.

  @param lu: Logical unit instance
  @param feedback_fn: Feedback function
  @type instance: L{objects.Instance}
  @param instance: Instance object
  @type pnode: L{objects.Node}
  @param pnode: Primary node of instance as an object
  @type source_x509_ca: OpenSSL.crypto.X509
  @param source_x509_ca: Import source's X509 CA
  @type cds: string
  @param cds: Cluster domain secret
  @type compress: string
  @param compress: one of L{constants.IEC_ALL}
  @type timeouts: L{ImportExportTimeouts}
  @param timeouts: Timeouts for this import

  """
  source_ca_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                  source_x509_ca)

  magic_base = utils.GenerateSecret(6)

  # Decide whether to use IPv6
  ipv6 = netutils.IP6Address.IsValid(pnode.primary_ip)

  # Create crypto key
  result = lu.rpc.call_x509_cert_create(instance.primary_node,
                                        constants.RIE_CERT_VALIDITY)
  result.Raise("Can't create X509 key and certificate on %s" % result.node)

  (x509_key_name, x509_cert_pem) = result.payload
  try:
    # Load certificate
    x509_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                x509_cert_pem)

    # Sign certificate
    signed_x509_cert_pem = \
      utils.SignX509Certificate(x509_cert, cds, utils.GenerateSecret(8))

    cbs = _RemoteImportCb(feedback_fn, cds, signed_x509_cert_pem,
                          len(instance.disks), pnode.primary_ip)

    ieloop = ImportExportLoop(lu)
    try:
      for idx, dev in enumerate(instance.disks):
        magic = _GetInstDiskMagic(magic_base, instance.name, idx)

        # Import daemon options
        opts = objects.ImportExportOptions(key_name=x509_key_name,
                                           ca_pem=source_ca_pem,
                                           magic=magic,
                                           compress=compress,
                                           ipv6=ipv6)

        ieloop.Add(DiskImport(lu, instance.primary_node, opts, instance,
                              "disk%d" % idx,
                              constants.IEIO_SCRIPT, ((dev, instance), idx),
                              timeouts, cbs, private=(idx, )))

      ieloop.Run()
    finally:
      ieloop.FinalizeAll()
  finally:
    # Remove crypto key and certificate
    result = lu.rpc.call_x509_cert_remove(instance.primary_node, x509_key_name)
    result.Raise("Can't remove X509 key and certificate on %s" % result.node)

  return cbs.disk_results


def _GetImportExportHandshakeMessage(version):
  """Returns the handshake message for a RIE protocol version.

  @type version: number

  """
  return "%s:%s" % (version, constants.RIE_HANDSHAKE)


def ComputeRemoteExportHandshake(cds):
  """Computes the remote import/export handshake.

  @type cds: string
  @param cds: Cluster domain secret

  """
  salt = utils.GenerateSecret(8)
  msg = _GetImportExportHandshakeMessage(constants.RIE_VERSION)
  return (constants.RIE_VERSION, utils.Sha1Hmac(cds, msg, salt=salt), salt)


def CheckRemoteExportHandshake(cds, handshake):
  """Checks the handshake of a remote import/export.

  @type cds: string
  @param cds: Cluster domain secret
  @type handshake: sequence
  @param handshake: Handshake sent by remote peer

  """
  try:
    (version, hmac_digest, hmac_salt) = handshake
  except (TypeError, ValueError), err:
    return "Invalid data: %s" % err

  if not utils.VerifySha1Hmac(cds, _GetImportExportHandshakeMessage(version),
                              hmac_digest, salt=hmac_salt):
    return "Hash didn't match, clusters don't share the same domain secret"

  if version != constants.RIE_VERSION:
    return ("Clusters don't have the same remote import/export protocol"
            " (local=%s, remote=%s)" %
            (constants.RIE_VERSION, version))

  return None


def _GetRieDiskInfoMessage(disk_index, host, port, magic):
  """Returns the hashed text for import/export disk information.

  @type disk_index: number
  @param disk_index: Index of disk (included in hash)
  @type host: string
  @param host: Hostname
  @type port: number
  @param port: Daemon port
  @type magic: string
  @param magic: Magic value

  """
  return "%s:%s:%s:%s" % (disk_index, host, port, magic)


def CheckRemoteExportDiskInfo(cds, disk_index, disk_info):
  """Verifies received disk information for an export.

  @type cds: string
  @param cds: Cluster domain secret
  @type disk_index: number
  @param disk_index: Index of disk (included in hash)
  @type disk_info: sequence
  @param disk_info: Disk information sent by remote peer

  """
  try:
    (host, port, magic, hmac_digest, hmac_salt) = disk_info
  except (TypeError, ValueError), err:
    raise errors.GenericError("Invalid data: %s" % err)

  if not (host and port and magic):
    raise errors.GenericError("Missing destination host, port or magic")

  msg = _GetRieDiskInfoMessage(disk_index, host, port, magic)

  if not utils.VerifySha1Hmac(cds, msg, hmac_digest, salt=hmac_salt):
    raise errors.GenericError("HMAC is wrong")

  if netutils.IP6Address.IsValid(host) or netutils.IP4Address.IsValid(host):
    destination = host
  else:
    destination = netutils.Hostname.GetNormalizedName(host)

  return (destination,
          utils.ValidateServiceName(port),
          magic)


def ComputeRemoteImportDiskInfo(cds, salt, disk_index, host, port, magic):
  """Computes the signed disk information for a remote import.

  @type cds: string
  @param cds: Cluster domain secret
  @type salt: string
  @param salt: HMAC salt
  @type disk_index: number
  @param disk_index: Index of disk (included in hash)
  @type host: string
  @param host: Hostname
  @type port: number
  @param port: Daemon port
  @type magic: string
  @param magic: Magic value

  """
  msg = _GetRieDiskInfoMessage(disk_index, host, port, magic)
  hmac_digest = utils.Sha1Hmac(cds, msg, salt=salt)
  return (host, port, magic, hmac_digest, salt)


def CalculateGroupIPolicy(cluster, group):
  """Calculate instance policy for group.

  """
  return cluster.SimpleFillIPolicy(group.ipolicy)


def ComputeDiskSize(disk_template, disks):
  """Compute disk size requirements according to disk template

  """
  # Required free disk space as a function of disk and swap space
  req_size_dict = {
    constants.DT_DISKLESS: 0,
    constants.DT_PLAIN: sum(d[constants.IDISK_SIZE] for d in disks),
    # 128 MB are added for drbd metadata for each disk
    constants.DT_DRBD8:
      sum(d[constants.IDISK_SIZE] + constants.DRBD_META_SIZE for d in disks),
    constants.DT_FILE: sum(d[constants.IDISK_SIZE] for d in disks),
    constants.DT_SHARED_FILE: sum(d[constants.IDISK_SIZE] for d in disks),
    constants.DT_GLUSTER: sum(d[constants.IDISK_SIZE] for d in disks),
    constants.DT_BLOCK: 0,
    constants.DT_RBD: sum(d[constants.IDISK_SIZE] for d in disks),
    constants.DT_EXT: sum(d[constants.IDISK_SIZE] for d in disks),
  }

  if disk_template not in req_size_dict:
    raise errors.ProgrammerError("Disk template '%s' size requirement"
                                 " is unknown" % disk_template)

  return req_size_dict[disk_template]
