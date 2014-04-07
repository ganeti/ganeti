#
#

# Copyright (C) 2014 Google Inc.
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


"""Qemu monitor control classes

"""


import os
import stat
import errno
import socket
import StringIO

from ganeti import errors
from ganeti import utils
from ganeti import serializer


class QmpCommandNotSupported(errors.HypervisorError):
  """QMP command not supported by the monitor.

  This is raised in case a QmpMonitor instance is asked to execute a command
  not supported by the instance.

  This is a KVM-specific exception, intended to assist in falling back to using
  the human monitor for operations QMP does not support.

  """
  pass


class QmpMessage(object):
  """QEMU Messaging Protocol (QMP) message.

  """
  def __init__(self, data):
    """Creates a new QMP message based on the passed data.

    """
    if not isinstance(data, dict):
      raise TypeError("QmpMessage must be initialized with a dict")

    self.data = data

  def __getitem__(self, field_name):
    """Get the value of the required field if present, or None.

    Overrides the [] operator to provide access to the message data,
    returning None if the required item is not in the message
    @return: the value of the field_name field, or None if field_name
             is not contained in the message

    """
    return self.data.get(field_name, None)

  def __setitem__(self, field_name, field_value):
    """Set the value of the required field_name to field_value.

    """
    self.data[field_name] = field_value

  def __len__(self):
    """Return the number of fields stored in this QmpMessage.

    """
    return len(self.data)

  def __delitem__(self, key):
    """Delete the specified element from the QmpMessage.

    """
    del(self.data[key])

  @staticmethod
  def BuildFromJsonString(json_string):
    """Build a QmpMessage from a JSON encoded string.

    @type json_string: str
    @param json_string: JSON string representing the message
    @rtype: L{QmpMessage}
    @return: a L{QmpMessage} built from json_string

    """
    # Parse the string
    data = serializer.LoadJson(json_string)
    return QmpMessage(data)

  def __str__(self):
    # The protocol expects the JSON object to be sent as a single line.
    return serializer.DumpJson(self.data)

  def __eq__(self, other):
    # When comparing two QmpMessages, we are interested in comparing
    # their internal representation of the message data
    return self.data == other.data


class MonitorSocket(object):
  _SOCKET_TIMEOUT = 5

  def __init__(self, monitor_filename):
    """Instantiates the MonitorSocket object.

    @type monitor_filename: string
    @param monitor_filename: the filename of the UNIX raw socket on which the
                             monitor (QMP or simple one) is listening

    """
    self.monitor_filename = monitor_filename
    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # We want to fail if the server doesn't send a complete message
    # in a reasonable amount of time
    self.sock.settimeout(self._SOCKET_TIMEOUT)
    self._connected = False

  def _check_socket(self):
    sock_stat = None
    try:
      sock_stat = os.stat(self.monitor_filename)
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        raise errors.HypervisorError("No monitor socket found")
      else:
        raise errors.HypervisorError("Error checking monitor socket: %s",
                                     utils.ErrnoOrStr(err))
    if not stat.S_ISSOCK(sock_stat.st_mode):
      raise errors.HypervisorError("Monitor socket is not a socket")

  def _check_connection(self):
    """Make sure that the connection is established.

    """
    if not self._connected:
      raise errors.ProgrammerError("To use a MonitorSocket you need to first"
                                   " invoke connect() on it")

  def connect(self):
    """Connects to the monitor.

    Connects to the UNIX socket

    @raise errors.HypervisorError: when there are communication errors

    """
    if self._connected:
      raise errors.ProgrammerError("Cannot connect twice")

    self._check_socket()

    # Check file existance/stuff
    try:
      self.sock.connect(self.monitor_filename)
    except EnvironmentError:
      raise errors.HypervisorError("Can't connect to qmp socket")
    self._connected = True

  def close(self):
    """Closes the socket

    It cannot be used after this call.

    """
    self.sock.close()


class QmpConnection(MonitorSocket):
  """Connection to the QEMU Monitor using the QEMU Monitor Protocol (QMP).

  """
  _FIRST_MESSAGE_KEY = "QMP"
  _EVENT_KEY = "event"
  _ERROR_KEY = "error"
  _RETURN_KEY = RETURN_KEY = "return"
  _ACTUAL_KEY = ACTUAL_KEY = "actual"
  _ERROR_CLASS_KEY = "class"
  _ERROR_DESC_KEY = "desc"
  _EXECUTE_KEY = "execute"
  _ARGUMENTS_KEY = "arguments"
  _VERSION_KEY = "version"
  _PACKAGE_KEY = "package"
  _QEMU_KEY = "qemu"
  _CAPABILITIES_COMMAND = "qmp_capabilities"
  _QUERY_COMMANDS = "query-commands"
  _MESSAGE_END_TOKEN = "\r\n"

  def __init__(self, monitor_filename):
    super(QmpConnection, self).__init__(monitor_filename)
    self._buf = ""
    self.supported_commands = None

  def connect(self):
    """Connects to the QMP monitor.

    Connects to the UNIX socket and makes sure that we can actually send and
    receive data to the kvm instance via QMP.

    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    super(QmpConnection, self).connect()
    # Check if we receive a correct greeting message from the server
    # (As per the QEMU Protocol Specification 0.1 - section 2.2)
    greeting = self._Recv()
    if not greeting[self._FIRST_MESSAGE_KEY]:
      self._connected = False
      raise errors.HypervisorError("kvm: QMP communication error (wrong"
                                   " server greeting")

    # Extract the version info from the greeting and make it available to users
    # of the monitor.
    version_info = greeting[self._FIRST_MESSAGE_KEY][self._VERSION_KEY]

    self.version = (version_info[self._QEMU_KEY]["major"],
                    version_info[self._QEMU_KEY]["minor"],
                    version_info[self._QEMU_KEY]["micro"])
    self.package = version_info[self._PACKAGE_KEY].strip()

    # This is needed because QMP can return more than one greetings
    # see https://groups.google.com/d/msg/ganeti-devel/gZYcvHKDooU/SnukC8dgS5AJ
    self._buf = ""

    # Let's put the monitor in command mode using the qmp_capabilities
    # command, or else no command will be executable.
    # (As per the QEMU Protocol Specification 0.1 - section 4)
    self.Execute(self._CAPABILITIES_COMMAND)
    self.supported_commands = self._GetSupportedCommands()

  def _ParseMessage(self, buf):
    """Extract and parse a QMP message from the given buffer.

    Seeks for a QMP message in the given buf. If found, it parses it and
    returns it together with the rest of the characters in the buf.
    If no message is found, returns None and the whole buffer.

    @raise errors.ProgrammerError: when there are data serialization errors

    """
    message = None
    # Check if we got the message end token (CRLF, as per the QEMU Protocol
    # Specification 0.1 - Section 2.1.1)
    pos = buf.find(self._MESSAGE_END_TOKEN)
    if pos >= 0:
      try:
        message = QmpMessage.BuildFromJsonString(buf[:pos + 1])
      except Exception, err:
        raise errors.ProgrammerError("QMP data serialization error: %s" % err)
      buf = buf[pos + 1:]

    return (message, buf)

  def _Recv(self):
    """Receives a message from QMP and decodes the received JSON object.

    @rtype: QmpMessage
    @return: the received message
    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    self._check_connection()

    # Check if there is already a message in the buffer
    (message, self._buf) = self._ParseMessage(self._buf)
    if message:
      return message

    recv_buffer = StringIO.StringIO(self._buf)
    recv_buffer.seek(len(self._buf))
    try:
      while True:
        data = self.sock.recv(4096)
        if not data:
          break
        recv_buffer.write(data)

        (message, self._buf) = self._ParseMessage(recv_buffer.getvalue())
        if message:
          return message

    except socket.timeout, err:
      raise errors.HypervisorError("Timeout while receiving a QMP message: "
                                   "%s" % (err))
    except socket.error, err:
      raise errors.HypervisorError("Unable to receive data from KVM using the"
                                   " QMP protocol: %s" % err)

  def _Send(self, message):
    """Encodes and sends a message to KVM using QMP.

    @type message: QmpMessage
    @param message: message to send to KVM
    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    self._check_connection()
    try:
      message_str = str(message)
    except Exception, err:
      raise errors.ProgrammerError("QMP data deserialization error: %s" % err)

    try:
      self.sock.sendall(message_str)
    except socket.timeout, err:
      raise errors.HypervisorError("Timeout while sending a QMP message: "
                                   "%s (%s)" % (err.string, err.errno))
    except socket.error, err:
      raise errors.HypervisorError("Unable to send data from KVM using the"
                                   " QMP protocol: %s" % err)

  def _GetSupportedCommands(self):
    """Update the list of supported commands.

    """
    result = self.Execute(self._QUERY_COMMANDS)
    return frozenset(com["name"] for com in result[self._RETURN_KEY])

  def Execute(self, command, arguments=None):
    """Executes a QMP command and returns the response of the server.

    @type command: str
    @param command: the command to execute
    @type arguments: dict
    @param arguments: dictionary of arguments to be passed to the command
    @rtype: dict
    @return: dictionary representing the received JSON object
    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    self._check_connection()

    # During the first calls of Execute, the list of supported commands has not
    # yet been populated, so we can't use it.
    if (self.supported_commands is not None and
        command not in self.supported_commands):
      raise QmpCommandNotSupported("Instance does not support the '%s'"
                                    " QMP command." % command)

    message = QmpMessage({self._EXECUTE_KEY: command})
    if arguments:
      message[self._ARGUMENTS_KEY] = arguments
    self._Send(message)

    # Events can occur between the sending of the command and the reception
    # of the response, so we need to filter out messages with the event key.
    while True:
      response = self._Recv()
      err = response[self._ERROR_KEY]
      if err:
        raise errors.HypervisorError("kvm: error executing the %s"
                                     " command: %s (%s):" %
                                     (command,
                                      err[self._ERROR_DESC_KEY],
                                      err[self._ERROR_CLASS_KEY]))

      elif not response[self._EVENT_KEY]:
        return response
