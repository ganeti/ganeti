#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""DRBD block device related functionality"""

import errno
import logging
import pyparsing as pyp
import re
import shlex
import time

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import compat
from ganeti import netutils
from ganeti import objects
from ganeti.block import base


# Size of reads in _CanReadDevice

_DEVICE_READ_SIZE = 128 * 1024


class BaseDRBD(base.BlockDev): # pylint: disable=W0223
  """Base DRBD class.

  This class contains a few bits of common functionality between the
  0.7 and 8.x versions of DRBD.

  """
  _VERSION_RE = re.compile(r"^version: (\d+)\.(\d+)\.(\d+)(?:\.\d+)?"
                           r" \(api:(\d+)/proto:(\d+)(?:-(\d+))?\)")
  _VALID_LINE_RE = re.compile("^ *([0-9]+): cs:([^ ]+).*$")
  _UNUSED_LINE_RE = re.compile("^ *([0-9]+): cs:Unconfigured$")

  _DRBD_MAJOR = 147
  _ST_UNCONFIGURED = "Unconfigured"
  _ST_WFCONNECTION = "WFConnection"
  _ST_CONNECTED = "Connected"

  _STATUS_FILE = constants.DRBD_STATUS_FILE
  _USERMODE_HELPER_FILE = "/sys/module/drbd/parameters/usermode_helper"

  @staticmethod
  def _GetProcData(filename=_STATUS_FILE):
    """Return data from /proc/drbd.

    """
    try:
      data = utils.ReadFile(filename).splitlines()
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        base.ThrowError("The file %s cannot be opened, check if the module"
                        " is loaded (%s)", filename, str(err))
      else:
        base.ThrowError("Can't read the DRBD proc file %s: %s",
                        filename, str(err))
    if not data:
      base.ThrowError("Can't read any data from %s", filename)
    return data

  @classmethod
  def _MassageProcData(cls, data):
    """Transform the output of _GetProdData into a nicer form.

    @return: a dictionary of minor: joined lines from /proc/drbd
        for that minor

    """
    results = {}
    old_minor = old_line = None
    for line in data:
      if not line: # completely empty lines, as can be returned by drbd8.0+
        continue
      lresult = cls._VALID_LINE_RE.match(line)
      if lresult is not None:
        if old_minor is not None:
          results[old_minor] = old_line
        old_minor = int(lresult.group(1))
        old_line = line
      else:
        if old_minor is not None:
          old_line += " " + line.strip()
    # add last line
    if old_minor is not None:
      results[old_minor] = old_line
    return results

  @classmethod
  def _GetVersion(cls, proc_data):
    """Return the DRBD version.

    This will return a dict with keys:
      - k_major
      - k_minor
      - k_point
      - api
      - proto
      - proto2 (only on drbd > 8.2.X)

    """
    first_line = proc_data[0].strip()
    version = cls._VERSION_RE.match(first_line)
    if not version:
      raise errors.BlockDeviceError("Can't parse DRBD version from '%s'" %
                                    first_line)

    values = version.groups()
    retval = {
      "k_major": int(values[0]),
      "k_minor": int(values[1]),
      "k_point": int(values[2]),
      "api": int(values[3]),
      "proto": int(values[4]),
      }
    if values[5] is not None:
      retval["proto2"] = values[5]

    return retval

  @staticmethod
  def GetUsermodeHelper(filename=_USERMODE_HELPER_FILE):
    """Returns DRBD usermode_helper currently set.

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
  def _DevPath(minor):
    """Return the path to a drbd device for a given minor.

    """
    return "/dev/drbd%d" % minor

  @classmethod
  def GetUsedDevs(cls):
    """Compute the list of used DRBD devices.

    """
    data = cls._GetProcData()

    used_devs = {}
    for line in data:
      match = cls._VALID_LINE_RE.match(line)
      if not match:
        continue
      minor = int(match.group(1))
      state = match.group(2)
      if state == cls._ST_UNCONFIGURED:
        continue
      used_devs[minor] = state, line

    return used_devs

  def _SetFromMinor(self, minor):
    """Set our parameters based on the given minor.

    This sets our minor variable and our dev_path.

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

  def Rename(self, new_id):
    """Rename a device.

    This is not supported for drbd devices.

    """
    raise errors.ProgrammerError("Can't rename a drbd device")


class DRBD8Status(object):
  """A DRBD status representation class.

  Note that this doesn't support unconfigured devices (cs:Unconfigured).

  """
  UNCONF_RE = re.compile(r"\s*[0-9]+:\s*cs:Unconfigured$")
  LINE_RE = re.compile(r"\s*[0-9]+:\s*cs:(\S+)\s+(?:st|ro):([^/]+)/(\S+)"
                       "\s+ds:([^/]+)/(\S+)\s+.*$")
  SYNC_RE = re.compile(r"^.*\ssync'ed:\s*([0-9.]+)%.*"
                       # Due to a bug in drbd in the kernel, introduced in
                       # commit 4b0715f096 (still unfixed as of 2011-08-22)
                       "(?:\s|M)"
                       "finish: ([0-9]+):([0-9]+):([0-9]+)\s.*$")

  CS_UNCONFIGURED = "Unconfigured"
  CS_STANDALONE = "StandAlone"
  CS_WFCONNECTION = "WFConnection"
  CS_WFREPORTPARAMS = "WFReportParams"
  CS_CONNECTED = "Connected"
  CS_STARTINGSYNCS = "StartingSyncS"
  CS_STARTINGSYNCT = "StartingSyncT"
  CS_WFBITMAPS = "WFBitMapS"
  CS_WFBITMAPT = "WFBitMapT"
  CS_WFSYNCUUID = "WFSyncUUID"
  CS_SYNCSOURCE = "SyncSource"
  CS_SYNCTARGET = "SyncTarget"
  CS_PAUSEDSYNCS = "PausedSyncS"
  CS_PAUSEDSYNCT = "PausedSyncT"
  CSET_SYNC = compat.UniqueFrozenset([
    CS_WFREPORTPARAMS,
    CS_STARTINGSYNCS,
    CS_STARTINGSYNCT,
    CS_WFBITMAPS,
    CS_WFBITMAPT,
    CS_WFSYNCUUID,
    CS_SYNCSOURCE,
    CS_SYNCTARGET,
    CS_PAUSEDSYNCS,
    CS_PAUSEDSYNCT,
    ])

  DS_DISKLESS = "Diskless"
  DS_ATTACHING = "Attaching" # transient state
  DS_FAILED = "Failed" # transient state, next: diskless
  DS_NEGOTIATING = "Negotiating" # transient state
  DS_INCONSISTENT = "Inconsistent" # while syncing or after creation
  DS_OUTDATED = "Outdated"
  DS_DUNKNOWN = "DUnknown" # shown for peer disk when not connected
  DS_CONSISTENT = "Consistent"
  DS_UPTODATE = "UpToDate" # normal state

  RO_PRIMARY = "Primary"
  RO_SECONDARY = "Secondary"
  RO_UNKNOWN = "Unknown"

  def __init__(self, procline):
    u = self.UNCONF_RE.match(procline)
    if u:
      self.cstatus = self.CS_UNCONFIGURED
      self.lrole = self.rrole = self.ldisk = self.rdisk = None
    else:
      m = self.LINE_RE.match(procline)
      if not m:
        raise errors.BlockDeviceError("Can't parse input data '%s'" % procline)
      self.cstatus = m.group(1)
      self.lrole = m.group(2)
      self.rrole = m.group(3)
      self.ldisk = m.group(4)
      self.rdisk = m.group(5)

    # end reading of data from the LINE_RE or UNCONF_RE

    self.is_standalone = self.cstatus == self.CS_STANDALONE
    self.is_wfconn = self.cstatus == self.CS_WFCONNECTION
    self.is_connected = self.cstatus == self.CS_CONNECTED
    self.is_primary = self.lrole == self.RO_PRIMARY
    self.is_secondary = self.lrole == self.RO_SECONDARY
    self.peer_primary = self.rrole == self.RO_PRIMARY
    self.peer_secondary = self.rrole == self.RO_SECONDARY
    self.both_primary = self.is_primary and self.peer_primary
    self.both_secondary = self.is_secondary and self.peer_secondary

    self.is_diskless = self.ldisk == self.DS_DISKLESS
    self.is_disk_uptodate = self.ldisk == self.DS_UPTODATE

    self.is_in_resync = self.cstatus in self.CSET_SYNC
    self.is_in_use = self.cstatus != self.CS_UNCONFIGURED

    m = self.SYNC_RE.match(procline)
    if m:
      self.sync_percent = float(m.group(1))
      hours = int(m.group(2))
      minutes = int(m.group(3))
      seconds = int(m.group(4))
      self.est_time = hours * 3600 + minutes * 60 + seconds
    else:
      # we have (in this if branch) no percent information, but if
      # we're resyncing we need to 'fake' a sync percent information,
      # as this is how cmdlib determines if it makes sense to wait for
      # resyncing or not
      if self.is_in_resync:
        self.sync_percent = 0
      else:
        self.sync_percent = None
      self.est_time = None


class DRBD8(BaseDRBD):
  """DRBD v8.x block device.

  This implements the local host part of the DRBD device, i.e. it
  doesn't do anything to the supposed peer. If you need a fully
  connected DRBD pair, you need to use this class on both hosts.

  The unique_id for the drbd device is a (local_ip, local_port,
  remote_ip, remote_port, local_minor, secret) tuple, and it must have
  two children: the data device and the meta_device. The meta device
  is checked for valid size and is zeroed on create.

  """
  _MAX_MINORS = 255
  _PARSE_SHOW = None

  # timeout constants
  _NET_RECONFIG_TIMEOUT = 60

  # command line options for barriers
  _DISABLE_DISK_OPTION = "--no-disk-barrier"  # -a
  _DISABLE_DRAIN_OPTION = "--no-disk-drain"   # -D
  _DISABLE_FLUSH_OPTION = "--no-disk-flushes" # -i
  _DISABLE_META_FLUSH_OPTION = "--no-md-flushes"  # -m

  def __init__(self, unique_id, children, size, params):
    if children and children.count(None) > 0:
      children = []
    if len(children) not in (0, 2):
      raise ValueError("Invalid configuration data %s" % str(children))
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 6:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    (self._lhost, self._lport,
     self._rhost, self._rport,
     self._aminor, self._secret) = unique_id
    if children:
      if not _CanReadDevice(children[1].dev_path):
        logging.info("drbd%s: Ignoring unreadable meta device", self._aminor)
        children = []
    super(DRBD8, self).__init__(unique_id, children, size, params)
    self.major = self._DRBD_MAJOR
    version = self._GetVersion(self._GetProcData())
    if version["k_major"] != 8:
      base.ThrowError("Mismatch in DRBD kernel version and requested ganeti"
                      " usage: kernel is %s.%s, ganeti wants 8.x",
                      version["k_major"], version["k_minor"])

    if (self._lhost is not None and self._lhost == self._rhost and
        self._lport == self._rport):
      raise ValueError("Invalid configuration data, same local/remote %s" %
                       (unique_id,))
    self.Attach()

  @classmethod
  def _InitMeta(cls, minor, dev_path):
    """Initialize a meta device.

    This will not work if the given minor is in use.

    """
    # Zero the metadata first, in order to make sure drbdmeta doesn't
    # try to auto-detect existing filesystems or similar (see
    # http://code.google.com/p/ganeti/issues/detail?id=182); we only
    # care about the first 128MB of data in the device, even though it
    # can be bigger
    result = utils.RunCmd([constants.DD_CMD,
                           "if=/dev/zero", "of=%s" % dev_path,
                           "bs=1048576", "count=128", "oflag=direct"])
    if result.failed:
      base.ThrowError("Can't wipe the meta device: %s", result.output)

    result = utils.RunCmd(["drbdmeta", "--force", cls._DevPath(minor),
                           "v08", dev_path, "0", "create-md"])
    if result.failed:
      base.ThrowError("Can't initialize meta device: %s", result.output)

  @classmethod
  def _FindUnusedMinor(cls):
    """Find an unused DRBD device.

    This is specific to 8.x as the minors are allocated dynamically,
    so non-existing numbers up to a max minor count are actually free.

    """
    data = cls._GetProcData()

    highest = None
    for line in data:
      match = cls._UNUSED_LINE_RE.match(line)
      if match:
        return int(match.group(1))
      match = cls._VALID_LINE_RE.match(line)
      if match:
        minor = int(match.group(1))
        highest = max(highest, minor)
    if highest is None: # there are no minors in use at all
      return 0
    if highest >= cls._MAX_MINORS:
      logging.error("Error: no free drbd minors!")
      raise errors.BlockDeviceError("Can't find a free DRBD minor")
    return highest + 1

  @classmethod
  def _GetShowParser(cls):
    """Return a parser for `drbd show` output.

    This will either create or return an already-created parser for the
    output of the command `drbd show`.

    """
    if cls._PARSE_SHOW is not None:
      return cls._PARSE_SHOW

    # pyparsing setup
    lbrace = pyp.Literal("{").suppress()
    rbrace = pyp.Literal("}").suppress()
    lbracket = pyp.Literal("[").suppress()
    rbracket = pyp.Literal("]").suppress()
    semi = pyp.Literal(";").suppress()
    colon = pyp.Literal(":").suppress()
    # this also converts the value to an int
    number = pyp.Word(pyp.nums).setParseAction(lambda s, l, t: int(t[0]))

    comment = pyp.Literal("#") + pyp.Optional(pyp.restOfLine)
    defa = pyp.Literal("_is_default").suppress()
    dbl_quote = pyp.Literal('"').suppress()

    keyword = pyp.Word(pyp.alphanums + "-")

    # value types
    value = pyp.Word(pyp.alphanums + "_-/.:")
    quoted = dbl_quote + pyp.CharsNotIn('"') + dbl_quote
    ipv4_addr = (pyp.Optional(pyp.Literal("ipv4")).suppress() +
                 pyp.Word(pyp.nums + ".") + colon + number)
    ipv6_addr = (pyp.Optional(pyp.Literal("ipv6")).suppress() +
                 pyp.Optional(lbracket) + pyp.Word(pyp.hexnums + ":") +
                 pyp.Optional(rbracket) + colon + number)
    # meta device, extended syntax
    meta_value = ((value ^ quoted) + lbracket + number + rbracket)
    # device name, extended syntax
    device_value = pyp.Literal("minor").suppress() + number

    # a statement
    stmt = (~rbrace + keyword + ~lbrace +
            pyp.Optional(ipv4_addr ^ ipv6_addr ^ value ^ quoted ^ meta_value ^
                         device_value) +
            pyp.Optional(defa) + semi +
            pyp.Optional(pyp.restOfLine).suppress())

    # an entire section
    section_name = pyp.Word(pyp.alphas + "_")
    section = section_name + lbrace + pyp.ZeroOrMore(pyp.Group(stmt)) + rbrace

    bnf = pyp.ZeroOrMore(pyp.Group(section ^ stmt))
    bnf.ignore(comment)

    cls._PARSE_SHOW = bnf

    return bnf

  @classmethod
  def _GetShowData(cls, minor):
    """Return the `drbdsetup show` data for a minor.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "show"])
    if result.failed:
      logging.error("Can't display the drbd config: %s - %s",
                    result.fail_reason, result.output)
      return None
    return result.stdout

  @classmethod
  def _GetDevInfo(cls, out):
    """Parse details about a given DRBD minor.

    This return, if available, the local backing device (as a path)
    and the local and remote (ip, port) information from a string
    containing the output of the `drbdsetup show` command as returned
    by _GetShowData.

    """
    data = {}
    if not out:
      return data

    bnf = cls._GetShowParser()
    # run pyparse

    try:
      results = bnf.parseString(out)
    except pyp.ParseException, err:
      base.ThrowError("Can't parse drbdsetup show output: %s", str(err))

    # and massage the results into our desired format
    for section in results:
      sname = section[0]
      if sname == "_this_host":
        for lst in section[1:]:
          if lst[0] == "disk":
            data["local_dev"] = lst[1]
          elif lst[0] == "meta-disk":
            data["meta_dev"] = lst[1]
            data["meta_index"] = lst[2]
          elif lst[0] == "address":
            data["local_addr"] = tuple(lst[1:])
      elif sname == "_remote_host":
        for lst in section[1:]:
          if lst[0] == "address":
            data["remote_addr"] = tuple(lst[1:])
    return data

  def _MatchesLocal(self, info):
    """Test if our local config matches with an existing device.

    The parameter should be as returned from `_GetDevInfo()`. This
    method tests if our local backing device is the same as the one in
    the info parameter, in effect testing if we look like the given
    device.

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
      retval = retval and ("meta_index" in info and
                           info["meta_index"] == 0)
    else:
      retval = retval and ("meta_dev" not in info and
                           "meta_index" not in info)
    return retval

  def _MatchesNet(self, info):
    """Test if our network config matches with an existing device.

    The parameter should be as returned from `_GetDevInfo()`. This
    method tests if our network configuration is the same as the one
    in the info parameter, in effect testing if we look like the given
    device.

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

    """
    args = ["drbdsetup", self._DevPath(minor), "disk",
            backend, meta, "0",
            "-e", "detach",
            "--create-device"]
    if size:
      args.extend(["-d", "%sm" % size])

    version = self._GetVersion(self._GetProcData())
    vmaj = version["k_major"]
    vmin = version["k_minor"]
    vrel = version["k_point"]

    barrier_args = \
      self._ComputeDiskBarrierArgs(vmaj, vmin, vrel,
                                   self.params[constants.LDP_BARRIERS],
                                   self.params[constants.LDP_NO_META_FLUSH])
    args.extend(barrier_args)

    if self.params[constants.LDP_DISK_CUSTOM]:
      args.extend(shlex.split(self.params[constants.LDP_DISK_CUSTOM]))

    result = utils.RunCmd(args)
    if result.failed:
      base.ThrowError("drbd%d: can't attach local disk: %s",
                      minor, result.output)

  @classmethod
  def _ComputeDiskBarrierArgs(cls, vmaj, vmin, vrel, disabled_barriers,
                              disable_meta_flush):
    """Compute the DRBD command line parameters for disk barriers

    Returns a list of the disk barrier parameters as requested via the
    disabled_barriers and disable_meta_flush arguments, and according to the
    supported ones in the DRBD version vmaj.vmin.vrel

    If the desired option is unsupported, raises errors.BlockDeviceError.

    """
    disabled_barriers_set = frozenset(disabled_barriers)
    if not disabled_barriers_set in constants.DRBD_VALID_BARRIER_OPT:
      raise errors.BlockDeviceError("%s is not a valid option set for DRBD"
                                    " barriers" % disabled_barriers)

    args = []

    # The following code assumes DRBD 8.x, with x < 4 and x != 1 (DRBD 8.1.x
    # does not exist)
    if not vmaj == 8 and vmin in (0, 2, 3):
      raise errors.BlockDeviceError("Unsupported DRBD version: %d.%d.%d" %
                                    (vmaj, vmin, vrel))

    def _AppendOrRaise(option, min_version):
      """Helper for DRBD options"""
      if min_version is not None and vrel >= min_version:
        args.append(option)
      else:
        raise errors.BlockDeviceError("Could not use the option %s as the"
                                      " DRBD version %d.%d.%d does not support"
                                      " it." % (option, vmaj, vmin, vrel))

    # the minimum version for each feature is encoded via pairs of (minor
    # version -> x) where x is version in which support for the option was
    # introduced.
    meta_flush_supported = disk_flush_supported = {
      0: 12,
      2: 7,
      3: 0,
      }

    disk_drain_supported = {
      2: 7,
      3: 0,
      }

    disk_barriers_supported = {
      3: 0,
      }

    # meta flushes
    if disable_meta_flush:
      _AppendOrRaise(cls._DISABLE_META_FLUSH_OPTION,
                     meta_flush_supported.get(vmin, None))

    # disk flushes
    if constants.DRBD_B_DISK_FLUSH in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_FLUSH_OPTION,
                     disk_flush_supported.get(vmin, None))

    # disk drain
    if constants.DRBD_B_DISK_DRAIN in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_DRAIN_OPTION,
                     disk_drain_supported.get(vmin, None))

    # disk barriers
    if constants.DRBD_B_DISK_BARRIERS in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_DISK_OPTION,
                     disk_barriers_supported.get(vmin, None))

    return args

  def _AssembleNet(self, minor, net_info, protocol,
                   dual_pri=False, hmac=None, secret=None):
    """Configure the network part of the device.

    """
    lhost, lport, rhost, rport = net_info
    if None in net_info:
      # we don't want network connection and actually want to make
      # sure its shutdown
      self._ShutdownNet(minor)
      return

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

    if netutils.IP6Address.IsValid(lhost):
      if not netutils.IP6Address.IsValid(rhost):
        base.ThrowError("drbd%d: can't connect ip %s to ip %s" %
                        (minor, lhost, rhost))
      family = "ipv6"
    elif netutils.IP4Address.IsValid(lhost):
      if not netutils.IP4Address.IsValid(rhost):
        base.ThrowError("drbd%d: can't connect ip %s to ip %s" %
                        (minor, lhost, rhost))
      family = "ipv4"
    else:
      base.ThrowError("drbd%d: Invalid ip %s" % (minor, lhost))

    args = ["drbdsetup", self._DevPath(minor), "net",
            "%s:%s:%s" % (family, lhost, lport),
            "%s:%s:%s" % (family, rhost, rport), protocol,
            "-A", "discard-zero-changes",
            "-B", "consensus",
            "--create-device",
            ]
    if dual_pri:
      args.append("-m")
    if hmac and secret:
      args.extend(["-a", hmac, "-x", secret])

    if self.params[constants.LDP_NET_CUSTOM]:
      args.extend(shlex.split(self.params[constants.LDP_NET_CUSTOM]))

    result = utils.RunCmd(args)
    if result.failed:
      base.ThrowError("drbd%d: can't setup network: %s - %s",
                      minor, result.fail_reason, result.output)

    def _CheckNetworkConfig():
      info = self._GetDevInfo(self._GetShowData(minor))
      if not "local_addr" in info or not "remote_addr" in info:
        raise utils.RetryAgain()

      if (info["local_addr"] != (lhost, lport) or
          info["remote_addr"] != (rhost, rport)):
        raise utils.RetryAgain()

    try:
      utils.Retry(_CheckNetworkConfig, 1.0, 10.0)
    except utils.RetryTimeout:
      base.ThrowError("drbd%d: timeout while configuring network", minor)

  def AddChildren(self, devices):
    """Add a disk to the DRBD device.

    """
    if self.minor is None:
      base.ThrowError("drbd%d: can't attach to dbrd8 during AddChildren",
                      self._aminor)
    if len(devices) != 2:
      base.ThrowError("drbd%d: need two devices for AddChildren", self.minor)
    info = self._GetDevInfo(self._GetShowData(self.minor))
    if "local_dev" in info:
      base.ThrowError("drbd%d: already attached to a local disk", self.minor)
    backend, meta = devices
    if backend.dev_path is None or meta.dev_path is None:
      base.ThrowError("drbd%d: children not ready during AddChildren",
                      self.minor)
    backend.Open()
    meta.Open()
    self._CheckMetaSize(meta.dev_path)
    self._InitMeta(self._FindUnusedMinor(), meta.dev_path)

    self._AssembleLocal(self.minor, backend.dev_path, meta.dev_path, self.size)
    self._children = devices

  def RemoveChildren(self, devices):
    """Detach the drbd device from local storage.

    """
    if self.minor is None:
      base.ThrowError("drbd%d: can't attach to drbd8 during RemoveChildren",
                      self._aminor)
    # early return if we don't actually have backing storage
    info = self._GetDevInfo(self._GetShowData(self.minor))
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

  @classmethod
  def _SetMinorSyncParams(cls, minor, params):
    """Set the parameters of the DRBD syncer.

    This is the low-level implementation.

    @type minor: int
    @param minor: the drbd minor whose settings we change
    @type params: dict
    @param params: LD level disk parameters related to the synchronization
    @rtype: list
    @return: a list of error messages

    """

    args = ["drbdsetup", cls._DevPath(minor), "syncer"]
    if params[constants.LDP_DYNAMIC_RESYNC]:
      version = cls._GetVersion(cls._GetProcData())
      vmin = version["k_minor"]
      vrel = version["k_point"]

      # By definition we are using 8.x, so just check the rest of the version
      # number
      if vmin != 3 or vrel < 9:
        msg = ("The current DRBD version (8.%d.%d) does not support the "
               "dynamic resync speed controller" % (vmin, vrel))
        logging.error(msg)
        return [msg]

      if params[constants.LDP_PLAN_AHEAD] == 0:
        msg = ("A value of 0 for c-plan-ahead disables the dynamic sync speed"
               " controller at DRBD level. If you want to disable it, please"
               " set the dynamic-resync disk parameter to False.")
        logging.error(msg)
        return [msg]

      # add the c-* parameters to args
      args.extend(["--c-plan-ahead", params[constants.LDP_PLAN_AHEAD],
                   "--c-fill-target", params[constants.LDP_FILL_TARGET],
                   "--c-delay-target", params[constants.LDP_DELAY_TARGET],
                   "--c-max-rate", params[constants.LDP_MAX_RATE],
                   "--c-min-rate", params[constants.LDP_MIN_RATE],
                   ])

    else:
      args.extend(["-r", "%d" % params[constants.LDP_RESYNC_RATE]])

    args.append("--create-device")
    result = utils.RunCmd(args)
    if result.failed:
      msg = ("Can't change syncer rate: %s - %s" %
             (result.fail_reason, result.output))
      logging.error(msg)
      return [msg]

    return []

  def SetSyncParams(self, params):
    """Set the synchronization parameters of the DRBD syncer.

    @type params: dict
    @param params: LD level disk parameters related to the synchronization
    @rtype: list
    @return: a list of error messages, emitted both by the current node and by
    children. An empty list means no errors

    """
    if self.minor is None:
      err = "Not attached during SetSyncParams"
      logging.info(err)
      return [err]

    children_result = super(DRBD8, self).SetSyncParams(params)
    children_result.extend(self._SetMinorSyncParams(self.minor, params))
    return children_result

  def PauseResumeSync(self, pause):
    """Pauses or resumes the sync of a DRBD device.

    @param pause: Wether to pause or resume
    @return: the success of the operation

    """
    if self.minor is None:
      logging.info("Not attached during PauseSync")
      return False

    children_result = super(DRBD8, self).PauseResumeSync(pause)

    if pause:
      cmd = "pause-sync"
    else:
      cmd = "resume-sync"

    result = utils.RunCmd(["drbdsetup", self.dev_path, cmd])
    if result.failed:
      logging.error("Can't %s: %s - %s", cmd,
                    result.fail_reason, result.output)
    return not result.failed and children_result

  def GetProcStatus(self):
    """Return device data from /proc.

    """
    if self.minor is None:
      base.ThrowError("drbd%d: GetStats() called while not attached",
                      self._aminor)
    proc_info = self._MassageProcData(self._GetProcData())
    if self.minor not in proc_info:
      base.ThrowError("drbd%d: can't find myself in /proc", self.minor)
    return DRBD8Status(proc_info[self.minor])

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
    else:
      ldisk_status = constants.LDS_UNKNOWN

    return objects.BlockDevStatus(dev_path=self.dev_path,
                                  major=self.major,
                                  minor=self.minor,
                                  sync_percent=stats.sync_percent,
                                  estimated_time=stats.est_time,
                                  is_degraded=is_degraded,
                                  ldisk_status=ldisk_status)

  def Open(self, force=False):
    """Make the local state primary.

    If the 'force' parameter is given, the '-o' option is passed to
    drbdsetup. Since this is a potentially dangerous operation, the
    force flag should be only given after creation, when it actually
    is mandatory.

    """
    if self.minor is None and not self.Attach():
      logging.error("DRBD cannot attach to a device during open")
      return False
    cmd = ["drbdsetup", self.dev_path, "primary"]
    if force:
      cmd.append("-o")
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
    result = utils.RunCmd(["drbdsetup", self.dev_path, "secondary"])
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

    class _DisconnectStatus:
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

    Args:
      - multimaster: init the network in dual-primary mode

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
                      constants.DRBD_NET_PROTOCOL, dual_pri=multimaster,
                      hmac=constants.DRBD_HMAC_ALG, secret=self._secret)

  def Attach(self):
    """Check if our minor is configured.

    This doesn't do any device configurations - it only checks if the
    minor is in a state different from Unconfigured.

    Note that this function will not change the state of the system in
    any way (except in case of side-effects caused by reading from
    /proc).

    """
    used_devs = self.GetUsedDevs()
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
    super(DRBD8, self).Assemble()

    self.Attach()
    if self.minor is None:
      # local device completely unconfigured
      self._FastAssemble()
    else:
      # we have to recheck the local and network status and try to fix
      # the device
      self._SlowAssemble()

    sync_errors = self.SetSyncParams(self.params)
    if sync_errors:
      base.ThrowError("drbd%d: can't set the synchronization parameters: %s" %
                      (self.minor, utils.CommaJoin(sync_errors)))

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
      info = self._GetDevInfo(self._GetShowData(minor))
      match_l = self._MatchesLocal(info)
      match_r = self._MatchesNet(info)

      if match_l and match_r:
        # everything matches
        break

      if match_l and not match_r and "local_addr" not in info:
        # disk matches, but not attached to network, attach and recheck
        self._AssembleNet(minor, net_data, constants.DRBD_NET_PROTOCOL,
                          hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
        if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
          break
        else:
          base.ThrowError("drbd%d: network attach successful, but 'drbdsetup"
                          " show' disagrees", minor)

      if match_r and "local_dev" not in info:
        # no local disk, but network attached and it matches
        self._AssembleLocal(minor, self._children[0].dev_path,
                            self._children[1].dev_path, self.size)
        if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
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
        self._AssembleNet(minor, net_data, constants.DRBD_NET_PROTOCOL,
                          hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
        if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
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
                        constants.DRBD_NET_PROTOCOL,
                        hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
    self._SetFromMinor(minor)

  @classmethod
  def _ShutdownLocal(cls, minor):
    """Detach from the local device.

    I/Os will continue to be served from the remote device. If we
    don't have a remote device, this operation will fail.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "detach"])
    if result.failed:
      base.ThrowError("drbd%d: can't detach local disk: %s",
                      minor, result.output)

  @classmethod
  def _ShutdownNet(cls, minor):
    """Disconnect from the remote peer.

    This fails if we don't have a local device.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "disconnect"])
    if result.failed:
      base.ThrowError("drbd%d: can't shutdown network: %s",
                      minor, result.output)

  @classmethod
  def _ShutdownAll(cls, minor):
    """Deactivate the device.

    This will, of course, fail if the device is in use.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "down"])
    if result.failed:
      base.ThrowError("drbd%d: can't shutdown drbd device: %s",
                      minor, result.output)

  def Shutdown(self):
    """Shutdown the DRBD device.

    """
    if self.minor is None and not self.Attach():
      logging.info("drbd%d: not attached during Shutdown()", self._aminor)
      return
    minor = self.minor
    self.minor = None
    self.dev_path = None
    self._ShutdownAll(minor)

  def Remove(self):
    """Stub remove for DRBD devices.

    """
    self.Shutdown()

  @classmethod
  def Create(cls, unique_id, children, size, params, excl_stor):
    """Create a new DRBD8 device.

    Since DRBD devices are not created per se, just assembled, this
    function only initializes the metadata.

    """
    if len(children) != 2:
      raise errors.ProgrammerError("Invalid setup for the drbd device")
    if excl_stor:
      raise errors.ProgrammerError("DRBD device requested with"
                                   " exclusive_storage")
    # check that the minor is unused
    aminor = unique_id[4]
    proc_info = cls._MassageProcData(cls._GetProcData())
    if aminor in proc_info:
      status = DRBD8Status(proc_info[aminor])
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
    return cls(unique_id, children, size, params)

  def Grow(self, amount, dryrun, backingstore):
    """Resize the DRBD device and its backing storage.

    """
    if self.minor is None:
      base.ThrowError("drbd%d: Grow called while not attached", self._aminor)
    if len(self._children) != 2 or None in self._children:
      base.ThrowError("drbd%d: cannot grow diskless device", self.minor)
    self._children[0].Grow(amount, dryrun, backingstore)
    if dryrun or backingstore:
      # DRBD does not support dry-run mode and is not backing storage,
      # so we'll return here
      return
    result = utils.RunCmd(["drbdsetup", self.dev_path, "resize", "-s",
                           "%dm" % (self.size + amount)])
    if result.failed:
      base.ThrowError("drbd%d: resize failed: %s", self.minor, result.output)


def _CanReadDevice(path):
  """Check if we can read from the given device.

  This tries to read the first 128k of the device.

  """
  try:
    utils.ReadFile(path, size=_DEVICE_READ_SIZE)
    return True
  except EnvironmentError:
    logging.warning("Can't read from device %s", path, exc_info=True)
    return False
