#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Utility functions with algorithms.

"""

import re
import time
import numbers
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


class _NiceSortAtom:
  """Helper class providing rich comparison between different types

  Wrap an object to provide rich comparison against None, numbers and strings
  and allow sorting of heterogeneous lists.

  """
  __slots__ = ["_obj"]

  def __init__(self, obj):
    if not isinstance(obj, (numbers.Real, str, type(None))):
      raise ValueError("Cannot wrap type %s" % type(obj))
    self._obj = obj

  def __lt__(self, other):
    if not isinstance(other, _NiceSortAtom):
      raise TypeError("Can compare only with _NiceSortAtom")

    try:
      return self._obj < other._obj
    except TypeError:
      pass

    if self._obj is None:
      # None is smaller than anything else
      return True
    elif isinstance(self._obj, numbers.Real):
      if other._obj is None:
        return False
      elif isinstance(other._obj, str):
        return True
    elif isinstance(self._obj, str):
      return False

    raise TypeError("Cannot compare with %s" % type(other._obj))

  def __eq__(self, other):
    if not isinstance(other, _NiceSortAtom):
      raise TypeError("Can compare only with _NiceSortAtom")

    return self._obj == other._obj

  # Mark the rest as NotImplemented and let the intepreter derive them using
  # __eq__ and __lt__.
  def __ne__(self, other):
    return NotImplemented

  def __gt__(self, other):
    return NotImplemented

  def __ge__(self, other):
    return NotImplemented

  def __le__(self, other):
    return NotImplemented


def _NiceSortGetKey(val):
  """Get a suitable sort key.

  Attempt to convert a value to an integer and wrap it in a _NiceSortKey.

  """

  if val and val.isdigit():
    val = int(val)

  return _NiceSortAtom(val)


def NiceSortKey(value):
  """Extract key for sorting.

  """
  return [_NiceSortGetKey(grp)
          for grp in _SORTER_RE.match(str(value)).groups()]


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
  keys = [key(s) for s in seq]

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
