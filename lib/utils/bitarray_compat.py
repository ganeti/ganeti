#
#

# Copyright (C) 2025 the Ganeti project
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

"""
With bitarray-3 the signature of search() has changed:

  old: search(sub_bitarray, limit) -> list

  new: search(sub_bitarray, start=0, stop=<end>, /, right=False)
         -> iterator
"""
from __future__ import annotations
from typing import Union, List
from bitarray import bitarray as _BaseBitarray
from ganeti import errors

class CompatBitarray(_BaseBitarray):
  # constructor forwarding for immutable C-Extension types
  def __new__(cls, *args, **kwargs):
    return _BaseBitarray.__new__(cls, *args, **kwargs)

  def search(self, sub_bitarray: Union[bitarray, int], *args) -> List[int]:
    # compatibility: accept at most one optional int (old 'limit')
    if len(args) > 1:
      raise errors.GenericError("The bitarray.search() compatibility only "
                                "supports one optional argument")

    limit = args[0] if args and isinstance(args[0], int) else None

    res = list(super().search(sub_bitarray))
    if limit is None:
      return res
    return res[:limit]

# Simple alias (Python 3.6 friendly)
# pylint: disable=C0103
bitarray = CompatBitarray

__all__ = ["CompatBitarray", "bitarray"]
