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

"""Utility functions with algorithms.

"""

import re
import time
import itertools

from ganeti import compat
from ganeti.utils import text


_SORTER_GROUPS = 8
_SORTER_RE = re.compile("^%s(.*)$" % (_SORTER_GROUPS * r"(\D+|\d+)?"))


def UniqueSequence(seq):
  """Returns a list with unique elements.

  Element order is preserved.

  @type seq: sequence
  @param seq: the sequence with the source elements
  @rtype: list
  @return: list of unique elements from seq

  """
  seen = set()
  return [i for i in seq if i not in seen and not seen.add(i)]


def JoinDisjointDicts(dict_a, dict_b):
  """Joins dictionaries with no conflicting keys.

  Enforces the constraint that the two key sets must be disjoint, and then
  merges the two dictionaries in a new dictionary that is returned to the
  caller.

  @type dict_a: dict
  @param dict_a: the first dictionary
  @type dict_b: dict
  @param dict_b: the second dictionary
  @rtype: dict
  @return: a new dictionary containing all the key/value pairs contained in the
  two dictionaries.

  """
  assert not (set(dict_a) & set(dict_b)), ("Duplicate keys found while joining"
                                           " %s and %s" % (dict_a, dict_b))
  result = dict_a.copy()
  result.update(dict_b)
  return result


def FindDuplicates(seq):
  """Identifies duplicates in a list.

  Does not preserve element order.

  @type seq: sequence
  @param seq: Sequence with source elements
  @rtype: list
  @return: List of duplicate elements from seq

  """
  dup = set()
  seen = set()

  for item in seq:
    if item in seen:
      dup.add(item)
    else:
      seen.add(item)

  return list(dup)


#pylint: disable=W0142 (use of *-magic in argument list)
def GetRepeatedKeys(*dicts):
  """Return the set of keys defined multiple times in the given dicts.

  >>> GetRepeatedKeys({"foo": 1, "bar": 2},
  ...                 {"foo": 5, "baz": 7}
  ...                )
  set("foo")

  @type dicts: dict
  @param dicts: The dictionaries to check for duplicate keys.
  @rtype: set
  @return: Keys used more than once across all dicts

  """
  if len(dicts) < 2:
    return set()

  keys = []
  for dictionary in dicts:
    keys.extend(dictionary)

  return set(FindDuplicates(keys))


def _NiceSortTryInt(val):
  """Attempts to convert a string to an integer.

  """
  if val and val.isdigit():
    return int(val)
  else:
    return val


def NiceSortKey(value):
  """Extract key for sorting.

  """
  return [_NiceSortTryInt(grp)
          for grp in _SORTER_RE.match(value).groups()]


def NiceSort(values, key=None):
  """Sort a list of strings based on digit and non-digit groupings.

  Given a list of names C{['a1', 'a10', 'a11', 'a2']} this function
  will sort the list in the logical order C{['a1', 'a2', 'a10',
  'a11']}.

  The sort algorithm breaks each name in groups of either only-digits
  or no-digits. Only the first eight such groups are considered, and
  after that we just use what's left of the string.

  @type values: list
  @param values: the names to be sorted
  @type key: callable or None
  @param key: function of one argument to extract a comparison key from each
    list element, must return string
  @rtype: list
  @return: a copy of the name list sorted with our algorithm

  """
  if key is None:
    keyfunc = NiceSortKey
  else:
    keyfunc = lambda value: NiceSortKey(key(value))

  return sorted(values, key=keyfunc)


def InvertDict(dict_in):
  """Inverts the key/value mapping of a dict.

  @param dict_in: The dict to invert
  @return: the inverted dict

  """
  return dict(zip(dict_in.values(), dict_in.keys()))


def InsertAtPos(src, pos, other):
  """Inserts C{other} at given C{pos} into C{src}.

  @note: This function does not modify C{src} in place but returns a new copy

  @type src: list
  @param src: The source list in which we want insert elements
  @type pos: int
  @param pos: The position where we want to start insert C{other}
  @type other: list
  @param other: The other list to insert into C{src}
  @return: A copy of C{src} with C{other} inserted at C{pos}

  """
  new = src[:pos]
  new.extend(other)
  new.extend(src[pos:])

  return new


def SequenceToDict(seq, key=compat.fst):
  """Converts a sequence to a dictionary with duplicate detection.

  @type seq: sequen
  @param seq: Input sequence
  @type key: callable
  @param key: Function for retrieving dictionary key from sequence element
  @rtype: dict

  """
  keys = map(key, seq)

  duplicates = FindDuplicates(keys)
  if duplicates:
    raise ValueError("Duplicate keys found: %s" % text.CommaJoin(duplicates))

  assert len(keys) == len(seq)

  return dict(zip(keys, seq))


def _MakeFlatToDict(data):
  """Helper function for C{FlatToDict}.

  This function is recursively called

  @param data: The input data as described in C{FlatToDict}, already splitted
  @returns: The so far converted dict

  """
  if not compat.fst(compat.fst(data)):
    assert len(data) == 1, \
      "not bottom most element, found %d elements, expected 1" % len(data)
    return compat.snd(compat.fst(data))

  keyfn = lambda e: compat.fst(e).pop(0)
  return dict([(k, _MakeFlatToDict(list(g)))
               for (k, g) in itertools.groupby(sorted(data), keyfn)])


def FlatToDict(data, field_sep="/"):
  """Converts a flat structure to a fully fledged dict.

  It accept a list of tuples in the form::

    [
      ("foo/bar", {"key1": "data1", "key2": "data2"}),
      ("foo/baz", {"key3" :"data3" }),
    ]

  where the first element is the key separated by C{field_sep}.

  This would then return::

    {
      "foo": {
        "bar": {"key1": "data1", "key2": "data2"},
        "baz": {"key3" :"data3" },
        },
    }

  @type data: list of tuple
  @param data: Input list to convert
  @type field_sep: str
  @param field_sep: The separator for the first field of the tuple
  @returns: A dict based on the input list

  """
  return _MakeFlatToDict([(keys.split(field_sep), value)
                          for (keys, value) in data])


class RunningTimeout(object):
  """Class to calculate remaining timeout when doing several operations.

  """
  __slots__ = [
    "_allow_negative",
    "_start_time",
    "_time_fn",
    "_timeout",
    ]

  def __init__(self, timeout, allow_negative, _time_fn=time.time):
    """Initializes this class.

    @type timeout: float
    @param timeout: Timeout duration
    @type allow_negative: bool
    @param allow_negative: Whether to return values below zero
    @param _time_fn: Time function for unittests

    """
    object.__init__(self)

    if timeout is not None and timeout < 0.0:
      raise ValueError("Timeout must not be negative")

    self._timeout = timeout
    self._allow_negative = allow_negative
    self._time_fn = _time_fn

    self._start_time = None

  def Remaining(self):
    """Returns the remaining timeout.

    """
    if self._timeout is None:
      return None

    # Get start time on first calculation
    if self._start_time is None:
      self._start_time = self._time_fn()

    # Calculate remaining time
    remaining_timeout = self._start_time + self._timeout - self._time_fn()

    if not self._allow_negative:
      # Ensure timeout is always >= 0
      return max(0.0, remaining_timeout)

    return remaining_timeout
