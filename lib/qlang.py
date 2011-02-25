#
#

# Copyright (C) 2010 Google Inc.
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


"""Module for a simple query language"""

from ganeti import errors


# Logic operators
OP_OR = "|"
OP_AND = "&"


# Unary operators
OP_NOT = "!"


# Binary operators
OP_EQUAL = "="
OP_NOT_EQUAL = "!="
OP_GLOB = "=*"
OP_REGEXP = "=~"
OP_CONTAINS = "=[]"


def ReadSimpleFilter(namefield, filter_):
  """Function extracting wanted names from restricted filter.

  This should only be used until proper filtering is implemented. The filter
  must either be empty or of the format C{["|", ["=", field, "name1"], ["=",
  field, "name2"], ...]}.

  """
  if filter_ is None:
    return []

  if not isinstance(filter_, list):
    raise errors.ParameterError("Filter should be list")

  if not filter_ or filter_[0] != OP_OR:
    raise errors.ParameterError("Filter should start with OR operator")

  if len(filter_) < 2:
    raise errors.ParameterError("Invalid filter, OR operator should have"
                                " operands")

  result = []

  for idx, item in enumerate(filter_[1:]):
    if not isinstance(item, list):
      raise errors.ParameterError("Invalid OR operator, operand %s not a"
                                  " list" % idx)

    if len(item) != 3 or item[0] != OP_EQUAL:
      raise errors.ParameterError("Invalid OR operator, operand %s is not an"
                                  " equality filter" % idx)

    (_, name, value) = item

    if not isinstance(value, basestring):
      raise errors.ParameterError("Operand %s for OR should compare against a"
                                  " string" % idx)

    if name != namefield:
      raise errors.ParameterError("Operand %s for OR should filter field '%s',"
                                  " not '%s'" % (idx, namefield, name))

    result.append(value)

  return result


def MakeSimpleFilter(namefield, values):
  """Builds a filter for use with L{ReadSimpleFilter}.

  @param namefield: Name of field containing item name
  @param values: List of names

  """
  if values:
    return [OP_OR] + [[OP_EQUAL, namefield, i] for i in values]

  return None
