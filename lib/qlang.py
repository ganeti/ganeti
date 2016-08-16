#
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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


"""Module for a simple query language

A query filter is always a list. The first item in the list is the operator
(e.g. C{[OP_AND, ...]}), while the other items depend on the operator. For
logic operators (e.g. L{OP_AND}, L{OP_OR}), they are subfilters whose results
are combined. Unary operators take exactly one other item (e.g. a subfilter for
L{OP_NOT} and a field name for L{OP_TRUE}). Binary operators take exactly two
operands, usually a field name and a value to compare against. Filters are
converted to callable functions by L{query._CompileFilter}.

"""

import re
import logging

import pyparsing as pyp

from ganeti import constants
from ganeti import errors
from ganeti import utils


OP_OR = constants.QLANG_OP_OR
OP_AND = constants.QLANG_OP_AND
OP_NOT = constants.QLANG_OP_NOT
OP_TRUE = constants.QLANG_OP_TRUE
OP_EQUAL = constants.QLANG_OP_EQUAL
OP_EQUAL_LEGACY = constants.QLANG_OP_EQUAL_LEGACY
OP_NOT_EQUAL = constants.QLANG_OP_NOT_EQUAL
OP_LT = constants.QLANG_OP_LT
OP_LE = constants.QLANG_OP_LE
OP_GT = constants.QLANG_OP_GT
OP_GE = constants.QLANG_OP_GE
OP_REGEXP = constants.QLANG_OP_REGEXP
OP_CONTAINS = constants.QLANG_OP_CONTAINS
FILTER_DETECTION_CHARS = constants.QLANG_FILTER_DETECTION_CHARS
GLOB_DETECTION_CHARS = constants.QLANG_GLOB_DETECTION_CHARS


def MakeSimpleFilter(namefield, values):
  """Builds simple a filter.

  @param namefield: Name of field containing item name
  @param values: List of names

  """
  if values:
    return [OP_OR] + [[OP_EQUAL, namefield, i] for i in values]

  return None


def _ConvertLogicOp(op):
  """Creates parsing action function for logic operator.

  @type op: string
  @param op: Operator for data structure, e.g. L{OP_AND}

  """
  def fn(toks):
    """Converts parser tokens to query operator structure.

    @rtype: list
    @return: Query operator structure, e.g. C{[OP_AND, ["=", "foo", "bar"]]}

    """
    operands = toks[0]

    if len(operands) == 1:
      return operands[0]

    # Build query operator structure
    return [[op] + operands.asList()]

  return fn


_KNOWN_REGEXP_DELIM = "/#^|"
_KNOWN_REGEXP_FLAGS = frozenset("si")


def _ConvertRegexpValue(_, loc, toks):
  """Regular expression value for condition.

  """
  (regexp, flags) = toks[0]

  # Ensure only whitelisted flags are used
  unknown_flags = (frozenset(flags) - _KNOWN_REGEXP_FLAGS)
  if unknown_flags:
    raise pyp.ParseFatalException("Unknown regular expression flags: '%s'" %
                                  "".join(unknown_flags), loc)

  if flags:
    re_flags = "(?%s)" % "".join(sorted(flags))
  else:
    re_flags = ""

  re_cond = re_flags + regexp

  # Test if valid
  try:
    re.compile(re_cond)
  except re.error, err:
    raise pyp.ParseFatalException("Invalid regular expression (%s)" % err, loc)

  return [re_cond]


def BuildFilterParser():
  """Builds a parser for query filter strings.

  @rtype: pyparsing.ParserElement

  """
  field_name = pyp.Word(pyp.alphas, pyp.alphanums + "_/.")

  # Integer
  num_sign = pyp.Word("-+", exact=1)
  number = pyp.Combine(pyp.Optional(num_sign) + pyp.Word(pyp.nums))
  number.setParseAction(lambda toks: int(toks[0]))

  quoted_string = pyp.quotedString.copy().setParseAction(pyp.removeQuotes)

  # Right-hand-side value
  rval = (number | quoted_string)

  # Boolean condition
  bool_cond = field_name.copy()
  bool_cond.setParseAction(lambda (fname, ): [[OP_TRUE, fname]])

  # Simple binary conditions
  binopstbl = {
    "==": OP_EQUAL,
    "=": OP_EQUAL,  # legacy support
    "!=": OP_NOT_EQUAL,  # legacy support
    "<": OP_LT,
    "<=": OP_LE,
    ">": OP_GT,
    ">=": OP_GE,
    }

  binary_cond = (field_name + pyp.oneOf(binopstbl.keys()) + rval)
  binary_cond.setParseAction(lambda (lhs, op, rhs): [[binopstbl[op], lhs, rhs]])

  # "in" condition
  in_cond = (rval + pyp.Suppress("in") + field_name)
  in_cond.setParseAction(lambda (value, field): [[OP_CONTAINS, field, value]])

  # "not in" condition
  not_in_cond = (rval + pyp.Suppress("not") + pyp.Suppress("in") + field_name)
  not_in_cond.setParseAction(lambda (value, field): [[OP_NOT, [OP_CONTAINS,
                                                               field, value]]])

  # Regular expression, e.g. m/foobar/i
  regexp_val = pyp.Group(pyp.Optional("m").suppress() +
                         pyp.MatchFirst([pyp.QuotedString(i, escChar="\\")
                                         for i in _KNOWN_REGEXP_DELIM]) +
                         pyp.Optional(pyp.Word(pyp.alphas), default=""))
  regexp_val.setParseAction(_ConvertRegexpValue)
  regexp_cond = (field_name + pyp.Suppress("=~") + regexp_val)
  regexp_cond.setParseAction(lambda (field, value): [[OP_REGEXP, field, value]])

  not_regexp_cond = (field_name + pyp.Suppress("!~") + regexp_val)
  not_regexp_cond.setParseAction(lambda (field, value):
                                 [[OP_NOT, [OP_REGEXP, field, value]]])

  # Globbing, e.g. name =* "*.site"
  glob_cond = (field_name + pyp.Suppress("=*") + quoted_string)
  glob_cond.setParseAction(lambda (field, value):
                           [[OP_REGEXP, field,
                             utils.DnsNameGlobPattern(value)]])

  not_glob_cond = (field_name + pyp.Suppress("!*") + quoted_string)
  not_glob_cond.setParseAction(lambda (field, value):
                               [[OP_NOT, [OP_REGEXP, field,
                                          utils.DnsNameGlobPattern(value)]]])

  # All possible conditions
  condition = (binary_cond ^ bool_cond ^
               in_cond ^ not_in_cond ^
               regexp_cond ^ not_regexp_cond ^
               glob_cond ^ not_glob_cond)

  # Associativity operators
  filter_expr = pyp.operatorPrecedence(condition, [
    (pyp.Keyword("not").suppress(), 1, pyp.opAssoc.RIGHT,
     lambda toks: [[OP_NOT, toks[0][0]]]),
    (pyp.Keyword("and").suppress(), 2, pyp.opAssoc.LEFT,
     _ConvertLogicOp(OP_AND)),
    (pyp.Keyword("or").suppress(), 2, pyp.opAssoc.LEFT,
     _ConvertLogicOp(OP_OR)),
    ])

  parser = pyp.StringStart() + filter_expr + pyp.StringEnd()
  parser.parseWithTabs()

  # Originally C{parser.validate} was called here, but there seems to be some
  # issue causing it to fail whenever the "not" operator is included above.

  return parser


def ParseFilter(text, parser=None):
  """Parses a query filter.

  @type text: string
  @param text: Query filter
  @type parser: pyparsing.ParserElement
  @param parser: Pyparsing object
  @rtype: list

  """
  logging.debug("Parsing as query filter: %s", text)

  if parser is None:
    parser = BuildFilterParser()

  try:
    return parser.parseString(text)[0]
  except pyp.ParseBaseException, err:
    raise errors.QueryFilterParseError("Failed to parse query filter"
                                       " '%s': %s" % (text, err), err)


def _CheckFilter(text):
  """CHecks if a string could be a filter.

  @rtype: bool

  """
  return bool(frozenset(text) & FILTER_DETECTION_CHARS)


def _CheckGlobbing(text):
  """Checks if a string could be a globbing pattern.

  @rtype: bool

  """
  return bool(frozenset(text) & GLOB_DETECTION_CHARS)


def _MakeFilterPart(namefield, text, isnumeric=False):
  """Generates filter for one argument.

  """
  if isnumeric:
    try:
      number = int(text)
    except (TypeError, ValueError), err:
      raise errors.OpPrereqError("Invalid job ID passed: %s" % str(err),
                                 errors.ECODE_INVAL)
    return [OP_EQUAL, namefield, number]
  elif _CheckGlobbing(text):
    return [OP_REGEXP, namefield, utils.DnsNameGlobPattern(text)]
  else:
    return [OP_EQUAL, namefield, text]


def MakeFilter(args, force_filter, namefield=None, isnumeric=False):
  """Try to make a filter from arguments to a command.

  If the name could be a filter it is parsed as such. If it's just a globbing
  pattern, e.g. "*.site", such a filter is constructed. As a last resort the
  names are treated just as a plain name filter.

  @type args: list of string
  @param args: Arguments to command
  @type force_filter: bool
  @param force_filter: Whether to force treatment as a full-fledged filter
  @type namefield: string
  @param namefield: Name of field to use for simple filters (use L{None} for
    a default of "name")
  @type isnumeric: bool
  @param isnumeric: Whether the namefield type is numeric, as opposed to
    the default string type; this influences how the filter is built
  @rtype: list
  @return: Query filter

  """
  if namefield is None:
    namefield = "name"

  if (force_filter or
      (args and len(args) == 1 and _CheckFilter(args[0]))):
    try:
      (filter_text, ) = args
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Exactly one argument must be given as a"
                                 " filter", errors.ECODE_INVAL)

    result = ParseFilter(filter_text)
  elif args:
    result = [OP_OR] + [
      _MakeFilterPart(namefield, arg, isnumeric=isnumeric)
      for arg in args
    ]
  else:
    result = None

  return result
