#
#

# Copyright (C) 2012 Google Inc.
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


"""Remote API test utilities.

"""

import logging

from ganeti import errors
from ganeti import opcodes


class VerificationError(Exception):
  """Dedicated error class for test utilities.

  This class is used to hide all of Ganeti's internal exception, so that
  external users of these utilities don't have to integrate Ganeti's exception
  hierarchy.

  """


def _GetOpById(op_id):
  """Tries to get an opcode class based on its C{OP_ID}.

  """
  try:
    return opcodes.OP_MAPPING[op_id]
  except KeyError:
    raise VerificationError("Unknown opcode ID '%s'" % op_id)


def _HideInternalErrors(fn):
  """Hides Ganeti-internal exceptions, see L{VerificationError}.

  """
  def wrapper(*args, **kwargs):
    try:
      return fn(*args, **kwargs)
    except errors.GenericError, err:
      raise VerificationError("Unhandled Ganeti error: %s" % err)

  return wrapper


@_HideInternalErrors
def VerifyOpInput(op_id, data):
  """Verifies opcode parameters according to their definition.

  @type op_id: string
  @param op_id: Opcode ID (C{OP_ID} attribute), e.g. C{OP_CLUSTER_VERIFY}
  @type data: dict
  @param data: Opcode parameter values
  @raise VerificationError: Parameter verification failed

  """
  op_cls = _GetOpById(op_id)

  try:
    op = op_cls(**data) # pylint: disable=W0142
  except TypeError, err:
    raise VerificationError("Unable to create opcode instance: %s" % err)

  try:
    op.Validate(False)
  except errors.OpPrereqError, err:
    raise VerificationError("Parameter validation for opcode '%s' failed: %s" %
                            (op_id, err))


@_HideInternalErrors
def VerifyOpResult(op_id, result):
  """Verifies opcode results used in tests (e.g. in a mock).

  @type op_id: string
  @param op_id: Opcode ID (C{OP_ID} attribute), e.g. C{OP_CLUSTER_VERIFY}
  @param result: Mocked opcode result
  @raise VerificationError: Return value verification failed

  """
  resultcheck_fn = _GetOpById(op_id).OP_RESULT

  if not resultcheck_fn:
    logging.warning("Opcode '%s' has no result type definition", op_id)
  elif not resultcheck_fn(result):
    raise VerificationError("Given result does not match result description"
                            " for opcode '%s': %s" % (op_id, resultcheck_fn))
