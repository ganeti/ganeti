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


_SORTER_RE = re.compile("^%s(.*)$" % (8 * "(\D+|\d+)?"))
_SORTER_DIGIT = re.compile("^\d+$")


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


def _NiceSortTryInt(val):
  """Attempts to convert a string to an integer.

  """
  if val and _SORTER_DIGIT.match(val):
    return int(val)
  else:
    return val


def _NiceSortKey(value):
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
    keyfunc = _NiceSortKey
  else:
    keyfunc = lambda value: _NiceSortKey(key(value))

  return sorted(values, key=keyfunc)


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
