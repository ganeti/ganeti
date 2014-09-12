#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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

"""Utility functions for LVM.

"""

from ganeti import constants


def CheckVolumeGroupSize(vglist, vgname, minsize):
  """Checks if the volume group list is valid.

  The function will check if a given volume group is in the list of
  volume groups and has a minimum size.

  @type vglist: dict
  @param vglist: dictionary of volume group names and their size
  @type vgname: str
  @param vgname: the volume group we should check
  @type minsize: int
  @param minsize: the minimum size we accept
  @rtype: None or str
  @return: None for success, otherwise the error message

  """
  vgsize = vglist.get(vgname, None)
  if vgsize is None:
    return "volume group '%s' missing" % vgname
  elif vgsize < minsize:
    return ("volume group '%s' too small (%s MiB required, %d MiB found)" %
            (vgname, minsize, vgsize))
  return None


def LvmExclusiveCheckNodePvs(pvs_info):
  """Check consistency of PV sizes in a node for exclusive storage.

  @type pvs_info: list
  @param pvs_info: list of L{LvmPvInfo} objects
  @rtype: tuple
  @return: A pair composed of: 1. a list of error strings describing the
    violations found, or an empty list if everything is ok; 2. a pair
    containing the sizes of the smallest and biggest PVs, in MiB.

  """
  errmsgs = []
  sizes = [pv.size for pv in pvs_info]
  # The sizes of PVs must be the same (tolerance is constants.PART_MARGIN)
  small = min(sizes)
  big = max(sizes)
  if LvmExclusiveTestBadPvSizes(small, big):
    m = ("Sizes of PVs are too different: min=%d max=%d" % (small, big))
    errmsgs.append(m)
  return (errmsgs, (small, big))


def LvmExclusiveTestBadPvSizes(small, big):
  """Test if the given PV sizes are permitted with exclusive storage.

  @param small: size of the smallest PV
  @param big: size of the biggest PV
  @return: True when the given sizes are bad, False otherwise
  """
  # Test whether no X exists such that:
  #   small >= X * (1 - constants.PART_MARGIN)  and
  #   big <= X * (1 + constants.PART_MARGIN)
  return (small * (1 + constants.PART_MARGIN) <
          big * (1 - constants.PART_MARGIN))
