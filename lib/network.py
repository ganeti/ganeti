#
#

# Copyright (C) 2011, 2012 Google Inc.
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


"""IP address pool management functions.

"""

import ipaddr

from bitarray import bitarray

from ganeti import errors


def _ComputeIpv4NumHosts(network_size):
  """Derives the number of hosts in an IPv4 network from the size.

  """
  return 2 ** (32 - network_size)


IPV4_NETWORK_MIN_SIZE = 30
# FIXME: This limit is for performance reasons. Remove when refactoring
# for performance tuning was successful.
IPV4_NETWORK_MAX_SIZE = 16
IPV4_NETWORK_MIN_NUM_HOSTS = _ComputeIpv4NumHosts(IPV4_NETWORK_MIN_SIZE)
IPV4_NETWORK_MAX_NUM_HOSTS = _ComputeIpv4NumHosts(IPV4_NETWORK_MAX_SIZE)


class AddressPool(object):
  """Address pool class, wrapping an C{objects.Network} object.

  This class provides methods to manipulate address pools, backed by
  L{objects.Network} objects.

  """
  FREE = bitarray("0")
  RESERVED = bitarray("1")

  def __init__(self, network):
    """Initialize a new IPv4 address pool from an L{objects.Network} object.

    @type network: L{objects.Network}
    @param network: the network object from which the pool will be generated

    """
    self.network = None
    self.gateway = None
    self.network6 = None
    self.gateway6 = None

    self.net = network

    self.network = ipaddr.IPNetwork(self.net.network)
    if self.network.numhosts > IPV4_NETWORK_MAX_NUM_HOSTS:
      raise errors.AddressPoolError("A big network with %s host(s) is currently"
                                    " not supported. please specify at most a"
                                    " /%s network" %
                                    (str(self.network.numhosts),
                                     IPV4_NETWORK_MAX_SIZE))

    if self.network.numhosts < IPV4_NETWORK_MIN_NUM_HOSTS:
      raise errors.AddressPoolError("A network with only %s host(s) is too"
                                    " small, please specify at least a /%s"
                                    " network" %
                                    (str(self.network.numhosts),
                                     IPV4_NETWORK_MIN_SIZE))
    if self.net.gateway:
      self.gateway = ipaddr.IPAddress(self.net.gateway)

    if self.net.network6:
      self.network6 = ipaddr.IPv6Network(self.net.network6)
    if self.net.gateway6:
      self.gateway6 = ipaddr.IPv6Address(self.net.gateway6)

    if self.net.reservations:
      self.reservations = bitarray(self.net.reservations)
    else:
      self.reservations = bitarray(self.network.numhosts)
      # pylint: disable=E1103
      self.reservations.setall(False)

    if self.net.ext_reservations:
      self.ext_reservations = bitarray(self.net.ext_reservations)
    else:
      self.ext_reservations = bitarray(self.network.numhosts)
      # pylint: disable=E1103
      self.ext_reservations.setall(False)

    assert len(self.reservations) == self.network.numhosts
    assert len(self.ext_reservations) == self.network.numhosts

  def Contains(self, address):
    if address is None:
      return False
    addr = ipaddr.IPAddress(address)

    return addr in self.network

  def _GetAddrIndex(self, address):
    addr = ipaddr.IPAddress(address)

    if not addr in self.network:
      raise errors.AddressPoolError("%s does not contain %s" %
                                    (self.network, addr))

    return int(addr) - int(self.network.network)

  def Update(self):
    """Write address pools back to the network object.

    """
    # pylint: disable=E1103
    self.net.ext_reservations = self.ext_reservations.to01()
    self.net.reservations = self.reservations.to01()

  def _Mark(self, address, value=True, external=False):
    idx = self._GetAddrIndex(address)
    if external:
      self.ext_reservations[idx] = value
    else:
      self.reservations[idx] = value
    self.Update()

  def _GetSize(self):
    return 2 ** (32 - self.network.prefixlen)

  @property
  def all_reservations(self):
    """Return a combined map of internal and external reservations.

    """
    return (self.reservations | self.ext_reservations)

  def Validate(self):
    assert len(self.reservations) == self._GetSize()
    assert len(self.ext_reservations) == self._GetSize()

    if self.gateway is not None:
      assert self.gateway in self.network

    if self.network6 and self.gateway6:
      assert self.gateway6 in self.network6 or self.gateway6.is_link_local

  def IsFull(self):
    """Check whether the network is full.

    """
    return self.all_reservations.all()

  def GetReservedCount(self):
    """Get the count of reserved addresses.

    """
    return self.all_reservations.count(True)

  def GetFreeCount(self):
    """Get the count of unused addresses.

    """
    return self.all_reservations.count(False)

  def GetMap(self):
    """Return a textual representation of the network's occupation status.

    """
    return self.all_reservations.to01().replace("1", "X").replace("0", ".")

  def IsReserved(self, address, external=False):
    """Checks if the given IP is reserved.

    """
    idx = self._GetAddrIndex(address)
    if external:
      return self.ext_reservations[idx]
    else:
      return self.reservations[idx]

  def Reserve(self, address, external=False):
    """Mark an address as used.

    """
    if self.IsReserved(address, external):
      if external:
        msg = "IP %s is already externally reserved" % address
      else:
        msg = "IP %s is already used by an instance" % address
      raise errors.AddressPoolError(msg)

    self._Mark(address, external=external)

  def Release(self, address, external=False):
    """Release a given address reservation.

    """
    if not self.IsReserved(address, external):
      if external:
        msg = "IP %s is not externally reserved" % address
      else:
        msg = "IP %s is not used by an instance" % address
      raise errors.AddressPoolError(msg)

    self._Mark(address, value=False, external=external)

  def GetFreeAddress(self):
    """Returns the first available address.

    """
    if self.IsFull():
      raise errors.AddressPoolError("%s is full" % self.network)

    idx = self.all_reservations.index(False)
    address = str(self.network[idx])
    self.Reserve(address)
    return address

  def GenerateFree(self):
    """Returns the first free address of the network.

    @raise errors.AddressPoolError: Pool is full

    """
    idx = self.all_reservations.search(self.FREE, 1)
    if idx:
      return str(self.network[idx[0]])
    else:
      raise errors.AddressPoolError("%s is full" % self.network)

  def GetExternalReservations(self):
    """Returns a list of all externally reserved addresses.

    """
    # pylint: disable=E1103
    idxs = self.ext_reservations.search(self.RESERVED)
    return [str(self.network[idx]) for idx in idxs]

  @classmethod
  def InitializeNetwork(cls, net):
    """Initialize an L{objects.Network} object.

    Reserve the network, broadcast and gateway IP addresses.

    """
    obj = cls(net)
    obj.Update()
    for ip in [obj.network[0], obj.network[-1]]:
      obj.Reserve(ip, external=True)
    if obj.net.gateway is not None:
      obj.Reserve(obj.net.gateway, external=True)
    obj.Validate()
    return obj
