#
#

# Copyright (C) 2014 Google Inc.
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


"""KVM hypervisor tap device helpers

"""

import os
import logging
import struct
import fcntl

from ganeti import errors


# TUN/TAP driver constants, taken from <linux/if_tun.h>
# They are architecture-independent and already hardcoded in qemu-kvm source,
# so we can safely include them here.
TUNSETIFF = 0x400454ca
TUNGETIFF = 0x800454d2
TUNGETFEATURES = 0x800454cf
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000
IFF_ONE_QUEUE = 0x2000
IFF_VNET_HDR = 0x4000


def _GetTunFeatures(fd, _ioctl=fcntl.ioctl):
  """Retrieves supported TUN features from file descriptor.

  @see: L{_ProbeTapVnetHdr}

  """
  req = struct.pack("I", 0)
  try:
    buf = _ioctl(fd, TUNGETFEATURES, req)
  except EnvironmentError, err:
    logging.warning("ioctl(TUNGETFEATURES) failed: %s", err)
    return None
  else:
    (flags, ) = struct.unpack("I", buf)
    return flags


def _ProbeTapVnetHdr(fd, _features_fn=_GetTunFeatures):
  """Check whether to enable the IFF_VNET_HDR flag.

  To do this, _all_ of the following conditions must be met:
   1. TUNGETFEATURES ioctl() *must* be implemented
   2. TUNGETFEATURES ioctl() result *must* contain the IFF_VNET_HDR flag
   3. TUNGETIFF ioctl() *must* be implemented; reading the kernel code in
      drivers/net/tun.c there is no way to test this until after the tap device
      has been created using TUNSETIFF, and there is no way to change the
      IFF_VNET_HDR flag after creating the interface, catch-22! However both
      TUNGETIFF and TUNGETFEATURES were introduced in kernel version 2.6.27,
      thus we can expect TUNGETIFF to be present if TUNGETFEATURES is.

   @type fd: int
   @param fd: the file descriptor of /dev/net/tun

  """
  flags = _features_fn(fd)

  if flags is None:
    # Not supported
    return False

  result = bool(flags & IFF_VNET_HDR)

  if not result:
    logging.warning("Kernel does not support IFF_VNET_HDR, not enabling")

  return result


def OpenTap(vnet_hdr=True, name=""):
  """Open a new tap device and return its file descriptor.

  This is intended to be used by a qemu-type hypervisor together with the -net
  tap,fd=<fd> command line parameter.

  @type vnet_hdr: boolean
  @param vnet_hdr: Enable the VNET Header

  @type name: string
  @param name: name for the TAP interface being created; if an empty
               string is passed, the OS will generate a unique name

  @return: (ifname, tapfd)
  @rtype: tuple

  """
  try:
    tapfd = os.open("/dev/net/tun", os.O_RDWR)
  except EnvironmentError:
    raise errors.HypervisorError("Failed to open /dev/net/tun")

  flags = IFF_TAP | IFF_NO_PI | IFF_ONE_QUEUE

  if vnet_hdr and _ProbeTapVnetHdr(tapfd):
    flags |= IFF_VNET_HDR

  # The struct ifreq ioctl request (see netdevice(7))
  ifr = struct.pack("16sh", name, flags)

  try:
    res = fcntl.ioctl(tapfd, TUNSETIFF, ifr)
  except EnvironmentError, err:
    raise errors.HypervisorError("Failed to allocate a new TAP device: %s" %
                                 err)

  # Get the interface name from the ioctl
  ifname = struct.unpack("16sh", res)[0].strip("\x00")
  return (ifname, tapfd)
