#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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
