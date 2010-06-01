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


"""Module containing backported language/library functionality.

"""

import itertools

try:
  import functools
except ImportError:
  functools = None

try:
  import roman
except ImportError:
  roman = None


# compat.md5_hash and compat.sha1_hash can be called to generate and md5 and a
# sha1 hashing modules, under python 2.4, 2.5 and 2.6, even though some changes
# went on. compat.sha1 is python-version specific and is used for python
# modules (hmac, for example) which have changed their behavior as well from
# one version to the other.
try:
  # Yes, we're not using the imports in this module.
  # pylint: disable-msg=W0611
  from hashlib import md5 as md5_hash
  from hashlib import sha1 as sha1_hash
  # this additional version is needed for compatibility with the hmac module
  sha1 = sha1_hash
except ImportError:
  from md5 import new as md5_hash
  import sha
  sha1 = sha
  sha1_hash = sha.new


def all(seq, pred=bool): # pylint: disable-msg=W0622
  """Returns True if pred(x) is True for every element in the iterable.

  Please note that this function provides a C{pred} parameter which isn't
  available in the version included in Python 2.5 and above.

  """
  for _ in itertools.ifilterfalse(pred, seq):
    return False
  return True


def any(seq, pred=bool): # pylint: disable-msg=W0622
  """Returns True if pred(x) is True for at least one element in the iterable.

  Please note that this function provides a C{pred} parameter which isn't
  available in the version included in Python 2.5 and above.

  """
  for _ in itertools.ifilter(pred, seq):
    return True
  return False


def partition(seq, pred=bool): # pylint: disable-msg=W0622
  """Partition a list in two, based on the given predicate.

  """
  return (list(itertools.ifilter(pred, seq)),
          list(itertools.ifilterfalse(pred, seq)))


# Even though we're using Python's built-in "partial" function if available,
# this one is always defined for testing.
def _partial(func, *args, **keywords): # pylint: disable-msg=W0622
  """Decorator with partial application of arguments and keywords.

  This function was copied from Python's documentation.

  """
  def newfunc(*fargs, **fkeywords):
    newkeywords = keywords.copy()
    newkeywords.update(fkeywords)
    return func(*(args + fargs), **newkeywords) # pylint: disable-msg=W0142

  newfunc.func = func
  newfunc.args = args
  newfunc.keywords = keywords
  return newfunc


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


if functools is None:
  partial = _partial
else:
  partial = functools.partial
