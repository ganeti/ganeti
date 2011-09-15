#
#

# Copyright (C) 2009 Google Inc.
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


"""Asynchronous pyinotify implementation"""


import asyncore
import logging

try:
  # pylint: disable=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import daemon
from ganeti import errors


# We contributed the AsyncNotifier class back to python-pyinotify, and it's
# part of their codebase since version 0.8.7. This code can be removed once
# we'll be ready to depend on python-pyinotify >= 0.8.7
class AsyncNotifier(asyncore.file_dispatcher):
  """An asyncore dispatcher for inotify events.

  """
  # pylint: disable=W0622,W0212
  def __init__(self, watch_manager, default_proc_fun=None, map=None):
    """Initializes this class.

    This is a a special asyncore file_dispatcher that actually wraps a
    pyinotify Notifier, making it asyncronous.

    """
    if default_proc_fun is None:
      default_proc_fun = pyinotify.ProcessEvent()

    self.notifier = pyinotify.Notifier(watch_manager, default_proc_fun)

    # here we need to steal the file descriptor from the notifier, so we can
    # use it in the global asyncore select, and avoid calling the
    # check_events() function of the notifier (which doesn't allow us to select
    # together with other file descriptors)
    self.fd = self.notifier._fd
    asyncore.file_dispatcher.__init__(self, self.fd, map)

  def handle_read(self):
    self.notifier.read_events()
    self.notifier.process_events()


class ErrorLoggingAsyncNotifier(AsyncNotifier,
                                daemon.GanetiBaseAsyncoreDispatcher):
  """An asyncnotifier that can survive errors in the callbacks.

  We define this as a separate class, since we don't want to make AsyncNotifier
  diverge from what we contributed upstream.

  """


class FileEventHandlerBase(pyinotify.ProcessEvent):
  """Base class for file event handlers.

  @ivar watch_manager: Inotify watch manager

  """
  def __init__(self, watch_manager):
    """Initializes this class.

    @type watch_manager: pyinotify.WatchManager
    @param watch_manager: inotify watch manager

    """
    # pylint: disable=W0231
    # no need to call the parent's constructor
    self.watch_manager = watch_manager

  def process_default(self, event):
    logging.error("Received unhandled inotify event: %s", event)

  def AddWatch(self, filename, mask):
    """Adds a file watch.

    @param filename: Path to file
    @param mask: Inotify event mask
    @return: Result

    """
    result = self.watch_manager.add_watch(filename, mask)

    ret = result.get(filename, -1)
    if ret <= 0:
      raise errors.InotifyError("Could not add inotify watcher (%s)" % ret)

    return result[filename]

  def RemoveWatch(self, handle):
    """Removes a handle from the watcher.

    @param handle: Inotify handle
    @return: Whether removal was successful

    """
    result = self.watch_manager.rm_watch(handle)

    return result[handle]


class SingleFileEventHandler(FileEventHandlerBase):
  """Handle modify events for a single file.

  """
  def __init__(self, watch_manager, callback, filename):
    """Constructor for SingleFileEventHandler

    @type watch_manager: pyinotify.WatchManager
    @param watch_manager: inotify watch manager
    @type callback: function accepting a boolean
    @param callback: function to call when an inotify event happens
    @type filename: string
    @param filename: config file to watch

    """
    FileEventHandlerBase.__init__(self, watch_manager)

    self._callback = callback
    self._filename = filename

    self._watch_handle = None

  def enable(self):
    """Watch the given file.

    """
    if self._watch_handle is not None:
      return

    # Different Pyinotify versions have the flag constants at different places,
    # hence not accessing them directly
    mask = (pyinotify.EventsCodes.ALL_FLAGS["IN_MODIFY"] |
            pyinotify.EventsCodes.ALL_FLAGS["IN_IGNORED"])

    self._watch_handle = self.AddWatch(self._filename, mask)

  def disable(self):
    """Stop watching the given file.

    """
    if self._watch_handle is not None and self.RemoveWatch(self._watch_handle):
      self._watch_handle = None

  # pylint: disable=C0103
  # this overrides a method in pyinotify.ProcessEvent
  def process_IN_IGNORED(self, event):
    # Since we monitor a single file rather than the directory it resides in,
    # when that file is replaced with another one (which is what happens when
    # utils.WriteFile, the most normal way of updating files in ganeti, is
    # called) we're going to receive an IN_IGNORED event from inotify, because
    # of the file removal (which is contextual with the replacement). In such a
    # case we'll need to create a watcher for the "new" file. This can be done
    # by the callback by calling "enable" again on us.
    logging.debug("Received 'ignored' inotify event for %s", event.path)
    self._watch_handle = None
    self._callback(False)

  # pylint: disable=C0103
  # this overrides a method in pyinotify.ProcessEvent
  def process_IN_MODIFY(self, event):
    # This gets called when the monitored file is modified. Note that this
    # doesn't usually happen in Ganeti, as most of the time we're just
    # replacing any file with a new one, at filesystem level, rather than
    # actually changing it. (see utils.WriteFile)
    logging.debug("Received 'modify' inotify event for %s", event.path)
    self._callback(True)
