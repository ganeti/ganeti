#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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
    except Exception, msg: # pylint: disable-msg=W0703
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
    self.statefile = os.fdopen(fd, 'w+')

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

    @type instance: L{Instance}
    @param instance: the instance to look up

    """
    idata = self._data["instance"]

    if instance_name in idata:
      return idata[instance_name][KEY_RESTART_COUNT]

    return 0

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
                         if idict[i][KEY_RESTART_WHEN] < earliest]
    for inst in expired_instances:
      logging.debug("Expiring record for instance %s", inst)
      idict.pop(inst, None)

  def RecordRestartAttempt(self, instance_name):
    """Record a restart attempt.

    @type instance: L{Instance}
    @param instance: the instance being restarted

    """
    idata = self._data["instance"]

    inst = idata.setdefault(instance_name, {})
    inst[KEY_RESTART_WHEN] = time.time()
    inst[KEY_RESTART_COUNT] = inst.get(KEY_RESTART_COUNT, 0) + 1

  def RemoveInstance(self, instance_name):
    """Update state to reflect that a machine is running.

    This method removes the record for a named instance (as we only
    track down instances).

    @type instance: L{Instance}
    @param instance: the instance to remove from books

    """
    idata = self._data["instance"]

    idata.pop(instance_name, None)
