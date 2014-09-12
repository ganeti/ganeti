#
#

# Copyright (C) 2009 Google Inc.
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
      raise errors.InotifyError("Could not add inotify watcher (error code %s);"
                                " increasing fs.inotify.max_user_watches sysctl"
                                " might be necessary" % ret)

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
