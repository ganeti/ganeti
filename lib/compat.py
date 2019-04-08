#
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Module containing backported language/library functionality.

"""

import itertools
import operator

try:
  # pylint: disable=F0401
  import functools
except ImportError:
  functools = None

try:
  # pylint: disable=F0401
  import roman
except ImportError:
  roman = None


def _all(seq):
  """Returns True if all elements in the iterable are True.

  """
  for _ in itertools.ifilterfalse(bool, seq):
    return False
  return True


def _any(seq):
  """Returns True if any element of the iterable are True.

  """
  for _ in itertools.ifilter(bool, seq):
    return True
  return False


try:
  # pylint: disable=E0601
  # pylint: disable=W0622
  all = all
except NameError:
  all = _all

try:
  # pylint: disable=E0601
  # pylint: disable=W0622
  any = any
except NameError:
  any = _any


def partition(seq, pred=bool): # pylint: disable=W0622
  """Partition a list in two, based on the given predicate.

  """
  return (list(itertools.ifilter(pred, seq)),
          list(itertools.ifilterfalse(pred, seq)))


# Even though we're using Python's built-in "partial" function if available,
# this one is always defined for testing.
def _partial(func, *args, **keywords): # pylint: disable=W0622
  """Decorator with partial application of arguments and keywords.

  This function was copied from Python's documentation.

  """
  def newfunc(*fargs, **fkeywords):
    newkeywords = keywords.copy()
    newkeywords.update(fkeywords)
    return func(*(args + fargs), **newkeywords)

  newfunc.func = func
  newfunc.args = args
  newfunc.keywords = keywords
  return newfunc


if functools is None:
  partial = _partial
else:
  partial = functools.partial


def RomanOrRounded(value, rounding, convert=True):
  """Try to round the value to the closest integer and return it as a roman
  numeral. If the conversion is disabled, or if the roman module could not be
  loaded, round the value to the specified level and return it.

  @type value: number
  @param value: value to convert
  @type rounding: integer
  @param rounding: how many decimal digits the number should be rounded to
  @type convert: boolean
  @param convert: if False, don't try conversion at all
  @rtype: string
  @return: roman numeral for val, or formatted string representing val if
           conversion didn't succeed

  """
  def _FormatOutput(val, r):
    format_string = "%0." + str(r) + "f"
    return format_string % val

  if roman is not None and convert:
    try:
      return roman.toRoman(round(value, 0))
    except roman.RomanError:
      return _FormatOutput(value, rounding)
  return _FormatOutput(value, rounding)


def TryToRoman(val, convert=True):
  """Try to convert a value to roman numerals

  If the roman module could be loaded convert the given value to a roman
  numeral. Gracefully fail back to leaving the value untouched.

  @type val: integer
  @param val: value to convert
  @type convert: boolean
  @param convert: if False, don't try conversion at all
  @rtype: string or typeof(val)
  @return: roman numeral for val, or val if conversion didn't succeed

  """
  if roman is not None and convert:
    try:
      return roman.toRoman(val)
    except roman.RomanError:
      return val
  else:
    return val


def UniqueFrozenset(seq):
  """Makes C{frozenset} from sequence after checking for duplicate elements.

  @raise ValueError: When there are duplicate elements

  """
  if isinstance(seq, (list, tuple)):
    items = seq
  else:
    items = list(seq)

  result = frozenset(items)

  if len(items) != len(result):
    raise ValueError("Duplicate values found")

  return result


#: returns the first element of a list-like value
fst = operator.itemgetter(0)

#: returns the second element of a list-like value
snd = operator.itemgetter(1)
