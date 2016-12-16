#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""DRBD block device related functionality"""

import errno
import logging
import time

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import netutils
from ganeti import objects
from ganeti.storage import base
from ganeti.storage.drbd_info import DRBD8Info
from ganeti.storage import drbd_info
from ganeti.storage import drbd_cmdgen


# Size of reads in _CanReadDevice

_DEVICE_READ_SIZE = 128 * 1024


class DRBD8(object):
  """Various methods to deals with the DRBD system as a whole.

  This class provides a set of methods to deal with the DRBD installation on
  the node or with uninitialized devices as opposed to a DRBD device.

  """
  _USERMODE_HELPER_FILE = "/sys/module/drbd/parameters/usermode_helper"

  _MAX_MINORS = 255

  @staticmethod
  def GetUsermodeHelper(filename=_USERMODE_HELPER_FILE):
    """Returns DRBD usermode_helper currently set.

    @type filename: string
    @param filename: the filename to read the usermode helper from
    @rtype: string
    @return: the currently configured DRBD usermode helper

    """
    try:
      helper = utils.ReadFile(filename).splitlines()[0]
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        base.ThrowError("The file %s cannot be opened, check if the module"
                        " is loaded (%s)", filename, str(err))
      else:
        base.ThrowError("Can't read DRBD helper file %s: %s",
                        filename, str(err))
    if not helper:
      base.ThrowError("Can't read any data from %s", filename)
    return helper

  @staticmethod
  def GetProcInfo():
    """Reads and parses information from /proc/drbd.

    @rtype: DRBD8Info
    @return: a L{DRBD8Info} instance containing the current /proc/drbd info

    """
    return DRBD8Info.CreateFromFile()

  @staticmethod
  def GetUsedDevs():
    """Compute the list of used DRBD minors.

    @rtype: list of ints

    """
    info = DRBD8.GetProcInfo()
    return [m for m in info.GetMinors()
            if not info.GetMinorStatus(m).is_unconfigured]

  @staticmethod
  def FindUnusedMinor():
    """Find an unused DRBD device.

    This is specific to 8.x as the minors are allocated dynamically,
    so non-existing numbers up to a max minor count are actually free.

    @rtype: int

    """
    highest = None
    info = DRBD8.GetProcInfo()
    for minor in info.GetMinors():
      status = info.GetMinorStatus(minor)
      if not status.is_in_use:
        return minor
      highest = max(highest, minor)

    if highest is None: # there are no minors in use at all
      return 0
    if highest >= DRBD8._MAX_MINORS:
      logging.error("Error: no free drbd minors!")
      raise errors.BlockDeviceError("Can't find a free DRBD minor")

    return highest + 1

  @staticmethod
  def GetCmdGenerator(info):
    """Creates a suitable L{BaseDRBDCmdGenerator} based on the given info.

    @type info: DRBD8Info
    @rtype: BaseDRBDCmdGenerator

    """
    version = info.GetVersion()
    if version["k_minor"] <= 3:
      return drbd_cmdgen.DRBD83CmdGenerator(version)
    else:
      return drbd_cmdgen.DRBD84CmdGenerator(version)

  @staticmethod
  def ShutdownAll(minor):
    """Deactivate the device.

    This will, of course, fail if the device is in use.

    @type minor: int
    @param minor: the minor to shut down

    """
    info = DRBD8.GetProcInfo()
    cmd_gen = DRBD8.GetCmdGenerator(info)

    cmd = cmd_gen.GenDownCmd(minor)
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: can't shutdown drbd device: %s",
                      minor, result.output)


class DRBD8Dev(base.BlockDev):
  """DRBD v8.x block device.

  This implements the local host part of the DRBD device, i.e. it
  doesn't do anything to the supposed peer. If you need a fully
  connected DRBD pair, you need to use this class on both hosts.

  The unique_id for the drbd device is a (pnode_uuid, snode_uuid,
  port, pnode_minor, lnode_minor, secret) tuple, and it must have
  two children: the data device and the meta_device. The meta
  device is checked for valid size and is zeroed on create.

  """
  _DRBD_MAJOR = 147

  # timeout constants
  _NET_RECONFIG_TIMEOUT = 60

  def __init__(self, unique_id, children, size, params, dyn_params, **kwargs):
    if children and children.count(None) > 0:
      children = []
    if len(children) not in (0, 2):
      raise ValueError("Invalid configuration data %s" % str(children))
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 6:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    if constants.DDP_LOCAL_IP not in dyn_params or \
       constants.DDP_REMOTE_IP not in dyn_params or \
       constants.DDP_LOCAL_MINOR not in dyn_params or \
       constants.DDP_REMOTE_MINOR not in dyn_params:
      raise ValueError("Invalid dynamic parameters %s" % str(dyn_params))

    self._lhost = dyn_params[constants.DDP_LOCAL_IP]
    self._lport = unique_id[2]
    self._rhost = dyn_params[constants.DDP_REMOTE_IP]
    self._rport = unique_id[2]
    self._aminor = dyn_params[constants.DDP_LOCAL_MINOR]
    # The secret is wrapped in the Private data type, and it has to be extracted
    # before use
    self._secret = unique_id[5].Get()

    if children:
      if not _CanReadDevice(children[1].dev_path):
        logging.info("drbd%s: Ignoring unreadable meta device", self._aminor)
        children = []
    super(DRBD8Dev, self).__init__(unique_id, children, size, params,
                                   dyn_params, **kwargs)
    self.major = self._DRBD_MAJOR

    info = DRBD8.GetProcInfo()
    version = info.GetVersion()
    if version["k_major"] != 8:
      base.ThrowError("Mismatch in DRBD kernel version and requested ganeti"
                      " usage: kernel is %s.%s, ganeti wants 8.x",
                      version["k_major"], version["k_minor"])

    if version["k_minor"] <= 3:
      self._show_info_cls = drbd_info.DRBD83ShowInfo
    else:
      self._show_info_cls = drbd_info.DRBD84ShowInfo

    self._cmd_gen = DRBD8.GetCmdGenerator(info)

    if (self._lhost is not None and self._lhost == self._rhost and
            self._lport == self._rport):
      raise ValueError("Invalid configuration data, same local/remote %s, %s" %
                       (unique_id, dyn_params))
    self.Attach()

  @staticmethod
  def _DevPath(minor):
    """Return the path to a drbd device for a given minor.

    @type minor: int
    @rtype: string

    """
    return "/dev/drbd%d" % minor

  def _SetFromMinor(self, minor):
    """Set our parameters based on the given minor.

    This sets our minor variable and our dev_path.

    @type minor: int

    """
    if minor is None:
      self.minor = self.dev_path = None
      self.attached = False
    else:
      self.minor = minor
      self.dev_path = self._DevPath(minor)
      self.attached = True

  @staticmethod
  def _CheckMetaSize(meta_device):
    """Check if the given meta device looks like a valid one.

    This currently only checks the size, which must be around
    128MiB.

    @type meta_device: string
    @param meta_device: the path to the device to check

    """
    result = utils.RunCmd(["blockdev", "--getsize", meta_device])
    if result.failed:
      base.ThrowError("Failed to get device size: %s - %s",
                      result.fail_reason, result.output)
    try:
      sectors = int(result.stdout)
    except (TypeError, ValueError):
      base.ThrowError("Invalid output from blockdev: '%s'", result.stdout)
    num_bytes = sectors * 512
    if num_bytes < 128 * 1024 * 1024: # less than 128MiB
      base.ThrowError("Meta device too small (%.2fMib)",
                      (num_bytes / 1024 / 1024))
    # the maximum *valid* size of the meta device when living on top
    # of LVM is hard to compute: it depends on the number of stripes
    # and the PE size; e.g. a 2-stripe, 64MB PE will result in a 128MB
    # (normal size), but an eight-stripe 128MB PE will result in a 1GB
    # size meta device; as such, we restrict it to 1GB (a little bit
    # too generous, but making assumptions about PE size is hard)
    if num_bytes > 1024 * 1024 * 1024:
      base.ThrowError("Meta device too big (%.2fMiB)",
                      (num_bytes / 1024 / 1024))

  def _GetShowData(self, minor):
    """Return the `drbdsetup show` data.

    @type minor: int
    @param minor: the minor to collect show output for
    @rtype: string

    """
    result = utils.RunCmd(self._cmd_gen.GenShowCmd(minor))
    if result.failed:
      logging.error("Can't display the drbd config: %s - %s",
                    result.fail_reason, result.output)
      return None
    return result.stdout

  def _GetShowInfo(self, minor):
    """Return parsed information from `drbdsetup show`.

    @type minor: int
    @param minor: the minor to return information for
    @rtype: dict as described in L{drbd_info.BaseShowInfo.GetDevInfo}

    """
    return self._show_info_cls.GetDevInfo(self._GetShowData(minor))

  def _MatchesLocal(self, info):
    """Test if our local config matches with an existing device.

    The parameter should be as returned from `_GetShowInfo()`. This
    method tests if our local backing device is the same as the one in
    the info parameter, in effect testing if we look like the given
    device.

    @type info: dict as described in L{drbd_info.BaseShowInfo.GetDevInfo}
    @rtype: boolean

    """
    if self._children:
      backend, meta = self._children
    else:
      backend = meta = None

    if backend is not None:
      retval = ("local_dev" in info and info["local_dev"] == backend.dev_path)
    else:
      retval = ("local_dev" not in info)

    if meta is not None:
      retval = retval and ("meta_dev" in info and
                           info["meta_dev"] == meta.dev_path)
      if "meta_index" in info:
        retval = retval and info["meta_index"] == 0
    else:
      retval = retval and ("meta_dev" not in info and
                           "meta_index" not in info)
    return retval

  def _MatchesNet(self, info):
    """Test if our network config matches with an existing device.

    The parameter should be as returned from `_GetShowInfo()`. This
    method tests if our network configuration is the same as the one
    in the info parameter, in effect testing if we look like the given
    device.

    @type info: dict as described in L{drbd_info.BaseShowInfo.GetDevInfo}
    @rtype: boolean

    """
    if (((self._lhost is None and not ("local_addr" in info)) and
         (self._rhost is None and not ("remote_addr" in info)))):
      return True

    if self._lhost is None:
      return False

    if not ("local_addr" in info and
            "remote_addr" in info):
      return False

    retval = (info["local_addr"] == (self._lhost, self._lport))
    retval = (retval and
              info["remote_addr"] == (self._rhost, self._rport))
    return retval

  def _AssembleLocal(self, minor, backend, meta, size):
    """Configure the local part of a DRBD device.

    @type minor: int
    @param minor: the minor to assemble locally
    @type backend: string
    @param backend: path to the data device to use
    @type meta: string
    @param meta: path to the meta device to use
    @type size: int
    @param size: size in MiB

    """
    cmds = self._cmd_gen.GenLocalInitCmds(minor, backend, meta,
                                          size, self.params)

    for cmd in cmds:
      result = utils.RunCmd(cmd)
      if result.failed:
        base.ThrowError("drbd%d: can't attach local disk: %s",
                        minor, result.output)

  def _AssembleNet(self, minor, net_info, dual_pri=False, hmac=None,
                   secret=None):
    """Configure the network part of the device.

    @type minor: int
    @param minor: the minor to assemble the network for
    @type net_info: (string, int, string, int)
    @param net_info: tuple containing the local address, local port, remote
      address and remote port
    @type dual_pri: boolean
    @param dual_pri: whether two primaries should be allowed or not
    @type hmac: string
    @param hmac: the HMAC algorithm to use
    @type secret: string
    @param secret: the shared secret to use

    """
    lhost, lport, rhost, rport = net_info
    if None in net_info:
      # we don't want network connection and actually want to make
      # sure its shutdown
      self._ShutdownNet(minor)
      return

    if dual_pri:
      protocol = constants.DRBD_MIGRATION_NET_PROTOCOL
    else:
      protocol = self.params[constants.LDP_PROTOCOL]

    # Workaround for a race condition. When DRBD is doing its dance to
    # establish a connection with its peer, it also sends the
    # synchronization speed over the wire. In some cases setting the
    # sync speed only after setting up both sides can race with DRBD
    # connecting, hence we set it here before telling DRBD anything
    # about its peer.
    sync_errors = self._SetMinorSyncParams(minor, self.params)
    if sync_errors:
      base.ThrowError("drbd%d: can't set the synchronization parameters: %s" %
                      (minor, utils.CommaJoin(sync_errors)))

    family = self._GetNetFamily(minor, lhost, rhost)

    cmd = self._cmd_gen.GenNetInitCmd(minor, family, lhost, lport,
                                      rhost, rport, protocol,
                                      dual_pri, hmac, secret, self.params)

    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: can't setup network: %s - %s",
                      minor, result.fail_reason, result.output)

    def _CheckNetworkConfig():
      info = self._GetShowInfo(minor)
      if not "local_addr" in info or not "remote_addr" in info:
        raise utils.RetryAgain()

      if (info["local_addr"] != (lhost, lport) or
          info["remote_addr"] != (rhost, rport)):
        raise utils.RetryAgain()

    try:
      utils.Retry(_CheckNetworkConfig, 1.0, 10.0)
    except utils.RetryTimeout:
      base.ThrowError("drbd%d: timeout while configuring network", minor)

    # Once the assembly is over, try to set the synchronization parameters
    try:
      # The minor may not have been set yet, requiring us to set it at least
      # temporarily
      old_minor = self.minor
      self._SetFromMinor(minor)
      sync_errors = self.SetSyncParams(self.params)
      if sync_errors:
        base.ThrowError("drbd%d: can't set the synchronization parameters: %s" %
                        (self.minor, utils.CommaJoin(sync_errors)))
    finally:
      # Undo the change, regardless of whether it will have to be done again
      # soon
      self._SetFromMinor(old_minor)

  @staticmethod
  def _GetNetFamily(minor, lhost, rhost):
    if netutils.IP6Address.IsValid(lhost):
      if not netutils.IP6Address.IsValid(rhost):
        base.ThrowError("drbd%d: can't connect ip %s to ip %s" %
                        (minor, lhost, rhost))
      return "ipv6"
    elif netutils.IP4Address.IsValid(lhost):
      if not netutils.IP4Address.IsValid(rhost):
        base.ThrowError("drbd%d: can't connect ip %s to ip %s" %
                        (minor, lhost, rhost))
      return "ipv4"
    else:
      base.ThrowError("drbd%d: Invalid ip %s" % (minor, lhost))

  def AddChildren(self, devices):
    """Add a disk to the DRBD device.

    @type devices: list of L{BlockDev}
    @param devices: a list of exactly two L{BlockDev} objects; the first
      denotes the data device, the second the meta device for this DRBD device

    """
    if self.minor is None:
      base.ThrowError("drbd%d: can't attach to dbrd8 during AddChildren",
                      self._aminor)
    if len(devices) != 2:
      base.ThrowError("drbd%d: need two devices for AddChildren", self.minor)
    info = self._GetShowInfo(self.minor)
    if "local_dev" in info:
      base.ThrowError("drbd%d: already attached to a local disk", self.minor)
    backend, meta = devices
    if backend.dev_path is None or meta.dev_path is None:
      base.ThrowError("drbd%d: children not ready during AddChildren",
                      self.minor)
    backend.Open()
    meta.Open()
    self._CheckMetaSize(meta.dev_path)
    self._InitMeta(DRBD8.FindUnusedMinor(), meta.dev_path)

    self._AssembleLocal(self.minor, backend.dev_path, meta.dev_path, self.size)
    self._children = devices

  def RemoveChildren(self, devices):
    """Detach the drbd device from local storage.

    @type devices: list of L{BlockDev}
    @param devices: a list of exactly two L{BlockDev} objects; the first
      denotes the data device, the second the meta device for this DRBD device

    """
    if self.minor is None:
      base.ThrowError("drbd%d: can't attach to drbd8 during RemoveChildren",
                      self._aminor)
    # early return if we don't actually have backing storage
    info = self._GetShowInfo(self.minor)
    if "local_dev" not in info:
      return
    if len(self._children) != 2:
      base.ThrowError("drbd%d: we don't have two children: %s", self.minor,
                      self._children)
    if self._children.count(None) == 2: # we don't actually have children :)
      logging.warning("drbd%d: requested detach while detached", self.minor)
      return
    if len(devices) != 2:
      base.ThrowError("drbd%d: we need two children in RemoveChildren",
                      self.minor)
    for child, dev in zip(self._children, devices):
      if dev != child.dev_path:
        base.ThrowError("drbd%d: mismatch in local storage (%s != %s) in"
                        " RemoveChildren", self.minor, dev, child.dev_path)

    self._ShutdownLocal(self.minor)
    self._children = []

  def _SetMinorSyncParams(self, minor, params):
    """Set the parameters of the DRBD syncer.

    This is the low-level implementation.

    @type minor: int
    @param minor: the drbd minor whose settings we change
    @type params: dict
    @param params: LD level disk parameters related to the synchronization
    @rtype: list
    @return: a list of error messages

    """
    cmd = self._cmd_gen.GenSyncParamsCmd(minor, params)
    result = utils.RunCmd(cmd)
    if result.failed:
      msg = ("Can't change syncer rate: %s - %s" %
             (result.fail_reason, result.output))
      logging.error(msg)
      return [msg]

    return []

  def SetSyncParams(self, params):
    """Set the synchronization parameters of the DRBD syncer.

    See L{BlockDev.SetSyncParams} for parameter description.

    """
    if self.minor is None:
      err = "Not attached during SetSyncParams"
      logging.info(err)
      return [err]

    children_result = super(DRBD8Dev, self).SetSyncParams(params)
    children_result.extend(self._SetMinorSyncParams(self.minor, params))
    return children_result

  def PauseResumeSync(self, pause):
    """Pauses or resumes the sync of a DRBD device.

    See L{BlockDev.PauseResumeSync} for parameter description.

    """
    if self.minor is None:
      logging.info("Not attached during PauseSync")
      return False

    children_result = super(DRBD8Dev, self).PauseResumeSync(pause)

    if pause:
      cmd = self._cmd_gen.GenPauseSyncCmd(self.minor)
    else:
      cmd = self._cmd_gen.GenResumeSyncCmd(self.minor)

    result = utils.RunCmd(cmd)
    if result.failed:
      logging.error("Can't %s: %s - %s", cmd,
                    result.fail_reason, result.output)
    return not result.failed and children_result

  def GetProcStatus(self):
    """Return the current status data from /proc/drbd for this device.

    @rtype: DRBD8Status

    """
    if self.minor is None:
      base.ThrowError("drbd%d: GetStats() called while not attached",
                      self._aminor)
    info = DRBD8.GetProcInfo()
    if not info.HasMinorStatus(self.minor):
      base.ThrowError("drbd%d: can't find myself in /proc", self.minor)
    return info.GetMinorStatus(self.minor)

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    If sync_percent is None, it means all is ok
    If estimated_time is None, it means we can't estimate
    the time needed, otherwise it's the time left in seconds.

    We set the is_degraded parameter to True on two conditions:
    network not connected or local disk missing.

    We compute the ldisk parameter based on whether we have a local
    disk or not.

    @rtype: objects.BlockDevStatus

    """
    if self.minor is None and not self.Attach():
      base.ThrowError("drbd%d: can't Attach() in GetSyncStatus", self._aminor)

    stats = self.GetProcStatus()
    is_degraded = not stats.is_connected or not stats.is_disk_uptodate

    if stats.is_disk_uptodate:
      ldisk_status = constants.LDS_OKAY
    elif stats.is_diskless:
      ldisk_status = constants.LDS_FAULTY
    elif stats.is_in_resync:
      ldisk_status = constants.LDS_SYNC
    else:
      ldisk_status = constants.LDS_UNKNOWN

    return objects.BlockDevStatus(dev_path=self.dev_path,
                                  major=self.major,
                                  minor=self.minor,
                                  sync_percent=stats.sync_percent,
                                  estimated_time=stats.est_time,
                                  is_degraded=is_degraded,
                                  ldisk_status=ldisk_status)

  def Open(self, force=False, exclusive=True):
    """Make the local state primary.

    If the 'force' parameter is given, DRBD is instructed to switch the device
    into primary mode. Since this is a potentially dangerous operation, the
    force flag should be only given after creation, when it actually is
    mandatory.

    """
    if self.minor is None and not self.Attach():
      logging.error("DRBD cannot attach to a device during open")
      return False

    cmd = self._cmd_gen.GenPrimaryCmd(self.minor, force)

    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: can't make drbd device primary: %s", self.minor,
                      result.output)

  def Close(self):
    """Make the local state secondary.

    This will, of course, fail if the device is in use.

    """
    if self.minor is None and not self.Attach():
      base.ThrowError("drbd%d: can't Attach() in Close()", self._aminor)
    cmd = self._cmd_gen.GenSecondaryCmd(self.minor)
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: can't switch drbd device to secondary: %s",
                      self.minor, result.output)

  def DisconnectNet(self):
    """Removes network configuration.

    This method shutdowns the network side of the device.

    The method will wait up to a hardcoded timeout for the device to
    go into standalone after the 'disconnect' command before
    re-configuring it, as sometimes it takes a while for the
    disconnect to actually propagate and thus we might issue a 'net'
    command while the device is still connected. If the device will
    still be attached to the network and we time out, we raise an
    exception.

    """
    if self.minor is None:
      base.ThrowError("drbd%d: disk not attached in re-attach net",
                      self._aminor)

    if None in (self._lhost, self._lport, self._rhost, self._rport):
      base.ThrowError("drbd%d: DRBD disk missing network info in"
                      " DisconnectNet()", self.minor)

    class _DisconnectStatus(object):
      def __init__(self, ever_disconnected):
        self.ever_disconnected = ever_disconnected

    dstatus = _DisconnectStatus(base.IgnoreError(self._ShutdownNet, self.minor))

    def _WaitForDisconnect():
      if self.GetProcStatus().is_standalone:
        return

      # retry the disconnect, it seems possible that due to a well-time
      # disconnect on the peer, my disconnect command might be ignored and
      # forgotten
      dstatus.ever_disconnected = \
        base.IgnoreError(self._ShutdownNet, self.minor) or \
        dstatus.ever_disconnected

      raise utils.RetryAgain()

    # Keep start time
    start_time = time.time()

    try:
      # Start delay at 100 milliseconds and grow up to 2 seconds
      utils.Retry(_WaitForDisconnect, (0.1, 1.5, 2.0),
                  self._NET_RECONFIG_TIMEOUT)
    except utils.RetryTimeout:
      if dstatus.ever_disconnected:
        msg = ("drbd%d: device did not react to the"
               " 'disconnect' command in a timely manner")
      else:
        msg = "drbd%d: can't shutdown network, even after multiple retries"

      base.ThrowError(msg, self.minor)

    reconfig_time = time.time() - start_time
    if reconfig_time > (self._NET_RECONFIG_TIMEOUT * 0.25):
      logging.info("drbd%d: DisconnectNet: detach took %.3f seconds",
                   self.minor, reconfig_time)

  def AttachNet(self, multimaster):
    """Reconnects the network.

    This method connects the network side of the device with a
    specified multi-master flag. The device needs to be 'Standalone'
    but have valid network configuration data.

    @type multimaster: boolean
    @param multimaster: init the network in dual-primary mode

    """
    if self.minor is None:
      base.ThrowError("drbd%d: device not attached in AttachNet", self._aminor)

    if None in (self._lhost, self._lport, self._rhost, self._rport):
      base.ThrowError("drbd%d: missing network info in AttachNet()", self.minor)

    status = self.GetProcStatus()

    if not status.is_standalone:
      base.ThrowError("drbd%d: device is not standalone in AttachNet",
                      self.minor)

    self._AssembleNet(self.minor,
                      (self._lhost, self._lport, self._rhost, self._rport),
                      dual_pri=multimaster, hmac=constants.DRBD_HMAC_ALG,
                      secret=self._secret)

  def Attach(self, **kwargs):
    """Check if our minor is configured.

    This doesn't do any device configurations - it only checks if the
    minor is in a state different from Unconfigured.

    Note that this function will not change the state of the system in
    any way (except in case of side-effects caused by reading from
    /proc).

    """
    used_devs = DRBD8.GetUsedDevs()
    if self._aminor in used_devs:
      minor = self._aminor
    else:
      minor = None

    self._SetFromMinor(minor)
    return minor is not None

  def Assemble(self):
    """Assemble the drbd.

    Method:
      - if we have a configured device, we try to ensure that it matches
        our config
      - if not, we create it from zero
      - anyway, set the device parameters

    """
    super(DRBD8Dev, self).Assemble()

    self.Attach()
    if self.minor is None:
      # local device completely unconfigured
      self._FastAssemble()
    else:
      # we have to recheck the local and network status and try to fix
      # the device
      self._SlowAssemble()

  def _SlowAssemble(self):
    """Assembles the DRBD device from a (partially) configured device.

    In case of partially attached (local device matches but no network
    setup), we perform the network attach. If successful, we re-test
    the attach if can return success.

    """
    # TODO: Rewrite to not use a for loop just because there is 'break'
    # pylint: disable=W0631
    net_data = (self._lhost, self._lport, self._rhost, self._rport)
    for minor in (self._aminor,):
      info = self._GetShowInfo(minor)
      match_l = self._MatchesLocal(info)
      match_r = self._MatchesNet(info)

      if match_l and match_r:
        # everything matches
        break

      if match_l and not match_r and "local_addr" not in info:
        # disk matches, but not attached to network, attach and recheck
        self._AssembleNet(minor, net_data, hmac=constants.DRBD_HMAC_ALG,
                          secret=self._secret)
        if self._MatchesNet(self._GetShowInfo(minor)):
          break
        else:
          base.ThrowError("drbd%d: network attach successful, but 'drbdsetup"
                          " show' disagrees", minor)

      if match_r and "local_dev" not in info:
        # no local disk, but network attached and it matches
        self._AssembleLocal(minor, self._children[0].dev_path,
                            self._children[1].dev_path, self.size)
        if self._MatchesLocal(self._GetShowInfo(minor)):
          break
        else:
          base.ThrowError("drbd%d: disk attach successful, but 'drbdsetup"
                          " show' disagrees", minor)

      # this case must be considered only if we actually have local
      # storage, i.e. not in diskless mode, because all diskless
      # devices are equal from the point of view of local
      # configuration
      if (match_l and "local_dev" in info and
          not match_r and "local_addr" in info):
        # strange case - the device network part points to somewhere
        # else, even though its local storage is ours; as we own the
        # drbd space, we try to disconnect from the remote peer and
        # reconnect to our correct one
        try:
          self._ShutdownNet(minor)
        except errors.BlockDeviceError, err:
          base.ThrowError("drbd%d: device has correct local storage, wrong"
                          " remote peer and is unable to disconnect in order"
                          " to attach to the correct peer: %s", minor, str(err))
        # note: _AssembleNet also handles the case when we don't want
        # local storage (i.e. one or more of the _[lr](host|port) is
        # None)
        self._AssembleNet(minor, net_data, hmac=constants.DRBD_HMAC_ALG,
                          secret=self._secret)
        if self._MatchesNet(self._GetShowInfo(minor)):
          break
        else:
          base.ThrowError("drbd%d: network attach successful, but 'drbdsetup"
                          " show' disagrees", minor)

    else:
      minor = None

    self._SetFromMinor(minor)
    if minor is None:
      base.ThrowError("drbd%d: cannot activate, unknown or unhandled reason",
                      self._aminor)

  def _FastAssemble(self):
    """Assemble the drbd device from zero.

    This is run when in Assemble we detect our minor is unused.

    """
    minor = self._aminor
    if self._children and self._children[0] and self._children[1]:
      self._AssembleLocal(minor, self._children[0].dev_path,
                          self._children[1].dev_path, self.size)
    if self._lhost and self._lport and self._rhost and self._rport:
      self._AssembleNet(minor,
                        (self._lhost, self._lport, self._rhost, self._rport),
                        hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
    self._SetFromMinor(minor)

  def _ShutdownLocal(self, minor):
    """Detach from the local device.

    I/Os will continue to be served from the remote device. If we
    don't have a remote device, this operation will fail.

    @type minor: int
    @param minor: the device to detach from the local device

    """
    cmd = self._cmd_gen.GenDetachCmd(minor)
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: can't detach local disk: %s",
                      minor, result.output)

  def _ShutdownNet(self, minor):
    """Disconnect from the remote peer.

    This fails if we don't have a local device.

    @type minor: boolean
    @param minor: the device to disconnect from the remote peer

    """
    family = self._GetNetFamily(minor, self._lhost, self._rhost)
    cmd = self._cmd_gen.GenDisconnectCmd(minor, family,
                                         self._lhost, self._lport,
                                         self._rhost, self._rport)
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: can't shutdown network: %s",
                      minor, result.output)

  def Shutdown(self):
    """Shutdown the DRBD device.

    """
    if self.minor is None and not self.Attach():
      logging.info("drbd%d: not attached during Shutdown()", self._aminor)
      return

    try:
      DRBD8.ShutdownAll(self.minor)
    finally:
      self.minor = None
      self.dev_path = None

  def Remove(self):
    """Stub remove for DRBD devices.

    """
    self.Shutdown()

  def Rename(self, new_id):
    """Rename a device.

    This is not supported for drbd devices.

    """
    raise errors.ProgrammerError("Can't rename a drbd device")

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Resize the DRBD device and its backing storage.

    See L{BlockDev.Grow} for parameter description.

    """
    if self.minor is None:
      base.ThrowError("drbd%d: Grow called while not attached", self._aminor)
    if len(self._children) != 2 or None in self._children:
      base.ThrowError("drbd%d: cannot grow diskless device", self.minor)
    self._children[0].Grow(amount, dryrun, backingstore, excl_stor)
    if dryrun or backingstore:
      # DRBD does not support dry-run mode and is not backing storage,
      # so we'll return here
      return
    cmd = self._cmd_gen.GenResizeCmd(self.minor, self.size + amount)
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("drbd%d: resize failed: %s", self.minor, result.output)

  @classmethod
  def _InitMeta(cls, minor, dev_path):
    """Initialize a meta device.

    This will not work if the given minor is in use.

    @type minor: int
    @param minor: the DRBD minor whose (future) meta device should be
      initialized
    @type dev_path: string
    @param dev_path: path to the meta device to initialize

    """
    # Zero the metadata first, in order to make sure drbdmeta doesn't
    # try to auto-detect existing filesystems or similar (see
    # http://code.google.com/p/ganeti/issues/detail?id=182); we only
    # care about the first 128MB of data in the device, even though it
    # can be bigger
    result = utils.RunCmd([constants.DD_CMD,
                           "if=/dev/zero", "of=%s" % dev_path,
                           "bs=%s" % constants.DD_BLOCK_SIZE, "count=128",
                           "oflag=direct"])
    if result.failed:
      base.ThrowError("Can't wipe the meta device: %s", result.output)

    info = DRBD8.GetProcInfo()
    cmd_gen = DRBD8.GetCmdGenerator(info)
    cmd = cmd_gen.GenInitMetaCmd(minor, dev_path)

    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("Can't initialize meta device: %s", result.output)

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, **kwargs):
    """Create a new DRBD8 device.

    Since DRBD devices are not created per se, just assembled, this
    function only initializes the metadata.

    """
    if len(children) != 2:
      raise errors.ProgrammerError("Invalid setup for the drbd device")
    if excl_stor:
      raise errors.ProgrammerError("DRBD device requested with"
                                   " exclusive_storage")
    if constants.DDP_LOCAL_MINOR not in dyn_params:
      raise errors.ProgrammerError("Invalid dynamic params for drbd device %s"
                                   % dyn_params)
    # check that the minor is unused
    aminor = dyn_params[constants.DDP_LOCAL_MINOR]

    info = DRBD8.GetProcInfo()
    if info.HasMinorStatus(aminor):
      status = info.GetMinorStatus(aminor)
      in_use = status.is_in_use
    else:
      in_use = False
    if in_use:
      base.ThrowError("drbd%d: minor is already in use at Create() time",
                      aminor)
    meta = children[1]
    meta.Assemble()
    if not meta.Attach():
      base.ThrowError("drbd%d: can't attach to meta device '%s'",
                      aminor, meta)
    cls._CheckMetaSize(meta.dev_path)
    cls._InitMeta(aminor, meta.dev_path)
    return cls(unique_id, children, size, params, dyn_params)


def _CanReadDevice(path):
  """Check if we can read from the given device.

  This tries to read the first 128k of the device.

  @type path: string

  """
  try:
    utils.ReadFile(path, size=_DEVICE_READ_SIZE)
    return True
  except EnvironmentError:
    logging.warning("Can't read from device %s", path, exc_info=True)
    return False
