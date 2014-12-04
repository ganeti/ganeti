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
IFF_MULTI_QUEUE = 0x0100


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


def _ProbeTapMqVirtioNet(fd, _features_fn=_GetTunFeatures):
  """Check whether to enable the IFF_MULTI_QUEUE flag.

  This flag was introduced in Linux kernel 3.8.

   @type fd: int
   @param fd: the file descriptor of /dev/net/tun

  """
  flags = _features_fn(fd)

  if flags is None:
    # Not supported
    return False

  result = bool(flags & IFF_MULTI_QUEUE)

  if not result:
    logging.warning("Kernel does not support IFF_MULTI_QUEUE, not enabling")

  return result


def OpenTap(name="", features=None):
  """Open a new tap device and return its file descriptor.

  This is intended to be used by a qemu-type hypervisor together with the -net
  tap,fd=<fd> or -net tap,fds=x:y:...:z command line parameter.

  @type name: string
  @param name: name for the TAP interface being created; if an empty
               string is passed, the OS will generate a unique name

  @type features: dict
  @param features: A dict denoting whether vhost, vnet_hdr, mq
    netdev features are enabled or not.

  @return: (ifname, [tapfds], [vhostfds])
  @rtype: tuple

  """
  tapfds = []
  vhostfds = []
  if features is None:
    features = {}
  vhost = features.get("vhost", False)
  vnet_hdr = features.get("vnet_hdr", True)
  _, virtio_net_queues = features.get("mq", (False, 1))

  for _ in range(virtio_net_queues):
    try:
      tapfd = os.open("/dev/net/tun", os.O_RDWR)
    except EnvironmentError:
      raise errors.HypervisorError("Failed to open /dev/net/tun")

    flags = IFF_TAP | IFF_NO_PI

    if vnet_hdr and _ProbeTapVnetHdr(tapfd):
      flags |= IFF_VNET_HDR

    # Check if it's ok to enable IFF_MULTI_QUEUE
    if virtio_net_queues > 1 and _ProbeTapMqVirtioNet(tapfd):
      flags |= IFF_MULTI_QUEUE
    else:
      flags |= IFF_ONE_QUEUE

    # The struct ifreq ioctl request (see netdevice(7))
    ifr = struct.pack("16sh", name, flags)

    try:
      res = fcntl.ioctl(tapfd, TUNSETIFF, ifr)
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to allocate a new TAP device: %s" %
                                   err)

    if vhost:
      # This is done regularly by the qemu process if vhost=on was passed with
      # --netdev option. Still, in case of hotplug and if the process does not
      # run with root privileges, we have to get the fds and pass them via
      # SCM_RIGHTS prior to qemu using them.
      try:
        vhostfd = os.open("/dev/vhost-net", os.O_RDWR)
        vhostfds.append(vhostfd)
      except EnvironmentError:
        raise errors.HypervisorError("Failed to open /dev/vhost-net")

    tapfds.append(tapfd)

  # Get the interface name from the ioctl
  ifname = struct.unpack("16sh", res)[0].strip("\x00")

  return (ifname, tapfds, vhostfds)
