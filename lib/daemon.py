#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Module with helper classes and functions for daemons"""


import os
import select
import signal
import errno
import logging

from ganeti import utils
from ganeti import constants


class Mainloop(object):
  """Generic mainloop for daemons

  """
  def __init__(self):
    """Constructs a new Mainloop instance.

    """
    self._io_wait = {}
    self._signal_wait = []
    self._poller = select.poll()

  @utils.SignalHandled([signal.SIGCHLD])
  @utils.SignalHandled([signal.SIGTERM])
  def Run(self, stop_on_empty=False, signal_handlers=None):
    """Runs the mainloop.

    @type stop_on_empty: bool
    @param stop_on_empty: Whether to stop mainloop once all I/O waiters
                          unregistered
    @type signal_handlers: dict
    @param signal_handlers: signal->L{utils.SignalHandler} passed by decorator

    """
    assert isinstance(signal_handlers, dict) and \
           len(signal_handlers) > 0, \
           "Broken SignalHandled decorator"
    running = True
    # Start actual main loop
    while running:
      # Stop if nothing is listening anymore
      if stop_on_empty and not (self._io_wait):
        break

      # Wait for I/O events
      try:
        io_events = self._poller.poll(None)
      except select.error, err:
        # EINTR can happen when signals are sent
        if err.args and err.args[0] in (errno.EINTR,):
          io_events = None
        else:
          raise

      if io_events:
        # Check for I/O events
        for (evfd, evcond) in io_events:
          owner = self._io_wait.get(evfd, None)
          if owner:
            owner.OnIO(evfd, evcond)

      # Check whether a signal was raised
      for sig in signal_handlers:
        handler = signal_handlers[sig]
        if handler.called:
          self._CallSignalWaiters(sig)
          running = (sig != signal.SIGTERM)
          handler.Clear()

  def _CallSignalWaiters(self, signum):
    """Calls all signal waiters for a certain signal.

    @type signum: int
    @param signum: Signal number

    """
    for owner in self._signal_wait:
      owner.OnSignal(signal.SIGCHLD)

  def RegisterIO(self, owner, fd, condition):
    """Registers a receiver for I/O notifications

    The receiver must support a "OnIO(self, fd, conditions)" function.

    @type owner: instance
    @param owner: Receiver
    @type fd: int
    @param fd: File descriptor
    @type condition: int
    @param condition: ORed field of conditions to be notified
                      (see select module)

    """
    # select.Poller also supports file() like objects, but we don't.
    assert isinstance(fd, (int, long)), \
      "Only integers are supported for file descriptors"

    self._io_wait[fd] = owner
    self._poller.register(fd, condition)

  def RegisterSignal(self, owner):
    """Registers a receiver for signal notifications

    The receiver must support a "OnSignal(self, signum)" function.

    @type owner: instance
    @param owner: Receiver

    """
    self._signal_wait.append(owner)


def GenericMain(daemon_name, optionparser, dirs, check_fn, exec_fn):
  """Shared main function for daemons.

  @type daemon_name: string
  @param daemon_name: daemon name
  @type optionparser: L{optparse.OptionParser}
  @param optionparser: initialized optionparser with daemon-specific options
                       (common -f -d options will be handled by this module)
  @type options: object @param options: OptionParser result, should contain at
                 least the fork and the debug options
  @type dirs: list of strings
  @param dirs: list of directories that must exist for this daemon to work
  @type check_fn: function which accepts (options, args)
  @param check_fn: function that checks start conditions and exits if they're
                   not met
  @type exec_fn: function which accepts (options, args)
  @param exec_fn: function that's executed with the daemon's pid file held, and
                  runs the daemon itself.

  """
  optionparser.add_option("-f", "--foreground", dest="fork",
                          help="Don't detach from the current terminal",
                          default=True, action="store_false")
  optionparser.add_option("-d", "--debug", dest="debug",
                          help="Enable some debug messages",
                          default=False, action="store_true")
  if daemon_name in constants.DAEMONS_PORTS:
    # for networked daemons we also allow choosing the bind port and address.
    # by default we use the port provided by utils.GetDaemonPort, and bind to
    # 0.0.0.0 (which is represented by and empty bind address.
    port = utils.GetDaemonPort(daemon_name)
    optionparser.add_option("-p", "--port", dest="port",
                            help="Network port (%s default)." % port,
                            default=port, type="int")
    optionparser.add_option("-b", "--bind", dest="bind_address",
                            help="Bind address",
                            default="", metavar="ADDRESS")

  if daemon_name in constants.DAEMONS_SSL:
    default_cert, default_key = constants.DAEMONS_SSL[daemon_name]
    optionparser.add_option("--no-ssl", dest="ssl",
                            help="Do not secure HTTP protocol with SSL",
                            default=True, action="store_false")
    optionparser.add_option("-K", "--ssl-key", dest="ssl_key",
                            help="SSL key",
                            default=default_key, type="string")
    optionparser.add_option("-C", "--ssl-cert", dest="ssl_cert",
                            help="SSL certificate",
                            default=default_cert, type="string")

  multithread = utils.no_fork = daemon_name in constants.MULTITHREADED_DAEMONS

  options, args = optionparser.parse_args()

  if hasattr(options, 'ssl') and options.ssl:
    if not (options.ssl_cert and options.ssl_key):
      print >> sys.stderr, "Need key and certificate to use ssl"
      sys.exit(constants.EXIT_FAILURE)
    for fname in (options.ssl_cert, options.ssl_key):
      if not os.path.isfile(fname):
        print >> sys.stderr, "Need ssl file %s to run" % fname
        sys.exit(constants.EXIT_FAILURE)

  if check_fn is not None:
    check_fn(options, args)

  utils.EnsureDirs(dirs)

  if options.fork:
    utils.CloseFDs()
    utils.Daemonize(logfile=constants.DAEMONS_LOGFILES[daemon_name])

  utils.WritePidFile(daemon_name)
  try:
    utils.SetupLogging(logfile=constants.DAEMONS_LOGFILES[daemon_name],
                       debug=options.debug,
                       stderr_logging=not options.fork,
                       multithreaded=multithread)
    logging.info("%s daemon startup" % daemon_name)
    exec_fn(options, args)
  finally:
    utils.RemovePidFile(daemon_name)

