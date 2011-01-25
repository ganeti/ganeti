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


"""Module implementing the parameter types code."""

from ganeti import compat

# Modifiable default values; need to define these here before the
# actual LUs

def EmptyList():
  """Returns an empty list.

  """
  return []


def EmptyDict():
  """Returns an empty dict.

  """
  return {}


#: The without-default default value
NoDefault = object()


#: The no-type (value to complex to check it in the type system)
NoType = object()


# Some basic types
def TNotNone(val):
  """Checks if the given value is not None.

  """
  return val is not None


def TNone(val):
  """Checks if the given value is None.

  """
  return val is None


def TBool(val):
  """Checks if the given value is a boolean.

  """
  return isinstance(val, bool)


def TInt(val):
  """Checks if the given value is an integer.

  """
  # For backwards compatibility with older Python versions, boolean values are
  # also integers and should be excluded in this test.
  #
  # >>> (isinstance(False, int), isinstance(True, int))
  # (True, True)
  return isinstance(val, int) and not isinstance(val, bool)


def TFloat(val):
  """Checks if the given value is a float.

  """
  return isinstance(val, float)


def TString(val):
  """Checks if the given value is a string.

  """
  return isinstance(val, basestring)


def TTrue(val):
  """Checks if a given value evaluates to a boolean True value.

  """
  return bool(val)


def TElemOf(target_list):
  """Builds a function that checks if a given value is a member of a list.

  """
  return lambda val: val in target_list


# Container types
def TList(val):
  """Checks if the given value is a list.

  """
  return isinstance(val, list)


def TDict(val):
  """Checks if the given value is a dictionary.

  """
  return isinstance(val, dict)


def TIsLength(size):
  """Check is the given container is of the given size.

  """
  return lambda container: len(container) == size


# Combinator types
def TAnd(*args):
  """Combine multiple functions using an AND operation.

  """
  def fn(val):
    return compat.all(t(val) for t in args)
  return fn


def TOr(*args):
  """Combine multiple functions using an AND operation.

  """
  def fn(val):
    return compat.any(t(val) for t in args)
  return fn


def TMap(fn, test):
  """Checks that a modified version of the argument passes the given test.

  """
  return lambda val: test(fn(val))


# Type aliases

#: a non-empty string
TNonEmptyString = TAnd(TString, TTrue)

#: a maybe non-empty string
TMaybeString = TOr(TNonEmptyString, TNone)

#: a maybe boolean (bool or none)
TMaybeBool = TOr(TBool, TNone)

#: Maybe a dictionary (dict or None)
TMaybeDict = TOr(TDict, TNone)

#: a positive integer
TPositiveInt = TAnd(TInt, lambda v: v >= 0)

#: a strictly positive integer
TStrictPositiveInt = TAnd(TInt, lambda v: v > 0)


def TListOf(my_type):
  """Checks if a given value is a list with all elements of the same type.

  """
  return TAnd(TList,
               lambda lst: compat.all(my_type(v) for v in lst))


def TDictOf(key_type, val_type):
  """Checks a dict type for the type of its key/values.

  """
  return TAnd(TDict,
              lambda my_dict: (compat.all(key_type(v) for v in my_dict.keys())
                               and compat.all(val_type(v)
                                              for v in my_dict.values())))
