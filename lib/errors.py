#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""Ganeti exception handling.

"""

from ganeti import constants


ECODE_RESOLVER = constants.ERRORS_ECODE_RESOLVER
ECODE_NORES = constants.ERRORS_ECODE_NORES
ECODE_TEMP_NORES = constants.ERRORS_ECODE_TEMP_NORES
ECODE_INVAL = constants.ERRORS_ECODE_INVAL
ECODE_STATE = constants.ERRORS_ECODE_STATE
ECODE_NOENT = constants.ERRORS_ECODE_NOENT
ECODE_EXISTS = constants.ERRORS_ECODE_EXISTS
ECODE_NOTUNIQUE = constants.ERRORS_ECODE_NOTUNIQUE
ECODE_FAULT = constants.ERRORS_ECODE_FAULT
ECODE_ENVIRON = constants.ERRORS_ECODE_ENVIRON
ECODE_ALL = constants.ERRORS_ECODE_ALL


class GenericError(Exception):
  """Base exception for Ganeti.

  """


class LockError(GenericError):
  """Lock error exception.

  This signifies problems in the locking subsystem.

  """


class PidFileLockError(LockError):
  """PID file is already locked by another process.

  """


class HypervisorError(GenericError):
  """Hypervisor-related exception.

  This is raised in case we can't communicate with the hypervisor
  properly.

  """


class HotplugError(HypervisorError):
  """Hotplug-related exception.

  This is raised in case a hotplug action fails or is not supported.
  It is currently used only by KVM hypervisor.

  """


class ProgrammerError(GenericError):
  """Programming-related error.

  This is raised in cases we determine that the calling conventions
  have been violated, meaning we got some desynchronisation between
  parts of our code. It signifies a real programming bug.

  """


class BlockDeviceError(GenericError):
  """Block-device related exception.

  This is raised in case we can't setup the instance's block devices
  properly.

  """


class ConfigurationError(GenericError):
  """Configuration related exception.

  Things like having an instance with a primary node that doesn't
  exist in the config or such raise this exception.

  """


class ConfigVersionMismatch(ConfigurationError):
  """Version mismatch in the configuration file.

  The error has two arguments: the expected and the actual found
  version.

  """


class ConfigVerifyError(ConfigurationError):
  """Error reported by configuration verification

  The error has two arguments: the main error message and a list of errors
  found.

  """


class AddressPoolError(GenericError):
  """Errors related to IP address pools.

  """


class ReservationError(GenericError):
  """Errors reserving a resource.

  """


class RemoteError(GenericError):
  """Programming-related error on remote call.

  This is raised when an unhandled error occurs in a call to a
  remote node.  It usually signifies a real programming bug.

  """


class SignatureError(GenericError):
  """Error authenticating a remote message.

  This is raised when the hmac signature on a message doesn't verify correctly
  to the message itself. It can happen because of network unreliability or
  because of spurious traffic.

  """


class ParameterError(GenericError):
  """A passed parameter to a command is invalid.

  This is raised when the parameter passed to a request function is
  invalid. Correct code should have verified this before passing the
  request structure.

  The argument to this exception should be the parameter name.

  """


class ResultValidationError(GenericError):
  """The iallocation results fails validation.

  """


class OpPrereqError(GenericError):
  """Prerequisites for the OpCode are not fulfilled.

  This exception has two arguments: an error message, and one of the
  ECODE_* codes.

  """


class OpExecError(GenericError):
  """Error during OpCode execution.

  """


class OpResultError(GenericError):
  """Issue with OpCode result.

  """


class OpRetryNotSupportedError(GenericError):
  """This opcode does not support retries

  """


class DeviceCreationError(GenericError):
  """Error during the creation of a device.

  This exception should contain the list of the devices actually created
  up to now, in the form of pairs (node, device)

  """
  def __init__(self, message, created_devices):
    GenericError.__init__(self)
    self.message = message
    self.created_devices = created_devices

  def __str__(self):
    return self.message


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


class JobCanceled(GenericError):
  """Submitted job was canceled.

  The job that was submitted has transitioned to a canceling or canceled
  state.

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


class X509CertError(GenericError):
  """Invalid X509 certificate.

  This error has two arguments: the certificate filename and the error cause.

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
  treated. This exception should be instantiated with two values. The
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


class QueryFilterParseError(ParseError):
  """Error while parsing query filter.

  This exception must be instantiated with two values. The first one is a
  string with an error description, the second one is an instance of a subclass
  of C{pyparsing.ParseBaseException} (used to display the exact error
  location).

  """
  def GetDetails(self):
    """Returns a list of strings with details about the error.

    """
    try:
      (_, inner) = self.args
    except IndexError:
      return None

    return [str(inner.line),
            (" " * (inner.column - 1)) + "^",
            str(inner)]


class RapiTestResult(GenericError):
  """Exception containing results from RAPI test utilities.

  """


class FileStoragePathError(GenericError):
  """Error from file storage path validation.

  """


class SshUpdateError(GenericError):
  """Error from updating the SSH setup.

  """


class JobSubmittedException(Exception):
  """Job was submitted, client should exit.

  This exception has one argument, the ID of the job that was
  submitted. The handler should print this ID.

  This is not an error, just a structured way to exit from clients.

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
    raise errcls(*args)
