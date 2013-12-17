#
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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


"""Ganeti network utility module.

This module holds functions that can be used in both daemons (all) and
the command line scripts.

"""


import errno
import os
import re
import socket
import struct
import IN
import logging

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import vcluster

# Structure definition for getsockopt(SOL_SOCKET, SO_PEERCRED, ...):
# struct ucred { pid_t pid; uid_t uid; gid_t gid; };
#
# The GNU C Library defines gid_t and uid_t to be "unsigned int" and
# pid_t to "int".
#
# IEEE Std 1003.1-2008:
# "nlink_t, uid_t, gid_t, and id_t shall be integer types"
# "blksize_t, pid_t, and ssize_t shall be signed integer types"
_STRUCT_UCRED = "iII"
_STRUCT_UCRED_SIZE = struct.calcsize(_STRUCT_UCRED)

# Workaround a bug in some linux distributions that don't define SO_PEERCRED
try:
  # pylint: disable=E1101
  _SO_PEERCRED = IN.SO_PEERCRED
except AttributeError:
  _SO_PEERCRED = 17

# Regexes used to find IP addresses in the output of ip.
_IP_RE_TEXT = r"[.:a-z0-9]+"      # separate for testing purposes
_IP_FAMILY_RE = re.compile(r"(?P<family>inet6?)\s+(?P<ip>%s)/" % _IP_RE_TEXT,
                           re.IGNORECASE)

# Dict used to convert from a string representing an IP family to an IP
# version
_NAME_TO_IP_VER = {
  "inet": constants.IP4_VERSION,
  "inet6": constants.IP6_VERSION,
  }


def _GetIpAddressesFromIpOutput(ip_output):
  """Parses the output of the ip command and retrieves the IP addresses and
  version.

  @param ip_output: string containing the output of the ip command;
  @rtype: dict; (int, list)
  @return: a dict having as keys the IP versions and as values the
           corresponding list of addresses found in the IP output.

  """
  addr = dict((i, []) for i in _NAME_TO_IP_VER.values())

  for row in ip_output.splitlines():
    match = _IP_FAMILY_RE.search(row)
    if match and IPAddress.IsValid(match.group("ip")):
      addr[_NAME_TO_IP_VER[match.group("family")]].append(match.group("ip"))

  return addr


def GetSocketCredentials(sock):
  """Returns the credentials of the foreign process connected to a socket.

  @param sock: Unix socket
  @rtype: tuple; (number, number, number)
  @return: The PID, UID and GID of the connected foreign process.

  """
  peercred = sock.getsockopt(socket.SOL_SOCKET, _SO_PEERCRED,
                             _STRUCT_UCRED_SIZE)
  return struct.unpack(_STRUCT_UCRED, peercred)


def IsValidInterface(ifname):
  """Validate an interface name.

  @type ifname: string
  @param ifname: Name of the network interface
  @return: boolean indicating whether the interface name is valid or not.

  """
  return os.path.exists(utils.PathJoin("/sys/class/net", ifname))


def GetInterfaceIpAddresses(ifname):
  """Returns the IP addresses associated to the interface.

  @type ifname: string
  @param ifname: Name of the network interface
  @return: A dict having for keys the IP version (either
           L{constants.IP4_VERSION} or L{constants.IP6_VERSION}) and for
           values the lists of IP addresses of the respective version
           associated to the interface

  """
  result = utils.RunCmd([constants.IP_COMMAND_PATH, "-o", "addr", "show",
                         ifname])

  if result.failed:
    logging.error("Error running the ip command while getting the IP"
                  " addresses of %s", ifname)
    return None

  return _GetIpAddressesFromIpOutput(result.output)


def GetHostname(name=None, family=None):
  """Returns a Hostname object.

  @type name: str
  @param name: hostname or None
  @type family: int
  @param family: AF_INET | AF_INET6 | None
  @rtype: L{Hostname}
  @return: Hostname object
  @raise errors.OpPrereqError: in case of errors in resolving

  """
  try:
    return Hostname(name=name, family=family)
  except errors.ResolverError, err:
    raise errors.OpPrereqError("The given name (%s) does not resolve: %s" %
                               (err[0], err[2]), errors.ECODE_RESOLVER)


class Hostname:
  """Class implementing resolver and hostname functionality.

  """
  _VALID_NAME_RE = re.compile("^[a-z0-9._-]{1,255}$")

  def __init__(self, name=None, family=None):
    """Initialize the host name object.

    If the name argument is None, it will use this system's name.

    @type family: int
    @param family: AF_INET | AF_INET6 | None
    @type name: str
    @param name: hostname or None

    """
    self.name = self.GetFqdn(name)
    self.ip = self.GetIP(self.name, family=family)

  @classmethod
  def GetSysName(cls):
    """Legacy method the get the current system's name.

    """
    return cls.GetFqdn()

  @classmethod
  def GetFqdn(cls, hostname=None):
    """Return fqdn.

    If hostname is None the system's fqdn is returned.

    @type hostname: str
    @param hostname: name to be fqdn'ed
    @rtype: str
    @return: fqdn of given name, if it exists, unmodified name otherwise

    """
    if hostname is None:
      virtfqdn = vcluster.GetVirtualHostname()
      if virtfqdn:
        result = virtfqdn
      else:
        result = socket.getfqdn()
    else:
      result = socket.getfqdn(hostname)

    return cls.GetNormalizedName(result)

  @staticmethod
  def GetIP(hostname, family=None):
    """Return IP address of given hostname.

    Supports both IPv4 and IPv6.

    @type hostname: str
    @param hostname: hostname to look up
    @type family: int
    @param family: AF_INET | AF_INET6 | None
    @rtype: str
    @return: IP address
    @raise errors.ResolverError: in case of errors in resolving

    """
    try:
      if family in (socket.AF_INET, socket.AF_INET6):
        result = socket.getaddrinfo(hostname, None, family)
      else:
        result = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, socket.herror, socket.error), err:
      # hostname not found in DNS, or other socket exception in the
      # (code, description format)
      raise errors.ResolverError(hostname, err.args[0], err.args[1])

    # getaddrinfo() returns a list of 5-tupes (family, socktype, proto,
    # canonname, sockaddr). We return the first tuple's first address in
    # sockaddr
    try:
      return result[0][4][0]
    except IndexError, err:
      # we don't have here an actual error code, it's just that the
      # data type returned by getaddrinfo is not what we expected;
      # let's keep the same format in the exception arguments with a
      # dummy error code
      raise errors.ResolverError(hostname, 0,
                                 "Unknown error in getaddrinfo(): %s" % err)

  @classmethod
  def GetNormalizedName(cls, hostname):
    """Validate and normalize the given hostname.

    @attention: the validation is a bit more relaxed than the standards
        require; most importantly, we allow underscores in names
    @raise errors.OpPrereqError: when the name is not valid

    """
    hostname = hostname.lower()
    if (not cls._VALID_NAME_RE.match(hostname) or
        # double-dots, meaning empty label
        ".." in hostname or
        # empty initial label
        hostname.startswith(".")):
      raise errors.OpPrereqError("Invalid hostname '%s'" % hostname,
                                 errors.ECODE_INVAL)
    if hostname.endswith("."):
      hostname = hostname.rstrip(".")
    return hostname


def ValidatePortNumber(port):
  """Returns the validated integer port number if it is valid.

  @param port: the port number to be validated

  @raise ValueError: if the port is not valid
  @rtype: int
  @return: the validated value.

  """

  try:
    port = int(port)
  except TypeError:
    raise errors.ProgrammerError("ValidatePortNumber called with non-numeric"
                                 " type %s." % port.__class__.__name__)
  except ValueError:
    raise ValueError("Invalid port value: '%s'" % port)

  if not 0 < port < 2 ** 16:
    raise ValueError("Invalid port value: '%d'" % port)

  return port


def TcpPing(target, port, timeout=10, live_port_needed=False, source=None):
  """Simple ping implementation using TCP connect(2).

  Check if the given IP is reachable by doing attempting a TCP connect
  to it.

  @type target: str
  @param target: the IP to ping
  @type port: int
  @param port: the port to connect to
  @type timeout: int
  @param timeout: the timeout on the connection attempt
  @type live_port_needed: boolean
  @param live_port_needed: whether a closed port will cause the
      function to return failure, as if there was a timeout
  @type source: str or None
  @param source: if specified, will cause the connect to be made
      from this specific source address; failures to bind other
      than C{EADDRNOTAVAIL} will be ignored

  """
  logging.debug("Attempting to reach TCP port %s on target %s with a timeout"
                " of %s seconds", port, target, timeout)

  try:
    family = IPAddress.GetAddressFamily(target)
  except errors.IPAddressError, err:
    raise errors.ProgrammerError("Family of IP address given in parameter"
                                 " 'target' can't be determined: %s" % err)

  sock = socket.socket(family, socket.SOCK_STREAM)
  success = False

  if source is not None:
    try:
      sock.bind((source, 0))
    except socket.error, err:
      if err[0] == errno.EADDRNOTAVAIL:
        success = False

  sock.settimeout(timeout)

  try:
    sock.connect((target, port))
    sock.close()
    success = True
  except socket.timeout:
    success = False
  except socket.error, err:
    success = (not live_port_needed) and (err[0] == errno.ECONNREFUSED)

  return success


def GetDaemonPort(daemon_name):
  """Get the daemon port for this cluster.

  Note that this routine does not read a ganeti-specific file, but
  instead uses C{socket.getservbyname} to allow pre-customization of
  this parameter outside of Ganeti.

  @type daemon_name: string
  @param daemon_name: daemon name (in constants.DAEMONS_PORTS)
  @rtype: int

  """
  if daemon_name not in constants.DAEMONS_PORTS:
    raise errors.ProgrammerError("Unknown daemon: %s" % daemon_name)

  (proto, default_port) = constants.DAEMONS_PORTS[daemon_name]
  try:
    port = socket.getservbyname(daemon_name, proto)
  except socket.error:
    port = default_port

  return port


class IPAddress(object):
  """Class that represents an IP address.

  """
  iplen = 0
  family = None
  loopback_cidr = None

  @staticmethod
  def _GetIPIntFromString(address):
    """Abstract method to please pylint.

    """
    raise NotImplementedError

  @classmethod
  def IsValid(cls, address):
    """Validate a IP address.

    @type address: str
    @param address: IP address to be checked
    @rtype: bool
    @return: True if valid, False otherwise

    """
    if cls.family is None:
      try:
        family = cls.GetAddressFamily(address)
      except errors.IPAddressError:
        return False
    else:
      family = cls.family

    try:
      socket.inet_pton(family, address)
      return True
    except socket.error:
      return False

  @classmethod
  def ValidateNetmask(cls, netmask):
    """Validate a netmask suffix in CIDR notation.

    @type netmask: int
    @param netmask: netmask suffix to validate
    @rtype: bool
    @return: True if valid, False otherwise

    """
    assert (isinstance(netmask, (int, long)))

    return 0 < netmask <= cls.iplen

  @classmethod
  def Own(cls, address):
    """Check if the current host has the the given IP address.

    This is done by trying to bind the given address. We return True if we
    succeed or false if a socket.error is raised.

    @type address: str
    @param address: IP address to be checked
    @rtype: bool
    @return: True if we own the address, False otherwise

    """
    if cls.family is None:
      try:
        family = cls.GetAddressFamily(address)
      except errors.IPAddressError:
        return False
    else:
      family = cls.family

    s = socket.socket(family, socket.SOCK_DGRAM)
    success = False
    try:
      try:
        s.bind((address, 0))
        success = True
      except socket.error:
        success = False
    finally:
      s.close()
    return success

  @classmethod
  def InNetwork(cls, cidr, address):
    """Determine whether an address is within a network.

    @type cidr: string
    @param cidr: Network in CIDR notation, e.g. '192.0.2.0/24', '2001:db8::/64'
    @type address: str
    @param address: IP address
    @rtype: bool
    @return: True if address is in cidr, False otherwise

    """
    address_int = cls._GetIPIntFromString(address)
    subnet = cidr.split("/")
    assert len(subnet) == 2
    try:
      prefix = int(subnet[1])
    except ValueError:
      return False

    assert 0 <= prefix <= cls.iplen
    target_int = cls._GetIPIntFromString(subnet[0])
    # Convert prefix netmask to integer value of netmask
    netmask_int = (2 ** cls.iplen) - 1 ^ ((2 ** cls.iplen) - 1 >> prefix)
    # Calculate hostmask
    hostmask_int = netmask_int ^ (2 ** cls.iplen) - 1
    # Calculate network address by and'ing netmask
    network_int = target_int & netmask_int
    # Calculate broadcast address by or'ing hostmask
    broadcast_int = target_int | hostmask_int

    return network_int <= address_int <= broadcast_int

  @staticmethod
  def GetAddressFamily(address):
    """Get the address family of the given address.

    @type address: str
    @param address: ip address whose family will be returned
    @rtype: int
    @return: C{socket.AF_INET} or C{socket.AF_INET6}
    @raise errors.GenericError: for invalid addresses

    """
    try:
      return IP4Address(address).family
    except errors.IPAddressError:
      pass

    try:
      return IP6Address(address).family
    except errors.IPAddressError:
      pass

    raise errors.IPAddressError("Invalid address '%s'" % address)

  @staticmethod
  def GetVersionFromAddressFamily(family):
    """Convert an IP address family to the corresponding IP version.

    @type family: int
    @param family: IP address family, one of socket.AF_INET or socket.AF_INET6
    @return: an int containing the IP version, one of L{constants.IP4_VERSION}
             or L{constants.IP6_VERSION}
    @raise errors.ProgrammerError: for unknown families

    """
    if family == socket.AF_INET:
      return constants.IP4_VERSION
    elif family == socket.AF_INET6:
      return constants.IP6_VERSION

    raise errors.ProgrammerError("%s is not a valid IP address family" % family)

  @staticmethod
  def GetAddressFamilyFromVersion(version):
    """Convert an IP version to the corresponding IP address family.

    @type version: int
    @param version: IP version, one of L{constants.IP4_VERSION} or
                    L{constants.IP6_VERSION}
    @return: an int containing the IP address family, one of C{socket.AF_INET}
             or C{socket.AF_INET6}
    @raise errors.ProgrammerError: for unknown IP versions

    """
    if version == constants.IP4_VERSION:
      return socket.AF_INET
    elif version == constants.IP6_VERSION:
      return socket.AF_INET6

    raise errors.ProgrammerError("%s is not a valid IP version" % version)

  @staticmethod
  def GetClassFromIpVersion(version):
    """Return the IPAddress subclass for the given IP version.

    @type version: int
    @param version: IP version, one of L{constants.IP4_VERSION} or
                    L{constants.IP6_VERSION}
    @return: a subclass of L{netutils.IPAddress}
    @raise errors.ProgrammerError: for unknowo IP versions

    """
    if version == constants.IP4_VERSION:
      return IP4Address
    elif version == constants.IP6_VERSION:
      return IP6Address

    raise errors.ProgrammerError("%s is not a valid IP version" % version)

  @staticmethod
  def GetClassFromIpFamily(family):
    """Return the IPAddress subclass for the given IP family.

    @param family: IP family (one of C{socket.AF_INET} or C{socket.AF_INET6}
    @return: a subclass of L{netutils.IPAddress}
    @raise errors.ProgrammerError: for unknowo IP versions

    """
    return IPAddress.GetClassFromIpVersion(
              IPAddress.GetVersionFromAddressFamily(family))

  @classmethod
  def IsLoopback(cls, address):
    """Determine whether it is a loopback address.

    @type address: str
    @param address: IP address to be checked
    @rtype: bool
    @return: True if loopback, False otherwise

    """
    try:
      return cls.InNetwork(cls.loopback_cidr, address)
    except errors.IPAddressError:
      return False


class IP4Address(IPAddress):
  """IPv4 address class.

  """
  iplen = 32
  family = socket.AF_INET
  loopback_cidr = "127.0.0.0/8"

  def __init__(self, address):
    """Constructor for IPv4 address.

    @type address: str
    @param address: IP address
    @raises errors.IPAddressError: if address invalid

    """
    IPAddress.__init__(self)
    if not self.IsValid(address):
      raise errors.IPAddressError("IPv4 Address %s invalid" % address)

    self.address = address

  @staticmethod
  def _GetIPIntFromString(address):
    """Get integer value of IPv4 address.

    @type address: str
    @param address: IPv6 address
    @rtype: int
    @return: integer value of given IP address

    """
    address_int = 0
    parts = address.split(".")
    assert len(parts) == 4
    for part in parts:
      address_int = (address_int << 8) | int(part)

    return address_int


class IP6Address(IPAddress):
  """IPv6 address class.

  """
  iplen = 128
  family = socket.AF_INET6
  loopback_cidr = "::1/128"

  def __init__(self, address):
    """Constructor for IPv6 address.

    @type address: str
    @param address: IP address
    @raises errors.IPAddressError: if address invalid

    """
    IPAddress.__init__(self)
    if not self.IsValid(address):
      raise errors.IPAddressError("IPv6 Address [%s] invalid" % address)
    self.address = address

  @staticmethod
  def _GetIPIntFromString(address):
    """Get integer value of IPv6 address.

    @type address: str
    @param address: IPv6 address
    @rtype: int
    @return: integer value of given IP address

    """
    doublecolons = address.count("::")
    assert not doublecolons > 1
    if doublecolons == 1:
      # We have a shorthand address, expand it
      parts = []
      twoparts = address.split("::")
      sep = len(twoparts[0].split(":")) + len(twoparts[1].split(":"))
      parts = twoparts[0].split(":")
      parts.extend(["0"] * (8 - sep))
      parts += twoparts[1].split(":")
    else:
      parts = address.split(":")

    address_int = 0
    for part in parts:
      address_int = (address_int << 16) + int(part or "0", 16)

    return address_int


def FormatAddress(address, family=None):
  """Format a socket address

  @type address: family specific (usually tuple)
  @param address: address, as reported by this class
  @type family: integer
  @param family: socket family (one of socket.AF_*) or None

  """
  if family is None:
    try:
      family = IPAddress.GetAddressFamily(address[0])
    except errors.IPAddressError:
      raise errors.ParameterError(address)

  if family == socket.AF_UNIX and len(address) == 3:
    return "pid=%s, uid=%s, gid=%s" % address

  if family in (socket.AF_INET, socket.AF_INET6) and len(address) == 2:
    host, port = address
    if family == socket.AF_INET6:
      res = "[%s]" % host
    else:
      res = host

    if port is not None:
      res += ":%s" % port

    return res

  raise errors.ParameterError(family, address)
