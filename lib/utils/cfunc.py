#
#

# Copyright (C) 2009, 2010, 2011 Google Inc.
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

"""Wrapper around mlockall(2).

"""

import os
import logging

from ganeti import errors

try:
  # pylint: disable=F0401
  import ctypes
except ImportError:
  ctypes = None


# Flags for mlockall(2) (from bits/mman.h)
_MCL_CURRENT = 1
_MCL_FUTURE = 2


class _FuncWrapper:
  def __init__(self, ct):
    """Initializes this class.

    """
    # Make use of a dlopen(3) feature whereby giving a NULL handle returns the
    # main program. Functions from all previously loaded libraries can then be
    # used.
    mainprog = ct.CDLL(None)

    # The ctypes module before Python 2.6 does not have built-in functionality
    # to access the global errno global (which, depending on the libc and build
    # options, is per-thread), where function error codes are stored. Use GNU
    # libc's way to retrieve errno(3) instead.
    try:
      errno_loc = getattr(mainprog, "__errno_location")
    except AttributeError, err:
      logging.debug("Unable to find errno location: %s", err)
      errno_fn = None
    else:
      errno_loc.restype = ct.POINTER(ct.c_int)
      errno_fn = lambda: errno_loc().contents.value

    self.errno_fn = errno_fn

    # Try to get mlockall(2)
    self.mlockall_fn = getattr(mainprog, "mlockall", None)


def Mlockall(_ctypes=ctypes):
  """Lock current process' virtual address space into RAM.

  This is equivalent to the C call C{mlockall(MCL_CURRENT | MCL_FUTURE)}. See
  mlockall(2) for more details. This function requires the C{ctypes} module.

  @raises errors.NoCtypesError: If the C{ctypes} module is not found

  """
  if _ctypes is None:
    raise errors.NoCtypesError()

  funcs = _FuncWrapper(_ctypes)

  if funcs.mlockall_fn is None:
    logging.debug("libc doesn't support mlockall(2)")
  else:
    if funcs.mlockall_fn(_MCL_CURRENT | _MCL_FUTURE) == 0:
      logging.debug("Memory lock set")
      return True

    logging.error("Cannot set memory lock: %s", os.strerror(funcs.errno_fn()))

  return False
