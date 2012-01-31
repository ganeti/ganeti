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
import operator

from ganeti import compat
from ganeti import utils
from ganeti import constants


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


class _WrapperBase(object):
  __slots__ = [
    "_fn",
    "_text",
    ]

  def __init__(self, text, fn):
    """Initializes this class.

    @param text: Description
    @param fn: Wrapped function

    """
    assert text.strip()

    self._text = text
    self._fn = fn

  def __call__(self, *args):
    return self._fn(*args)


class _DescWrapper(_WrapperBase):
  """Wrapper class for description text.

  """
  def __str__(self):
    return self._text


class _CommentWrapper(_WrapperBase):
  """Wrapper class for comment.

  """
  def __str__(self):
    return "%s [%s]" % (self._fn, self._text)


def WithDesc(text):
  """Builds wrapper class with description text.

  @type text: string
  @param text: Description text
  @return: Callable class

  """
  assert text[0] == text[0].upper()

  return compat.partial(_DescWrapper, text)


def Comment(text):
  """Builds wrapper for adding comment to description text.

  @type text: string
  @param text: Comment text
  @return: Callable class

  """
  assert not frozenset(text).intersection("[]")

  return compat.partial(_CommentWrapper, text)


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
@WithDesc("Anything")
def TAny(_):
  """Accepts any value.

  """
  return True


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
  return isinstance(val, (int, long)) and not isinstance(val, bool)


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


def TRegex(pobj):
  """Checks whether a string matches a specific regular expression.

  @param pobj: Compiled regular expression as returned by C{re.compile}

  """
  desc = WithDesc("String matching regex \"%s\"" %
                  pobj.pattern.encode("string_escape"))

  return desc(TAnd(TString, pobj.match))


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

#: a maybe positive integer (positive integer or None)
TMaybePositiveInt = TOr(TPositiveInt, TNone)

#: a strictly positive integer
TStrictPositiveInt = \
  TAnd(TInt, WithDesc("GreaterThanZero")(lambda v: v > 0))

#: a maybe strictly positive integer (strictly positive integer or None)
TMaybeStrictPositiveInt = TOr(TStrictPositiveInt, TNone)

#: a strictly negative integer (0 > value)
TStrictNegativeInt = \
  TAnd(TInt, WithDesc("LessThanZero")(compat.partial(operator.gt, 0)))

#: a positive float
TPositiveFloat = \
  TAnd(TFloat, WithDesc("EqualGreaterZero")(lambda v: v >= 0.0))

#: Job ID
TJobId = WithDesc("JobId")(TOr(TPositiveInt,
                               TRegex(re.compile("^%s$" %
                                                 constants.JOB_ID_TEMPLATE))))

#: Number
TNumber = TOr(TInt, TFloat)

#: Relative job ID
TRelativeJobId = WithDesc("RelativeJobId")(TStrictNegativeInt)


def TListOf(my_type):
  """Checks if a given value is a list with all elements of the same type.

  """
  desc = WithDesc("List of %s" % (Parens(my_type), ))
  return desc(TAnd(TList, lambda lst: compat.all(my_type(v) for v in lst)))


TMaybeListOf = lambda item_type: TOr(TNone, TListOf(item_type))


def TDictOf(key_type, val_type):
  """Checks a dict type for the type of its key/values.

  """
  desc = WithDesc("Dictionary with keys of %s and values of %s" %
                  (Parens(key_type), Parens(val_type)))

  def fn(container):
    return (compat.all(key_type(v) for v in container.keys()) and
            compat.all(val_type(v) for v in container.values()))

  return desc(TAnd(TDict, fn))


def _TStrictDictCheck(require_all, exclusive, items, val):
  """Helper function for L{TStrictDict}.

  """
  notfound_fn = lambda _: not exclusive

  if require_all and not frozenset(val.keys()).issuperset(items.keys()):
    # Requires items not found in value
    return False

  return compat.all(items.get(key, notfound_fn)(value)
                    for (key, value) in val.items())


def TStrictDict(require_all, exclusive, items):
  """Strict dictionary check with specific keys.

  @type require_all: boolean
  @param require_all: Whether all keys in L{items} are required
  @type exclusive: boolean
  @param exclusive: Whether only keys listed in L{items} should be accepted
  @type items: dictionary
  @param items: Mapping from key (string) to verification function

  """
  descparts = ["Dictionary containing"]

  if exclusive:
    descparts.append(" none but the")

  if require_all:
    descparts.append(" required")

  if len(items) == 1:
    descparts.append(" key ")
  else:
    descparts.append(" keys ")

  descparts.append(utils.CommaJoin("\"%s\" (value %s)" % (key, value)
                                   for (key, value) in items.items()))

  desc = WithDesc("".join(descparts))

  return desc(TAnd(TDict,
                   compat.partial(_TStrictDictCheck, require_all, exclusive,
                                  items)))


def TItems(items):
  """Checks individual items of a container.

  If the verified value and the list of expected items differ in length, this
  check considers only as many items as are contained in the shorter list. Use
  L{TIsLength} to enforce a certain length.

  @type items: list
  @param items: List of checks

  """
  assert items, "Need items"

  text = ["Item", "item"]
  desc = WithDesc(utils.CommaJoin("%s %s is %s" %
                                  (text[int(idx > 0)], idx, Parens(check))
                                  for (idx, check) in enumerate(items)))

  return desc(lambda value: compat.all(check(i)
                                       for (check, i) in zip(items, value)))
