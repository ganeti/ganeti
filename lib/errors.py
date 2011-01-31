#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010 Google Inc.
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


"""Ganeti exception handling"""


# OpPrereqError failure types

# resolver errors
ECODE_RESOLVER = "resolver_error"
# not enough resources (iallocator failure, disk space, memory, etc.)
ECODE_NORES = "insufficient_resources"
# wrong arguments (at syntax level)
ECODE_INVAL = "wrong_input"
# wrong entity state
ECODE_STATE = "wrong_state"
# entity not found
ECODE_NOENT = "unknown_entity"
# entity already exists
ECODE_EXISTS = "already_exists"
# resource not unique (e.g. MAC or IP duplication)
ECODE_NOTUNIQUE = "resource_not_unique"
# internal cluster error
ECODE_FAULT = "internal_error"
# environment error (e.g. node disk error)
ECODE_ENVIRON = "environment_error"


class GenericError(Exception):
  """Base exception for Ganeti.

  """
  pass


class LVMError(GenericError):
  """LVM-related exception.

  This exception codifies problems with LVM setup.

  """
  pass


class LockError(GenericError):
  """Lock error exception.

  This signifies problems in the locking subsystem.

  """
  pass


class HypervisorError(GenericError):
  """Hypervisor-related exception.

  This is raised in case we can't communicate with the hypervisor
  properly.

  """
  pass


class ProgrammerError(GenericError):
  """Programming-related error.

  This is raised in cases we determine that the calling conventions
  have been violated, meaning we got some desynchronisation between
  parts of our code. It signifies a real programming bug.

  """
  pass


class BlockDeviceError(GenericError):
  """Block-device related exception.

  This is raised in case we can't setup the instance's block devices
  properly.

  """
  pass


class ConfigurationError(GenericError):
  """Configuration related exception.

  Things like having an instance with a primary node that doesn't
  exist in the config or such raise this exception.

  """
  pass


class ConfigVersionMismatch(ConfigurationError):
  """Version mismatch in the configuration file.

  The error has two arguments: the expected and the actual found
  version.

  """
  pass


class ReservationError(GenericError):
  """Errors reserving a resource.

  """


class RemoteError(GenericError):
  """Programming-related error on remote call.

  This is raised when an unhandled error occurs in a call to a
  remote node.  It usually signifies a real programming bug.

  """
  pass


class SignatureError(GenericError):
  """Error authenticating a remote message.

  This is raised when the hmac signature on a message doesn't verify correctly
  to the message itself. It can happen because of network unreliability or
  because of spurious traffic.

  """
  pass


class ParameterError(GenericError):
  """A passed parameter to a command is invalid.

  This is raised when the parameter passed to a request function is
  invalid. Correct code should have verified this before passing the
  request structure.

  The argument to this exception should be the parameter name.

  """
  pass


class OpPrereqError(GenericError):
  """Prerequisites for the OpCode are not fulfilled.

  This exception will have either one or two arguments. For the
  two-argument construction, the second argument should be one of the
  ECODE_* codes.

  """


class OpExecError(GenericError):
  """Error during OpCode execution.

  """


class OpCodeUnknown(GenericError):
  """Unknown opcode submitted.

  This signifies a mismatch between the definitions on the client and
  server side.

  """


class JobLost(GenericError):
  """Submitted job lost.

  The job was submitted but it cannot be found in the current job
  list.

  """


class JobFileCorrupted(GenericError):
  """Job file could not be properly decoded/restored.

  """


class ResolverError(GenericError):
  """Host name cannot be resolved.

  This is not a normal situation for Ganeti, as we rely on having a
  working resolver.

  The non-resolvable hostname is available as the first element of the
  args tuple; the other two elements of the tuple are the first two
  args of the socket.gaierror exception (error code and description).

  """


class HooksFailure(GenericError):
  """A generic hook failure.

  This signifies usually a setup misconfiguration.

  """


class HooksAbort(HooksFailure):
  """A required hook has failed.

  This caused an abort of the operation in the initial phase. This
  exception always has an attribute args which is a list of tuples of:
    - node: the source node on which this hooks has failed
    - script: the name of the script which aborted the run

  """


class UnitParseError(GenericError):
  """Unable to parse size unit.

  """


class ParseError(GenericError):
  """Generic parse error.

  Raised when unable to parse user input.

  """


class TypeEnforcementError(GenericError):
  """Unable to enforce data type.

  """


class SshKeyError(GenericError):
  """Invalid SSH key.

  """


class TagError(GenericError):
  """Generic tag error.

  The argument to this exception will show the exact error.

  """


class CommandError(GenericError):
  """External command error.

  """


class StorageError(GenericError):
  """Storage-related exception.

  """


class InotifyError(GenericError):
  """Error raised when there is a failure setting up an inotify watcher.

  """


class QuitGanetiException(Exception):
  """Signal Ganeti that it must quit.

  This is not necessarily an error (and thus not a subclass of
  GenericError), but it's an exceptional circumstance and it is thus
  treated. This instance should be instantiated with two values. The
  first one will specify the return code to the caller, and the second
  one will be the returned result (either as an error or as a normal
  result). Usually only the leave cluster rpc call should return
  status True (as there it's expected we quit), every other call will
  return status False (as a critical error was encountered).

  Examples::

    # Return a result of "True" to the caller, but quit ganeti afterwards
    raise QuitGanetiException(True, None)
    # Send an error to the caller, and quit ganeti
    raise QuitGanetiException(False, "Fatal safety violation, shutting down")

  """


class JobQueueError(GenericError):
  """Job queue error.

  """


class JobQueueDrainError(JobQueueError):
  """Job queue is marked for drain error.

  This is raised when a job submission attempt is made but the queue
  is marked for drain.

  """


class JobQueueFull(JobQueueError):
  """Job queue full error.

  Raised when job queue size reached its hard limit.

  """


class ConfdRequestError(GenericError):
  """A request error in Ganeti confd.

  Events that should make confd abort the current request and proceed serving
  different ones.

  """


class ConfdMagicError(GenericError):
  """A magic fourcc error in Ganeti confd.

  Errors processing the fourcc in ganeti confd datagrams.

  """


class ConfdClientError(GenericError):
  """A magic fourcc error in Ganeti confd.

  Errors in the confd client library.

  """


class UdpDataSizeError(GenericError):
  """UDP payload too big.

  """


class NoCtypesError(GenericError):
  """python ctypes module is not found in the system.

  """


class IPAddressError(GenericError):
  """Generic IP address error.

  """


class LuxiError(GenericError):
  """LUXI error.

  """


# errors should be added above


def GetErrorClass(name):
  """Return the class of an exception.

  Given the class name, return the class itself.

  @type name: str
  @param name: the exception name
  @rtype: class
  @return: the actual class, or None if not found

  """
  item = globals().get(name, None)
  if item is not None:
    if not (isinstance(item, type(Exception)) and
            issubclass(item, GenericError)):
      item = None
  return item


def EncodeException(err):
  """Encodes an exception into a format that L{MaybeRaise} will recognise.

  The passed L{err} argument will be formatted as a tuple (exception
  name, arguments) that the MaybeRaise function will recognise.

  @type err: GenericError child
  @param err: usually a child of GenericError (but any exception
      will be accepted)
  @rtype: tuple
  @return: tuple of (exception name, exception arguments)

  """
  return (err.__class__.__name__, err.args)


def GetEncodedError(result):
  """If this looks like an encoded Ganeti exception, return it.

  This function tries to parse the passed argument and if it looks
  like an encoding done by EncodeException, it will return the class
  object and arguments.

  """
  tlt = (tuple, list)
  if (isinstance(result, tlt) and len(result) == 2 and
      isinstance(result[1], tlt)):
    # custom ganeti errors
    errcls = GetErrorClass(result[0])
    if errcls:
      return (errcls, tuple(result[1]))

  return None


def MaybeRaise(result):
  """If this looks like an encoded Ganeti exception, raise it.

  This function tries to parse the passed argument and if it looks
  like an encoding done by EncodeException, it will re-raise it.

  """
  error = GetEncodedError(result)
  if error:
    (errcls, args) = error
    raise errcls, args
