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


"""DRBD information parsing utilities"""

import errno
import pyparsing as pyp
import re

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import compat
from ganeti.storage import base


class DRBD8Status(object): # pylint: disable=R0902
  """A DRBD status representation class.

  Note that this class is meant to be used to parse one of the entries returned
  from L{DRBD8Info._JoinLinesPerMinor}.

  """
  UNCONF_RE = re.compile(r"\s*[0-9]+:\s*cs:Unconfigured$")
  LINE_RE = re.compile(r"\s*[0-9]+:\s*cs:(\S+)\s+(?:st|ro):([^/]+)/(\S+)"
                       r"\s+ds:([^/]+)/(\S+)\s+.*$")
  SYNC_RE = re.compile(r"^.*\ssync'ed:\s*([0-9.]+)%.*"
                       # Due to a bug in drbd in the kernel, introduced in
                       # commit 4b0715f096 (still unfixed as of 2011-08-22)
                       r"(?:\s|M)"
                       r"finish: ([0-9]+):([0-9]+):([0-9]+)\s.*$")

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
    self.peer_disk_uptodate = self.rdisk == self.DS_UPTODATE

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

  def __repr__(self):
    return ("<%s: cstatus=%s, lrole=%s, rrole=%s, ldisk=%s, rdisk=%s>" %
            (self.__class__, self.cstatus, self.lrole, self.rrole,
             self.ldisk, self.rdisk))


class DRBD8Info(object):
  """Represents information DRBD exports (usually via /proc/drbd).

  An instance of this class is created by one of the CreateFrom... methods.

  """

  _VERSION_RE = re.compile(r"^version: (\d+)\.(\d+)\.(\d+)"
                           r"(?:\.(\d+))?(?:-(\d+))?"
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
      - k_fix (only on some drbd versions)
      - k_release
      - api
      - proto
      - proto2 (only on drbd > 8.2.X)

    """
    return self._version

  def GetVersionString(self):
    """Return the DRBD version as a single string.

    """
    version = self.GetVersion()
    retval = "%d.%d.%d" % \
             (version["k_major"], version["k_minor"], version["k_point"])
    if "k_fix" in version:
      retval += ".%s" % version["k_fix"]
    if "k_release" in version:
      retval += "-%s" % version["k_release"]

    retval += " (api:%d/proto:%d" % (version["api"], version["proto"])
    if "proto2" in version:
      retval += "-%s" % version["proto2"]
    retval += ")"
    return retval

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
      "api": int(values[5]),
      "proto": int(values[6]),
      }
    if values[3] is not None:
      retval["k_fix"] = values[3]
    if values[4] is not None:
      retval["k_release"] = values[4]
    if values[7] is not None:
      retval["proto2"] = values[7]

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


class BaseShowInfo(object):
  """Base class for parsing the `drbdsetup show` output.

  Holds various common pyparsing expressions which are used by subclasses. Also
  provides caching of the constructed parser.

  """
  _PARSE_SHOW = None

  # pyparsing setup
  _lbrace = pyp.Literal("{").suppress()
  _rbrace = pyp.Literal("}").suppress()
  _lbracket = pyp.Literal("[").suppress()
  _rbracket = pyp.Literal("]").suppress()
  _semi = pyp.Literal(";").suppress()
  _colon = pyp.Literal(":").suppress()
  # this also converts the value to an int
  _number = pyp.Word(pyp.nums).setParseAction(lambda s, l, t: int(t[0]))

  _comment = pyp.Literal("#") + pyp.Optional(pyp.restOfLine)
  _defa = pyp.Literal("_is_default").suppress()
  _dbl_quote = pyp.Literal('"').suppress()

  _keyword = pyp.Word(pyp.alphanums + "-")

  # value types
  _value = pyp.Word(pyp.alphanums + "_-/.:")
  _quoted = _dbl_quote + pyp.CharsNotIn('"') + _dbl_quote
  _ipv4_addr = (pyp.Optional(pyp.Literal("ipv4")).suppress() +
                pyp.Word(pyp.nums + ".") + _colon + _number)
  _ipv6_addr = (pyp.Optional(pyp.Literal("ipv6")).suppress() +
                pyp.Optional(_lbracket) + pyp.Word(pyp.hexnums + ":") +
                pyp.Optional(_rbracket) + _colon + _number)
  # meta device, extended syntax
  _meta_value = ((_value ^ _quoted) + _lbracket + _number + _rbracket)
  # device name, extended syntax
  _device_value = pyp.Literal("minor").suppress() + _number

  # a statement
  _stmt = (~_rbrace + _keyword + ~_lbrace +
           pyp.Optional(_ipv4_addr ^ _ipv6_addr ^ _value ^ _quoted ^
                        _meta_value ^ _device_value) +
           pyp.Optional(_defa) + _semi +
           pyp.Optional(pyp.restOfLine).suppress())

  @classmethod
  def GetDevInfo(cls, show_data):
    """Parse details about a given DRBD minor.

    This returns, if available, the local backing device (as a path)
    and the local and remote (ip, port) information from a string
    containing the output of the `drbdsetup show` command as returned
    by DRBD8Dev._GetShowData.

    This will return a dict with keys:
      - local_dev
      - meta_dev
      - meta_index
      - local_addr
      - remote_addr

    """
    if not show_data:
      return {}

    try:
      # run pyparse
      results = (cls._GetShowParser()).parseString(show_data)
    except pyp.ParseException, err:
      base.ThrowError("Can't parse drbdsetup show output: %s", str(err))

    return cls._TransformParseResult(results)

  @classmethod
  def _TransformParseResult(cls, parse_result):
    raise NotImplementedError

  @classmethod
  def _GetShowParser(cls):
    """Return a parser for `drbd show` output.

    This will either create or return an already-created parser for the
    output of the command `drbd show`.

    """
    if cls._PARSE_SHOW is None:
      cls._PARSE_SHOW = cls._ConstructShowParser()

    return cls._PARSE_SHOW

  @classmethod
  def _ConstructShowParser(cls):
    raise NotImplementedError


class DRBD83ShowInfo(BaseShowInfo):
  @classmethod
  def _ConstructShowParser(cls):
    # an entire section
    section_name = pyp.Word(pyp.alphas + "_")
    section = section_name + \
              cls._lbrace + \
              pyp.ZeroOrMore(pyp.Group(cls._stmt)) + \
              cls._rbrace

    bnf = pyp.ZeroOrMore(pyp.Group(section ^ cls._stmt))
    bnf.ignore(cls._comment)

    return bnf

  @classmethod
  def _TransformParseResult(cls, parse_result):
    retval = {}
    for section in parse_result:
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


class DRBD84ShowInfo(BaseShowInfo):
  @classmethod
  def _ConstructShowParser(cls):
    # an entire section (sections can be nested in DRBD 8.4, and there exist
    # sections like "volume 0")
    section_name = pyp.Word(pyp.alphas + "_") + \
                   pyp.Optional(pyp.Word(pyp.nums)).suppress() # skip volume idx
    section = pyp.Forward()
    # pylint: disable=W0106
    section << (section_name +
                cls._lbrace +
                pyp.ZeroOrMore(pyp.Group(cls._stmt ^ section)) +
                cls._rbrace)

    resource_name = pyp.Word(pyp.alphanums + "_-.")
    resource = (pyp.Literal("resource") + resource_name).suppress() + \
               cls._lbrace + \
               pyp.ZeroOrMore(pyp.Group(section)) + \
               cls._rbrace

    resource.ignore(cls._comment)

    return resource

  @classmethod
  def _TransformVolumeSection(cls, vol_content, retval):
    for entry in vol_content:
      if entry[0] == "disk" and len(entry) == 2 and \
          isinstance(entry[1], basestring):
        retval["local_dev"] = entry[1]
      elif entry[0] == "meta-disk":
        if len(entry) > 1:
          retval["meta_dev"] = entry[1]
        if len(entry) > 2:
          retval["meta_index"] = entry[2]

  @classmethod
  def _TransformParseResult(cls, parse_result):
    retval = {}
    for section in parse_result:
      sname = section[0]
      if sname == "_this_host":
        for lst in section[1:]:
          if lst[0] == "address":
            retval["local_addr"] = tuple(lst[1:])
          elif lst[0] == "volume":
            cls._TransformVolumeSection(lst[1:], retval)
      elif sname == "_remote_host":
        for lst in section[1:]:
          if lst[0] == "address":
            retval["remote_addr"] = tuple(lst[1:])
    return retval
