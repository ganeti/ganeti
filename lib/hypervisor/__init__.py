#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Virtualization interface abstraction

"""

from ganeti import ssconf
from ganeti import constants
from ganeti import errors

from ganeti.hypervisor import FakeHypervisor
from ganeti.hypervisor import XenHypervisor


def GetHypervisor():
  """Return a Hypervisor instance.

  This function parses the cluster hypervisor configuration file and
  instantiates a class based on the value of this file.

  """
  ht_kind = ssconf.SimpleStore().GetHypervisorType()
  if ht_kind == constants.HT_XEN_PVM30:
    cls = XenHypervisor.XenPvmHypervisor
  elif ht_kind == constants.HT_XEN_HVM31:
    cls = XenHypervisor.XenHvmHypervisor
  elif ht_kind == constants.HT_FAKE:
    cls = FakeHypervisor.FakeHypervisor
  else:
    raise errors.HypervisorError("Unknown hypervisor type '%s'" % ht_kind)
  return cls()
