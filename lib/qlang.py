#
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Module for a simple query language

A query filter is always a list. The first item in the list is the operator
(e.g. C{[OP_AND, ...]}), while the other items depend on the operator. For
logic operators (e.g. L{OP_AND}, L{OP_OR}), they are subfilters whose results
are combined. Unary operators take exactly one other item (e.g. a subfilter for
L{OP_NOT} and a field name for L{OP_TRUE}). Binary operators take exactly two
operands, usually a field name and a value to compare against. Filters are
converted to callable functions by L{query._CompileFilter}.

"""

from ganeti import errors


# Logic operators with one or more operands, each of which is a filter on its
# own
OP_OR = "|"
OP_AND = "&"


# Unary operators with exactly one operand
OP_NOT = "!"
OP_TRUE = "?"


# Binary operators with exactly two operands, the field name and an
# operator-specific value
OP_EQUAL = "="
OP_NOT_EQUAL = "!="
OP_GLOB = "=*"
OP_REGEXP = "=~"
OP_CONTAINS = "=[]"


def MakeSimpleFilter(namefield, values):
  """Builds simple a filter.

  @param namefield: Name of field containing item name
  @param values: List of names

  """
  if values:
    return [OP_OR] + [[OP_EQUAL, namefield, i] for i in values]

  return None
