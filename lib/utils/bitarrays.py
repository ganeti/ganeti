#
#

# Copyright (C) 2014 Google Inc.
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

"""Utility functions for managing bitarrays.

"""


from bitarray import bitarray

from ganeti import errors

# Constant bitarray that reflects to a free slot
# Use it with bitarray.search()
_AVAILABLE_SLOT = bitarray("0")


def GetFreeSlot(slots, slot=None, reserve=False):
  """Helper method to get first available slot in a bitarray

  @type slots: bitarray
  @param slots: the bitarray to operate on
  @type slot: integer
  @param slot: if given we check whether the slot is free
  @type reserve: boolean
  @param reserve: whether to reserve the first available slot or not
  @return: the idx of the (first) available slot
  @raise errors.OpPrereqError: If all slots in a bitarray are occupied
    or the given slot is not free.

  """
  if slot is not None:
    assert slot < len(slots)
    if slots[slot]:
      raise errors.GenericError("Slot %d occupied" % slot)

  else:
    avail = slots.search(_AVAILABLE_SLOT, 1)
    if not avail:
      raise errors.GenericError("All slots occupied")

    slot = int(avail[0])

  if reserve:
    slots[slot] = True

  return slot
