#
#

# Copyright (C) 2009, 2010, 2011 Google Inc.
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


def Mlockall(_ctypes=ctypes):
  """Lock current process' virtual address space into RAM.

  This is equivalent to the C call C{mlockall(MCL_CURRENT | MCL_FUTURE)}. See
  mlockall(2) for more details. This function requires the C{ctypes} module.

  @raises errors.NoCtypesError: If the C{ctypes} module is not found

  """
  if _ctypes is None:
    raise errors.NoCtypesError()

  try:
    libc = _ctypes.cdll.LoadLibrary("libc.so.6")
  except EnvironmentError, err:
    logging.error("Failure trying to load libc: %s", err)
    libc = None
  if libc is None:
    logging.error("Cannot set memory lock, ctypes cannot load libc")
    return

  # The ctypes module before Python 2.6 does not have built-in functionality to
  # access the global errno global (which, depending on the libc and build
  # options, is per thread), where function error codes are stored. Use GNU
  # libc's way to retrieve errno(3) instead, which is to use the pointer named
  # "__errno_location" (see errno.h and bits/errno.h).
  # pylint: disable=W0212
  libc.__errno_location.restype = _ctypes.POINTER(_ctypes.c_int)

  if libc.mlockall(_MCL_CURRENT | _MCL_FUTURE):
    # pylint: disable=W0212
    logging.error("Cannot set memory lock: %s",
                  os.strerror(libc.__errno_location().contents.value))
    return

  logging.debug("Memory lock set")
