#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Utility functions for manipulating /etc/hosts.

"""

from cStringIO import StringIO

from ganeti import constants

from ganeti.utils import algo
from ganeti.utils import io


def SetEtcHostsEntry(file_name, ip, hostname, aliases):
  """Sets the name of an IP address and hostname in /etc/hosts.

  @type file_name: str
  @param file_name: path to the file to modify (usually C{/etc/hosts})
  @type ip: str
  @param ip: the IP address
  @type hostname: str
  @param hostname: the hostname to be added
  @type aliases: list
  @param aliases: the list of aliases to add for the hostname

  """
  # Ensure aliases are unique
  names = algo.UniqueSequence([hostname] + aliases)

  out = StringIO()

  def _write_entry(written):
    if not written:
      out.write("%s\t%s\n" % (ip, " ".join(names)))
    return True

  written = False
  for line in io.ReadFile(file_name).splitlines(True):
    fields = line.split()
    if fields and not fields[0].startswith("#") and ip == fields[0]:
      written = _write_entry(written)
    else:
      out.write(line)
  _write_entry(written)

  io.WriteFile(file_name, data=out.getvalue(), mode=0644)


def AddHostToEtcHosts(hostname, ip):
  """Wrapper around SetEtcHostsEntry.

  @type hostname: str
  @param hostname: a hostname that will be resolved and added to
      L{constants.ETC_HOSTS}
  @type ip: str
  @param ip: The ip address of the host

  """
  SetEtcHostsEntry(constants.ETC_HOSTS, ip, hostname, [hostname.split(".")[0]])


def RemoveEtcHostsEntry(file_name, hostname):
  """Removes a hostname from /etc/hosts.

  IP addresses without names are removed from the file.

  @type file_name: str
  @param file_name: path to the file to modify (usually C{/etc/hosts})
  @type hostname: str
  @param hostname: the hostname to be removed

  """
  out = StringIO()

  for line in io.ReadFile(file_name).splitlines(True):
    fields = line.split()
    if len(fields) > 1 and not fields[0].startswith("#"):
      names = fields[1:]
      if hostname in names:
        while hostname in names:
          names.remove(hostname)
        if names:
          out.write("%s %s\n" % (fields[0], " ".join(names)))
        continue

    out.write(line)

  io.WriteFile(file_name, data=out.getvalue(), mode=0644)


def RemoveHostFromEtcHosts(hostname):
  """Wrapper around RemoveEtcHostsEntry.

  @type hostname: str
  @param hostname: hostname that will be resolved and its
      full and shot name will be removed from
      L{constants.ETC_HOSTS}

  """
  RemoveEtcHostsEntry(constants.ETC_HOSTS, hostname)
  RemoveEtcHostsEntry(constants.ETC_HOSTS, hostname.split(".")[0])
