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


"""Ganeti exception handling"""


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


class RemoteError(GenericError):
  """Programming-related error on remote call.

  This is raised when an unhandled error occurs in a call to a
  remote node.  It usually signifies a real programming bug.

  """
  pass


class InvalidOS(GenericError):
  """Missing OS on node.

  This is raised when an OS exists on the master (or is otherwise
  requested to the code) but not on the target node.

  This exception has two arguments:
    - the name of the os
    - the reason why we consider this an invalid OS (text of error message)

  """


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

  """


class OpExecError(GenericError):
  """Error during OpCode execution.

  """


class OpRetryError(OpExecError):
  """Error during OpCode execution, action can be retried.

  """


class OpCodeUnknown(GenericError):
  """Unknown opcode submitted.

  This signifies a mismatch between the definitions on the client and
  server side.

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


class SshKeyError(GenericError):
  """Invalid SSH key.
  """


class TagError(GenericError):
  """Generic tag error.

  The argument to this exception will show the exact error.

  """
