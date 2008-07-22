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


"""Remote API base resources library.

"""

import ganeti.cli
import ganeti.opcodes


def BuildUriList(ids, uri_format, uri_fields=("name", "uri")):
  """Builds a URI list as used by index resources.

  Args:
  - ids: List of ids as strings
  - uri_format: Format to be applied for URI
  - uri_fields: Optional parameter for field ids

  """
  (field_id, field_uri) = uri_fields
  
  def _MapId(m_id):
    return { field_id: m_id, field_uri: uri_format % m_id, }

  # Make sure the result is sorted, makes it nicer to look at and simplifies
  # unittests.
  ids.sort()

  return map(_MapId, ids)


def ExtractField(sequence, index):
  """Creates a list containing one column out of a list of lists.

  Args:
  - sequence: Sequence of lists
  - index: Index of field

  """
  return map(lambda item: item[index], sequence)


def MapFields(names, data):
  """Maps two lists into one dictionary.

  Args:
  - names: Field names (list of strings)
  - data: Field data (list)

  Example:
  >>> MapFields(["a", "b"], ["foo", 123])
  {'a': 'foo', 'b': 123}

  """
  if len(names) != len(data):
    raise AttributeError("Names and data must have the same length")
  return dict([(names[i], data[i]) for i in range(len(names))])


def _Tags_GET(kind, name=None):
  """Helper function to retrieve tags.

  """
  if name is None:
    # Do not cause "missing parameter" error, which happens if a parameter
    # is None.
    name = ""
  op = ganeti.opcodes.OpGetTags(kind=kind, name=name)
  tags = ganeti.cli.SubmitOpCode(op)
  return list(tags)


class R_Generic(object):
  """Generic class for resources.

  """
  def __init__(self, request, items, queryargs):
    """Generic resource constructor.

    Args:
      request: HTTPRequestHandler object
      items: a list with variables encoded in the URL
      queryargs: a dictionary with additional options from URL

    """
    self.request = request
    self.items = items
    self.queryargs = queryargs
