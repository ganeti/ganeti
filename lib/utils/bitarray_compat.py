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
CompatBitarray: Subclass from bitarray.bitarray returns always a list for
a.search(...)
"""

from typing import TypeAlias
from bitarray import bitarray as _BaseBitarray


class CompatBitarray(_BaseBitarray):
  # constructor forwarding for immutable C-Extension-Types
  def __new__(
    cls: "type[CompatBitarray]",
    *args,
    **kwargs
  ) -> "CompatBitarray":
    return _BaseBitarray.__new__(cls, *args, **kwargs)

  def search(self, *args, **kwargs) -> list[int]:
    """
    https://github.com/ilanschnell/bitarray/blob/master/doc/bitarray3.rst
    """
    res = super().search(*args, **kwargs)
    return res if isinstance(res, list) else list(res)


# Alias
# pylint: disable=C0103
bitarray: TypeAlias = CompatBitarray

__all__ = ["CompatBitarray", "bitarray"]
