#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Ganeti utility module.

This module holds functions that can be used in both daemons (all) and
the command line scripts.

"""

# Allow wildcard import in pylint: disable=W0401

import os
import re
import errno
import pwd
import time
import itertools
import select
import logging
import signal

from ganeti import errors
from ganeti import constants
from ganeti import compat
from ganeti import pathutils

from ganeti.utils.algo import *
from ganeti.utils.filelock import *
from ganeti.utils.hash import *
from ganeti.utils.io import *
from ganeti.utils.livelock import *
from ganeti.utils.log import *
from ganeti.utils.lvm import *
from ganeti.utils.mlock import *
from ganeti.utils.nodesetup import *
from ganeti.utils.process import *
from ganeti.utils.retry import *
from ganeti.utils.security import *
from ganeti.utils.storage import *
from ganeti.utils.tags import *
from ganeti.utils.text import *
from ganeti.utils.wrapper import *
from ganeti.utils.version import *
from ganeti.utils.x509 import *
from ganeti.utils.bitarrays import *


_VALID_SERVICE_NAME_RE = re.compile("^[-_.a-zA-Z0-9]{1,128}$")

UUID_RE = re.compile(constants.UUID_REGEX)


def ForceDictType(target, key_types, allowed_values=None):
  """Force the values of a dict to have certain types.

  @type target: dict
  @param target: the dict to update
  @type key_types: dict
  @param key_types: dict mapping target dict keys to types
                    in constants.ENFORCEABLE_TYPES
  @type allowed_values: list
  @keyword allowed_values: list of specially allowed values

  """
  if allowed_values is None:
    allowed_values = []

  if not isinstance(target, dict):
    msg = "Expected dictionary, got '%s'" % target
    raise errors.TypeEnforcementError(msg)

  for key in target:
    if key not in key_types:
      msg = "Unknown parameter '%s'" % key
      raise errors.TypeEnforcementError(msg)

    if target[key] in allowed_values:
      continue

    ktype = key_types[key]
    if ktype not in constants.ENFORCEABLE_TYPES:
      msg = "'%s' has non-enforceable type %s" % (key, ktype)
      raise errors.ProgrammerError(msg)

    if ktype in (constants.VTYPE_STRING, constants.VTYPE_MAYBE_STRING):
      if target[key] is None and ktype == constants.VTYPE_MAYBE_STRING:
        pass
      elif not isinstance(target[key], basestring):
        if isinstance(target[key], bool) and not target[key]:
          target[key] = ""
        else:
          msg = "'%s' (value %s) is not a valid string" % (key, target[key])
          raise errors.TypeEnforcementError(msg)
    elif ktype == constants.VTYPE_BOOL:
      if isinstance(target[key], basestring) and target[key]:
        if target[key].lower() == constants.VALUE_FALSE:
          target[key] = False
        elif target[key].lower() == constants.VALUE_TRUE:
          target[key] = True
        else:
          msg = "'%s' (value %s) is not a valid boolean" % (key, target[key])
          raise errors.TypeEnforcementError(msg)
      elif target[key]:
        target[key] = True
      else:
        target[key] = False
    elif ktype == constants.VTYPE_SIZE:
      try:
        target[key] = ParseUnit(target[key])
      except errors.UnitParseError, err:
        msg = "'%s' (value %s) is not a valid size. error: %s" % \
              (key, target[key], err)
        raise errors.TypeEnforcementError(msg)
    elif ktype == constants.VTYPE_INT:
      try:
        target[key] = int(target[key])
      except (ValueError, TypeError):
        msg = "'%s' (value %s) is not a valid integer" % (key, target[key])
        raise errors.TypeEnforcementError(msg)
    elif ktype == constants.VTYPE_FLOAT:
      try:
        target[key] = float(target[key])
      except (ValueError, TypeError):
        msg = "'%s' (value %s) is not a valid float" % (key, target[key])
        raise errors.TypeEnforcementError(msg)


def ValidateServiceName(name):
  """Validate the given service name.

  @type name: number or string
  @param name: Service name or port specification

  """
  try:
    numport = int(name)
  except (ValueError, TypeError):
    # Non-numeric service name
    valid = _VALID_SERVICE_NAME_RE.match(name)
  else:
    # Numeric port (protocols other than TCP or UDP might need adjustments
    # here)
    valid = (numport >= 0 and numport < (1 << 16))

  if not valid:
    raise errors.OpPrereqError("Invalid service name '%s'" % name,
                               errors.ECODE_INVAL)

  return name


def _ComputeMissingKeys(key_path, options, defaults):
  """Helper functions to compute which keys a invalid.

  @param key_path: The current key path (if any)
  @param options: The user provided options
  @param defaults: The default dictionary
  @return: A list of invalid keys

  """
  defaults_keys = frozenset(defaults.keys())
  invalid = []
  for key, value in options.items():
    if key_path:
      new_path = "%s/%s" % (key_path, key)
    else:
      new_path = key

    if key not in defaults_keys:
      invalid.append(new_path)
    elif isinstance(value, dict):
      invalid.extend(_ComputeMissingKeys(new_path, value, defaults[key]))

  return invalid


def VerifyDictOptions(options, defaults):
  """Verify a dict has only keys set which also are in the defaults dict.

  @param options: The user provided options
  @param defaults: The default dictionary
  @raise error.OpPrereqError: If one of the keys is not supported

  """
  invalid = _ComputeMissingKeys("", options, defaults)

  if invalid:
    raise errors.OpPrereqError("Provided option keys not supported: %s" %
                               CommaJoin(invalid), errors.ECODE_INVAL)


def ListVolumeGroups():
  """List volume groups and their size

  @rtype: dict
  @return:
       Dictionary with keys volume name and values
       the size of the volume

  """
  command = "vgs --noheadings --units m --nosuffix -o name,size"
  result = RunCmd(command)
  retval = {}
  if result.failed:
    return retval

  for line in result.stdout.splitlines():
    try:
      name, size = line.split()
      size = int(float(size))
    except (IndexError, ValueError), err:
      logging.error("Invalid output from vgs (%s): %s", err, line)
      continue

    retval[name] = size

  return retval


def BridgeExists(bridge):
  """Check whether the given bridge exists in the system

  @type bridge: str
  @param bridge: the bridge name to check
  @rtype: boolean
  @return: True if it does

  """
  return os.path.isdir("/sys/class/net/%s/bridge" % bridge)


def TryConvert(fn, val):
  """Try to convert a value ignoring errors.

  This function tries to apply function I{fn} to I{val}. If no
  C{ValueError} or C{TypeError} exceptions are raised, it will return
  the result, else it will return the original value. Any other
  exceptions are propagated to the caller.

  @type fn: callable
  @param fn: function to apply to the value
  @param val: the value to be converted
  @return: The converted value if the conversion was successful,
      otherwise the original value.

  """
  try:
    nv = fn(val)
  except (ValueError, TypeError):
    nv = val
  return nv


def ParseCpuMask(cpu_mask):
  """Parse a CPU mask definition and return the list of CPU IDs.

  CPU mask format: comma-separated list of CPU IDs
  or dash-separated ID ranges
  Example: "0-2,5" -> "0,1,2,5"

  @type cpu_mask: str
  @param cpu_mask: CPU mask definition
  @rtype: list of int
  @return: list of CPU IDs

  """
  if not cpu_mask:
    return []
  cpu_list = []
  for range_def in cpu_mask.split(","):
    boundaries = range_def.split("-")
    n_elements = len(boundaries)
    if n_elements > 2:
      raise errors.ParseError("Invalid CPU ID range definition"
                              " (only one hyphen allowed): %s" % range_def)
    try:
      lower = int(boundaries[0])
    except (ValueError, TypeError), err:
      raise errors.ParseError("Invalid CPU ID value for lower boundary of"
                              " CPU ID range: %s" % str(err))
    try:
      higher = int(boundaries[-1])
    except (ValueError, TypeError), err:
      raise errors.ParseError("Invalid CPU ID value for higher boundary of"
                              " CPU ID range: %s" % str(err))
    if lower > higher:
      raise errors.ParseError("Invalid CPU ID range definition"
                              " (%d > %d): %s" % (lower, higher, range_def))
    cpu_list.extend(range(lower, higher + 1))
  return cpu_list


def ParseMultiCpuMask(cpu_mask):
  """Parse a multiple CPU mask definition and return the list of CPU IDs.

  CPU mask format: colon-separated list of comma-separated list of CPU IDs
  or dash-separated ID ranges, with optional "all" as CPU value
  Example: "0-2,5:all:1,5,6:2" -> [ [ 0,1,2,5 ], [ -1 ], [ 1, 5, 6 ], [ 2 ] ]

  @type cpu_mask: str
  @param cpu_mask: multiple CPU mask definition
  @rtype: list of lists of int
  @return: list of lists of CPU IDs

  """
  if not cpu_mask:
    return []
  cpu_list = []
  for range_def in cpu_mask.split(constants.CPU_PINNING_SEP):
    if range_def == constants.CPU_PINNING_ALL:
      cpu_list.append([constants.CPU_PINNING_ALL_VAL, ])
    else:
      # Uniquify and sort the list before adding
      cpu_list.append(sorted(set(ParseCpuMask(range_def))))

  return cpu_list


def GetHomeDir(user, default=None):
  """Try to get the homedir of the given user.

  The user can be passed either as a string (denoting the name) or as
  an integer (denoting the user id). If the user is not found, the
  C{default} argument is returned, which defaults to C{None}.

  """
  try:
    if isinstance(user, basestring):
      result = pwd.getpwnam(user)
    elif isinstance(user, (int, long)):
      result = pwd.getpwuid(user)
    else:
      raise errors.ProgrammerError("Invalid type passed to GetHomeDir (%s)" %
                                   type(user))
  except KeyError:
    return default
  return result.pw_dir


def FirstFree(seq, base=0):
  """Returns the first non-existing integer from seq.

  The seq argument should be a sorted list of positive integers. The
  first time the index of an element is smaller than the element
  value, the index will be returned.

  The base argument is used to start at a different offset,
  i.e. C{[3, 4, 6]} with I{offset=3} will return 5.

  Example: C{[0, 1, 3]} will return I{2}.

  @type seq: sequence
  @param seq: the sequence to be analyzed.
  @type base: int
  @param base: use this value as the base index of the sequence
  @rtype: int
  @return: the first non-used index in the sequence

  """
  for idx, elem in enumerate(seq):
    assert elem >= base, "Passed element is higher than base offset"
    if elem > idx + base:
      # idx is not used
      return idx + base
  return None


def SingleWaitForFdCondition(fdobj, event, timeout):
  """Waits for a condition to occur on the socket.

  Immediately returns at the first interruption.

  @type fdobj: integer or object supporting a fileno() method
  @param fdobj: entity to wait for events on
  @type event: integer
  @param event: ORed condition (see select module)
  @type timeout: float or None
  @param timeout: Timeout in seconds
  @rtype: int or None
  @return: None for timeout, otherwise occured conditions

  """
  check = (event | select.POLLPRI |
           select.POLLNVAL | select.POLLHUP | select.POLLERR)

  if timeout is not None:
    # Poller object expects milliseconds
    timeout *= 1000

  poller = select.poll()
  poller.register(fdobj, event)
  try:
    # TODO: If the main thread receives a signal and we have no timeout, we
    # could wait forever. This should check a global "quit" flag or something
    # every so often.
    io_events = poller.poll(timeout)
  except select.error, err:
    if err[0] != errno.EINTR:
      raise
    io_events = []
  if io_events and io_events[0][1] & check:
    return io_events[0][1]
  else:
    return None


class FdConditionWaiterHelper(object):
  """Retry helper for WaitForFdCondition.

  This class contains the retried and wait functions that make sure
  WaitForFdCondition can continue waiting until the timeout is actually
  expired.

  """

  def __init__(self, timeout):
    self.timeout = timeout

  def Poll(self, fdobj, event):
    result = SingleWaitForFdCondition(fdobj, event, self.timeout)
    if result is None:
      raise RetryAgain()
    else:
      return result

  def UpdateTimeout(self, timeout):
    self.timeout = timeout


def WaitForFdCondition(fdobj, event, timeout):
  """Waits for a condition to occur on the socket.

  Retries until the timeout is expired, even if interrupted.

  @type fdobj: integer or object supporting a fileno() method
  @param fdobj: entity to wait for events on
  @type event: integer
  @param event: ORed condition (see select module)
  @type timeout: float or None
  @param timeout: Timeout in seconds
  @rtype: int or None
  @return: None for timeout, otherwise occured conditions

  """
  if timeout is not None:
    retrywaiter = FdConditionWaiterHelper(timeout)
    try:
      result = Retry(retrywaiter.Poll, RETRY_REMAINING_TIME, timeout,
                     args=(fdobj, event), wait_fn=retrywaiter.UpdateTimeout)
    except RetryTimeout:
      result = None
  else:
    result = None
    while result is None:
      result = SingleWaitForFdCondition(fdobj, event, timeout)
  return result


def EnsureDaemon(name):
  """Check for and start daemon if not alive.

  @type name: string
  @param name: daemon name

  @rtype: bool
  @return: 'True' if daemon successfully started,
           'False' otherwise

  """
  result = RunCmd([pathutils.DAEMON_UTIL, "check-and-start", name])
  if result.failed:
    logging.error("Can't start daemon '%s', failure %s, output: %s",
                  name, result.fail_reason, result.output)
    return False

  return True


def StopDaemon(name):
  """Stop daemon

  @type name: string
  @param name: daemon name

  @rtype: bool
  @return: 'True' if daemon successfully stopped,
           'False' otherwise

  """
  result = RunCmd([pathutils.DAEMON_UTIL, "stop", name])
  if result.failed:
    logging.error("Can't stop daemon '%s', failure %s, output: %s",
                  name, result.fail_reason, result.output)
    return False

  return True


def SplitTime(value):
  """Splits time as floating point number into a tuple.

  @param value: Time in seconds
  @type value: int or float
  @return: Tuple containing (seconds, microseconds)

  """
  (seconds, microseconds) = divmod(int(value * 1000000), 1000000)
  # pylint: disable=C0122
  assert 0 <= seconds, \
    "Seconds must be larger than or equal to 0, but are %s" % seconds
  assert 0 <= microseconds <= 999999, \
    "Microseconds must be 0-999999, but are %s" % microseconds

  return (int(seconds), int(microseconds))


def MergeTime(timetuple):
  """Merges a tuple into time as a floating point number.

  @param timetuple: Time as tuple, (seconds, microseconds)
  @type timetuple: tuple
  @return: Time as a floating point number expressed in seconds

  """
  (seconds, microseconds) = timetuple
  # pylint: disable=C0122
  assert 0 <= seconds, \
    "Seconds must be larger than or equal to 0, but are %s" % seconds
  assert 0 <= microseconds <= 999999, \
    "Microseconds must be 0-999999, but are %s" % microseconds

  return float(seconds) + (float(microseconds) * 0.000001)


def EpochNano():
  """Return the current timestamp expressed as number of nanoseconds since the
  unix epoch

  @return: nanoseconds since the Unix epoch

  """
  return int(time.time() * 1000000000)


def FindMatch(data, name):
  """Tries to find an item in a dictionary matching a name.

  Callers have to ensure the data names aren't contradictory (e.g. a regexp
  that matches a string). If the name isn't a direct key, all regular
  expression objects in the dictionary are matched against it.

  @type data: dict
  @param data: Dictionary containing data
  @type name: string
  @param name: Name to look for
  @rtype: tuple; (value in dictionary, matched groups as list)

  """
  if name in data:
    return (data[name], [])

  for key, value in data.items():
    # Regex objects
    if hasattr(key, "match"):
      m = key.match(name)
      if m:
        return (value, list(m.groups()))

  return None


def GetMounts(filename=constants.PROC_MOUNTS):
  """Returns the list of mounted filesystems.

  This function is Linux-specific.

  @param filename: path of mounts file (/proc/mounts by default)
  @rtype: list of tuples
  @return: list of mount entries (device, mountpoint, fstype, options)

  """
  # TODO(iustin): investigate non-Linux options (e.g. via mount output)
  data = []
  mountlines = ReadFile(filename).splitlines()
  for line in mountlines:
    device, mountpoint, fstype, options, _ = line.split(None, 4)
    data.append((device, mountpoint, fstype, options))

  return data


def SignalHandled(signums):
  """Signal Handled decoration.

  This special decorator installs a signal handler and then calls the target
  function. The function must accept a 'signal_handlers' keyword argument,
  which will contain a dict indexed by signal number, with SignalHandler
  objects as values.

  The decorator can be safely stacked with iself, to handle multiple signals
  with different handlers.

  @type signums: list
  @param signums: signals to intercept

  """
  def wrap(fn):
    def sig_function(*args, **kwargs):
      assert "signal_handlers" not in kwargs or \
             kwargs["signal_handlers"] is None or \
             isinstance(kwargs["signal_handlers"], dict), \
             "Wrong signal_handlers parameter in original function call"
      if "signal_handlers" in kwargs and kwargs["signal_handlers"] is not None:
        signal_handlers = kwargs["signal_handlers"]
      else:
        signal_handlers = {}
        kwargs["signal_handlers"] = signal_handlers
      sighandler = SignalHandler(signums)
      try:
        for sig in signums:
          signal_handlers[sig] = sighandler
        return fn(*args, **kwargs)
      finally:
        sighandler.Reset()
    return sig_function
  return wrap


def TimeoutExpired(epoch, timeout, _time_fn=time.time):
  """Checks whether a timeout has expired.

  """
  return _time_fn() > (epoch + timeout)


class SignalWakeupFd(object):
  try:
    # This is only supported in Python 2.5 and above (some distributions
    # backported it to Python 2.4)
    _set_wakeup_fd_fn = signal.set_wakeup_fd
  except AttributeError:
    # Not supported

    def _SetWakeupFd(self, _): # pylint: disable=R0201
      return -1
  else:

    def _SetWakeupFd(self, fd):
      return self._set_wakeup_fd_fn(fd)

  def __init__(self):
    """Initializes this class.

    """
    (read_fd, write_fd) = os.pipe()

    # Once these succeeded, the file descriptors will be closed automatically.
    # Buffer size 0 is important, otherwise .read() with a specified length
    # might buffer data and the file descriptors won't be marked readable.
    self._read_fh = os.fdopen(read_fd, "r", 0)
    self._write_fh = os.fdopen(write_fd, "w", 0)

    self._previous = self._SetWakeupFd(self._write_fh.fileno())

    # Utility functions
    self.fileno = self._read_fh.fileno
    self.read = self._read_fh.read

  def Reset(self):
    """Restores the previous wakeup file descriptor.

    """
    if hasattr(self, "_previous") and self._previous is not None:
      self._SetWakeupFd(self._previous)
      self._previous = None

  def Notify(self):
    """Notifies the wakeup file descriptor.

    """
    self._write_fh.write(chr(0))

  def __del__(self):
    """Called before object deletion.

    """
    self.Reset()


class SignalHandler(object):
  """Generic signal handler class.

  It automatically restores the original handler when deconstructed or
  when L{Reset} is called. You can either pass your own handler
  function in or query the L{called} attribute to detect whether the
  signal was sent.

  @type signum: list
  @ivar signum: the signals we handle
  @type called: boolean
  @ivar called: tracks whether any of the signals have been raised

  """
  def __init__(self, signum, handler_fn=None, wakeup=None):
    """Constructs a new SignalHandler instance.

    @type signum: int or list of ints
    @param signum: Single signal number or set of signal numbers
    @type handler_fn: callable
    @param handler_fn: Signal handling function

    """
    assert handler_fn is None or callable(handler_fn)

    self.signum = set(signum)
    self.called = False

    self._handler_fn = handler_fn
    self._wakeup = wakeup

    self._previous = {}
    try:
      for signum in self.signum:
        # Setup handler
        prev_handler = signal.signal(signum, self._HandleSignal)
        try:
          self._previous[signum] = prev_handler
        except:
          # Restore previous handler
          signal.signal(signum, prev_handler)
          raise
    except:
      # Reset all handlers
      self.Reset()
      # Here we have a race condition: a handler may have already been called,
      # but there's not much we can do about it at this point.
      raise

  def __del__(self):
    self.Reset()

  def Reset(self):
    """Restore previous handler.

    This will reset all the signals to their previous handlers.

    """
    for signum, prev_handler in self._previous.items():
      signal.signal(signum, prev_handler)
      # If successful, remove from dict
      del self._previous[signum]

  def Clear(self):
    """Unsets the L{called} flag.

    This function can be used in case a signal may arrive several times.

    """
    self.called = False

  def _HandleSignal(self, signum, frame):
    """Actual signal handling function.

    """
    # This is not nice and not absolutely atomic, but it appears to be the only
    # solution in Python -- there are no atomic types.
    self.called = True

    if self._wakeup:
      # Notify whoever is interested in signals
      self._wakeup.Notify()

    if self._handler_fn:
      self._handler_fn(signum, frame)


class FieldSet(object):
  """A simple field set.

  Among the features are:
    - checking if a string is among a list of static string or regex objects
    - checking if a whole list of string matches
    - returning the matching groups from a regex match

  Internally, all fields are held as regular expression objects.

  """
  def __init__(self, *items):
    self.items = [re.compile("^%s$" % value) for value in items]

  def Extend(self, other_set):
    """Extend the field set with the items from another one"""
    self.items.extend(other_set.items)

  def Matches(self, field):
    """Checks if a field matches the current set

    @type field: str
    @param field: the string to match
    @return: either None or a regular expression match object

    """
    for m in itertools.ifilter(None, (val.match(field) for val in self.items)):
      return m
    return None

  def NonMatching(self, items):
    """Returns the list of fields not matching the current set

    @type items: list
    @param items: the list of fields to check
    @rtype: list
    @return: list of non-matching fields

    """
    return [val for val in items if not self.Matches(val)]


def ValidateDeviceNames(kind, container):
  """Validate instance device names.

  Check that a device container contains only unique and valid names.

  @type kind: string
  @param kind: One-word item description
  @type container: list
  @param container: Container containing the devices

  """

  valid = []
  for device in container:
    if isinstance(device, dict):
      if kind == "NIC":
        name = device.get(constants.INIC_NAME, None)
      elif kind == "disk":
        name = device.get(constants.IDISK_NAME, None)
      else:
        raise errors.OpPrereqError("Invalid container kind '%s'" % kind,
                                   errors.ECODE_INVAL)
    else:
      name = device.name
      # Check that a device name is not the UUID of another device
      valid.append(device.uuid)

    try:
      int(name)
    except (ValueError, TypeError):
      pass
    else:
      raise errors.OpPrereqError("Invalid name '%s'. Purely numeric %s names"
                                 " are not allowed" % (name, kind),
                                 errors.ECODE_INVAL)

    if name is not None and name.lower() != constants.VALUE_NONE:
      if name in valid:
        raise errors.OpPrereqError("%s name '%s' already used" % (kind, name),
                                   errors.ECODE_NOTUNIQUE)
      else:
        valid.append(name)


def AllDiskOfType(disks_info, dev_types):
  """Checks if the instance has only disks of any of the dev_types.

  @type disks_info: list of L{Disk}
  @param disks_info: all the disks of the instance.
  @type dev_types: list of disk templates
  @param dev_types: the disk type required.

  @rtype: bool
  @return: True iff the instance only has disks of type dev_type.
  """

  assert not isinstance(dev_types, str)

  if not disks_info and constants.DT_DISKLESS not in dev_types:
    return False

  for disk in disks_info:
    if disk.dev_type not in dev_types:
      return False

  return True


def AnyDiskOfType(disks_info, dev_types):
  """Checks if the instance has some disks of any types in dev_types.

  @type disks_info: list of L{Disk}
  @param disks_info: all the disks of the instance.
  @type dev_types: list of disk template
  @param dev_types: the disk type required.

  @rtype: bool
  @return: True if the instance has disks of type dev_types or the instance has
    no disks and the dev_types allow DT_DISKLESS.
  """

  assert not isinstance(dev_types, str)

  if not disks_info and constants.DT_DISKLESS in dev_types:
    return True

  for disk in disks_info:
    if disk.dev_type in dev_types:
      return True

  return False


def GetDiskTemplateString(disk_types):
  """Gives a summary disk template from disk devtypes.

  @type disk_types: list of string
  @param disk_types: all the dev_types of the instance.
  @rtype disk template
  @returns the summarized disk template of the disk types.

  """
  disk_types = set(dev_type for dev_type in disk_types)
  if not disk_types:
    return constants.DT_DISKLESS
  elif len(disk_types) > 1:
    return constants.DT_MIXED
  else:
    return disk_types.pop()


def GetDiskTemplate(disks_info):
  """Gives a summary disk template from disks.

  @type disks_info: list of L{Disk}
  @param disks_info: all the disks of the instance.
  @rtype disk template
  @returns the summarized disk template of the disk types.

  """
  return GetDiskTemplateString(d.dev_type for d in disks_info)
