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

from ganeti import luxi


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
  return dict(zip(names, data))


def _Tags_GET(kind, name=""):
  """Helper function to retrieve tags.

  """
  op = ganeti.opcodes.OpGetTags(kind=kind, name=name)
  tags = ganeti.cli.SubmitOpCode(op)
  return list(tags)


def _Tags_POST(kind, tags, name=""):
  """Helper function to set tags.

  """
  cl = luxi.Client()
  return cl.SubmitJob([ganeti.opcodes.OpAddTags(kind=kind, name=name,
                                                tags=tags)])


def _Tags_DELETE(kind, tags, name=""):
  """Helper function to delete tags.

  """
  cl = luxi.Client()
  return cl.SubmitJob([ganeti.opcodes.OpDelTags(kind=kind, name=name,
                                                tags=tags)])


def MapBulkFields(itemslist, fields):
  """Map value to field name in to one dictionary.

  Args:
  - itemslist: A list of items values
  - instance: A list of items names

  Returns:
    A list of mapped dictionaries
  """
  items_details = []
  for item in itemslist:
    mapped = MapFields(fields, item)
    items_details.append(mapped)
  return items_details


class R_Generic(object):
  """Generic class for resources.

  """
  def __init__(self, items, queryargs, post_data):
    """Generic resource constructor.

    Args:
      items: a list with variables encoded in the URL
      queryargs: a dictionary with additional options from URL

    """
    self.items = items
    self.queryargs = queryargs
    self.post_data = post_data
    self.sn = None

  def getSerialNumber(self):
    """Get Serial Number.

    """
    return self.sn
