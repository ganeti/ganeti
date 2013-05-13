#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Common functions used by multiple logical units."""

from ganeti import errors


def _ExpandItemName(fn, name, kind):
  """Expand an item name.

  @param fn: the function to use for expansion
  @param name: requested item name
  @param kind: text description ('Node' or 'Instance')
  @return: the resolved (full) name
  @raise errors.OpPrereqError: if the item is not found

  """
  full_name = fn(name)
  if full_name is None:
    raise errors.OpPrereqError("%s '%s' not known" % (kind, name),
                               errors.ECODE_NOENT)
  return full_name


def _ExpandInstanceName(cfg, name):
  """Wrapper over L{_ExpandItemName} for instance."""
  return _ExpandItemName(cfg.ExpandInstanceName, name, "Instance")


def _ExpandNodeName(cfg, name):
  """Wrapper over L{_ExpandItemName} for nodes."""
  return _ExpandItemName(cfg.ExpandNodeName, name, "Node")
