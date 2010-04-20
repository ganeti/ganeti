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

from ganeti import constants
from ganeti import errors

from ganeti.hypervisor import hv_fake
from ganeti.hypervisor import hv_xen
from ganeti.hypervisor import hv_kvm
from ganeti.hypervisor import hv_chroot
from ganeti.hypervisor import hv_lxc


_HYPERVISOR_MAP = {
  constants.HT_XEN_PVM: hv_xen.XenPvmHypervisor,
  constants.HT_XEN_HVM: hv_xen.XenHvmHypervisor,
  constants.HT_FAKE: hv_fake.FakeHypervisor,
  constants.HT_KVM: hv_kvm.KVMHypervisor,
  constants.HT_CHROOT: hv_chroot.ChrootManager,
  constants.HT_LXC: hv_lxc.LXCHypervisor,
  }


def GetHypervisorClass(ht_kind):
  """Return a Hypervisor class.

  This function returns the hypervisor class corresponding to the
  given hypervisor name.

  @type ht_kind: string
  @param ht_kind: The requested hypervisor type

  """
  if ht_kind not in _HYPERVISOR_MAP:
    raise errors.HypervisorError("Unknown hypervisor type '%s'" % ht_kind)

  cls = _HYPERVISOR_MAP[ht_kind]
  return cls


def GetHypervisor(ht_kind):
  """Return a Hypervisor instance.

  This is a wrapper over L{GetHypervisorClass} which returns an
  instance of the class.

  @type ht_kind: string
  @param ht_kind: The requested hypervisor type

  """
  cls = GetHypervisorClass(ht_kind)

  return cls()
