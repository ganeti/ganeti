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


"""DRBD information parsing utilities"""

import errno
import pyparsing as pyp
import re

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import compat
from ganeti.block import base


class DRBD8Status(object): # pylint: disable=R0902
  """A DRBD status representation class.

  Note that this class is meant to be used to parse one of the entries returned
  from L{DRBD8Info._JoinLinesPerMinor}.

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
    self.is_unconfigured = self.cstatus == self.CS_UNCONFIGURED
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


class DRBD8Info(object):
  """Represents information DRBD exports (usually via /proc/drbd).

  An instance of this class is created by one of the CreateFrom... methods.

  """

  _VERSION_RE = re.compile(r"^version: (\d+)\.(\d+)\.(\d+)(?:\.\d+)?"
                           r" \(api:(\d+)/proto:(\d+)(?:-(\d+))?\)")
  _VALID_LINE_RE = re.compile("^ *([0-9]+): cs:([^ ]+).*$")

  def __init__(self, lines):
    self._version = self._ParseVersion(lines)
    self._minors, self._line_per_minor = self._JoinLinesPerMinor(lines)

  def GetVersion(self):
    """Return the DRBD version.

    This will return a dict with keys:
      - k_major
      - k_minor
      - k_point
      - api
      - proto
      - proto2 (only on drbd > 8.2.X)

    """
    return self._version

  def GetMinors(self):
    """Return a list of minor for which information is available.

    This list is ordered in exactly the order which was found in the underlying
    data.

    """
    return self._minors

  def HasMinorStatus(self, minor):
    return minor in self._line_per_minor

  def GetMinorStatus(self, minor):
    return DRBD8Status(self._line_per_minor[minor])

  def _ParseVersion(self, lines):
    first_line = lines[0].strip()
    version = self._VERSION_RE.match(first_line)
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

  def _JoinLinesPerMinor(self, lines):
    """Transform the raw lines into a dictionary based on the minor.

    @return: a dictionary of minor: joined lines from /proc/drbd
        for that minor

    """
    minors = []
    results = {}
    old_minor = old_line = None
    for line in lines:
      if not line: # completely empty lines, as can be returned by drbd8.0+
        continue
      lresult = self._VALID_LINE_RE.match(line)
      if lresult is not None:
        if old_minor is not None:
          minors.append(old_minor)
          results[old_minor] = old_line
        old_minor = int(lresult.group(1))
        old_line = line
      else:
        if old_minor is not None:
          old_line += " " + line.strip()
    # add last line
    if old_minor is not None:
      minors.append(old_minor)
      results[old_minor] = old_line
    return minors, results

  @staticmethod
  def CreateFromLines(lines):
    return DRBD8Info(lines)

  @staticmethod
  def CreateFromFile(filename=constants.DRBD_STATUS_FILE):
    try:
      lines = utils.ReadFile(filename).splitlines()
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        base.ThrowError("The file %s cannot be opened, check if the module"
                        " is loaded (%s)", filename, str(err))
      else:
        base.ThrowError("Can't read the DRBD proc file %s: %s",
                        filename, str(err))
    if not lines:
      base.ThrowError("Can't read any data from %s", filename)
    return DRBD8Info.CreateFromLines(lines)


class DRBD8ShowInfo(object):
  """Helper class which parses the output of drbdsetup show

  """
  _PARSE_SHOW = None

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
  def GetDevInfo(cls, show_data):
    """Parse details about a given DRBD minor.

    This returns, if available, the local backing device (as a path)
    and the local and remote (ip, port) information from a string
    containing the output of the `drbdsetup show` command as returned
    by DRBD8._GetShowData.

    This will return a dict with keys:
      - local_dev
      - meta_dev
      - meta_index
      - local_addr
      - remote_addr

    """
    retval = {}
    if not show_data:
      return retval

    try:
      # run pyparse
      results = (cls._GetShowParser()).parseString(show_data)
    except pyp.ParseException, err:
      base.ThrowError("Can't parse drbdsetup show output: %s", str(err))

    # and massage the results into our desired format
    for section in results:
      sname = section[0]
      if sname == "_this_host":
        for lst in section[1:]:
          if lst[0] == "disk":
            retval["local_dev"] = lst[1]
          elif lst[0] == "meta-disk":
            retval["meta_dev"] = lst[1]
            retval["meta_index"] = lst[2]
          elif lst[0] == "address":
            retval["local_addr"] = tuple(lst[1:])
      elif sname == "_remote_host":
        for lst in section[1:]:
          if lst[0] == "address":
            retval["remote_addr"] = tuple(lst[1:])
    return retval
