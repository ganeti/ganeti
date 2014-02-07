#
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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
import ipaddr

from ganeti import compat
from ganeti import utils
from ganeti import constants
from ganeti import objects
from ganeti.serializer import Private

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

  def __repr__(self):
    return "<%s %r>" % (self._text, self._fn)


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
  # Some type descriptions are rather long. If "None" is listed at the
  # end or somewhere in between it is easily missed. Therefore it should
  # be at the beginning, e.g. "None or (long description)".
  if __debug__ and TNone in args and args.index(TNone) > 0:
    raise Exception("TNone must be listed first")

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


@WithDesc("ValueNone")
def TValueNone(val):
  """Checks if the given value is L{constants.VALUE_NONE}.

  """
  return val == constants.VALUE_NONE


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


@WithDesc("Tuple")
def TTuple(val):
  """Checks if the given value is a tuple.

  """
  return isinstance(val, tuple)


@WithDesc("Dictionary")
def TDict(val):
  """Checks if the given value is a dictionary.

  Note that L{PrivateDict}s subclass dict and pass this check.

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
  """Combine multiple functions using an OR operation.

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


def TMaybe(test):
  """Wrap a test in a TOr(TNone, test).

  This makes it easier to define TMaybe* types.

  """
  return TOr(TNone, test)


def TMaybeValueNone(test):
  """Used for unsetting values.

  """
  return TMaybe(TOr(TValueNone, test))


# Type aliases

#: a non-empty string
TNonEmptyString = WithDesc("NonEmptyString")(TAnd(TString, TTrue))

#: a maybe non-empty string
TMaybeString = TMaybe(TNonEmptyString)

#: a maybe boolean (bool or none)
TMaybeBool = TMaybe(TBool)

#: Maybe a dictionary (dict or None)
TMaybeDict = TMaybe(TDict)

#: Maybe a list (list or None)
TMaybeList = TMaybe(TList)


#: a non-negative number (value > 0)
# val_type should be TInt, TDouble (== TFloat), or TNumber
def TNonNegative(val_type):
  return WithDesc("EqualOrGreaterThanZero")(TAnd(val_type, lambda v: v >= 0))


#: a positive number (value >= 0)
# val_type should be TInt, TDouble (== TFloat), or TNumber
def TPositive(val_type):
  return WithDesc("GreaterThanZero")(TAnd(val_type, lambda v: v > 0))


#: a non-negative integer (value >= 0)
TNonNegativeInt = TNonNegative(TInt)

#: a positive integer (value > 0)
TPositiveInt = TPositive(TInt)

#: a maybe positive integer (positive integer or None)
TMaybePositiveInt = TMaybe(TPositiveInt)

#: a negative integer (value < 0)
TNegativeInt = \
  TAnd(TInt, WithDesc("LessThanZero")(compat.partial(operator.gt, 0)))

#: a positive float
TNonNegativeFloat = \
  TAnd(TFloat, WithDesc("EqualOrGreaterThanZero")(lambda v: v >= 0.0))

#: Job ID
TJobId = WithDesc("JobId")(TOr(TNonNegativeInt,
                               TRegex(re.compile("^%s$" %
                                                 constants.JOB_ID_TEMPLATE))))

#: Double (== Float)
TDouble = TFloat

#: Number
TNumber = TOr(TInt, TFloat)

#: Relative job ID
TRelativeJobId = WithDesc("RelativeJobId")(TNegativeInt)


def TInstanceOf(cls):
  """Checks if a given value is an instance of C{cls}.

  @type cls: class
  @param cls: Class object

  """
  name = "%s.%s" % (cls.__module__, cls.__name__)

  desc = WithDesc("Instance of %s" % (Parens(name), ))

  return desc(lambda val: isinstance(val, cls))


def TPrivate(val_type):
  """Checks if a given value is an instance of Private.

  """
  def fn(val):
    return isinstance(val, Private) and val_type(val.Get())

  desc = WithDesc("Private %s" % Parens(val_type))

  return desc(fn)


def TListOf(my_type):
  """Checks if a given value is a list with all elements of the same type.

  """
  desc = WithDesc("List of %s" % (Parens(my_type), ))
  return desc(TAnd(TList, lambda lst: compat.all(my_type(v) for v in lst)))


TMaybeListOf = lambda item_type: TMaybe(TListOf(item_type))


def TTupleOf(*val_types):
  """Checks if a given value is a list with the proper size and its
     elements match the given types.

  """
  desc = WithDesc("Tuple of %s" % (Parens(val_types), ))
  return desc(TAnd(TIsLength(len(val_types)), TItems(val_types)))


def TSetOf(val_type):
  """Checks if a given value is a list with all elements of the same
     type and eliminates duplicated elements.

  """
  desc = WithDesc("Set of %s" % (Parens(val_type), ))
  return desc(lambda st: TListOf(val_type)(list(set(st))))


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


TAllocPolicy = TElemOf(constants.VALID_ALLOC_POLICIES)
TCVErrorCode = TElemOf(constants.CV_ALL_ECODES_STRINGS)
TQueryResultCode = TElemOf(constants.RS_ALL)
TExportTarget = TOr(TNonEmptyString, TList)
TExportMode = TElemOf(constants.EXPORT_MODES)
TDiskIndex = TAnd(TNonNegativeInt, lambda val: val < constants.MAX_DISKS)
TReplaceDisksMode = TElemOf(constants.REPLACE_MODES)
TDiskTemplate = TElemOf(constants.DISK_TEMPLATES)
TEvacMode = TElemOf(constants.NODE_EVAC_MODES)
TIAllocatorTestDir = TElemOf(constants.VALID_IALLOCATOR_DIRECTIONS)
TIAllocatorMode = TElemOf(constants.VALID_IALLOCATOR_MODES)
TImportExportCompression = TElemOf(constants.IEC_ALL)


def TSetParamsMods(fn):
  """Generates a check for modification lists.

  """
  # Old format
  # TODO: Remove in version 2.11 including support in LUInstanceSetParams
  old_mod_item_fn = \
    TAnd(TIsLength(2),
         TItems([TOr(TElemOf(constants.DDMS_VALUES), TNonNegativeInt), fn]))

  # New format, supporting adding/removing disks/NICs at arbitrary indices
  mod_item_fn = \
      TAnd(TIsLength(3), TItems([
        TElemOf(constants.DDMS_VALUES_WITH_MODIFY),
        Comment("Device index, can be negative, e.g. -1 for last disk")
                 (TOr(TInt, TString)),
        fn,
        ]))

  return TOr(Comment("Recommended")(TListOf(mod_item_fn)),
             Comment("Deprecated")(TListOf(old_mod_item_fn)))


TINicParams = \
    Comment("NIC parameters")(TDictOf(TElemOf(constants.INIC_PARAMS),
                                      TMaybe(TString)))

TIDiskParams = \
    Comment("Disk parameters")(TDictOf(TNonEmptyString,
                                       TOr(TNonEmptyString, TInt)))

THypervisor = TElemOf(constants.HYPER_TYPES)
TMigrationMode = TElemOf(constants.HT_MIGRATION_MODES)
TNICMode = TElemOf(constants.NIC_VALID_MODES)
TInstCreateMode = TElemOf(constants.INSTANCE_CREATE_MODES)
TRebootType = TElemOf(constants.REBOOT_TYPES)
TFileDriver = TElemOf(constants.FILE_DRIVER)
TOobCommand = TElemOf(constants.OOB_COMMANDS)
# FIXME: adjust this after all queries are in haskell
TQueryTypeOp = TElemOf(set(constants.QR_VIA_OP)
                       .union(set(constants.QR_VIA_LUXI)))

TDiskParams = \
    Comment("Disk parameters")(TDictOf(TNonEmptyString,
                                       TOr(TNonEmptyString, TInt)))

TDiskChanges = \
    TAnd(TIsLength(2),
         TItems([Comment("Disk index")(TNonNegativeInt),
                 Comment("Parameters")(TDiskParams)]))

TRecreateDisksInfo = TOr(TListOf(TNonNegativeInt), TListOf(TDiskChanges))


def TStorageType(val):
  """Builds a function that checks if a given value is a valid storage
  type.

  """
  return (val in constants.STORAGE_TYPES)


TTagKind = TElemOf(constants.VALID_TAG_TYPES)
TDdmSimple = TElemOf(constants.DDMS_VALUES)
TVerifyOptionalChecks = TElemOf(constants.VERIFY_OPTIONAL_CHECKS)


@WithDesc("IPv4 network")
def _CheckCIDRNetNotation(value):
  """Ensure a given CIDR notation type is valid.

  """
  try:
    ipaddr.IPv4Network(value)
  except ipaddr.AddressValueError:
    return False
  return True


@WithDesc("IPv4 address")
def _CheckCIDRAddrNotation(value):
  """Ensure a given CIDR notation type is valid.

  """
  try:
    ipaddr.IPv4Address(value)
  except ipaddr.AddressValueError:
    return False
  return True


@WithDesc("IPv6 address")
def _CheckCIDR6AddrNotation(value):
  """Ensure a given CIDR notation type is valid.

  """
  try:
    ipaddr.IPv6Address(value)
  except ipaddr.AddressValueError:
    return False
  return True


@WithDesc("IPv6 network")
def _CheckCIDR6NetNotation(value):
  """Ensure a given CIDR notation type is valid.

  """
  try:
    ipaddr.IPv6Network(value)
  except ipaddr.AddressValueError:
    return False
  return True


TIPv4Address = TAnd(TString, _CheckCIDRAddrNotation)
TIPv6Address = TAnd(TString, _CheckCIDR6AddrNotation)
TIPv4Network = TAnd(TString, _CheckCIDRNetNotation)
TIPv6Network = TAnd(TString, _CheckCIDR6NetNotation)


def TObject(val_type):
  return TDictOf(TAny, val_type)


def TObjectCheck(obj, fields_types):
  """Helper to generate type checks for objects.

  @param obj: The object to generate type checks
  @param fields_types: The fields and their types as a dict
  @return: A ht type check function

  """
  assert set(obj.GetAllSlots()) == set(fields_types.keys()), \
    "%s != %s" % (set(obj.GetAllSlots()), set(fields_types.keys()))
  return TStrictDict(True, True, fields_types)


TQueryFieldDef = \
    TObjectCheck(objects.QueryFieldDefinition, {
        "name": TNonEmptyString,
        "title": TNonEmptyString,
        "kind": TElemOf(constants.QFT_ALL),
        "doc": TNonEmptyString
    })

TQueryRow = \
    TListOf(TAnd(TIsLength(2),
                 TItems([TElemOf(constants.RS_ALL), TAny])))

TQueryResult = TListOf(TQueryRow)

TQueryResponse = \
    TObjectCheck(objects.QueryResponse, {
        "fields": TListOf(TQueryFieldDef),
        "data": TQueryResult
    })

TQueryFieldsResponse = \
    TObjectCheck(objects.QueryFieldsResponse, {
        "fields": TListOf(TQueryFieldDef)
    })

TJobIdListItem = \
    TAnd(TIsLength(2),
         TItems([Comment("success")(TBool),
                 Comment("Job ID if successful, error message"
                         " otherwise")(TOr(TString, TJobId))]))

TJobIdList = TListOf(TJobIdListItem)

TJobIdListOnly = TStrictDict(True, True, {
  constants.JOB_IDS_KEY: Comment("List of submitted jobs")(TJobIdList)
  })

TInstanceMultiAllocResponse = \
    TStrictDict(True, True, {
      constants.JOB_IDS_KEY: Comment("List of submitted jobs")(TJobIdList),
      constants.ALLOCATABLE_KEY: TListOf(TNonEmptyString),
      constants.FAILED_KEY: TListOf(TNonEmptyString)
    })
