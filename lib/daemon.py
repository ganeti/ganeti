#
#

# Copyright (C) 2006, 2007, 2008, 2010, 2011, 2012 Google Inc.
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


import asyncore
import asynchat
import collections
import os
import signal
import logging
import sched
import time
import socket
import select
import sys

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import ssconf
from ganeti import runtime
from ganeti import compat


class SchedulerBreakout(Exception):
  """Exception used to get out of the scheduler loop

  """


def AsyncoreDelayFunction(timeout):
  """Asyncore-compatible scheduler delay function.

  This is a delay function for sched that, rather than actually sleeping,
  executes asyncore events happening in the meantime.

  After an event has occurred, rather than returning, it raises a
  SchedulerBreakout exception, which will force the current scheduler.run()
  invocation to terminate, so that we can also check for signals. The main loop
  will then call the scheduler run again, which will allow it to actually
  process any due events.

  This is needed because scheduler.run() doesn't support a count=..., as
  asyncore loop, and the scheduler module documents throwing exceptions from
  inside the delay function as an allowed usage model.

  """
  asyncore.loop(timeout=timeout, count=1, use_poll=True)
  raise SchedulerBreakout()


class AsyncoreScheduler(sched.scheduler):
  """Event scheduler integrated with asyncore

  """
  def __init__(self, timefunc):
    """Initializes this class.

    """
    sched.scheduler.__init__(self, timefunc, self._LimitedDelay)
    self._max_delay = None

  def run(self, max_delay=None): # pylint: disable=W0221
    """Run any pending events.

    @type max_delay: None or number
    @param max_delay: Maximum delay (useful if caller has timeouts running)

    """
    assert self._max_delay is None

    # The delay function used by the scheduler can't be different on each run,
    # hence an instance variable must be used.
    if max_delay is None:
      self._max_delay = None
    else:
      self._max_delay = utils.RunningTimeout(max_delay, False)

    try:
      return sched.scheduler.run(self)
    finally:
      self._max_delay = None

  def _LimitedDelay(self, duration):
    """Custom delay function for C{sched.scheduler}.

    """
    if self._max_delay is None:
      timeout = duration
    else:
      timeout = min(duration, self._max_delay.Remaining())

    return AsyncoreDelayFunction(timeout)


class GanetiBaseAsyncoreDispatcher(asyncore.dispatcher):
  """Base Ganeti Asyncore Dispacher

  """
  # this method is overriding an asyncore.dispatcher method
  def handle_error(self):
    """Log an error in handling any request, and proceed.

    """
    logging.exception("Error while handling asyncore request")

  # this method is overriding an asyncore.dispatcher method
  def writable(self):
    """Most of the time we don't want to check for writability.

    """
    return False


class AsyncStreamServer(GanetiBaseAsyncoreDispatcher):
  """A stream server to use with asyncore.

  Each request is accepted, and then dispatched to a separate asyncore
  dispatcher to handle.

  """

  _REQUEST_QUEUE_SIZE = 5

  def __init__(self, family, address):
    """Constructor for AsyncStreamServer

    @type family: integer
    @param family: socket family (one of socket.AF_*)
    @type address: address family dependent
    @param address: address to bind the socket to

    """
    GanetiBaseAsyncoreDispatcher.__init__(self)
    self.family = family
    self.create_socket(self.family, socket.SOCK_STREAM)
    self.set_reuse_addr()
    self.bind(address)
    self.listen(self._REQUEST_QUEUE_SIZE)

  # this method is overriding an asyncore.dispatcher method
  def handle_accept(self):
    """Accept a new client connection.

    Creates a new instance of the handler class, which will use asyncore to
    serve the client.

    """
    accept_result = utils.IgnoreSignals(self.accept)
    if accept_result is not None:
      connected_socket, client_address = accept_result
      if self.family == socket.AF_UNIX:
        # override the client address, as for unix sockets nothing meaningful
        # is passed in from accept anyway
        client_address = netutils.GetSocketCredentials(connected_socket)
      logging.info("Accepted connection from %s",
                   netutils.FormatAddress(client_address, family=self.family))
      self.handle_connection(connected_socket, client_address)

  def handle_connection(self, connected_socket, client_address):
    """Handle an already accepted connection.

    """
    raise NotImplementedError


class AsyncTerminatedMessageStream(asynchat.async_chat):
  """A terminator separated message stream asyncore module.

  Handles a stream connection receiving messages terminated by a defined
  separator. For each complete message handle_message is called.

  """
  def __init__(self, connected_socket, peer_address, terminator, family,
               unhandled_limit):
    """AsyncTerminatedMessageStream constructor.

    @type connected_socket: socket.socket
    @param connected_socket: connected stream socket to receive messages from
    @param peer_address: family-specific peer address
    @type terminator: string
    @param terminator: terminator separating messages in the stream
    @type family: integer
    @param family: socket family
    @type unhandled_limit: integer or None
    @param unhandled_limit: maximum unanswered messages

    """
    # python 2.4/2.5 uses conn=... while 2.6 has sock=... we have to cheat by
    # using a positional argument rather than a keyword one.
    asynchat.async_chat.__init__(self, connected_socket)
    self.connected_socket = connected_socket
    # on python 2.4 there is no "family" attribute for the socket class
    # FIXME: when we move to python 2.5 or above remove the family parameter
    #self.family = self.connected_socket.family
    self.family = family
    self.peer_address = peer_address
    self.terminator = terminator
    self.unhandled_limit = unhandled_limit
    self.set_terminator(terminator)
    self.ibuffer = []
    self.receive_count = 0
    self.send_count = 0
    self.oqueue = collections.deque()
    self.iqueue = collections.deque()

  # this method is overriding an asynchat.async_chat method
  def collect_incoming_data(self, data):
    self.ibuffer.append(data)

  def _can_handle_message(self):
    return (self.unhandled_limit is None or
            (self.receive_count < self.send_count + self.unhandled_limit) and
             not self.iqueue)

  # this method is overriding an asynchat.async_chat method
  def found_terminator(self):
    message = "".join(self.ibuffer)
    self.ibuffer = []
    message_id = self.receive_count
    # We need to increase the receive_count after checking if the message can
    # be handled, but before calling handle_message
    can_handle = self._can_handle_message()
    self.receive_count += 1
    if can_handle:
      self.handle_message(message, message_id)
    else:
      self.iqueue.append((message, message_id))

  def handle_message(self, message, message_id):
    """Handle a terminated message.

    @type message: string
    @param message: message to handle
    @type message_id: integer
    @param message_id: stream's message sequence number

    """
    pass
    # TODO: move this method to raise NotImplementedError
    # raise NotImplementedError

  def send_message(self, message):
    """Send a message to the remote peer. This function is thread-safe.

    @type message: string
    @param message: message to send, without the terminator

    @warning: If calling this function from a thread different than the one
    performing the main asyncore loop, remember that you have to wake that one
    up.

    """
    # If we just append the message we received to the output queue, this
    # function can be safely called by multiple threads at the same time, and
    # we don't need locking, since deques are thread safe. handle_write in the
    # asyncore thread will handle the next input message if there are any
    # enqueued.
    self.oqueue.append(message)

  # this method is overriding an asyncore.dispatcher method
  def readable(self):
    # read from the socket if we can handle the next requests
    return self._can_handle_message() and asynchat.async_chat.readable(self)

  # this method is overriding an asyncore.dispatcher method
  def writable(self):
    # the output queue may become full just after we called writable. This only
    # works if we know we'll have something else waking us up from the select,
    # in such case, anyway.
    return asynchat.async_chat.writable(self) or self.oqueue

  # this method is overriding an asyncore.dispatcher method
  def handle_write(self):
    if self.oqueue:
      # if we have data in the output queue, then send_message was called.
      # this means we can process one more message from the input queue, if
      # there are any.
      data = self.oqueue.popleft()
      self.push(data + self.terminator)
      self.send_count += 1
      if self.iqueue:
        self.handle_message(*self.iqueue.popleft())
    self.initiate_send()

  def close_log(self):
    logging.info("Closing connection from %s",
                 netutils.FormatAddress(self.peer_address, family=self.family))
    self.close()

  # this method is overriding an asyncore.dispatcher method
  def handle_expt(self):
    self.close_log()

  # this method is overriding an asyncore.dispatcher method
  def handle_error(self):
    """Log an error in handling any request, and proceed.

    """
    logging.exception("Error while handling asyncore request")
    self.close_log()


class AsyncUDPSocket(GanetiBaseAsyncoreDispatcher):
  """An improved asyncore udp socket.

  """
  def __init__(self, family):
    """Constructor for AsyncUDPSocket

    """
    GanetiBaseAsyncoreDispatcher.__init__(self)
    self._out_queue = []
    self._family = family
    self.create_socket(family, socket.SOCK_DGRAM)

  # this method is overriding an asyncore.dispatcher method
  def handle_connect(self):
    # Python thinks that the first udp message from a source qualifies as a
    # "connect" and further ones are part of the same connection. We beg to
    # differ and treat all messages equally.
    pass

  # this method is overriding an asyncore.dispatcher method
  def handle_read(self):
    recv_result = utils.IgnoreSignals(self.recvfrom,
                                      constants.MAX_UDP_DATA_SIZE)
    if recv_result is not None:
      payload, address = recv_result
      if self._family == socket.AF_INET6:
        # we ignore 'flow info' and 'scope id' as we don't need them
        ip, port, _, _ = address
      else:
        ip, port = address

      self.handle_datagram(payload, ip, port)

  def handle_datagram(self, payload, ip, port):
    """Handle an already read udp datagram

    """
    raise NotImplementedError

  # this method is overriding an asyncore.dispatcher method
  def writable(self):
    # We should check whether we can write to the socket only if we have
    # something scheduled to be written
    return bool(self._out_queue)

  # this method is overriding an asyncore.dispatcher method
  def handle_write(self):
    if not self._out_queue:
      logging.error("handle_write called with empty output queue")
      return
    (ip, port, payload) = self._out_queue[0]
    utils.IgnoreSignals(self.sendto, payload, 0, (ip, port))
    self._out_queue.pop(0)

  def enqueue_send(self, ip, port, payload):
    """Enqueue a datagram to be sent when possible

    """
    if len(payload) > constants.MAX_UDP_DATA_SIZE:
      raise errors.UdpDataSizeError("Packet too big: %s > %s" % (len(payload),
                                    constants.MAX_UDP_DATA_SIZE))
    self._out_queue.append((ip, port, payload))

  def process_next_packet(self, timeout=0):
    """Process the next datagram, waiting for it if necessary.

    @type timeout: float
    @param timeout: how long to wait for data
    @rtype: boolean
    @return: True if some data has been handled, False otherwise

    """
    result = utils.WaitForFdCondition(self, select.POLLIN, timeout)
    if result is not None and result & select.POLLIN:
      self.handle_read()
      return True
    else:
      return False


class AsyncAwaker(GanetiBaseAsyncoreDispatcher):
  """A way to notify the asyncore loop that something is going on.

  If an asyncore daemon is multithreaded when a thread tries to push some data
  to a socket, the main loop handling asynchronous requests might be sleeping
  waiting on a select(). To avoid this it can create an instance of the
  AsyncAwaker, which other threads can use to wake it up.

  """
  def __init__(self, signal_fn=None):
    """Constructor for AsyncAwaker

    @type signal_fn: function
    @param signal_fn: function to call when awaken

    """
    GanetiBaseAsyncoreDispatcher.__init__(self)
    assert signal_fn is None or callable(signal_fn)
    (self.in_socket, self.out_socket) = socket.socketpair(socket.AF_UNIX,
                                                          socket.SOCK_STREAM)
    self.in_socket.setblocking(0)
    self.in_socket.shutdown(socket.SHUT_WR)
    self.out_socket.shutdown(socket.SHUT_RD)
    self.set_socket(self.in_socket)
    self.need_signal = True
    self.signal_fn = signal_fn
    self.connected = True

  # this method is overriding an asyncore.dispatcher method
  def handle_read(self):
    utils.IgnoreSignals(self.recv, 4096)
    if self.signal_fn:
      self.signal_fn()
    self.need_signal = True

  # this method is overriding an asyncore.dispatcher method
  def close(self):
    asyncore.dispatcher.close(self)
    self.out_socket.close()

  def signal(self):
    """Signal the asyncore main loop.

    Any data we send here will be ignored, but it will cause the select() call
    to return.

    """
    # Yes, there is a race condition here. No, we don't care, at worst we're
    # sending more than one wakeup token, which doesn't harm at all.
    if self.need_signal:
      self.need_signal = False
      self.out_socket.send(chr(0))


class _ShutdownCheck:
  """Logic for L{Mainloop} shutdown.

  """
  def __init__(self, fn):
    """Initializes this class.

    @type fn: callable
    @param fn: Function returning C{None} if mainloop can be stopped or a
      duration in seconds after which the function should be called again
    @see: L{Mainloop.Run}

    """
    assert callable(fn)

    self._fn = fn
    self._defer = None

  def CanShutdown(self):
    """Checks whether mainloop can be stopped.

    @rtype: bool

    """
    if self._defer and self._defer.Remaining() > 0:
      # A deferred check has already been scheduled
      return False

    # Ask mainloop driver whether we can stop or should check again
    timeout = self._fn()

    if timeout is None:
      # Yes, can stop mainloop
      return True

    # Schedule another check in the future
    self._defer = utils.RunningTimeout(timeout, True)

    return False


class Mainloop(object):
  """Generic mainloop for daemons

  @ivar scheduler: A sched.scheduler object, which can be used to register
    timed events

  """
  _SHUTDOWN_TIMEOUT_PRIORITY = -(sys.maxint - 1)

  def __init__(self):
    """Constructs a new Mainloop instance.

    """
    self._signal_wait = []
    self.scheduler = AsyncoreScheduler(time.time)

    # Resolve uid/gids used
    runtime.GetEnts()

  @utils.SignalHandled([signal.SIGCHLD])
  @utils.SignalHandled([signal.SIGTERM])
  @utils.SignalHandled([signal.SIGINT])
  def Run(self, shutdown_wait_fn=None, signal_handlers=None):
    """Runs the mainloop.

    @type shutdown_wait_fn: callable
    @param shutdown_wait_fn: Function to check whether loop can be terminated;
      B{important}: function must be idempotent and must return either None
      for shutting down or a timeout for another call
    @type signal_handlers: dict
    @param signal_handlers: signal->L{utils.SignalHandler} passed by decorator

    """
    assert isinstance(signal_handlers, dict) and \
           len(signal_handlers) > 0, \
           "Broken SignalHandled decorator"

    # Counter for received signals
    shutdown_signals = 0

    # Logic to wait for shutdown
    shutdown_waiter = None

    # Start actual main loop
    while True:
      if shutdown_signals == 1 and shutdown_wait_fn is not None:
        if shutdown_waiter is None:
          shutdown_waiter = _ShutdownCheck(shutdown_wait_fn)

        # Let mainloop driver decide if we can already abort
        if shutdown_waiter.CanShutdown():
          break

        # Re-evaluate in a second
        timeout = 1.0

      elif shutdown_signals >= 1:
        # Abort loop if more than one signal has been sent or no callback has
        # been given
        break

      else:
        # Wait forever on I/O events
        timeout = None

      if self.scheduler.empty():
        asyncore.loop(count=1, timeout=timeout, use_poll=True)
      else:
        try:
          self.scheduler.run(max_delay=timeout)
        except SchedulerBreakout:
          pass

      # Check whether a signal was raised
      for (sig, handler) in signal_handlers.items():
        if handler.called:
          self._CallSignalWaiters(sig)
          if sig in (signal.SIGTERM, signal.SIGINT):
            logging.info("Received signal %s asking for shutdown", sig)
            shutdown_signals += 1
          handler.Clear()

  def _CallSignalWaiters(self, signum):
    """Calls all signal waiters for a certain signal.

    @type signum: int
    @param signum: Signal number

    """
    for owner in self._signal_wait:
      owner.OnSignal(signum)

  def RegisterSignal(self, owner):
    """Registers a receiver for signal notifications

    The receiver must support a "OnSignal(self, signum)" function.

    @type owner: instance
    @param owner: Receiver

    """
    self._signal_wait.append(owner)


def _VerifyDaemonUser(daemon_name):
  """Verifies the process uid matches the configured uid.

  This method verifies that a daemon is started as the user it is
  intended to be run

  @param daemon_name: The name of daemon to be started
  @return: A tuple with the first item indicating success or not,
           the second item current uid and third with expected uid

  """
  getents = runtime.GetEnts()
  running_uid = os.getuid()
  daemon_uids = {
    constants.MASTERD: getents.masterd_uid,
    constants.RAPI: getents.rapi_uid,
    constants.NODED: getents.noded_uid,
    constants.CONFD: getents.confd_uid,
    }
  assert daemon_name in daemon_uids, "Invalid daemon %s" % daemon_name

  return (daemon_uids[daemon_name] == running_uid, running_uid,
          daemon_uids[daemon_name])


def _BeautifyError(err):
  """Try to format an error better.

  Since we're dealing with daemon startup errors, in many cases this
  will be due to socket error and such, so we try to format these cases better.

  @param err: an exception object
  @rtype: string
  @return: the formatted error description

  """
  try:
    if isinstance(err, socket.error):
      return "Socket-related error: %s (errno=%s)" % (err.args[1], err.args[0])
    elif isinstance(err, EnvironmentError):
      if err.filename is None:
        return "%s (errno=%s)" % (err.strerror, err.errno)
      else:
        return "%s (file %s) (errno=%s)" % (err.strerror, err.filename,
                                            err.errno)
    else:
      return str(err)
  except Exception: # pylint: disable=W0703
    logging.exception("Error while handling existing error %s", err)
    return "%s" % str(err)


def _HandleSigHup(reopen_fn, signum, frame): # pylint: disable=W0613
  """Handler for SIGHUP.

  @param reopen_fn: List of callback functions for reopening log files

  """
  logging.info("Reopening log files after receiving SIGHUP")

  for fn in reopen_fn:
    if fn:
      fn()


def GenericMain(daemon_name, optionparser,
                check_fn, prepare_fn, exec_fn,
                multithreaded=False, console_logging=False,
                default_ssl_cert=None, default_ssl_key=None,
                warn_breach=False):
  """Shared main function for daemons.

  @type daemon_name: string
  @param daemon_name: daemon name
  @type optionparser: optparse.OptionParser
  @param optionparser: initialized optionparser with daemon-specific options
                       (common -f -d options will be handled by this module)
  @type check_fn: function which accepts (options, args)
  @param check_fn: function that checks start conditions and exits if they're
                   not met
  @type prepare_fn: function which accepts (options, args)
  @param prepare_fn: function that is run before forking, or None;
      it's result will be passed as the third parameter to exec_fn, or
      if None was passed in, we will just pass None to exec_fn
  @type exec_fn: function which accepts (options, args, prepare_results)
  @param exec_fn: function that's executed with the daemon's pid file held, and
                  runs the daemon itself.
  @type multithreaded: bool
  @param multithreaded: Whether the daemon uses threads
  @type console_logging: boolean
  @param console_logging: if True, the daemon will fall back to the system
                          console if logging fails
  @type default_ssl_cert: string
  @param default_ssl_cert: Default SSL certificate path
  @type default_ssl_key: string
  @param default_ssl_key: Default SSL key path
  @type warn_breach: bool
  @param warn_breach: issue a warning at daemon launch time, before
      daemonizing, about the possibility of breaking parameter privacy
      invariants through the otherwise helpful debug logging.

  """
  optionparser.add_option("-f", "--foreground", dest="fork",
                          help="Don't detach from the current terminal",
                          default=True, action="store_false")
  optionparser.add_option("-d", "--debug", dest="debug",
                          help="Enable some debug messages",
                          default=False, action="store_true")
  optionparser.add_option("--syslog", dest="syslog",
                          help="Enable logging to syslog (except debug"
                          " messages); one of 'no', 'yes' or 'only' [%s]" %
                          constants.SYSLOG_USAGE,
                          default=constants.SYSLOG_USAGE,
                          choices=["no", "yes", "only"])

  family = ssconf.SimpleStore().GetPrimaryIPFamily()
  # family will default to AF_INET if there is no ssconf file (e.g. when
  # upgrading a cluster from 2.2 -> 2.3. This is intended, as Ganeti clusters
  # <= 2.2 can not be AF_INET6
  if daemon_name in constants.DAEMONS_PORTS:
    default_bind_address = constants.IP4_ADDRESS_ANY
    if family == netutils.IP6Address.family:
      default_bind_address = constants.IP6_ADDRESS_ANY

    default_port = netutils.GetDaemonPort(daemon_name)

    # For networked daemons we allow choosing the port and bind address
    optionparser.add_option("-p", "--port", dest="port",
                            help="Network port (default: %s)" % default_port,
                            default=default_port, type="int")
    optionparser.add_option("-b", "--bind", dest="bind_address",
                            help=("Bind address (default: '%s')" %
                                  default_bind_address),
                            default=default_bind_address, metavar="ADDRESS")
    optionparser.add_option("-i", "--interface", dest="bind_interface",
                            help=("Bind interface"), metavar="INTERFACE")

  if default_ssl_key is not None and default_ssl_cert is not None:
    optionparser.add_option("--no-ssl", dest="ssl",
                            help="Do not secure HTTP protocol with SSL",
                            default=True, action="store_false")
    optionparser.add_option("-K", "--ssl-key", dest="ssl_key",
                            help=("SSL key path (default: %s)" %
                                  default_ssl_key),
                            default=default_ssl_key, type="string",
                            metavar="SSL_KEY_PATH")
    optionparser.add_option("-C", "--ssl-cert", dest="ssl_cert",
                            help=("SSL certificate path (default: %s)" %
                                  default_ssl_cert),
                            default=default_ssl_cert, type="string",
                            metavar="SSL_CERT_PATH")

  # Disable the use of fork(2) if the daemon uses threads
  if multithreaded:
    utils.DisableFork()

  options, args = optionparser.parse_args()

  if getattr(options, "bind_interface", None) is not None:
    if options.bind_address != default_bind_address:
      msg = ("Can't specify both, bind address (%s) and bind interface (%s)" %
             (options.bind_address, options.bind_interface))
      print >> sys.stderr, msg
      sys.exit(constants.EXIT_FAILURE)
    interface_ip_addresses = \
      netutils.GetInterfaceIpAddresses(options.bind_interface)
    if family == netutils.IP6Address.family:
      if_addresses = interface_ip_addresses[constants.IP6_VERSION]
    else:
      if_addresses = interface_ip_addresses[constants.IP4_VERSION]
    if len(if_addresses) < 1:
      msg = "Failed to find IP for interface %s" % options.bind_interace
      print >> sys.stderr, msg
      sys.exit(constants.EXIT_FAILURE)
    options.bind_address = if_addresses[0]

  if getattr(options, "ssl", False):
    ssl_paths = {
      "certificate": options.ssl_cert,
      "key": options.ssl_key,
      }

    for name, path in ssl_paths.iteritems():
      if not os.path.isfile(path):
        print >> sys.stderr, "SSL %s file '%s' was not found" % (name, path)
        sys.exit(constants.EXIT_FAILURE)

    # TODO: By initiating http.HttpSslParams here we would only read the files
    # once and have a proper validation (isfile returns False on directories)
    # at the same time.

  result, running_uid, expected_uid = _VerifyDaemonUser(daemon_name)
  if not result:
    msg = ("%s started using wrong user ID (%d), expected %d" %
           (daemon_name, running_uid, expected_uid))
    print >> sys.stderr, msg
    sys.exit(constants.EXIT_FAILURE)

  if check_fn is not None:
    check_fn(options, args)

  log_filename = constants.DAEMONS_LOGFILES[daemon_name]

  # node-daemon logging in lib/http/server.py, _HandleServerRequestInner
  if options.debug and warn_breach:
    sys.stderr.write(constants.DEBUG_MODE_CONFIDENTIALITY_WARNING % daemon_name)

  if options.fork:
    utils.CloseFDs()
    (wpipe, stdio_reopen_fn) = utils.Daemonize(logfile=log_filename)
  else:
    (wpipe, stdio_reopen_fn) = (None, None)

  log_reopen_fn = \
    utils.SetupLogging(log_filename, daemon_name,
                       debug=options.debug,
                       stderr_logging=not options.fork,
                       multithreaded=multithreaded,
                       syslog=options.syslog,
                       console_logging=console_logging)

  # Reopen log file(s) on SIGHUP
  signal.signal(signal.SIGHUP,
                compat.partial(_HandleSigHup, [log_reopen_fn, stdio_reopen_fn]))

  try:
    utils.WritePidFile(utils.DaemonPidFileName(daemon_name))
  except errors.PidFileLockError, err:
    print >> sys.stderr, "Error while locking PID file:\n%s" % err
    sys.exit(constants.EXIT_FAILURE)

  try:
    try:
      logging.info("%s daemon startup", daemon_name)
      if callable(prepare_fn):
        prep_results = prepare_fn(options, args)
      else:
        prep_results = None
    except Exception, err:
      utils.WriteErrorToFD(wpipe, _BeautifyError(err))
      raise

    if wpipe is not None:
      # we're done with the preparation phase, we close the pipe to
      # let the parent know it's safe to exit
      os.close(wpipe)

    exec_fn(options, args, prep_results)
  finally:
    utils.RemoveFile(utils.DaemonPidFileName(daemon_name))
