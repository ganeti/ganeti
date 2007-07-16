#!/usr/bin/python
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


"""Global Configuration data for Ganeti.

This module provides the interface to a special case of cluster
configuration data, which is mostly static and available to all nodes.

"""

import os
import tempfile
import errno
import socket

from ganeti import errors
from ganeti import constants


class SimpleStore:
  """Interface to static cluster data.

  This is different that the config.ConfigWriter class in that it
  holds data that is (mostly) constant after the cluster
  initialization. Its purpose is to allow limited customization of
  things which would otherwise normally live in constants.py. Note
  that this data cannot live in ConfigWriter as that is available only
  on the master node, and our data must be readable by both the master
  and the nodes.

  Other particularities of the datastore:
    - keys are restricted to predefined values
    - values are small (<4k)
    - since the data is practically static, read keys are cached in memory
    - some keys are handled specially (read from the system, so
      we can't update them)

  """
  _SS_FILEPREFIX = "ssconf_"
  SS_HYPERVISOR = "hypervisor"
  SS_NODED_PASS = "node_pass"
  _VALID_KEYS = (SS_HYPERVISOR, SS_NODED_PASS,)
  _MAX_SIZE = 4096

  def __init__(self, cfg_location=None):
    if cfg_location is None:
      self._cfg_dir = constants.DATA_DIR
    else:
      self._cfg_dir = cfg_location
    self._cache = {}

  def KeyToFilename(self, key):
    """Convert a given key into filename.

    """
    if key not in self._VALID_KEYS:
      raise errors.ProgrammerError, ("Invalid key requested from SSConf: '%s'"
                                     % str(key))

    filename = self._cfg_dir + '/' + self._SS_FILEPREFIX + key
    return filename

  def _ReadFile(self, key):
    """Generic routine to read keys.

    This will read the file which holds the value requested. Errors
    will be changed into ConfigurationErrors.

    """
    if key in self._cache:
      return self._cache[key]
    filename = self.KeyToFilename(key)
    try:
      fh = file(filename, 'r')
      try:
        data = fh.readline(self._MAX_SIZE)
        data = data.rstrip('\n')
      finally:
        fh.close()
    except EnvironmentError, err:
      raise errors.ConfigurationError, ("Can't read from the ssconf file:"
                                        " '%s'" % str(err))
    self._cache[key] = data
    return data

  def GetNodeDaemonPort(self):
    """Get the node daemon port for this cluster.

    Note that this routine does not read a ganeti-specific file, but
    instead uses socket.getservbyname to allow pre-customization of
    this parameter outside of ganeti.

    """
    try:
      port = socket.getservbyname("ganeti-noded", "tcp")
    except socket.error:
      port = constants.DEFAULT_NODED_PORT

    return port

  def GetHypervisorType(self):
    """Get the hypervisor type for this cluster.

    """
    return self._ReadFile(self.SS_HYPERVISOR)

  def GetNodeDaemonPassword(self):
    """Get the node password for this cluster.

    """
    return self._ReadFile(self.SS_NODED_PASS)

  def SetKey(self, key, value):
    """Set the value of a key.

    This should be used only when adding a node to a cluster.

    """
    file_name = self.KeyToFilename(key)
    dir_name, small_name = os.path.split(file_name)
    fd, new_name = tempfile.mkstemp('.new', small_name, dir_name)
    # here we need to make sure we remove the temp file, if any error
    # leaves it in place
    try:
      os.chown(new_name, 0, 0)
      os.chmod(new_name, 0400)
      os.write(fd, "%s\n" % str(value))
      os.fsync(fd)
      os.rename(new_name, file_name)
      self._cache[key] = value
    finally:
      os.close(fd)
      try:
        os.unlink(new_name)
      except OSError, err:
        if err.errno != errno.ENOENT:
          raise

  def GetFileList(self):
    """Return the lis of all config files.

    This is used for computing node replication data.

    """
    return [self.KeyToFilename(key) for key in self._VALID_KEYS]
