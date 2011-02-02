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


"""Module implementing the parameter types code."""

import re

from ganeti import compat
from ganeti import utils


_PAREN_RE = re.compile("^[a-zA-Z0-9_-]+$")


def Parens(text):
  """Enclose text in parens if necessary.

  @param text: Text

  """
  text = str(text)

  if _PAREN_RE.match(text):
    return text
  else:
    return "(%s)" % text


def WithDesc(text):
  """Builds wrapper class with description text.

  @type text: string
  @param text: Description text
  @return: Callable class

  """
  assert text[0] == text[0].upper()

  class wrapper(object): # pylint: disable-msg=C0103
    __slots__ = ["__call__"]

    def __init__(self, fn):
      """Initializes this class.

      @param fn: Wrapped function

      """
      self.__call__ = fn

    def __str__(self):
      return text

  return wrapper


def CombinationDesc(op, args, fn):
  """Build description for combinating operator.

  @type op: string
  @param op: Operator as text (e.g. "and")
  @type args: list
  @param args: Operator arguments
  @type fn: callable
  @param fn: Wrapped function

  """
  if len(args) == 1:
    descr = str(args[0])
  else:
    descr = (" %s " % op).join(Parens(i) for i in args)

  return WithDesc(descr)(fn)


# Modifiable default values; need to define these here before the
# actual LUs

@WithDesc(str([]))
def EmptyList():
  """Returns an empty list.

  """
  return []


@WithDesc(str({}))
def EmptyDict():
  """Returns an empty dict.

  """
  return {}


#: The without-default default value
NoDefault = object()


#: The no-type (value too complex to check it in the type system)
NoType = object()


# Some basic types
@WithDesc("NotNone")
def TNotNone(val):
  """Checks if the given value is not None.

  """
  return val is not None


@WithDesc("None")
def TNone(val):
  """Checks if the given value is None.

  """
  return val is None


@WithDesc("Boolean")
def TBool(val):
  """Checks if the given value is a boolean.

  """
  return isinstance(val, bool)


@WithDesc("Integer")
def TInt(val):
  """Checks if the given value is an integer.

  """
  # For backwards compatibility with older Python versions, boolean values are
  # also integers and should be excluded in this test.
  #
  # >>> (isinstance(False, int), isinstance(True, int))
  # (True, True)
  return isinstance(val, int) and not isinstance(val, bool)


@WithDesc("Float")
def TFloat(val):
  """Checks if the given value is a float.

  """
  return isinstance(val, float)


@WithDesc("String")
def TString(val):
  """Checks if the given value is a string.

  """
  return isinstance(val, basestring)


@WithDesc("EvalToTrue")
def TTrue(val):
  """Checks if a given value evaluates to a boolean True value.

  """
  return bool(val)


def TElemOf(target_list):
  """Builds a function that checks if a given value is a member of a list.

  """
  def fn(val):
    return val in target_list

  return WithDesc("OneOf %s" % (utils.CommaJoin(target_list), ))(fn)


# Container types
@WithDesc("List")
def TList(val):
  """Checks if the given value is a list.

  """
  return isinstance(val, list)


@WithDesc("Dictionary")
def TDict(val):
  """Checks if the given value is a dictionary.

  """
  return isinstance(val, dict)


def TIsLength(size):
  """Check is the given container is of the given size.

  """
  def fn(container):
    return len(container) == size

  return WithDesc("Length %s" % (size, ))(fn)


# Combinator types
def TAnd(*args):
  """Combine multiple functions using an AND operation.

  """
  def fn(val):
    return compat.all(t(val) for t in args)

  return CombinationDesc("and", args, fn)


def TOr(*args):
  """Combine multiple functions using an AND operation.

  """
  def fn(val):
    return compat.any(t(val) for t in args)

  return CombinationDesc("or", args, fn)


def TMap(fn, test):
  """Checks that a modified version of the argument passes the given test.

  """
  return WithDesc("Result of %s must be %s" %
                  (Parens(fn), Parens(test)))(lambda val: test(fn(val)))


# Type aliases

#: a non-empty string
TNonEmptyString = WithDesc("NonEmptyString")(TAnd(TString, TTrue))

#: a maybe non-empty string
TMaybeString = TOr(TNonEmptyString, TNone)

#: a maybe boolean (bool or none)
TMaybeBool = TOr(TBool, TNone)

#: Maybe a dictionary (dict or None)
TMaybeDict = TOr(TDict, TNone)

#: a positive integer
TPositiveInt = \
  TAnd(TInt, WithDesc("EqualGreaterZero")(lambda v: v >= 0))

#: a strictly positive integer
TStrictPositiveInt = \
  TAnd(TInt, WithDesc("GreaterThanZero")(lambda v: v > 0))


def TListOf(my_type):
  """Checks if a given value is a list with all elements of the same type.

  """
  desc = WithDesc("List of %s" % (Parens(my_type), ))
  return desc(TAnd(TList, lambda lst: compat.all(my_type(v) for v in lst)))


def TDictOf(key_type, val_type):
  """Checks a dict type for the type of its key/values.

  """
  desc = WithDesc("Dictionary with keys of %s and values of %s" %
                  (Parens(key_type), Parens(val_type)))

  def fn(container):
    return (compat.all(key_type(v) for v in container.keys()) and
            compat.all(val_type(v) for v in container.values()))

  return desc(TAnd(TDict, fn))
