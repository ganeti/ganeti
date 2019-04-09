#
#

# Copyright (C) 2009, 2012 Google Inc.
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


"""Ganeti confd client/server library

"""

from ganeti import constants
from ganeti import errors
from ganeti import ht


_FOURCC_LEN = 4


#: Items in the individual rows of the NodeDrbd query
_HTNodeDrbdItems = [ht.TString, ht.TInt, ht.TString,
                    ht.TString, ht.TString, ht.TString]
#: Type for the (top-level) result of NodeDrbd query
HTNodeDrbd = ht.TListOf(ht.TAnd(ht.TList, ht.TIsLength(len(_HTNodeDrbdItems)),
                                ht.TItems(_HTNodeDrbdItems)))


def PackMagic(payload):
  """Prepend the confd magic fourcc to a payload.

  """
  return b"".join([constants.CONFD_MAGIC_FOURCC_BYTES, payload])


def UnpackMagic(payload):
  """Unpack and check the confd magic fourcc from a payload.

  """
  if len(payload) < _FOURCC_LEN:
    raise errors.ConfdMagicError("UDP payload too short to contain the"
                                 " fourcc code")

  magic_number = payload[:_FOURCC_LEN]
  if magic_number != constants.CONFD_MAGIC_FOURCC_BYTES:
    raise errors.ConfdMagicError("UDP payload contains an unkown fourcc")

  return payload[_FOURCC_LEN:]
