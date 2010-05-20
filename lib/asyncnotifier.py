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

try:
  # pylint: disable-msg=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify


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
