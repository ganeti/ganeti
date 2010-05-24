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
  # pylint: disable-msg=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import errors

# We contributed the AsyncNotifier class back to python-pyinotify, and it's
# part of their codebase since version 0.8.7. This code can be removed once
# we'll be ready to depend on python-pyinotify >= 0.8.7
class AsyncNotifier(asyncore.file_dispatcher):
  """An asyncore dispatcher for inotify events.

  """
  # pylint: disable-msg=W0622,W0212
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


class SingleFileEventHandler(pyinotify.ProcessEvent):
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
    # pylint: disable-msg=W0231
    # no need to call the parent's constructor
    self.watch_manager = watch_manager
    self.callback = callback
    self.mask = pyinotify.EventsCodes.ALL_FLAGS["IN_IGNORED"] | \
                pyinotify.EventsCodes.ALL_FLAGS["IN_MODIFY"]
    self.file = filename
    self.watch_handle = None

  def enable(self):
    """Watch the given file

    """
    if self.watch_handle is None:
      result = self.watch_manager.add_watch(self.file, self.mask)
      if not self.file in result or result[self.file] <= 0:
        raise errors.InotifyError("Could not add inotify watcher")
      else:
        self.watch_handle = result[self.file]

  def disable(self):
    """Stop watching the given file

    """
    if self.watch_handle is not None:
      result = self.watch_manager.rm_watch(self.watch_handle)
      if result[self.watch_handle]:
        self.watch_handle = None

  # pylint: disable-msg=C0103
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
    self.watch_handle = None

    try:
      self.callback(False)
    except: # pylint: disable-msg=W0702
      # we need to catch any exception here, log it, but proceed, because even
      # if we failed handling a single request, we still want our daemon to
      # proceed.
      logging.error("Unexpected exception", exc_info=True)

  # pylint: disable-msg=C0103
  # this overrides a method in pyinotify.ProcessEvent
  def process_IN_MODIFY(self, event):
    # This gets called when the monitored file is modified. Note that this
    # doesn't usually happen in Ganeti, as most of the time we're just
    # replacing any file with a new one, at filesystem level, rather than
    # actually changing it. (see utils.WriteFile)
    logging.debug("Received 'modify' inotify event for %s", event.path)

    try:
      self.callback(True)
    except: # pylint: disable-msg=W0702
      # we need to catch any exception here, log it, but proceed, because even
      # if we failed handling a single request, we still want our daemon to
      # proceed.
      logging.error("Unexpected exception", exc_info=True)

  def process_default(self, event):
    logging.error("Received unhandled inotify event: %s", event)
