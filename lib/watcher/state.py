#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""Module keeping state for Ganeti watcher.

"""

import os
import time
import logging

from ganeti import utils
from ganeti import serializer
from ganeti import errors


# Delete any record that is older than 8 hours; this value is based on
# the fact that the current retry counter is 5, and watcher runs every
# 5 minutes, so it takes around half an hour to exceed the retry
# counter, so 8 hours (16*1/2h) seems like a reasonable reset time
RETRY_EXPIRATION = 8 * 3600

KEY_CLEANUP_COUNT = "cleanup_count"
KEY_CLEANUP_WHEN = "cleanup_when"
KEY_RESTART_COUNT = "restart_count"
KEY_RESTART_WHEN = "restart_when"
KEY_BOOT_ID = "bootid"


def OpenStateFile(path):
  """Opens the state file and acquires a lock on it.

  @type path: string
  @param path: Path to state file

  """
  # The two-step dance below is necessary to allow both opening existing
  # file read/write and creating if not existing. Vanilla open will truncate
  # an existing file -or- allow creating if not existing.
  statefile_fd = os.open(path, os.O_RDWR | os.O_CREAT)

  # Try to acquire lock on state file. If this fails, another watcher instance
  # might already be running or another program is temporarily blocking the
  # watcher from running.
  try:
    utils.LockFile(statefile_fd)
  except errors.LockError, err:
    logging.error("Can't acquire lock on state file %s: %s", path, err)
    return None

  return os.fdopen(statefile_fd, "w+")


class WatcherState(object):
  """Interface to a state file recording restart attempts.

  """
  def __init__(self, statefile):
    """Open, lock, read and parse the file.

    @type statefile: file
    @param statefile: State file object

    """
    self.statefile = statefile

    try:
      state_data = self.statefile.read()
      if not state_data:
        self._data = {}
      else:
        self._data = serializer.Load(state_data)
    except Exception, msg: # pylint: disable=W0703
      # Ignore errors while loading the file and treat it as empty
      self._data = {}
      logging.warning(("Invalid state file. Using defaults."
                       " Error message: %s"), msg)

    if "instance" not in self._data:
      self._data["instance"] = {}
    if "node" not in self._data:
      self._data["node"] = {}

    self._orig_data = serializer.Dump(self._data)

  def Save(self, filename):
    """Save state to file, then unlock and close it.

    """
    assert self.statefile

    serialized_form = serializer.Dump(self._data)
    if self._orig_data == serialized_form:
      logging.debug("Data didn't change, just touching status file")
      os.utime(filename, None)
      return

    # We need to make sure the file is locked before renaming it, otherwise
    # starting ganeti-watcher again at the same time will create a conflict.
    fd = utils.WriteFile(filename,
                         data=serialized_form,
                         prewrite=utils.LockFile, close=False)
    self.statefile = os.fdopen(fd, "w+")

  def Close(self):
    """Unlock configuration file and close it.

    """
    assert self.statefile

    # Files are automatically unlocked when closing them
    self.statefile.close()
    self.statefile = None

  def GetNodeBootID(self, name):
    """Returns the last boot ID of a node or None.

    """
    ndata = self._data["node"]

    if name in ndata and KEY_BOOT_ID in ndata[name]:
      return ndata[name][KEY_BOOT_ID]
    return None

  def SetNodeBootID(self, name, bootid):
    """Sets the boot ID of a node.

    """
    assert bootid

    ndata = self._data["node"]

    ndata.setdefault(name, {})[KEY_BOOT_ID] = bootid

  def NumberOfRestartAttempts(self, instance_name):
    """Returns number of previous restart attempts.

    @type instance_name: string
    @param instance_name: the name of the instance to look up

    """
    idata = self._data["instance"]
    return idata.get(instance_name, {}).get(KEY_RESTART_COUNT, 0)

  def NumberOfCleanupAttempts(self, instance_name):
    """Returns number of previous cleanup attempts.

    @type instance_name: string
    @param instance_name: the name of the instance to look up

    """
    idata = self._data["instance"]
    return idata.get(instance_name, {}).get(KEY_CLEANUP_COUNT, 0)

  def MaintainInstanceList(self, instances):
    """Perform maintenance on the recorded instances.

    @type instances: list of string
    @param instances: the list of currently existing instances

    """
    idict = self._data["instance"]

    # First, delete obsolete instances
    obsolete_instances = set(idict).difference(instances)
    for inst in obsolete_instances:
      logging.debug("Forgetting obsolete instance %s", inst)
      idict.pop(inst, None)

    # Second, delete expired records
    earliest = time.time() - RETRY_EXPIRATION
    expired_instances = [i for i in idict
                         if idict[i].get(KEY_RESTART_WHEN, 0) < earliest]
    for inst in expired_instances:
      logging.debug("Expiring record for instance %s", inst)
      idict.pop(inst, None)

  @staticmethod
  def _RecordAttempt(instances, instance_name, key_when, key_count):
    """Record an event.

    @type instances: dict
    @param instances: contains instance data indexed by instance_name

    @type instance_name: string
    @param instance_name: name of the instance involved in the event

    @type key_when:
    @param key_when: dict key for the information for when the event occurred

    @type key_count: int
    @param key_count: dict key for the information for how many times
                      the event occurred

    """
    instance = instances.setdefault(instance_name, {})
    instance[key_when] = time.time()
    instance[key_count] = instance.get(key_count, 0) + 1

  def RecordRestartAttempt(self, instance_name):
    """Record a restart attempt.

    @type instance_name: string
    @param instance_name: the name of the instance being restarted

    """
    self._RecordAttempt(self._data["instance"], instance_name,
                        KEY_RESTART_WHEN, KEY_RESTART_COUNT)

  def RecordCleanupAttempt(self, instance_name):
    """Record a cleanup attempt.

    @type instance_name: string
    @param instance_name: the name of the instance being cleaned up

    """
    self._RecordAttempt(self._data["instance"], instance_name,
                        KEY_CLEANUP_WHEN, KEY_CLEANUP_COUNT)

  def RemoveInstance(self, instance_name):
    """Update state to reflect that a machine is running.

    This method removes the record for a named instance (as we only
    track down instances).

    @type instance_name: string
    @param instance_name: the name of the instance to remove from books

    """
    idata = self._data["instance"]

    idata.pop(instance_name, None)
